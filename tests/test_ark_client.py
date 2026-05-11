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
    ArkTimeoutError,
)


class RecordingTransport:
    def __init__(
        self,
        response: ArkHTTPResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response or ArkHTTPResponse(200, {}, b"{}")
        self.error = error
        self.requests: list[ArkRequest] = []
        self.timeout: float | None = None

    def send(self, request: ArkRequest, timeout: float) -> ArkHTTPResponse:
        self.requests.append(request)
        self.timeout = timeout
        if self.error:
            raise self.error
        return self.response


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
