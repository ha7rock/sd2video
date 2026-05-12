"""Local-only image generation bridge backed by Codex/ChatGPT OAuth.

This module is intentionally not a production API client. It exists so local
development can generate reference images through a separate Codex OAuth token
store without exposing tokens to the browser or reusing ``~/.codex/auth.json``.
"""

from __future__ import annotations

import base64
import json
import os
import stat
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib import error as urlerror
from urllib import parse, request

CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_AUTH_ISSUER = "https://auth.openai.com"
DEFAULT_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
DEFAULT_CODEX_CHAT_MODEL = "gpt-5.4"
DEFAULT_IMAGE_MODEL = "gpt-image-2"
DEFAULT_TIMEOUT_SECONDS = 120.0
ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 120

VALID_SIZES = {"1024x1024", "1536x1024", "1024x1536"}
VALID_QUALITIES = {"low", "medium", "high"}
VALID_BACKGROUNDS = {"opaque", "transparent", "auto"}
VALID_OUTPUT_FORMATS = {"png", "jpeg", "webp"}


class LocalImageError(Exception):
    """Base class for local image bridge failures."""

    def __init__(self, message: str, *, code: str = "local_image_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class LocalImageFeatureDisabled(LocalImageError):
    """Raised when the local image feature flag is off."""


class LocalImageAuthError(LocalImageError):
    """Raised for missing, expired, or invalid Codex OAuth credentials."""


class LocalImageAPIError(LocalImageError):
    """Raised when the Codex backend rejects a request."""


class LocalImageNetworkError(LocalImageError):
    """Raised when the Codex backend cannot be reached."""


@dataclass(frozen=True)
class HTTPResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class LocalImageRequest:
    prompt: str
    size: str = "1024x1024"
    quality: str = "medium"
    background: str = "opaque"
    output_format: str = "png"


@dataclass(frozen=True)
class LocalImageResult:
    id: str
    file_path: Path
    prompt: str
    size: str
    quality: str
    background: str
    output_format: str
    model: str = DEFAULT_IMAGE_MODEL
    provider: str = "openai-codex"


class HTTPTransport(Protocol):
    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        timeout: float,
    ) -> HTTPResponse:
        """Send a POST request and return a raw response."""


class UrllibHTTPTransport:
    """Small urllib transport so the default path has no third-party deps."""

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        timeout: float,
    ) -> HTTPResponse:
        req = request.Request(url, data=body, headers=dict(headers), method="POST")
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                return HTTPResponse(resp.status, dict(resp.headers.items()), resp.read())
        except urlerror.HTTPError as exc:
            return HTTPResponse(exc.code, dict(exc.headers.items()), exc.read())
        except (TimeoutError, OSError, urlerror.URLError) as exc:
            raise LocalImageNetworkError(
                "Codex image request failed before receiving a response",
                code="network_error",
            ) from exc


