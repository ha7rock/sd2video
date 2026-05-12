"""Tiny local HTTP bridge for Codex OAuth image generation."""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .local_images import (
    CodexOAuthClient,
    LocalImageAuthError,
    LocalImageError,
    LocalImageFeatureDisabled,
    LocalImageService,
    default_cache_dir,
)


class LocalImageHandler(BaseHTTPRequestHandler):
    service: LocalImageService = LocalImageService()

    def do_OPTIONS(self) -> None:
        self._send_json(204, None)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/v1/local-images/status":
            self._send_json(200, self.service.status())
            return
        if path.startswith("/api/v1/local-images/assets/"):
            self._send_asset(path.rsplit("/", 1)[-1])
            return
        self._send_json(404, {"success": False, "error": "not found", "code": "not_found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/v1/local-images/generate":
            self._send_json(404, {"success": False, "error": "not found", "code": "not_found"})
            return
        try:
            payload = self._read_json()
            result = self.service.generate(payload)
        except LocalImageFeatureDisabled as exc:
            self._send_json(404, _error_payload(exc))
        except LocalImageAuthError as exc:
            self._send_json(401, _error_payload(exc))
        except LocalImageError as exc:
            self._send_json(400, _error_payload(exc))
        except Exception:
            self._send_json(
                500,
                {
                    "success": False,
                    "error": "Local image generation failed.",
                    "code": "internal_error",
                },
            )
        else:
            self._send_json(200, result)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        raw_len = int(self.headers.get("Content-Length", "0") or "0")
        if raw_len > 64 * 1024:
            raise LocalImageError("Request body is too large.", code="body_too_large")
        raw = self.rfile.read(raw_len)
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise LocalImageError("Request body must be JSON.", code="invalid_json") from exc
        if not isinstance(data, dict):
            raise LocalImageError("Request JSON must be an object.", code="invalid_json")
        return data

    def _send_json(self, status: int, payload: Any) -> None:
        body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _send_asset(self, raw_name: str) -> None:
        name = unquote(raw_name)
        if "/" in name or "\\" in name or name.startswith("."):
            self._send_json(404, {"success": False, "error": "not found", "code": "not_found"})
            return
        path = default_cache_dir() / name
        try:
            resolved = path.resolve()
            root = default_cache_dir().resolve()
        except OSError:
            self._send_json(404, {"success": False, "error": "not found", "code": "not_found"})
            return
        if root not in resolved.parents or not resolved.is_file():
            self._send_json(404, {"success": False, "error": "not found", "code": "not_found"})
            return
        content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        data = resolved.read_bytes()
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _error_payload(exc: LocalImageError) -> dict[str, Any]:
    return {"success": False, "error": exc.message, "code": exc.code}


def serve(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), LocalImageHandler)
    print(f"sd2video local image bridge listening on http://{host}:{port}")
    server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="sd2video local Codex image bridge")
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve_cmd = sub.add_parser("serve", help="run the local HTTP bridge")
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=8765)

    sub.add_parser("auth-login", help="run Codex device-code login into the sd2video token store")
    sub.add_parser("auth-clear", help="delete the sd2video Codex token store")

    args = parser.parse_args(argv)
    if args.cmd == "serve":
        serve(args.host, args.port)
        return 0
    if args.cmd == "auth-login":
        path = CodexOAuthClient().login_device_code()
        print(f"Saved sd2video Codex OAuth tokens to {path}")
        return 0
    if args.cmd == "auth-clear":
        client = CodexOAuthClient()
        path = Path(client.token_store_path)
        client.clear_tokens()
        print(f"Removed sd2video Codex OAuth tokens at {path}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
