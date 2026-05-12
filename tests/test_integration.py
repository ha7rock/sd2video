"""End-to-end integration tests with mock transport (HOM-31).

These tests exercise the full stack from Workflow → ArkClient → Transport,
using a RecordingTransport to mock the HTTP layer. They cover:

Success paths:
  1. text-to-video: submit → poll queued→running→succeeded → video_url
  2. image-to-video: submit → immediate success
  3. list → select → delete → confirm cancelled

Failure / edge paths:
  4. submit → poll → failed with error message extraction
  5. submit → cancel before completion (cancelled during running)
  6. submit → poll → timeout
  7. auth error propagation through workflow
  8. network error propagation through workflow
  9. delete declined by user confirmation
  10. duplicate submission detection via task tracking

Parameter mapping tests:
  11. full parameter set mapping (resolution, ratio, duration, seed, etc.)
  12. default model fallback
  13. API key never leaks in errors
"""

from __future__ import annotations

import json
import unittest

from sd2video.ark import (
    ArkAuthenticationError,
    ArkClient,
    ArkConfig,
    ArkHTTPResponse,
    ArkNetworkError,
    ArkParameterError,
    ArkTaskDeleteError,
    ArkTimeoutError,
    TaskState,
    VideoGenerationWorkflow,
    WorkflowCallbacks,
    WorkflowConfig,
)


class RecordingTransport:
    """Test double that records requests and returns a sequence of canned responses."""

    def __init__(
        self,
        response: ArkHTTPResponse | list[ArkHTTPResponse] | None = None,
        error: Exception | None = None,
    ) -> None:
        if isinstance(response, list):
            self.responses = list(response)
        else:
            self.responses = [response or ArkHTTPResponse(200, {}, b"{}")]
        self.error = error
        self.requests = []
        self.timeout: float | None = None

    def send(self, request, timeout: float):
        self.requests.append(request)
        self.timeout = timeout
        if self.error:
            raise self.error
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


def _json_response(data: dict, status: int = 200) -> ArkHTTPResponse:
    return ArkHTTPResponse(status, {}, json.dumps(data).encode())


def _make_client(transport) -> ArkClient:
    return ArkClient(
        ArkConfig(api_key="test-key", default_model_id="doubao-seedance-2-0-fast-260128"),
        transport=transport,
    )


def _make_workflow(transport, **kwargs) -> VideoGenerationWorkflow:
    client = _make_client(transport)
    config = kwargs.pop("config", WorkflowConfig(poll_interval_seconds=0.01, poll_timeout_seconds=5))
    return VideoGenerationWorkflow(client, config=config, **kwargs)


# ---------------------------------------------------------------------------
# Success path 1: text-to-video full flow
# ---------------------------------------------------------------------------

class TestTextToVideoFullFlow(unittest.TestCase):
    """Submit text → poll queued→running→succeeded → get video_url."""

    def test_full_flow(self) -> None:
        transport = RecordingTransport([
            # POST create
            ArkHTTPResponse(200, {}, b'{"id":"cgt-full"}'),
            # GET poll 1: queued
            _json_response({"data": {"id": "cgt-full", "status": "queued"}}),
            # GET poll 2: running
            _json_response({"data": {"id": "cgt-full", "status": "running"}}),
            # GET poll 3: succeeded
            _json_response({"data": {
                "id": "cgt-full",
                "status": "succeeded",
                "model": {"id": "doubao-seedance-2-0"},
                "created_at": "2026-05-12T10:00:00Z",
                "updated_at": "2026-05-12T10:05:00Z",
                "content": [
                    {"type": "video_url", "video_url": {"url": "https://cdn.example.com/result.mp4"}},
                ],
            }}),
        ])
        wf = _make_workflow(transport)

        # Capture status transitions
        transitions = []
        wf._callbacks = WorkflowCallbacks(
            on_status_change=lambda tid, label: transitions.append((tid, label)),
        )

        state = wf.submit("A cat dancing in the rain", ratio="16:9", duration=5)
        self.assertEqual("cgt-full", state.task_id)
        self.assertEqual("queued", state.status)

        result = wf.wait(state.task_id)

        self.assertEqual("succeeded", result.status)
        self.assertEqual("https://cdn.example.com/result.mp4", result.video_url)
        self.assertTrue(result.succeeded)
        self.assertTrue(result.is_terminal)
        self.assertEqual("doubao-seedance-2-0", result.model)

        # Verify status transitions were recorded
        status_labels = [t[1] for t in transitions]
        self.assertIn("生成中", status_labels)
        self.assertIn("已完成", status_labels)

        # Verify POST body was correct
        sent = json.loads(transport.requests[0].body)
        self.assertEqual("text", sent["content"][0]["type"])
        self.assertEqual("A cat dancing in the rain", sent["content"][0]["text"])
        self.assertEqual("16:9", sent["ratio"])
        self.assertEqual(5, sent["duration"])


