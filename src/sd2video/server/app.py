"""Minimal ASGI app exposing the sd2video backend to local frontends."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import parse_qs

from sd2video.ark import ArkConfigError

from .capabilities import build_capabilities
from .config import ServerConfig
from .errors import map_exception
from .service import (
    VideoBackend,
    build_backend,
    serialize_delete,
    serialize_list,
    serialize_task,
)

Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
Scope = Mapping[str, Any]


class Sd2VideoASGIApp:
    def __init__(self, config: ServerConfig, backend: VideoBackend) -> None:
        self.config = config
        self.backend = backend
        self._started_at = time.monotonic()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            raise RuntimeError("sd2video server only supports HTTP scopes")

        request = Request(scope, receive)
        try:
            if request.method == "OPTIONS":
                await self._send_json(send, request, 204, None)
                return
            status, body = await self._dispatch(request)
        except Exception as exc:
            status, body = map_exception(exc, request_id=request.request_id)
        await self._send_json(send, request, status, body)

    async def _dispatch(self, request: "Request") -> tuple[int, Any]:
        path = request.path.rstrip("/") or "/"
        method = request.method

        if method == "GET" and path == "/api/v1/health":
            return 200, {
                "status": "ok",
                "version": self.config.version,
                "mock": self.config.mock,
                "uptime_seconds": int(time.monotonic() - self._started_at),
            }

        if method == "GET" and path == "/api/v1/capabilities":
            return 200, build_capabilities(
                default_model_id=self.config.default_model_id,
                poll_interval_seconds=self.config.poll_interval_seconds,
                poll_timeout_seconds=self.config.poll_timeout_seconds,
            )

        if path == "/api/v1/tasks":
            if method == "POST":
                payload = await request.json()
                return 201, self.backend.create_task(payload)
            if method == "GET":
                params = request.query
                result = self.backend.list_tasks(
                    page_num=_int_param(params, "page_num", 1),
                    page_size=_int_param(params, "page_size", 10),
                    status_filter=_list_param(params, "status"),
                    task_ids=_list_values(params, "task_ids"),
                )
                return 200, serialize_list(result)

        task_id, action = _task_route(path)
        if task_id:
            if method == "GET" and action is None:
                return 200, serialize_task(self.backend.get_task(task_id))
            if method == "DELETE" and action is None:
                payload = await request.json(required=False)
                return 200, serialize_delete(
                    self.backend.delete_task(
                        task_id,
                        current_status=payload.get("current_status"),
                    )
                )
            if method == "POST" and action == "poll":
                payload = await request.json(required=False)
                detail = self.backend.poll_task(
                    task_id,
                    interval_seconds=float(
                        payload.get(
                            "interval_seconds",
                            self.config.poll_interval_seconds,
                        )
                    ),
                    timeout_seconds=float(
                        payload.get(
                            "timeout_seconds",
                            self.config.poll_timeout_seconds,
                        )
                    ),
                )
                return 200, serialize_task(detail)

        return 404, {
            "error": {
                "code": "task_not_found" if path.startswith("/api/v1/tasks/") else "parameter_invalid",
                "message": "Endpoint not found",
                "request_id": request.request_id,
            }
        }

    async def _send_json(
        self,
        send: Send,
        request: "Request",
        status: int,
        body: Any,
    ) -> None:
        headers = [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"cache-control", b"no-store"),
            (b"x-client-request-id", request.request_id.encode("ascii")),
        ]
        headers.extend(self._cors_headers(request))
        response_body = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": headers,
            }
        )
        await send({"type": "http.response.body", "body": response_body})

    def _cors_headers(self, request: "Request") -> list[tuple[bytes, bytes]]:
        origin = request.headers.get("origin", "").rstrip("/")
        allowed_origin = origin
        if origin == "null" and "file://" in self.config.cors_origins:
            allowed_origin = "null"
        elif origin not in self.config.cors_origins:
            return []
        return [
            (b"access-control-allow-origin", allowed_origin.encode("ascii")),
            (b"vary", b"Origin"),
            (b"access-control-allow-methods", b"GET,POST,DELETE,OPTIONS"),
            (b"access-control-allow-headers", b"Accept,Content-Type,X-Client-Request-Id"),
            (b"access-control-max-age", b"600"),
        ]


class Request:
    def __init__(self, scope: Scope, receive: Receive) -> None:
        self.scope = scope
        self.receive = receive
        self.method = str(scope.get("method", "GET")).upper()
        self.path = str(scope.get("path", "/"))
        self.query = parse_qs(scope.get("query_string", b"").decode("ascii"))
        self.headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        self.request_id = _request_id(self.headers)

    async def json(self, *, required: bool = True) -> Mapping[str, Any]:
        body = await self.body()
        if not body:
            if required:
                raise ValueError("JSON body is required")
            return {}
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Request body must be valid JSON") from exc
        if not isinstance(data, Mapping):
            raise ValueError("JSON body must be an object")
        return data

    async def body(self) -> bytes:
        chunks: list[bytes] = []
        more_body = True
        while more_body:
            message = await self.receive()
            chunks.append(message.get("body", b""))
            more_body = bool(message.get("more_body", False))
        return b"".join(chunks)


def create_app(
    config: ServerConfig | None = None,
    backend: VideoBackend | None = None,
) -> Sd2VideoASGIApp:
    config = config or ServerConfig.from_env()
    try:
        backend = backend or build_backend(config)
    except ArkConfigError:
        raise
    return Sd2VideoASGIApp(config, backend)


def _task_route(path: str) -> tuple[str | None, str | None]:
    parts = [part for part in path.split("/") if part]
    if len(parts) == 4 and parts[:3] == ["api", "v1", "tasks"]:
        return parts[3], None
    if len(parts) == 5 and parts[:3] == ["api", "v1", "tasks"]:
        return parts[3], parts[4]
    return None, None


def _int_param(params: Mapping[str, list[str]], key: str, default: int) -> int:
    values = params.get(key)
    if not values:
        return default
    return int(values[0])


def _list_param(params: Mapping[str, list[str]], key: str) -> str | list[str] | None:
    items = _list_values(params, key)
    if items is None:
        return None
    if len(items) == 1:
        return items[0]
    return items


def _list_values(params: Mapping[str, list[str]], key: str) -> list[str] | None:
    values = params.get(key)
    if not values:
        return None
    items: list[str] = []
    for value in values:
        items.extend(part.strip() for part in value.split(",") if part.strip())
    if not items:
        return None
    return items


def _request_id(headers: Mapping[str, str]) -> str:
    value = headers.get("x-client-request-id", "").strip()
    if value:
        return value
    return str(uuid.uuid4())
