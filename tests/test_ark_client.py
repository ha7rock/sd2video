from __future__ import annotations

import json
import unittest
from urllib.parse import parse_qs, urlsplit

from sd2video.ark import (
    ArkAPIError,
    ArkAuthenticationError,
    ArkClient,
    ArkConfig,
    ArkConfigError,
    ArkHTTPResponse,
    ArkNetworkError,
    ArkParameterError,
    ArkRequest,
    ArkTaskDeleteError,
    ArkTimeoutError,
)


class RecordingTransport:
    def __init__(
        self,
        response: ArkHTTPResponse | list[ArkHTTPResponse] | None = None,
        error: Exception | None = None,
    ) -> None:
        if isinstance(response, list):
            self.responses = response
        else:
            self.responses = [response or ArkHTTPResponse(200, {}, b"{}")]
        self.error = error
        self.requests: list[ArkRequest] = []
        self.timeout: float | None = None

    def send(self, request: ArkRequest, timeout: float) -> ArkHTTPResponse:
        self.requests.append(request)
        self.timeout = timeout
        if self.error:
            raise self.error
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


class ArkClientTests(unittest.TestCase):
    def test_request_tasks_adds_headers_base_url_and_timeout(self) -> None:
        transport = RecordingTransport(
            ArkHTTPResponse(200, {"Content-Type": "application/json"}, b'{"id":"task-1"}')
        )
        client = ArkClient(
            ArkConfig(
                api_key="test-key",
                base_url="https://example.test/",
                timeout_seconds=9.5,
            ),
            transport=transport,
        )

        response = client.request_tasks("post", json={"prompt": "hello"})

        request = transport.requests[0]
        self.assertEqual("POST", request.method)
        self.assertEqual(
            "https://example.test/api/v3/contents/generations/tasks",
            request.url,
        )
        self.assertEqual("Bearer test-key", request.headers["Authorization"])
        self.assertEqual("application/json", request.headers["Content-Type"])
        self.assertIn("<redacted>", repr(request))
        self.assertNotIn("test-key", repr(request))
        self.assertEqual(9.5, transport.timeout)
        self.assertEqual({"prompt": "hello"}, json.loads(request.body or b"{}"))
        self.assertEqual({"id": "task-1"}, response.data)

    def test_request_tasks_builds_task_url_and_query(self) -> None:
        transport = RecordingTransport()
        client = ArkClient(
            ArkConfig(api_key="test-key", base_url="https://proxy.test/base"),
            transport=transport,
        )

        client.request_tasks(
            "get",
            task_id="task/one",
            query={"limit": 20, "cursor": "a b", "skip": None},
        )

        parsed = urlsplit(transport.requests[0].url)
        self.assertEqual(
            "https://proxy.test/base/api/v3/contents/generations/tasks/task%2Fone",
            f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
        )
        self.assertEqual({"limit": ["20"], "cursor": ["a b"]}, parse_qs(parsed.query))

    def test_delete_task_sends_delete_and_refreshes_status(self) -> None:
        transport = RecordingTransport(
            [
                ArkHTTPResponse(200, {}, b"{}"),
                ArkHTTPResponse(200, {}, b'{"data":{"status":"cancelled"}}'),
            ]
        )
        client = ArkClient(
            ArkConfig(api_key="test-key", base_url="https://example.test"),
            transport=transport,
        )

        result = client.delete_task("cgt-123", current_status="running")

        delete_request = transport.requests[0]
        self.assertEqual("DELETE", delete_request.method)
        self.assertEqual(
            "https://example.test/api/v3/contents/generations/tasks/cgt-123",
            delete_request.url,
        )
        self.assertEqual("Bearer test-key", delete_request.headers["Authorization"])
        self.assertEqual("application/json", delete_request.headers["Content-Type"])
        self.assertIsNone(delete_request.body)
        self.assertEqual("GET", transport.requests[1].method)
        self.assertEqual("cancelled", result.status)
        self.assertEqual("cancelled", result.remote_status)
        self.assertTrue(result.deleted)
        self.assertTrue(result.refreshed)

    def test_delete_task_accepts_camel_case_alias(self) -> None:
        transport = RecordingTransport(ArkHTTPResponse(200, {}, b"{}"))
        client = ArkClient(ArkConfig(api_key="test-key"), transport=transport)

        result = client.deleteTask("cgt-123", refresh=False)

        self.assertEqual("DELETE", transport.requests[0].method)
        self.assertEqual("deleted", result.status)

    def test_delete_task_treats_missing_after_refresh_as_deleted(self) -> None:
        transport = RecordingTransport(
            [
                ArkHTTPResponse(200, {}, b"{}"),
                ArkHTTPResponse(
                    404,
                    {},
                    b'{"error":{"code":"NotFound","message":"task missing"}}',
                ),
            ]
        )
        client = ArkClient(ArkConfig(api_key="test-key"), transport=transport)

        result = client.delete_task("cgt-123")

        self.assertEqual("deleted", result.status)
        self.assertEqual("deleted", result.remote_status)
        self.assertTrue(result.refreshed)
        self.assertIn("no longer returned", result.message or "")

    def test_delete_task_rejects_invalid_ids_without_request(self) -> None:
        transport = RecordingTransport()
        client = ArkClient(ArkConfig(api_key="test-key"), transport=transport)

        for task_id in ("", "   ", "task with spaces", "task/one", "task\\one"):
            with self.subTest(task_id=task_id):
                with self.assertRaises(ArkParameterError):
                    client.delete_task(task_id)

        self.assertEqual([], transport.requests)

    def test_delete_task_rejects_unknown_local_status_without_request(self) -> None:
        transport = RecordingTransport()
        client = ArkClient(ArkConfig(api_key="test-key"), transport=transport)

        with self.assertRaises(ArkParameterError):
            client.delete_task("cgt-123", current_status="paused")

        self.assertEqual([], transport.requests)

    def test_delete_task_skips_when_already_deleted_locally(self) -> None:
        transport = RecordingTransport()
        client = ArkClient(ArkConfig(api_key="test-key"), transport=transport)

        result = client.delete_task("cgt-123", current_status="deleted")

        self.assertEqual("deleted", result.status)
        self.assertTrue(result.deleted)
        self.assertIsNone(result.response)
        self.assertEqual([], transport.requests)

    def test_delete_task_maps_duplicate_or_missing_delete_to_readable_error(self) -> None:
        transport = RecordingTransport(
            ArkHTTPResponse(
                404,
                {"X-Request-Id": "req-delete"},
                b'{"error":{"code":"NotFound","message":"missing"}}',
            )
        )
        client = ArkClient(ArkConfig(api_key="test-key"), transport=transport)

        with self.assertRaises(ArkTaskDeleteError) as raised:
            client.delete_task("cgt-123")

        error = raised.exception
        self.assertEqual(404, error.status_code)
        self.assertEqual("cgt-123", error.task_id)
        self.assertIn("not found", str(error))
        self.assertIn("already been deleted", str(error))

    def test_delete_task_maps_forbidden_delete_to_readable_error(self) -> None:
        transport = RecordingTransport(
            ArkHTTPResponse(
                403,
                {},
                b'{"error":{"code":"Forbidden","message":"denied"}}',
            )
        )
        client = ArkClient(ArkConfig(api_key="test-key"), transport=transport)

        with self.assertRaises(ArkTaskDeleteError) as raised:
            client.delete_task("cgt-123")

        self.assertEqual(403, raised.exception.status_code)
        self.assertIn("No permission", str(raised.exception))

    def test_config_from_env_supports_key_base_url_model_and_timeout(self) -> None:
        config = ArkConfig.from_env(
            {
                "ARK_API_KEY": " env-key ",
                "ARK_BASE_URL": "https://env.test/",
                "ARK_DEFAULT_MODEL_ID": "model-from-env",
                "ARK_TIMEOUT_SECONDS": "4.25",
            }
        )

        self.assertEqual("env-key", config.api_key)
        self.assertEqual("https://env.test", config.base_url)
        self.assertEqual("model-from-env", config.default_model_id)
        self.assertEqual(4.25, config.timeout_seconds)
        self.assertNotIn("env-key", repr(config))

    def test_config_rejects_missing_api_key(self) -> None:
        with self.assertRaises(ArkConfigError):
            ArkConfig.from_env({})

    def test_authentication_error_is_mapped_and_redacts_api_key(self) -> None:
        api_key = "secret-token"
        transport = RecordingTransport(
            ArkHTTPResponse(
                401,
                {"X-Request-Id": "req-1"},
                b'{"error":{"code":"Unauthorized","message":"bad secret-token"}}',
            )
        )
        client = ArkClient(ArkConfig(api_key=api_key), transport=transport)

        with self.assertRaises(ArkAuthenticationError) as raised:
            client.request_tasks("get")

        error = raised.exception
        self.assertEqual(401, error.status_code)
        self.assertEqual("Unauthorized", error.code)
        self.assertIn("<redacted>", str(error))
        self.assertNotIn(api_key, str(error))

    def test_parameter_error_is_mapped_from_top_level_error_body(self) -> None:
        transport = RecordingTransport(
            ArkHTTPResponse(400, {}, b'{"code":"InvalidParameter","message":"bad prompt"}')
        )
        client = ArkClient(ArkConfig(api_key="test-key"), transport=transport)

        with self.assertRaises(ArkParameterError) as raised:
            client.request_tasks("post", json={"prompt": ""})

        self.assertEqual(400, raised.exception.status_code)
        self.assertEqual("InvalidParameter", raised.exception.code)
        self.assertIn("bad prompt", str(raised.exception))

    def test_generic_api_error_preserves_request_id(self) -> None:
        transport = RecordingTransport(
            ArkHTTPResponse(
                500,
                {"X-Tt-Logid": "log-1"},
                b'{"error":{"code":"InternalError","message":"try again"}}',
            )
        )
        client = ArkClient(ArkConfig(api_key="test-key"), transport=transport)

        with self.assertRaises(ArkAPIError) as raised:
            client.request_tasks("get")

        self.assertEqual(500, raised.exception.status_code)
        self.assertEqual("InternalError", raised.exception.code)
        self.assertEqual("log-1", raised.exception.request_id)

    def test_transport_timeout_is_mapped(self) -> None:
        client = ArkClient(
            ArkConfig(api_key="test-key"),
            transport=RecordingTransport(error=TimeoutError("too slow")),
        )

        with self.assertRaises(ArkTimeoutError):
            client.request_tasks("get")

    def test_transport_os_error_is_mapped_to_network_error(self) -> None:
        client = ArkClient(
            ArkConfig(api_key="test-key"),
            transport=RecordingTransport(error=OSError("dns failure")),
        )

        with self.assertRaises(ArkNetworkError):
            client.request_tasks("get")


if __name__ == "__main__":
    unittest.main()