# ---------------------------------------------------------------------------
# Success path 2: image-to-video immediate success
# ---------------------------------------------------------------------------

class TestImageToVideoImmediateSuccess(unittest.TestCase):
    """Submit image-to-video → immediate success."""

    def test_i2v_success(self) -> None:
        transport = RecordingTransport([
            ArkHTTPResponse(200, {}, b'{"id":"cgt-i2v"}'),
            _json_response({"data": {
                "id": "cgt-i2v",
                "status": "succeeded",
                "content": [
                    {"type": "video_url", "video_url": {"url": "https://cdn.example.com/i2v.mp4"}},
                ],
            }}),
        ])
        wf = _make_workflow(transport)

        result = wf.run(
            "Animate this",
            image_url="https://example.com/cat.png",
            ratio="1:1",
            duration=4,
        )

        self.assertTrue(result.succeeded)
        self.assertEqual("https://cdn.example.com/i2v.mp4", result.video_url)

        # Verify image content was included
        sent = json.loads(transport.requests[0].body)
        self.assertEqual(2, len(sent["content"]))
        self.assertEqual("text", sent["content"][0]["type"])
        self.assertEqual("image_url", sent["content"][1]["type"])
        self.assertEqual("first_frame", sent["content"][1]["role"])


# ---------------------------------------------------------------------------
# Success path 3: list → select → delete
# ---------------------------------------------------------------------------

class TestListSelectDeleteFlow(unittest.TestCase):
    """List tasks → find one → delete → confirm cancelled."""

    def test_list_then_delete(self) -> None:
        transport = RecordingTransport([
            # list response
            _json_response({
                "total": 2,
                "items": [
                    {"id": "cgt-1", "status": "succeeded"},
                    {"id": "cgt-2", "status": "running"},
                ],
            }),
            # delete request
            ArkHTTPResponse(200, {}, b"{}"),
            # refresh after delete
            _json_response({"data": {"id": "cgt-2", "status": "cancelled"}}),
        ])
        wf = _make_workflow(transport)

        # List
        result = wf.list(page_num=1, page_size=10)
        self.assertEqual(2, result.total)
        running_task = [t for t in result.items if t.status == "running"][0]

        # Delete (skip confirmation)
        state = wf.delete(running_task.task_id, confirm=False)
        self.assertEqual("cancelled", state.status)


# ---------------------------------------------------------------------------
# Failure path 4: submit → poll → failed with error extraction
# ---------------------------------------------------------------------------

class TestTaskFailedWithError(unittest.TestCase):
    """Task fails with error message extraction."""

    def test_failed_with_error_object(self) -> None:
        transport = RecordingTransport([
            ArkHTTPResponse(200, {}, b'{"id":"cgt-fail"}'),
            _json_response({"data": {
                "id": "cgt-fail",
                "status": "failed",
                "error": {"message": "Content policy violation"},
            }}),
        ])
        wf = _make_workflow(transport,
            callbacks=WorkflowCallbacks(on_failed=lambda s: None),
        )

        state = wf.submit("Test")
        result = wf.wait(state.task_id)

        self.assertEqual("failed", result.status)
        self.assertEqual("Content policy violation", result.error_message)
        self.assertIsNone(result.video_url)
        self.assertTrue(result.is_terminal)
        self.assertFalse(result.succeeded)

    def test_failed_with_status_message(self) -> None:
        transport = RecordingTransport([
            ArkHTTPResponse(200, {}, b'{"id":"cgt-fail2"}'),
            _json_response({"data": {
                "id": "cgt-fail2",
                "status": "failed",
                "status_message": "Rate limit exceeded",
            }}),
        ])
        wf = _make_workflow(transport)

        state = wf.submit("Test")
        result = wf.wait(state.task_id)

        self.assertEqual("failed", result.status)
        self.assertEqual("Rate limit exceeded", result.error_message)

    def test_failed_with_no_error_details(self) -> None:
        transport = RecordingTransport([
            ArkHTTPResponse(200, {}, b'{"id":"cgt-fail3"}'),
            _json_response({"data": {"id": "cgt-fail3", "status": "failed"}}),
        ])
        wf = _make_workflow(transport)

        state = wf.submit("Test")
        result = wf.wait(state.task_id)

        self.assertEqual("failed", result.status)
        self.assertIsNone(result.error_message)