class CodexTokenStore:
    """Project-owned Codex token store.

    The default path is ``~/.sd2video/codex_oauth.json``. Set
    ``SD2VIDEO_CODEX_AUTH_PATH`` to relocate it for tests or local profiles.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_auth_path()

    def load_tokens(self) -> dict[str, Any]:
        if not self.path.exists():
            raise LocalImageAuthError(
                "No sd2video Codex OAuth tokens found. Run the local image auth login command.",
                code="auth_missing",
            )
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise LocalImageAuthError(
                "sd2video Codex OAuth token store is unreadable.",
                code="auth_store_invalid",
            ) from exc
        tokens = data.get("tokens")
        if not isinstance(tokens, dict):
            raise LocalImageAuthError(
                "sd2video Codex OAuth token store is missing tokens.",
                code="auth_store_invalid",
            )
        access_token = str(tokens.get("access_token") or "").strip()
        refresh_token = str(tokens.get("refresh_token") or "").strip()
        if not access_token or not refresh_token:
            raise LocalImageAuthError(
                "sd2video Codex OAuth token store is missing access_token or refresh_token.",
                code="auth_store_invalid",
            )
        return dict(tokens)

    def save_tokens(self, tokens: Mapping[str, Any]) -> Path:
        access_token = str(tokens.get("access_token") or "").strip()
        refresh_token = str(tokens.get("refresh_token") or "").strip()
        if not access_token or not refresh_token:
            raise LocalImageAuthError(
                "Cannot save incomplete Codex OAuth tokens.",
                code="auth_store_invalid",
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        payload = {
            "version": 1,
            "provider": "openai-codex",
            "auth_mode": "chatgpt",
            "updated_at": _now_iso(),
            "tokens": {
                "access_token": access_token,
                "refresh_token": refresh_token,
            },
        }
        tmp = self.path.with_name(f"{self.path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}")
        fd = os.open(
            str(tmp),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            stat.S_IRUSR | stat.S_IWUSR,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
        try:
            self.path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        return self.path

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


class CodexOAuthClient:
    """Device-code login and refresh for the project-owned token store."""

    def __init__(
        self,
        *,
        token_store: CodexTokenStore | None = None,
        transport: HTTPTransport | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self._token_store = token_store or CodexTokenStore()
        self._transport = transport or UrllibHTTPTransport()
        self._timeout = timeout_seconds

    def get_access_token(self, *, force_refresh: bool = False) -> str:
        tokens = self._token_store.load_tokens()
        access_token = str(tokens.get("access_token") or "")
        if force_refresh or access_token_is_expiring(access_token, ACCESS_TOKEN_REFRESH_SKEW_SECONDS):
            tokens = self.refresh_tokens(tokens)
            access_token = str(tokens.get("access_token") or "")
        return access_token

    def refresh_tokens(self, tokens: Mapping[str, Any]) -> dict[str, str]:
        refresh_token = str(tokens.get("refresh_token") or "").strip()
        if not refresh_token:
            raise LocalImageAuthError("Codex refresh_token is missing.", code="refresh_missing")
        body = parse.urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CODEX_OAUTH_CLIENT_ID,
            }
        ).encode("utf-8")
        response = self._transport.post(
            CODEX_OAUTH_TOKEN_URL,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            body=body,
            timeout=self._timeout,
        )
        data = _decode_json_response(response)
        if response.status_code != 200:
            code, message = _extract_error(data, default_code="refresh_failed")
            raise LocalImageAuthError(message, code=code)
        access_token = str(data.get("access_token") or "").strip() if isinstance(data, dict) else ""
        next_refresh = str(data.get("refresh_token") or "").strip() if isinstance(data, dict) else ""
        if not access_token:
            raise LocalImageAuthError(
                "Codex token refresh response was missing access_token.",
                code="refresh_missing_access_token",
            )
        updated = {
            "access_token": access_token,
            "refresh_token": next_refresh or refresh_token,
        }
        self._token_store.save_tokens(updated)
        return updated

    @property
    def token_store_path(self) -> Path:
        return self._token_store.path

    def clear_tokens(self) -> None:
        self._token_store.clear()

    def login_device_code(self, *, print_fn=print, sleep_fn=time.sleep) -> Path:
        """Run the OpenAI Codex device-code flow and persist tokens locally."""

        usercode_resp = self._transport.post(
            f"{CODEX_AUTH_ISSUER}/api/accounts/deviceauth/usercode",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            body=_json_bytes({"client_id": CODEX_OAUTH_CLIENT_ID}),
            timeout=self._timeout,
        )
        usercode_data = _decode_json_response(usercode_resp)
        if usercode_resp.status_code != 200 or not isinstance(usercode_data, dict):
            raise LocalImageAuthError(
                "Codex device-code request failed.",
                code="device_code_request_failed",
            )
        user_code = str(usercode_data.get("user_code") or "")
        device_auth_id = str(usercode_data.get("device_auth_id") or "")
        interval = max(3, int(usercode_data.get("interval") or 5))
        if not user_code or not device_auth_id:
            raise LocalImageAuthError(
                "Codex device-code response was incomplete.",
                code="device_code_incomplete",
            )

        print_fn("Open https://auth.openai.com/codex/device and enter this code:")
        print_fn(user_code)

        code_data: dict[str, Any] | None = None
        deadline = time.monotonic() + 15 * 60
        while time.monotonic() < deadline:
            sleep_fn(interval)
            poll_resp = self._transport.post(
                f"{CODEX_AUTH_ISSUER}/api/accounts/deviceauth/token",
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                body=_json_bytes({"device_auth_id": device_auth_id, "user_code": user_code}),
                timeout=self._timeout,
            )
            if poll_resp.status_code == 200:
                decoded = _decode_json_response(poll_resp)
                if isinstance(decoded, dict):
                    code_data = decoded
                    break
            if poll_resp.status_code not in {403, 404}:
                raise LocalImageAuthError(
                    f"Codex device-code polling failed with status {poll_resp.status_code}.",
                    code="device_code_poll_failed",
                )
        if not code_data:
            raise LocalImageAuthError("Codex device-code login timed out.", code="device_code_timeout")

        authorization_code = str(code_data.get("authorization_code") or "")
        code_verifier = str(code_data.get("code_verifier") or "")
        if not authorization_code or not code_verifier:
            raise LocalImageAuthError(
                "Codex device-code exchange data was incomplete.",
                code="device_code_exchange_incomplete",
            )

        token_resp = self._transport.post(
            CODEX_OAUTH_TOKEN_URL,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            body=parse.urlencode(
                {
                    "grant_type": "authorization_code",
                    "code": authorization_code,
                    "redirect_uri": f"{CODEX_AUTH_ISSUER}/deviceauth/callback",
                    "client_id": CODEX_OAUTH_CLIENT_ID,
                    "code_verifier": code_verifier,
                }
            ).encode("utf-8"),
            timeout=self._timeout,
        )
        token_data = _decode_json_response(token_resp)
        if token_resp.status_code != 200 or not isinstance(token_data, dict):
            raise LocalImageAuthError(
                "Codex token exchange failed.",
                code="token_exchange_failed",
            )
        return self._token_store.save_tokens(token_data)


class CodexImageProvider:
    """Generate one image through the Codex Responses ``image_generation`` tool."""

    def __init__(
        self,
        *,
        oauth_client: CodexOAuthClient | None = None,
        transport: HTTPTransport | None = None,
        cache_dir: Path | None = None,
        base_url: str | None = None,
        chat_model: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._oauth_client = oauth_client or CodexOAuthClient()
        self._transport = transport or UrllibHTTPTransport()
        self._cache_dir = cache_dir or default_cache_dir()
        self._base_url = (base_url or os.getenv("SD2VIDEO_CODEX_BASE_URL") or DEFAULT_CODEX_BASE_URL).rstrip("/")
        self._chat_model = chat_model or os.getenv("SD2VIDEO_CODEX_CHAT_MODEL") or DEFAULT_CODEX_CHAT_MODEL
        self._timeout = timeout_seconds

    def generate(self, req: LocalImageRequest) -> LocalImageResult:
        req = validate_request(req)
        token = self._oauth_client.get_access_token()
        payload = {
            "model": self._chat_model,
            "store": False,
            "instructions": (
                "Use the image_generation tool to generate exactly one image. "
                "Return no secrets and do not describe credentials."
            ),
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": req.prompt}],
                }
            ],
            "tools": [
                {
                    "type": "image_generation",
                    "model": DEFAULT_IMAGE_MODEL,
                    "size": req.size,
                    "quality": req.quality,
                    "output_format": req.output_format,
                    "background": req.background,
                    "partial_images": 1,
                }
            ],
            "tool_choice": {
                "type": "allowed_tools",
                "mode": "required",
                "tools": [{"type": "image_generation"}],
            },
        }
        response = self._transport.post(
            f"{self._base_url}/responses",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                **codex_backend_headers(token),
            },
            body=_json_bytes(payload),
            timeout=self._timeout,
        )
        data = _decode_json_response(response)
        if response.status_code == 401:
            token = self._oauth_client.get_access_token(force_refresh=True)
            response = self._transport.post(
                f"{self._base_url}/responses",
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    **codex_backend_headers(token),
                },
                body=_json_bytes(payload),
                timeout=self._timeout,
            )
            data = _decode_json_response(response)
        if response.status_code < 200 or response.status_code >= 300:
            code, message = _extract_error(data, default_code="codex_api_error")
            raise LocalImageAPIError(message, code=code)

        b64_image = _extract_image_result(data)
        if not b64_image:
            raise LocalImageAPIError(
                "Codex response contained no image_generation result.",
                code="empty_image_result",
            )
        image_id = uuid.uuid4().hex
        path = self._save_image(b64_image, image_id, req.output_format)
        return LocalImageResult(
            id=image_id,
            file_path=path,
            prompt=req.prompt,
            size=req.size,
            quality=req.quality,
            background=req.background,
            output_format=req.output_format,
        )

    def _save_image(self, b64_image: str, image_id: str, output_format: str) -> Path:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self._cache_dir, 0o700)
        except OSError:
            pass
        path = self._cache_dir / f"{image_id}.{output_format}"
        try:
            path.write_bytes(base64.b64decode(b64_image))
        except Exception as exc:
            raise LocalImageError("Could not decode generated image.", code="image_decode_error") from exc
        return path


class LocalImageService:
    """Feature-flagged service used by the local HTTP bridge."""

    def __init__(
        self,
        *,
        provider: Any | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._provider = provider or CodexImageProvider()
        self._environ = os.environ if environ is None else environ

    @property
    def enabled(self) -> bool:
        return is_truthy(self._environ.get("SD2VIDEO_ENABLE_CODEX_IMAGE"))

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "provider": "openai-codex",
            "temporary": True,
        }

    def generate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            raise LocalImageFeatureDisabled(
                "Local Codex image generation is disabled. Set SD2VIDEO_ENABLE_CODEX_IMAGE=1.",
                code="feature_disabled",
            )
        req = validate_request(
            LocalImageRequest(
                prompt=str(payload.get("prompt") or ""),
                size=str(payload.get("size") or "1024x1024"),
                quality=str(payload.get("quality") or "medium"),
                background=str(payload.get("background") or "opaque"),
                output_format=str(payload.get("output_format") or "png"),
            )
        )
        result = self._provider.generate(req)
        return {
            "success": True,
            "asset": {
                "id": result.id,
                "kind": "image",
                "title": title_from_prompt(result.prompt),
                "url": f"/api/v1/local-images/assets/{result.file_path.name}",
                "source": "local-codex-oauth",
                "temporary": True,
                "provider_label": "本地临时 / Codex OAuth / 非 Ark 生成",
            },
            "metadata": {
                "provider": result.provider,
                "model": result.model,
                "size": result.size,
                "quality": result.quality,
                "background": result.background,
                "output_format": result.output_format,
                "created_at": _now_iso(),
            },
        }


def validate_request(req: LocalImageRequest) -> LocalImageRequest:
    prompt = (req.prompt or "").strip()
    if not prompt:
        raise LocalImageError("prompt is required.", code="invalid_prompt")
    if len(prompt) > 8000:
        raise LocalImageError("prompt is too long.", code="invalid_prompt")
    size = req.size if req.size in VALID_SIZES else "1024x1024"
    quality = req.quality if req.quality in VALID_QUALITIES else "medium"
    background = req.background if req.background in VALID_BACKGROUNDS else "opaque"
    output_format = req.output_format if req.output_format in VALID_OUTPUT_FORMATS else "png"
    return LocalImageRequest(
        prompt=prompt,
        size=size,
        quality=quality,
        background=background,
        output_format=output_format,
    )


def default_auth_path() -> Path:
    override = os.getenv("SD2VIDEO_CODEX_AUTH_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".sd2video" / "codex_oauth.json"


def default_cache_dir() -> Path:
    override = os.getenv("SD2VIDEO_LOCAL_IMAGE_CACHE", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".sd2video" / "local-images"


def is_truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def title_from_prompt(prompt: str) -> str:
    prompt = " ".join((prompt or "").split())
    return prompt[:30] or "本地生成图片"


def codex_backend_headers(access_token: str) -> dict[str, str]:
    headers = {
        "User-Agent": "codex_cli_rs/0.0.0 (sd2video local image)",
        "originator": "codex_cli_rs",
    }
    account_id = _chatgpt_account_id(access_token)
    if account_id:
        headers["ChatGPT-Account-ID"] = account_id
    return headers


def access_token_is_expiring(access_token: str, skew_seconds: int) -> bool:
    exp = _jwt_exp(access_token)
    if exp is None:
        return True
    return exp <= int(time.time()) + int(skew_seconds)


def _jwt_exp(access_token: str) -> int | None:
    claims = _jwt_claims(access_token)
    exp = claims.get("exp") if isinstance(claims, dict) else None
    return int(exp) if isinstance(exp, (int, float)) else None


def _chatgpt_account_id(access_token: str) -> str | None:
    claims = _jwt_claims(access_token)
    auth_claims = claims.get("https://api.openai.com/auth") if isinstance(claims, dict) else None
    account_id = auth_claims.get("chatgpt_account_id") if isinstance(auth_claims, dict) else None
    return account_id if isinstance(account_id, str) and account_id else None


def _jwt_claims(access_token: str) -> dict[str, Any]:
    try:
        parts = str(access_token).split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        data = base64.urlsafe_b64decode(payload.encode("ascii"))
        decoded = json.loads(data)
        return decoded if isinstance(decoded, dict) else {}
    except Exception:
        return {}


def _extract_image_result(data: Any) -> str | None:
    if isinstance(data, dict):
        if data.get("type") == "image_generation_call" and isinstance(data.get("result"), str):
            return data["result"]
        for value in data.values():
            found = _extract_image_result(value)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _extract_image_result(item)
            if found:
                return found
    return None


def _extract_error(data: Any, *, default_code: str) -> tuple[str, str]:
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            code = str(err.get("code") or err.get("type") or default_code)
            message = str(err.get("message") or f"Codex request failed ({code}).")
            return code, message
        if isinstance(err, str):
            return err, str(data.get("error_description") or data.get("message") or err)
        message = data.get("message")
        if isinstance(message, str) and message:
            return default_code, message
    return default_code, "Codex request failed."


def _decode_json_response(response: HTTPResponse) -> Any:
    if not response.body:
        return None
    try:
        return json.loads(response.body.decode("utf-8"))
    except Exception:
        return response.body.decode("utf-8", errors="replace")


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
