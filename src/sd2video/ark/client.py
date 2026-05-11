"""Unified Volcengine Ark client entrypoint."""

from __future__ import annotations

import json as jsonlib
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, urlencode

from .config import ArkConfig
from .errors import (
    ArkAPIError,
    ArkAuthenticationError,
    ArkError,
    ArkNetworkError,
    ArkParameterError,
    ArkTimeoutError,
)
from .transport import ArkTransport, UrllibArkTransport
from .types import ArkHTTPResponse, ArkRequest, ArkResponse


class ArkClient:
    """Single client for Ark video generation task requests."""

    def __init__(
        self,
        config: ArkConfig,
        *,
        transport: ArkTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport or UrllibArkTransport()

    @classmethod
    def from_env(
        cls,
        *,
        transport: ArkTransport | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> "ArkClient":
        return cls(ArkConfig.from_env(environ), transport=transport)

    @property
    def config(self) -> ArkConfig:
        return self._config

    def request_tasks(
        self,
        method: str,
        *,
        task_id: str | None = None,
        query: Mapping[str, Any] | None = None,
        json: Any | None = None,
    ) -> ArkResponse:
        """Request the Ark video generation task resource without caller URL work."""

        return self.request(
            method,
            self._task_path(task_id),
            query=query,
            json=json,
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        json: Any | None = None,
    ) -> ArkResponse:
        request = ArkRequest(
            method=method.upper(),
            url=self._build_url(path, query=query),
            headers=self._headers(),
            body=self._encode_body(json),
        )

        try:
            http_response = self._transport.send(
                request,
                timeout=self._config.timeout_seconds,
            )
        except ArkError:
            raise
        except TimeoutError as exc:
            raise ArkTimeoutError("Ark request timed out") from exc
        except OSError as exc:
            raise ArkNetworkError("Ark network request failed") from exc

        data = self._decode_body(http_response.body)
        if http_response.status_code >= 400:
            raise self._map_error(http_response, data)
        return ArkResponse(
            status_code=http_response.status_code,
            headers=http_response.headers,
            data=data,
        )

    def _task_path(self, task_id: str | None) -> str:
        path = self._config.tasks_path
        if task_id is None:
            return path
        return f"{path}/{quote(task_id, safe='')}"

    def _build_url(
        self,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
    ) -> str:
        normalized_path = path if path.startswith("/") else f"/{path}"
        url = f"{self._config.base_url}{normalized_path}"
        if query:
            filtered_query = {key: value for key, value in query.items() if value is not None}
            if filtered_query:
                url = f"{url}?{urlencode(filtered_query, doseq=True)}"
        return url

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _encode_body(payload: Any | None) -> bytes | None:
        if payload is None:
            return None
        return jsonlib.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )

    @staticmethod
    def _decode_body(body: bytes) -> Any:
        if not body:
            return None
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            return body
        try:
            return jsonlib.loads(text)
        except jsonlib.JSONDecodeError:
            return text

    def _map_error(self, response: ArkHTTPResponse, data: Any) -> ArkAPIError:
        code, message, request_id = self._extract_error(data, response.headers)
        status_code = response.status_code
        error_type: type[ArkAPIError]
        if status_code in {401, 403}:
            error_type = ArkAuthenticationError
        elif status_code in {400, 422}:
            error_type = ArkParameterError
        else:
            error_type = ArkAPIError
        return error_type(
            message or "Ark API request failed",
            status_code=status_code,
            code=code,
            request_id=request_id,
        )

    def _extract_error(
        self,
        data: Any,
        headers: Mapping[str, str],
    ) -> tuple[str | None, str | None, str | None]:
        source: Mapping[str, Any] = {}
        message: str | None = None
        if isinstance(data, Mapping):
            error = data.get("error")
            if isinstance(error, Mapping):
                source = error
            else:
                source = data
                if isinstance(error, str):
                    message = error
        elif isinstance(data, str):
            message = data

        code = (source.get("code") or source.get("type")) if source else None
        message = (
            message
            or (source.get("message") if source else None)
            or (source.get("msg") if source else None)
            or (source.get("error_description") if source else None)
        )
        request_id = (
            _header(headers, "x-request-id")
            or _header(headers, "x-tt-logid")
            or (source.get("request_id") if source else None)
        )
        return (
            self._sanitize(code),
            self._sanitize(message),
            self._sanitize(request_id),
        )

    def _sanitize(self, value: Any | None) -> str | None:
        if value is None:
            return None
        text = str(value)
        if self._config.api_key:
            text = text.replace(self._config.api_key, "<redacted>")
        return text


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None