# ---------------------------------------------------------------------------
# Failure path 5: cancel before completion
# ---------------------------------------------------------------------------

class TestCancelBeforeCompletion(unittest.TestCase):
    """Cancel a running task."""

    def test_cancel_running_task(self) -> None:
        transport = RecordingTransport([
            ArkHTTPResponse(200, {}, b'{"id":"cgt-cancel"}'),
            # delete request
            ArkHTTPResponse(200, {}, b"{}"),
            # refresh shows cancelled
            _json_response({"data": {"id": "cgt-cancel", "status": "cancelled"}}),
        ])
        wf = _make_workflow(transport)

        state = wf.submit("Test")
        self.assertEqual("queued", state.status)

        result = wf.delete(state.task_id, confirm=False)
        self.assertEqual("cancelled", result.status)


# ---------------------------------------------------------------------------
# Failure path 6: poll timeout
# ---------------------------------------------------------------------------

class TestPollTimeout(unittest.TestCase):
    """Task does not reach terminal state within timeout."""

    def test_timeout_raises(self) -> None:
        # create + many running polls
        responses = [ArkHTTPResponse(200, {}, b'{"id":"cgt-timeout"}')]
        for _ in range(20):
            responses.append(
                _json_response({"data": {"id": "cgt-timeout", "status": "running"}})
            )
        transport = RecordingTransport(responses)
        wf = _make_workflow(transport,
            config=WorkflowConfig(poll_interval_seconds=0.01, poll_timeout_seconds=0.1),
        )

        state = wf.submit("Test")
        with self.assertRaises(TimeoutError) as ctx:
            wf.wait(state.task_id)
        self.assertIn("cgt-timeout", str(ctx.exception))


# ---------------------------------------------------------------------------
# Failure path 7: auth error propagation
# ---------------------------------------------------------------------------

class TestAuthErrorPropagation(unittest.TestCase):
    """Authentication error propagates through workflow."""

    def test_401_on_create(self) -> None:
        transport = RecordingTransport(
            _json_response(
                {"error": {"code": "Unauthorized", "message": "Invalid API key"}},
                status=401,
            )
        )
        wf = _make_workflow(transport)

        from sd2video.ark import ArkAuthenticationError
        with self.assertRaises(ArkAuthenticationError):
            wf.submit("Test")

    def test_403_on_poll(self) -> None:
        transport = RecordingTransport([
            ArkHTTPResponse(200, {}, b'{"id":"cgt-auth"}'),
            _json_response(
                {"error": {"code": "Forbidden", "message": "Permission denied"}},
                status=403,
            ),
        ])
        wf = _make_workflow(transport)

        state = wf.submit("Test")
        with self.assertRaises(ArkAuthenticationError):
            wf.wait(state.task_id)

    def test_api_key_redacted_in_error_message(self) -> None:
        api_key = "super-secret-key-12345"
        transport = RecordingTransport(
            ArkHTTPResponse(
                401,
                {},
                json.dumps({"error": {"message": f"Auth failed with key {api_key}"}}).encode(),
            )
        )
        client = ArkClient(ArkConfig(api_key=api_key), transport=transport)

        with self.assertRaises(ArkAuthenticationError) as ctx:
            client.request_tasks("get")

        error_str = str(ctx.exception)
        self.assertNotIn(api_key, error_str)
        self.assertIn("<redacted>", error_str)


# ---------------------------------------------------------------------------
# Failure path 8: network error propagation
# ---------------------------------------------------------------------------

class TestNetworkErrorPropagation(unittest.TestCase):
    """Network and timeout errors propagate cleanly."""

    def test_timeout_error(self) -> None:
        transport = RecordingTransport(error=TimeoutError("connection timed out"))
        wf = _make_workflow(transport)

        with self.assertRaises(ArkTimeoutError):
            wf.submit("Test")

    def test_network_error(self) -> None:
        transport = RecordingTransport(error=OSError("DNS resolution failed"))
        wf = _make_workflow(transport)

        with self.assertRaises(ArkNetworkError):
            wf.submit("Test")


# ---------------------------------------------------------------------------
# Failure path 9: delete declined
# ---------------------------------------------------------------------------

class TestDeleteDeclined(unittest.TestCase):
    """Delete confirmation declined → task not touched."""

    def test_declined_delete(self) -> None:
        transport = RecordingTransport([
            ArkHTTPResponse(200, {}, b'{"id":"cgt-decline"}'),
        ])
        wf = _make_workflow(transport,
            callbacks=WorkflowCallbacks(on_confirm_delete=lambda tid, status: False),
        )

        state = wf.submit("Test")
        result = wf.delete(state.task_id, confirm=True)

        # Only 1 request (create), no delete sent
        self.assertEqual(1, len(transport.requests))
        self.assertEqual("queued", result.status)


