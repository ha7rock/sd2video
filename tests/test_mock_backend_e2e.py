from __future__ import annotations

import unittest

from sd2video.server import MockVideoBackend, ServerConfig, create_app

from tests.test_server import request


class MockBackendE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = ServerConfig(
            mock=True,
            poll_interval_seconds=0.01,
            poll_timeout_seconds=1.0,
        )
        self.app = create_app(self.config, MockVideoBackend(self.config))

    def test_create_poll_result_preview_history_recovery_and_delete(self) -> None:
        create_body = {
            "mode": "t2v",
            "model": "doubao-seedance-2-0-fast-260128",
            "prompt": "A red ball rolls across a white floor.",
            "ratio": "16:9",
            "resolution": "480p",
            "duration": 4,
            "client_request_id": "e2e-success-1",
        }
        status, _, created = request(self.app, "POST", "/api/v1/tasks", body=create_body)
        self.assertEqual(201, status)
        task_id = created["task_id"]
        self.assertEqual("queued", created["status"])

        status, _, polled = request(
            self.app,
            "POST",
            f"/api/v1/tasks/{task_id}/poll",
            body={"interval_seconds": 0.01, "timeout_seconds": 1.0},
        )
        self.assertEqual(200, status)
        self.assertEqual("succeeded", polled["status"])
        self.assertTrue(polled["video_url"].startswith("data:video/mp4"))

        status, _, listed = request(self.app, "GET", "/api/v1/tasks?page_num=1&page_size=10")
        self.assertEqual(200, status)
        self.assertEqual(1, listed["total"])
        self.assertEqual(task_id, listed["items"][0]["task_id"])

        status, _, recovered = request(self.app, "GET", f"/api/v1/tasks/{task_id}")
        self.assertEqual(200, status)
        self.assertEqual("succeeded", recovered["status"])
        self.assertEqual(polled["video_url"], recovered["video_url"])

        status, _, deleted = request(
            self.app,
            "DELETE",
            f"/api/v1/tasks/{task_id}",
            body={"current_status": "succeeded"},
        )
        self.assertEqual(200, status)
        self.assertTrue(deleted["deleted"])
        self.assertEqual("deleted", deleted["status"])

    def test_cancel_running_task_and_preserve_history(self) -> None:
        status, _, created = request(
            self.app,
            "POST",
            "/api/v1/tasks",
            body={
                "mode": "t2v",
                "model": "doubao-seedance-2-0-fast-260128",
                "prompt": "A blue cube rotates slowly.",
                "ratio": "1:1",
                "resolution": "480p",
                "duration": 4,
                "client_request_id": "e2e-cancel-1",
            },
        )
        self.assertEqual(201, status)
        task_id = created["task_id"]

        status, _, running = request(self.app, "GET", f"/api/v1/tasks/{task_id}")
        self.assertEqual(200, status)
        self.assertEqual("running", running["status"])

        status, _, cancelled = request(
            self.app,
            "DELETE",
            f"/api/v1/tasks/{task_id}",
            body={"current_status": "running"},
        )
        self.assertEqual(200, status)
        self.assertEqual("cancelled", cancelled["status"])

        status, _, recovered = request(self.app, "GET", f"/api/v1/tasks/{task_id}")
        self.assertEqual(200, status)
        self.assertEqual("cancelled", recovered["status"])

    def test_duplicate_create_and_invalid_payload_do_not_create_extra_history(self) -> None:
        payload = {
            "mode": "t2v",
            "model": "doubao-seedance-2-0-fast-260128",
            "prompt": "A yellow triangle floats.",
            "client_request_id": "e2e-duplicate-1",
        }
        status, _, created = request(self.app, "POST", "/api/v1/tasks", body=payload)
        self.assertEqual(201, status)

        status, _, duplicate = request(self.app, "POST", "/api/v1/tasks", body=payload)
        self.assertEqual(409, status)
        self.assertEqual("duplicate_request", duplicate["error"]["code"])
        self.assertEqual(created["task_id"], duplicate["existing"]["task_id"])

        status, _, invalid = request(
            self.app,
            "POST",
            "/api/v1/tasks",
            body={
                "mode": "edit",
                "model": "doubao-seedance-2-0-fast-260128",
                "prompt": "Edit this",
                "assets": {"edit_video": "blob:http://localhost/private"},
            },
        )
        self.assertEqual(415, status)
        self.assertEqual("unsupported_media_type", invalid["error"]["code"])

        status, _, listed = request(self.app, "GET", "/api/v1/tasks")
        self.assertEqual(200, status)
        self.assertEqual(1, listed["total"])


if __name__ == "__main__":
    unittest.main()
