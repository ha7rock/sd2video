from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any

from sd2video.ark import ArkAuthenticationError, ArkNetworkError
from sd2video.server import MockVideoBackend, ServerConfig, create_app
from sd2video.server.service import VideoBackend


class BrokenBackend(VideoBackend):
    def __init__(self, error: Exception) -> None:
        super().__init__(ServerConfig())
        self.error = error

    def create_task(self, payload):
        raise self.error

    def get_task(self, task_id):
        raise self.error

    def list_tasks(self, *, page_num=1, page_size=10, status_filter=None, task_ids=None):
        raise self.error

    def delete_task(self, task_id, *, current_status=None):
        raise self.error


async def asgi_request(
    app,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], Any]:
    raw_body = b"" if body is None else json.dumps(body).encode("utf-8")
    sent: list[dict[str, Any]] = []
    received = False

    async def receive() -> dict[str, Any]:
        nonlocal received
        if received:
            return {"type": "http.request", "body": b"", "more_body": False}
        received = True
        return {"type": "http.request", "body": raw_body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    raw_headers = [
        (key.lower().encode("ascii"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    path_only, _, query = path.partition("?")
    await app(
        {
            "type": "http",
            "method": method,
            "path": path_only,
            "query_string": query.encode("ascii"),
            "headers": raw_headers,
        },
        receive,
        send,
    )

    start = sent[0]
    body_message = sent[1]
    response_headers = {
        key.decode("latin-1"): value.decode("latin-1")
        for key, value in start["headers"]
    }
    response_body = body_message.get("body", b"")
    data = None if not response_body else json.loads(response_body.decode("utf-8"))
    return start["status"], response_headers, data


def request(app, method: str, path: str, **kwargs):
    return asyncio.run(asgi_request(app, method, path, **kwargs))


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = ServerConfig(
            mock=True,
            cors_origins=("http://localhost:5173",),
            poll_interval_seconds=0.01,
            poll_timeout_seconds=1.0,
        )
        self.app = create_app(self.config, MockVideoBackend(self.config))

    def test_health_config_and_capabilities_do_not_expose_api_key(self) -> None:
        status, _, health = request(self.app, "GET", "/api/v1/health")
        self.assertEqual(200, status)
        self.assertTrue(health["mock"])
        self.assertEqual("ok", health["status"])

        status, _, capabilities = request(self.app, "GET", "/api/v1/capabilities")
        self.assertEqual(200, status)
        self.assertIn("16:9", capabilities["ratios"])
        self.assertIn("1080p", capabilities["resolutions"])
        self.assertIn("limits", capabilities)
        self.assertIn("default_model", capabilities)
        self.assertNotIn("api_key", json.dumps(capabilities).lower())

    def test_mock_task_create_get_list_poll_and_delete_flow(self) -> None:
        status, _, created = request(
            self.app,
            "POST",
            "/api/v1/tasks",
            body={
                "mode": "t2v",
                "model": "doubao-seedance-2-0-fast-260128",
                "prompt": "test video",
                "ratio": "16:9",
                "duration": 5,
                "client_request_id": "req-1",
            },
        )
        self.assertEqual(201, status)
        task_id = created["task_id"]
        self.assertTrue(task_id.startswith("cgt-mock-"))
        self.assertEqual("queued", created["status"])
        self.assertTrue(created["submitted_payload_digest"].startswith("sha256:"))

        status, _, duplicate = request(
            self.app,
            "POST",
            "/api/v1/tasks",
            body={
                "mode": "t2v",
                "model": "doubao-seedance-2-0-fast-260128",
                "prompt": "test video",
                "client_request_id": "req-1",
            },
        )
        self.assertEqual(409, status)
        self.assertEqual("duplicate_request", duplicate["error"]["code"])
        self.assertEqual(task_id, duplicate["existing"]["task_id"])

        status, _, detail = request(self.app, "GET", f"/api/v1/tasks/{task_id}")
        self.assertEqual(200, status)
        self.assertEqual(task_id, detail["task_id"])
        self.assertEqual("running", detail["status"])

        status, _, detail = request(self.app, "GET", f"/api/v1/tasks/{task_id}")
        self.assertEqual(200, status)
        self.assertEqual("succeeded", detail["status"])
        self.assertTrue(detail["video_url"].startswith("data:video/mp4"))

        status, _, listed = request(self.app, "GET", "/api/v1/tasks?page_num=1&page_size=10")
        self.assertEqual(200, status)
        self.assertEqual(1, listed["total"])
        self.assertEqual(task_id, listed["items"][0]["task_id"])

        status, _, filtered = request(self.app, "GET", f"/api/v1/tasks?task_ids={task_id}")
        self.assertEqual(200, status)
        self.assertEqual(1, filtered["total"])
        self.assertEqual(task_id, filtered["items"][0]["task_id"])

        status, _, deleted = request(
            self.app,
            "DELETE",
            f"/api/v1/tasks/{task_id}",
            body={"current_status": "succeeded"},
        )
        self.assertEqual(200, status)
        self.assertTrue(deleted["deleted"])
        self.assertEqual("deleted", deleted["status"])

    def test_create_validation_error_is_mapped(self) -> None:
        status, _, body = request(self.app, "POST", "/api/v1/tasks", body={"mode": "t2v", "prompt": ""})
        self.assertEqual(400, status)
        self.assertEqual("parameter_invalid", body["error"]["code"])

    def test_missing_task_is_mapped_to_not_found(self) -> None:
        status, _, body = request(self.app, "GET", "/api/v1/tasks/missing")
        self.assertEqual(404, status)
        self.assertEqual("task_not_found", body["error"]["code"])

    def test_cors_only_allows_configured_origin(self) -> None:
        status, headers, _ = request(
            self.app,
            "OPTIONS",
            "/api/v1/tasks",
            headers={"origin": "http://localhost:5173"},
        )
        self.assertEqual(204, status)
        self.assertEqual("http://localhost:5173", headers["access-control-allow-origin"])

        status, headers, _ = request(
            self.app,
            "OPTIONS",
            "/api/v1/tasks",
            headers={"origin": "http://evil.test"},
        )
        self.assertEqual(204, status)
        self.assertNotIn("access-control-allow-origin", headers)

    def test_authentication_and_network_errors_are_mapped(self) -> None:
        app = create_app(self.config, BrokenBackend(ArkAuthenticationError("denied")))
        status, _, body = request(app, "GET", "/api/v1/tasks")
        self.assertEqual(401, status)
        self.assertEqual("upstream_unauthorized", body["error"]["code"])

        app = create_app(self.config, BrokenBackend(ArkNetworkError("dns failure")))
        status, _, body = request(app, "GET", "/api/v1/tasks")
        self.assertEqual(502, status)
        self.assertEqual("upstream_failed", body["error"]["code"])


if __name__ == "__main__":
    unittest.main()