# ---------------------------------------------------------------------------
# Failure path 10: duplicate submission detection
# ---------------------------------------------------------------------------

class TestDuplicateSubmissionDetection(unittest.TestCase):
    """All tasks tracked; duplicate detection via get_state/all_tasks."""

    def test_tasks_tracked_after_submit(self) -> None:
        transport = RecordingTransport([
            ArkHTTPResponse(200, {}, b'{"id":"cgt-1"}'),
            ArkHTTPResponse(200, {}, b'{"id":"cgt-2"}'),
        ])
        wf = _make_workflow(transport)

        state1 = wf.submit("First task")
        state2 = wf.submit("Second task")

        self.assertEqual(2, len(wf.all_tasks()))
        self.assertIsNotNone(wf.get_state("cgt-1"))
        self.assertIsNotNone(wf.get_state("cgt-2"))
        self.assertIsNone(wf.get_state("nonexistent"))

    def test_same_task_id_overwrites_state(self) -> None:
        """If the API returns the same ID twice, the second submit overwrites."""
        transport = RecordingTransport([
            ArkHTTPResponse(200, {}, b'{"id":"cgt-same"}'),
            ArkHTTPResponse(200, {}, b'{"id":"cgt-same"}'),
        ])
        wf = _make_workflow(transport)

        wf.submit("Task 1")
        wf.submit("Task 2")

        # Both submit calls succeeded, but they share the same task ID
        # so the workflow dict has only one entry
        self.assertEqual(1, len(wf.all_tasks()))
        self.assertEqual("cgt-same", wf.get_state("cgt-same").task_id)


# ---------------------------------------------------------------------------
# Parameter mapping tests
# ---------------------------------------------------------------------------

class TestParameterMapping(unittest.TestCase):
    """Verify user-friendly parameters map correctly to API body."""

    def test_full_parameter_set(self) -> None:
        transport = RecordingTransport(ArkHTTPResponse(200, {}, b'{"id":"cgt-params"}'))
        client = _make_client(transport)

        from sd2video.ark import CreateTaskRequest
        req = CreateTaskRequest.text_to_video(
            "A scene",
            model="doubao-seedance-2-0",
            resolution="1080p",
            ratio="21:9",
            duration=10,
            seed=42,
            camera_fixed=True,
            watermark=False,
            generate_audio=True,
            service_tier="flex",
        )
        client.create_task(req)

        sent = json.loads(transport.requests[0].body)
        self.assertEqual("1080p", sent["resolution"])
        self.assertEqual("21:9", sent["ratio"])
        self.assertEqual(10, sent["duration"])
        self.assertEqual(42, sent["seed"])
        self.assertIs(True, sent["camera_fixed"])
        self.assertIs(False, sent["watermark"])
        self.assertIs(True, sent["generate_audio"])
        self.assertEqual("flex", sent["service_tier"])

    def test_null_params_omitted(self) -> None:
        transport = RecordingTransport(ArkHTTPResponse(200, {}, b'{"id":"cgt-min"}'))
        client = _make_client(transport)

        from sd2video.ark import CreateTaskRequest
        req = CreateTaskRequest.text_to_video("A scene", model="m")
        client.create_task(req)

        sent = json.loads(transport.requests[0].body)
        for key in ("resolution", "ratio", "duration", "seed",
                     "camera_fixed", "watermark", "generate_audio", "service_tier"):
            self.assertNotIn(key, sent, f"{key} should be omitted when None")

    def test_default_model_fallback(self) -> None:
        transport = RecordingTransport(ArkHTTPResponse(200, {}, b'{"id":"cgt-def"}'))
        client = _make_client(transport)

        from sd2video.ark import CreateTaskRequest
        req = CreateTaskRequest.text_to_video("Test")  # no model
        client.create_task(req)

        sent = json.loads(transport.requests[0].body)
        self.assertEqual("doubao-seedance-2-0-fast-260128", sent["model"])

    def test_image_to_video_parameter_mapping(self) -> None:
        transport = RecordingTransport(ArkHTTPResponse(200, {}, b'{"id":"cgt-i2v-p"}'))
        client = _make_client(transport)

        from sd2video.ark import CreateTaskRequest
        req = CreateTaskRequest.image_to_video(
            "https://example.com/start.png",
            prompt="Move this",
            model="doubao-seedance-2-0",
            last_frame_url="https://example.com/end.png",
            resolution="720p",
            ratio="9:16",
            duration=8,
            generate_audio=True,
        )
        client.create_task(req)

        sent = json.loads(transport.requests[0].body)
        self.assertEqual(3, len(sent["content"]))
        self.assertEqual("text", sent["content"][0]["type"])
        self.assertEqual("first_frame", sent["content"][1]["role"])
        self.assertEqual("last_frame", sent["content"][2]["role"])
        self.assertEqual("720p", sent["resolution"])
        self.assertEqual("9:16", sent["ratio"])
        self.assertEqual(8, sent["duration"])


