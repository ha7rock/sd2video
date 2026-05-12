from __future__ import annotations

import base64
import json
import tempfile
import time
import unittest
from pathlib import Path

from sd2video.local_images import (
    CODEX_OAUTH_TOKEN_URL,
    CodexImageProvider,
    CodexOAuthClient,
    CodexTokenStore,
    HTTPResponse,
    LocalImageAPIError,
    LocalImageAuthError,
    LocalImageFeatureDisabled,
    LocalImageNetworkError,
    LocalImageRequest,
    LocalImageResult,
    LocalImageService,
    codex_backend_headers,
    default_auth_path,
)


class RecordingHTTPTransport:
    def __init__(
        self,
        responses: list[HTTPResponse] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.requests: list[dict] = []

    def post(self, url, *, headers, body, timeout):
        self.requests.append(
            {
                "url": url,
                "headers": dict(headers),
                "body": body,
                "timeout": timeout,
            }
        )
        if self.error:
            raise self.error
        if self.responses:
            return self.responses.pop(0)
        return HTTPResponse(200, {}, b"{}")


class StubProvider:
    def __init__(self, result: LocalImageResult | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.requests: list[LocalImageRequest] = []

    def generate(self, req: LocalImageRequest) -> LocalImageResult:
        self.requests.append(req)
        if self.error:
            raise self.error
        assert self.result is not None
        return self.result


def jwt_with_claims(claims: dict) -> str:
    def enc(obj: dict) -> str:
        raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{enc({'alg': 'none'})}.{enc(claims)}."


class LocalImageServiceTests(unittest.TestCase):
    def test_feature_flag_disabled_rejects_generation(self) -> None:
        service = LocalImageService(provider=StubProvider(), environ={})

        with self.assertRaises(LocalImageFeatureDisabled):
            service.generate({"prompt": "cat"})

    def test_enabled_generation_returns_local_reference_asset_without_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "img.png"
            path.write_bytes(b"png")
            provider = StubProvider(
                LocalImageResult(
                    id="asset-1",
                    file_path=path,
                    prompt="  a quiet courtyard  ",
                    size="1024x1024",
                    quality="medium",
                    background="opaque",
                    output_format="png",
                )
            )
            service = LocalImageService(
                provider=provider,
                environ={"SD2VIDEO_ENABLE_CODEX_IMAGE": "1"},
            )

            result = service.generate(
                {
                    "prompt": "  a quiet courtyard  ",
                    "size": "1536x1024",
                    "quality": "high",
                    "background": "transparent",
                    "output_format": "webp",
                }
            )

        self.assertTrue(result["success"])
        self.assertEqual("image", result["asset"]["kind"])
        self.assertEqual("local-codex-oauth", result["asset"]["source"])
        self.assertEqual("本地临时 / Codex OAuth / 非 Ark 生成", result["asset"]["provider_label"])
        self.assertEqual("1536x1024", provider.requests[0].size)
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("access_token", serialized)
        self.assertNotIn("refresh_token", serialized)
        self.assertNotIn("account_id", serialized)

    def test_service_surfaces_auth_and_network_failures_from_mock_provider(self) -> None:
        auth_service = LocalImageService(
            provider=StubProvider(error=LocalImageAuthError("login", code="auth_required")),
            environ={"SD2VIDEO_ENABLE_CODEX_IMAGE": "1"},
        )
        with self.assertRaises(LocalImageAuthError):
            auth_service.generate({"prompt": "cat"})

        network_service = LocalImageService(
            provider=StubProvider(error=LocalImageNetworkError("offline", code="network_error")),
            environ={"SD2VIDEO_ENABLE_CODEX_IMAGE": "1"},
        )
        with self.assertRaises(LocalImageNetworkError):
            network_service.generate({"prompt": "cat"})


class CodexTokenStoreTests(unittest.TestCase):
    def test_token_store_uses_project_path_and_never_codex_auth_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sd2video" / "codex_oauth.json"
            store = CodexTokenStore(path)
            store.save_tokens({"access_token": "aaa.bbb.ccc", "refresh_token": "rrr"})

            self.assertEqual(path, store.path)
            self.assertNotIn(".codex", str(store.path))
            self.assertEqual("aaa.bbb.ccc", store.load_tokens()["access_token"])
            self.assertTrue(path.exists())

    def test_default_auth_path_is_sd2video_not_codex(self) -> None:
        self.assertIn(".sd2video", str(default_auth_path()))
        self.assertNotIn(".codex", str(default_auth_path()))


class CodexImageProviderTests(unittest.TestCase):
    def test_success_posts_responses_image_generation_and_saves_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            token = jwt_with_claims(
                {
                    "exp": int(time.time()) + 3600,
                    "https://api.openai.com/auth": {"chatgpt_account_id": "acct_123"},
                }
            )
            store = CodexTokenStore(Path(tmp) / "auth.json")
            store.save_tokens({"access_token": token, "refresh_token": "refresh"})
            image_b64 = base64.b64encode(b"image-bytes").decode("ascii")
            transport = RecordingHTTPTransport(
                [
                    HTTPResponse(
                        200,
                        {},
                        json.dumps(
                            {
                                "output": [
                                    {"type": "image_generation_call", "result": image_b64}
                                ]
                            }
                        ).encode("utf-8"),
                    )
                ]
            )
            provider = CodexImageProvider(
                oauth_client=CodexOAuthClient(token_store=store, transport=transport),
                transport=transport,
                cache_dir=Path(tmp) / "images",
                base_url="https://codex.test",
                chat_model="gpt-test",
            )

            result = provider.generate(
                LocalImageRequest(
                    prompt="cat",
                    size="1024x1536",
                    quality="low",
                    background="opaque",
                    output_format="png",
                )
            )

            request = transport.requests[0]
            body = json.loads(request["body"].decode("utf-8"))
            self.assertEqual("https://codex.test/responses", request["url"])
            self.assertEqual(f"Bearer {token}", request["headers"]["Authorization"])
            self.assertEqual("codex_cli_rs", request["headers"]["originator"])
            self.assertEqual("acct_123", request["headers"]["ChatGPT-Account-ID"])
            self.assertEqual("gpt-test", body["model"])
            self.assertFalse(body["store"])
            self.assertEqual("image_generation", body["tools"][0]["type"])
            self.assertEqual("gpt-image-2", body["tools"][0]["model"])
            self.assertEqual("1024x1536", body["tools"][0]["size"])
            self.assertEqual("low", body["tools"][0]["quality"])
            self.assertEqual(b"image-bytes", result.file_path.read_bytes())

    def test_401_refreshes_token_once_and_retries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_token = jwt_with_claims({"exp": int(time.time()) + 3600})
            new_token = jwt_with_claims({"exp": int(time.time()) + 3600})
            store = CodexTokenStore(Path(tmp) / "auth.json")
            store.save_tokens({"access_token": old_token, "refresh_token": "refresh-old"})
            image_b64 = base64.b64encode(b"ok").decode("ascii")
            transport = RecordingHTTPTransport(
                [
                    HTTPResponse(401, {}, b'{"error":{"code":"expired","message":"expired"}}'),
                    HTTPResponse(
                        200,
                        {},
                        json.dumps(
                            {"access_token": new_token, "refresh_token": "refresh-new"}
                        ).encode("utf-8"),
                    ),
                    HTTPResponse(
                        200,
                        {},
                        json.dumps(
                            {"output": [{"type": "image_generation_call", "result": image_b64}]}
                        ).encode("utf-8"),
                    ),
                ]
            )
            provider = CodexImageProvider(
                oauth_client=CodexOAuthClient(token_store=store, transport=transport),
                transport=transport,
                cache_dir=Path(tmp) / "images",
                base_url="https://codex.test",
            )

            result = provider.generate(LocalImageRequest(prompt="cat"))

            self.assertEqual(b"ok", result.file_path.read_bytes())
            self.assertEqual(3, len(transport.requests))
            self.assertEqual(CODEX_OAUTH_TOKEN_URL, transport.requests[1]["url"])
            self.assertEqual(f"Bearer {new_token}", transport.requests[2]["headers"]["Authorization"])
            self.assertEqual("refresh-new", store.load_tokens()["refresh_token"])

    def test_api_failure_raises_without_leaking_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            token = jwt_with_claims({"exp": int(time.time()) + 3600})
            store = CodexTokenStore(Path(tmp) / "auth.json")
            store.save_tokens({"access_token": token, "refresh_token": "refresh"})
            transport = RecordingHTTPTransport(
                [
                    HTTPResponse(
                        500,
                        {},
                        b'{"error":{"code":"server_error","message":"generation failed"}}',
                    )
                ]
            )
            provider = CodexImageProvider(
                oauth_client=CodexOAuthClient(token_store=store, transport=transport),
                transport=transport,
                cache_dir=Path(tmp) / "images",
                base_url="https://codex.test",
            )

            with self.assertRaises(LocalImageAPIError) as ctx:
                provider.generate(LocalImageRequest(prompt="cat"))

        self.assertEqual("server_error", ctx.exception.code)
        self.assertNotIn(token, str(ctx.exception))

    def test_codex_headers_tolerate_malformed_token(self) -> None:
        headers = codex_backend_headers("not-a-jwt")
        self.assertEqual("codex_cli_rs", headers["originator"])
        self.assertNotIn("ChatGPT-Account-ID", headers)


if __name__ == "__main__":
    unittest.main()