# ---------------------------------------------------------------------------
# Validation boundary tests
# ---------------------------------------------------------------------------

class TestValidationBoundaries(unittest.TestCase):
    """Boundary validation for parameters."""

    def test_invalid_resolution_rejected(self) -> None:
        from sd2video.ark import CreateTaskRequest
        req = CreateTaskRequest.text_to_video("Test", model="m", resolution="4K")
        with self.assertRaises(ArkParameterError):
            req.build()

    def test_invalid_ratio_rejected(self) -> None:
        from sd2video.ark import CreateTaskRequest
        req = CreateTaskRequest.text_to_video("Test", model="m", ratio="5:4")
        with self.assertRaises(ArkParameterError):
            req.build()

    def test_invalid_service_tier_rejected(self) -> None:
        from sd2video.ark import CreateTaskRequest
        req = CreateTaskRequest.text_to_video("Test", model="m", service_tier="premium")
        with self.assertRaises(ArkParameterError):
            req.build()

    def test_frames_out_of_range_rejected(self) -> None:
        from sd2video.ark import CreateTaskRequest
        req = CreateTaskRequest.text_to_video("Test", model="m", frames=10)
        with self.assertRaises(ArkParameterError):
            req.build()

    def test_seed_out_of_range_rejected(self) -> None:
        from sd2video.ark import CreateTaskRequest
        req = CreateTaskRequest.text_to_video("Test", model="m", seed=-5)
        with self.assertRaises(ArkParameterError):
            req.build()

    def test_empty_prompt_rejected(self) -> None:
        from sd2video.ark import CreateTaskRequest
        with self.assertRaises(ArkParameterError):
            CreateTaskRequest.text_to_video("", model="m")

    def test_empty_model_rejected_on_build(self) -> None:
        from sd2video.ark import CreateTaskRequest
        req = CreateTaskRequest.text_to_video("Test", model="")
        with self.assertRaises(ArkParameterError):
            req.build()


# ---------------------------------------------------------------------------
# Workflow refresh and state management
# ---------------------------------------------------------------------------

class TestWorkflowRefreshAndState(unittest.TestCase):
    """Test refresh method and state tracking."""

    def test_refresh_updates_state(self) -> None:
        transport = RecordingTransport([
            ArkHTTPResponse(200, {}, b'{"id":"cgt-r"}'),
            _json_response({"data": {"id": "cgt-r", "status": "running"}}),
            _json_response({"data": {
                "id": "cgt-r",
                "status": "succeeded",
                "content": [{"type": "video_url", "video_url": {"url": "https://cdn.example.com/v.mp4"}}],
            }}),
        ])
        wf = _make_workflow(transport)

        state = wf.submit("Test")
        self.assertEqual("queued", state.status)

        state = wf.refresh(state.task_id)
        self.assertEqual("running", state.status)

        state = wf.refresh(state.task_id)
        self.assertEqual("succeeded", state.status)
        self.assertEqual("https://cdn.example.com/v.mp4", state.video_url)

    def test_refresh_creates_state_for_unknown_task(self) -> None:
        transport = RecordingTransport(
            _json_response({"data": {"id": "ext-123", "status": "running"}}),
        )
        wf = _make_workflow(transport)

        # Refresh a task that was never submitted through this workflow
        state = wf.refresh("ext-123")
        self.assertEqual("ext-123", state.task_id)
        self.assertEqual("running", state.status)
        self.assertIsNotNone(wf.get_state("ext-123"))


# ---------------------------------------------------------------------------
# API error during poll
# ---------------------------------------------------------------------------

class TestAPIErrorDuringPoll(unittest.TestCase):
    """API error returned during polling."""

    def test_500_during_poll_raises(self) -> None:
        transport = RecordingTransport([
            ArkHTTPResponse(200, {}, b'{"id":"cgt-err"}'),
            _json_response(
                {"error": {"code": "InternalError", "message": "try again"}},
                status=500,
            ),
        ])
        wf = _make_workflow(transport)

        state = wf.submit("Test")
        with self.assertRaises(Exception):  # ArkAPIError
            wf.wait(state.task_id)


if __name__ == "__main__":
    unittest.main()
