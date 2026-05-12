"""Tests for the video generation workflow (HOM-17)."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from sd2video.ark import (
    ArkClient,
    ArkConfig,
    ArkHTTPResponse,
    ArkParameterError,
    ArkTaskDetail,
    ArkTaskListResult,
    CreateTaskRequest,
    TaskState,
    VideoGenerationWorkflow,
    WorkflowCallbacks,
    WorkflowConfig,
)
from sd2video.ark.types import STATUS_LABELS


class RecordingTransport:
    """Test double that records requests and returns canned responses."""

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


def _make_client(transport) -> ArkClient:
    return ArkClient(
        ArkConfig(api_key="test-key", default_model_id="doubao-seedance-2-0-fast-260128"),
        transport=transport,
    )


# ---------------------------------------------------------------------------
# ArkTaskDetail tests
# ---------------------------------------------------------------------------


class ArkTaskDetailTests(unittest.TestCase):
    def test_from_response_basic(self) -> None:
        data = {
            "data": {
                "id": "cgt-123",
                "status": "running",
                "model": {"id": "doubao-seedance-2-0"},
                "created_at": "2026-05-11T10:00:00Z",
                "updated_at": "2026-05-11T10:01:00Z",
            }
        }
        detail = ArkTaskDetail.from_response(data)
        self.assertEqual("cgt-123", detail.task_id)
        self.assertEqual("running", detail.status)
        self.assertEqual("doubao-seedance-2-0", detail.model)
        self.assertIsNone(detail.video_url)
        self.assertFalse(detail.is_terminal)
        self.assertTrue(detail.is_pending)

    def test_from_response_succeeded_with_video_url(self) -> None:
        data = {
            "data": {
                "id": "cgt-456",
                "status": "succeeded",
                "content": [
                    {
                        "type": "video_url",
                        "video_url": {"url": "https://cdn.example.com/video.mp4"},
                    }
                ],
            }
        }
        detail = ArkTaskDetail.from_response(data)
        self.assertEqual("succeeded", detail.status)
        self.assertEqual("https://cdn.example.com/video.mp4", detail.video_url)
        self.assertTrue(detail.is_terminal)
        self.assertTrue(detail.succeeded)

    def test_from_response_flat_structure(self) -> None:
        """Some API responses may not wrap in 'data'."""
        data = {"id": "cgt-789", "status": "queued"}
        detail = ArkTaskDetail.from_response(data)
        self.assertEqual("cgt-789", detail.task_id)
        self.assertEqual("queued", detail.status)

    def test_status_label(self) -> None:
        for status, label in STATUS_LABELS.items():
            detail = ArkTaskDetail(task_id="x", status=status)
            self.assertEqual(label, detail.status_label)

    def test_unknown_status_label(self) -> None:
        detail = ArkTaskDetail(task_id="x", status="mystery")
        self.assertEqual("mystery", detail.status_label)


# ---------------------------------------------------------------------------
# ArkTaskListResult tests
# ---------------------------------------------------------------------------


class ArkTaskListResultTests(unittest.TestCase):
    def test_from_response_with_items(self) -> None:
        data = {
            "total": 3,
            "items": [
                {"id": "cgt-1", "status": "succeeded"},
                {"id": "cgt-2", "status": "running"},
                {"id": "cgt-3", "status": "failed"},
            ],
        }
        result = ArkTaskListResult.from_response(data, page_num=1, page_size=10)
        self.assertEqual(3, result.total)
        self.assertEqual(3, len(result.items))
        self.assertEqual("cgt-1", result.items[0].task_id)
        self.assertFalse(result.has_more)

    def test_has_more(self) -> None:
        data = {"total": 100, "items": []}
        result = ArkTaskListResult.from_response(data, page_num=1, page_size=10)
        self.assertTrue(result.has_more)

        result2 = ArkTaskListResult.from_response(data, page_num=10, page_size=10)
        self.assertFalse(result2.has_more)

    def test_empty_response(self) -> None:
        result = ArkTaskListResult.from_response({}, page_num=1, page_size=10)
        self.assertEqual(0, result.total)
        self.assertEqual(0, len(result.items))

    def test_non_dict_response(self) -> None:
        result = ArkTaskListResult.from_response("error", page_num=1, page_size=10)
        self.assertEqual(0, result.total)


# ---------------------------------------------------------------------------
# ArkClient.get_task tests
# ---------------------------------------------------------------------------


class GetTaskClientTests(unittest.TestCase):
    def test_get_task_returns_detail(self) -> None:
        transport = RecordingTransport(
            ArkHTTPResponse(
                200,
                {},
                json.dumps({
                    "data": {
                        "id": "cgt-abc",
                        "status": "succeeded",
                        "model": "doubao-seedance-2-0",
                        "content": [
                            {
                                "type": "video_url",
                                "video_url": {"url": "https://cdn.example.com/v.mp4"},
                            }
                        ],
                    }
                }).encode(),
            )
        )
        client = _make_client(transport)
        detail = client.get_task("cgt-abc")

        self.assertEqual("cgt-abc", detail.task_id)
        self.assertEqual("succeeded", detail.status)
        self.assertEqual("https://cdn.example.com/v.mp4", detail.video_url)
        # Verify GET was sent to the right URL
        self.assertEqual("GET", transport.requests[0].method)
        self.assertIn("cgt-abc", transport.requests[0].url)

    def test_get_task_rejects_empty_id(self) -> None:
        client = _make_client(RecordingTransport())
        with self.assertRaises(ArkParameterError):
            client.get_task("")

    def test_get_task_rejects_id_with_slash(self) -> None:
        client = _make_client(RecordingTransport())
        with self.assertRaises(ArkParameterError):
            client.get_task("task/with/slash")


# ---------------------------------------------------------------------------
# ArkClient.list_tasks tests
# ---------------------------------------------------------------------------


class ListTasksClientTests(unittest.TestCase):
    def test_list_tasks_basic(self) -> None:
        transport = RecordingTransport(
            ArkHTTPResponse(
                200,
                {},
                json.dumps({
                    "total": 2,
                    "items": [
                        {"id": "cgt-1", "status": "succeeded"},
                        {"id": "cgt-2", "status": "running"},
                    ],
                }).encode(),
            )
        )
        client = _make_client(transport)
        result = client.list_tasks()

        self.assertEqual(2, result.total)
        self.assertEqual(2, len(result.items))
        # Verify query params
        self.assertEqual("GET", transport.requests[0].method)
        self.assertIn("page_num=1", transport.requests[0].url)
        self.assertIn("page_size=10", transport.requests[0].url)

    def test_list_tasks_with_status_filter(self) -> None:
        transport = RecordingTransport(
            ArkHTTPResponse(200, {}, b'{"total":0,"items":[]}')
        )
        client = _make_client(transport)
        client.list_tasks(status_filter=["running", "queued"])

        self.assertIn("filter.status=running%2Cqueued", transport.requests[0].url)

    def test_list_tasks_with_task_ids(self) -> None:
        transport = RecordingTransport(
            ArkHTTPResponse(200, {}, b'{"total":0,"items":[]}')
        )
        client = _make_client(transport)
        client.list_tasks(task_ids=["cgt-1", "cgt-2"])

        self.assertIn("filter.task_ids=cgt-1%2Ccgt-2", transport.requests[0].url)

    def test_list_tasks_rejects_invalid_page_size(self) -> None:
        client = _make_client(RecordingTransport())
        with self.assertRaises(ArkParameterError):
            client.list_tasks(page_size=0)
        with self.assertRaises(ArkParameterError):
            client.list_tasks(page_size=100)

    def test_list_tasks_rejects_invalid_page_num(self) -> None:
        client = _make_client(RecordingTransport())
        with self.assertRaises(ArkParameterError):
            client.list_tasks(page_num=0)

    def test_list_tasks_rejects_invalid_status_filter(self) -> None:
        client = _make_client(RecordingTransport())
        with self.assertRaises(ArkParameterError):
            client.list_tasks(status_filter="invalid_status")


# ---------------------------------------------------------------------------
# TaskState tests
# ---------------------------------------------------------------------------


class TaskStateTests(unittest.TestCase):
    def test_initial_state(self) -> None:
        state = TaskState(task_id="cgt-123")
        self.assertEqual("queued", state.status)
        self.assertEqual("排队中", state.status_label)
        self.assertFalse(state.is_terminal)
        self.assertTrue(state.is_pending)

    def test_update_from_detail(self) -> None:
        state = TaskState(task_id="cgt-123")
        detail = ArkTaskDetail(
            task_id="cgt-123",
            status="succeeded",
            video_url="https://example.com/v.mp4",
            model="doubao-seedance-2-0",
        )
        state.update_from_detail(detail)
        self.assertEqual("succeeded", state.status)
        self.assertEqual("https://example.com/v.mp4", state.video_url)
        self.assertTrue(state.succeeded)

    def test_error_extraction_from_failed_task(self) -> None:
        state = TaskState(task_id="cgt-123")
        detail = ArkTaskDetail(
            task_id="cgt-123",
            status="failed",
            raw={"data": {"error": {"message": "Content policy violation"}}},
        )
        state.update_from_detail(detail)
        self.assertEqual("failed", state.status)
        self.assertEqual("Content policy violation", state.error_message)


# ---------------------------------------------------------------------------
# VideoGenerationWorkflow tests
# ---------------------------------------------------------------------------


class WorkflowSubmitTests(unittest.TestCase):
    def test_submit_text_to_video(self) -> None:
        transport = RecordingTransport(
            ArkHTTPResponse(200, {}, b'{"id":"cgt-new"}')
        )
        client = _make_client(transport)
        wf = VideoGenerationWorkflow(client)

        state = wf.submit("A cat dancing", ratio="16:9", duration=5)

        self.assertEqual("cgt-new", state.task_id)
        self.assertEqual("queued", state.status)
        self.assertIn("cgt-new", [s.task_id for s in wf.all_tasks()])

        # Verify the POST body
        sent = json.loads(transport.requests[0].body)
        self.assertEqual("text", sent["content"][0]["type"])
        self.assertEqual("A cat dancing", sent["content"][0]["text"])
        self.assertEqual("16:9", sent["ratio"])
        self.assertEqual(5, sent["duration"])

    def test_submit_image_to_video(self) -> None:
        transport = RecordingTransport(
            ArkHTTPResponse(200, {}, b'{"id":"cgt-img"}')
        )
        client = _make_client(transport)
        wf = VideoGenerationWorkflow(client)

        state = wf.submit(
            "Animate this",
            image_url="https://example.com/cat.png",
            last_frame_url="https://example.com/cat2.png",
        )

        self.assertEqual("cgt-img", state.task_id)
        sent = json.loads(transport.requests[0].body)
        self.assertEqual(3, len(sent["content"]))  # text + first_frame + last_frame

    def test_submit_uses_default_model(self) -> None:
        transport = RecordingTransport(
            ArkHTTPResponse(200, {}, b'{"id":"cgt-def"}')
        )
        client = _make_client(transport)
        wf = VideoGenerationWorkflow(
            client,
            config=WorkflowConfig(default_model="my-model"),
        )

        wf.submit("Test")
        sent = json.loads(transport.requests[0].body)
        self.assertEqual("my-model", sent["model"])

    def test_submit_fires_callback(self) -> None:
        transport = RecordingTransport(
            ArkHTTPResponse(200, {}, b'{"id":"cgt-cb"}')
        )
        client = _make_client(transport)

        created_ids = []
        wf = VideoGenerationWorkflow(
            client,
            callbacks=WorkflowCallbacks(on_task_created=created_ids.append),
        )
        wf.submit("Test")
        self.assertEqual(["cgt-cb"], created_ids)

    def test_high_cost_submit_requires_confirmation_when_callback_is_set(self) -> None:
        transport = RecordingTransport(
            ArkHTTPResponse(200, {}, b'{"id":"cgt-cost"}')
        )
        client = _make_client(transport)
        confirmations = []
        wf = VideoGenerationWorkflow(
            client,
            callbacks=WorkflowCallbacks(
                on_confirm_submit=lambda warnings, payload: (
                    confirmations.append((warnings, payload)),
                    False,
                )[1],
            ),
        )

        with self.assertRaises(ArkParameterError):
            wf.submit(
                "Expensive task",
                resolution="1080p",
                duration=12,
                generate_audio=True,
            )

        self.assertEqual(1, len(confirmations))
        self.assertEqual(0, len(transport.requests))

    def test_duplicate_submit_prompts_within_configured_window(self) -> None:
        transport = RecordingTransport(
            [
                ArkHTTPResponse(200, {}, b'{"id":"cgt-1"}'),
                ArkHTTPResponse(200, {}, b'{"id":"cgt-2"}'),
            ]
        )
        client = _make_client(transport)
        warnings_seen = []
        wf = VideoGenerationWorkflow(
            client,
            config=WorkflowConfig(duplicate_submit_window_seconds=30),
            callbacks=WorkflowCallbacks(
                on_confirm_submit=lambda warnings, payload: (
                    warnings_seen.append(warnings),
                    True,
                )[1],
            ),
        )

        first = wf.submit("Same task", ratio="16:9", duration=5)
        second = wf.submit("Same task", ratio="16:9", duration=5)

        self.assertEqual("cgt-1", first.task_id)
        self.assertEqual("cgt-2", second.task_id)
        self.assertEqual(1, len(warnings_seen))
        self.assertTrue(any("Same generation parameters" in w for w in warnings_seen[0]))

    def test_submit_lock_is_released_after_create_error(self) -> None:
        transport = RecordingTransport(error=RuntimeError("boom"))
        client = _make_client(transport)
        wf = VideoGenerationWorkflow(client)

        with self.assertRaises(RuntimeError):
            wf.submit("Will fail")

        transport.error = None
        transport.responses = [ArkHTTPResponse(200, {}, b'{"id":"cgt-ok"}')]
        result = wf.submit("Will retry")
        self.assertEqual("cgt-ok", result.task_id)


class WorkflowWaitTests(unittest.TestCase):
    def test_wait_polls_until_succeeded(self) -> None:
        transport = RecordingTransport(
            [
                ArkHTTPResponse(200, {}, b'{"id":"cgt-w"}'),  # create
                ArkHTTPResponse(200, {}, json.dumps({  # poll 1: running
                    "data": {"id": "cgt-w", "status": "running"}
                }).encode()),
                ArkHTTPResponse(200, {}, json.dumps({  # poll 2: succeeded
                    "data": {
                        "id": "cgt-w",
                        "status": "succeeded",
                        "content": [
                            {
                                "type": "video_url",
                                "video_url": {"url": "https://cdn.example.com/v.mp4"},
                            }
                        ],
                    }
                }).encode()),
            ]
        )
        client = _make_client(transport)
        wf = VideoGenerationWorkflow(
            client,
            config=WorkflowConfig(poll_interval_seconds=0.01, poll_timeout_seconds=5),
        )

        state = wf.submit("Test")
        result = wf.wait(state.task_id)

        self.assertEqual("succeeded", result.status)
        self.assertEqual("https://cdn.example.com/v.mp4", result.video_url)
        self.assertTrue(result.succeeded)

    def test_wait_handles_failed_status(self) -> None:
        transport = RecordingTransport(
            [
                ArkHTTPResponse(200, {}, b'{"id":"cgt-f"}'),
                ArkHTTPResponse(200, {}, json.dumps({
                    "data": {
                        "id": "cgt-f",
                        "status": "failed",
                        "error": {"message": "Rate limit exceeded"},
                    }
                }).encode()),
            ]
        )
        client = _make_client(transport)

        failed_ids = []
        wf = VideoGenerationWorkflow(
            client,
            config=WorkflowConfig(poll_interval_seconds=0.01),
            callbacks=WorkflowCallbacks(
                on_failed=lambda s: failed_ids.append(s.task_id),
            ),
        )

        state = wf.submit("Test")
        result = wf.wait(state.task_id)

        self.assertEqual("failed", result.status)
        self.assertEqual("Rate limit exceeded", result.error_message)
        self.assertEqual(["cgt-f"], failed_ids)

    def test_wait_handles_cancelled_status(self) -> None:
        transport = RecordingTransport(
            [
                ArkHTTPResponse(200, {}, b'{"id":"cgt-c"}'),
                ArkHTTPResponse(200, {}, json.dumps({
                    "data": {"id": "cgt-c", "status": "cancelled"}
                }).encode()),
            ]
        )
        client = _make_client(transport)

        cancelled_ids = []
        wf = VideoGenerationWorkflow(
            client,
            config=WorkflowConfig(poll_interval_seconds=0.01),
            callbacks=WorkflowCallbacks(
                on_cancelled=lambda s: cancelled_ids.append(s.task_id),
            ),
        )

        state = wf.submit("Test")
        result = wf.wait(state.task_id)

        self.assertEqual("cancelled", result.status)
        self.assertEqual(["cgt-c"], cancelled_ids)

    def test_wait_timeout_raises(self) -> None:
        transport = RecordingTransport(
            [
                ArkHTTPResponse(200, {}, b'{"id":"cgt-t"}'),
                # Always running
                ArkHTTPResponse(200, {}, json.dumps({
                    "data": {"id": "cgt-t", "status": "running"}
                }).encode()),
            ]
        )
        client = _make_client(transport)
        wf = VideoGenerationWorkflow(
            client,
            config=WorkflowConfig(poll_interval_seconds=0.01, poll_timeout_seconds=0.05),
        )

        state = wf.submit("Test")
        with self.assertRaises(TimeoutError):
            wf.wait(state.task_id)

    def test_status_change_callback_fires(self) -> None:
        transport = RecordingTransport(
            [
                ArkHTTPResponse(200, {}, b'{"id":"cgt-sc"}'),
                ArkHTTPResponse(200, {}, json.dumps({
                    "data": {"id": "cgt-sc", "status": "running"}
                }).encode()),
                ArkHTTPResponse(200, {}, json.dumps({
                    "data": {"id": "cgt-sc", "status": "succeeded", "content": []}
                }).encode()),
            ]
        )
        client = _make_client(transport)

        changes = []
        wf = VideoGenerationWorkflow(
            client,
            config=WorkflowConfig(poll_interval_seconds=0.01),
            callbacks=WorkflowCallbacks(
                on_status_change=lambda tid, label: changes.append((tid, label)),
            ),
        )

        state = wf.submit("Test")
        wf.wait(state.task_id)

        self.assertEqual(2, len(changes))
        self.assertEqual(("cgt-sc", "生成中"), changes[0])
        self.assertEqual(("cgt-sc", "已完成"), changes[1])


class WorkflowRunTests(unittest.TestCase):
    def test_run_end_to_end(self) -> None:
        transport = RecordingTransport(
            [
                ArkHTTPResponse(200, {}, b'{"id":"cgt-e2e"}'),
                ArkHTTPResponse(200, {}, json.dumps({
                    "data": {"id": "cgt-e2e", "status": "succeeded", "content": [
                        {"type": "video_url", "video_url": {"url": "https://cdn.example.com/final.mp4"}}
                    ]}
                }).encode()),
            ]
        )
        client = _make_client(transport)
        wf = VideoGenerationWorkflow(
            client,
            config=WorkflowConfig(poll_interval_seconds=0.01),
        )

        result = wf.run("A cat", ratio="1:1")
        self.assertEqual("succeeded", result.status)
        self.assertEqual("https://cdn.example.com/final.mp4", result.video_url)


class WorkflowDeleteTests(unittest.TestCase):
    def test_cancel_pending_task_with_confirmation(self) -> None:
        transport = RecordingTransport(
            [
                ArkHTTPResponse(200, {}, b'{"id":"cgt-d"}'),
                # delete request
                ArkHTTPResponse(200, {}, b"{}"),
                # refresh after delete
                ArkHTTPResponse(200, {}, json.dumps({
                    "data": {"id": "cgt-d", "status": "cancelled"}
                }).encode()),
            ]
        )
        client = _make_client(transport)

        confirmed = []
        wf = VideoGenerationWorkflow(
            client,
            callbacks=WorkflowCallbacks(
                on_confirm_delete=lambda tid, status: (confirmed.append(True), True)[1],
            ),
        )

        state = wf.submit("Test")
        result = wf.cancel(state.task_id, confirm=True)

        self.assertEqual("cancelled", result.status)
        self.assertEqual([True], confirmed)

    def test_cancel_declined_by_user(self) -> None:
        transport = RecordingTransport(
            [
                ArkHTTPResponse(200, {}, b'{"id":"cgt-dd"}'),
            ]
        )
        client = _make_client(transport)
        wf = VideoGenerationWorkflow(
            client,
            callbacks=WorkflowCallbacks(
                on_confirm_delete=lambda tid, status: False,
            ),
        )

        state = wf.submit("Test")
        result = wf.cancel(state.task_id, confirm=True)

        # Status should still be queued (delete was not sent)
        self.assertEqual("queued", result.status)
        # Only 1 request (the create), not 2
        self.assertEqual(1, len(transport.requests))

    def test_cancel_without_confirmation(self) -> None:
        transport = RecordingTransport(
            [
                ArkHTTPResponse(200, {}, b'{"id":"cgt-nc"}'),
                ArkHTTPResponse(200, {}, b"{}"),
                ArkHTTPResponse(404, {}, b'{"error":{"code":"NotFound"}}'),
            ]
        )
        client = _make_client(transport)
        wf = VideoGenerationWorkflow(client)

        state = wf.submit("Test")
        result = wf.cancel(state.task_id, confirm=False)

        self.assertEqual("deleted", result.status)

    def test_delete_rejects_pending_task(self) -> None:
        transport = RecordingTransport(
            ArkHTTPResponse(200, {}, b'{"id":"cgt-pending"}')
        )
        client = _make_client(transport)
        wf = VideoGenerationWorkflow(client)

        state = wf.submit("Test")
        with self.assertRaises(ArkParameterError):
            wf.delete(state.task_id, confirm=False)

        self.assertEqual("queued", state.status)
        self.assertEqual(1, len(transport.requests))

    def test_cancel_rejects_terminal_task(self) -> None:
        transport = RecordingTransport(
            [
                ArkHTTPResponse(200, {}, b'{"id":"cgt-terminal"}'),
                ArkHTTPResponse(200, {}, json.dumps({
                    "data": {"id": "cgt-terminal", "status": "succeeded"}
                }).encode()),
            ]
        )
        client = _make_client(transport)
        wf = VideoGenerationWorkflow(client)

        state = wf.submit("Test")
        wf.refresh(state.task_id)
        with self.assertRaises(ArkParameterError):
            wf.cancel(state.task_id, confirm=False)

    def test_delete_terminal_history_task_with_known_status(self) -> None:
        transport = RecordingTransport(
            [
                ArkHTTPResponse(200, {}, b"{}"),
                ArkHTTPResponse(404, {}, b'{"error":{"code":"NotFound"}}'),
            ]
        )
        client = _make_client(transport)
        wf = VideoGenerationWorkflow(client)

        result = wf.delete(
            "cgt-history",
            confirm=False,
            current_status="succeeded",
        )

        self.assertEqual("deleted", result.status)
        self.assertEqual(["DELETE", "GET"], [r.method for r in transport.requests])

    def test_delete_unknown_history_task_refreshes_remote_status_before_delete(self) -> None:
        transport = RecordingTransport(
            [
                ArkHTTPResponse(200, {}, json.dumps({
                    "data": {"id": "cgt-remote", "status": "succeeded"}
                }).encode()),
                ArkHTTPResponse(200, {}, b"{}"),
                ArkHTTPResponse(404, {}, b'{"error":{"code":"NotFound"}}'),
            ]
        )
        client = _make_client(transport)
        wf = VideoGenerationWorkflow(client)

        result = wf.delete("cgt-remote", confirm=False)

        self.assertEqual("deleted", result.status)
        self.assertEqual(["GET", "DELETE", "GET"], [r.method for r in transport.requests])

    def test_delete_failure_preserves_status_and_fires_error_callback(self) -> None:
        transport = RecordingTransport(
            [
                ArkHTTPResponse(200, {}, b'{"id":"cgt-err"}'),
                ArkHTTPResponse(200, {}, json.dumps({
                    "data": {"id": "cgt-err", "status": "succeeded"}
                }).encode()),
                ArkHTTPResponse(409, {}, b'{"error":{"message":"Task is locked"}}'),
            ]
        )
        client = _make_client(transport)
        errors = []
        wf = VideoGenerationWorkflow(
            client,
            callbacks=WorkflowCallbacks(on_delete_error=lambda *args: errors.append(args)),
        )

        state = wf.submit("Test")
        wf.refresh(state.task_id)
        with self.assertRaises(Exception):
            wf.delete(state.task_id, confirm=False)

        self.assertEqual("succeeded", state.status)
        self.assertEqual(1, len(errors))
        self.assertEqual((state.task_id, "delete"), errors[0][:2])


class WorkflowListTests(unittest.TestCase):
    def test_list_tasks(self) -> None:
        transport = RecordingTransport(
            ArkHTTPResponse(200, {}, json.dumps({
                "total": 5,
                "items": [
                    {"id": "cgt-1", "status": "succeeded"},
                    {"id": "cgt-2", "status": "running"},
                    {"id": "cgt-3", "status": "failed"},
                ],
            }).encode()),
        )
        client = _make_client(transport)
        wf = VideoGenerationWorkflow(client)

        result = wf.list(page_num=1, page_size=3, status_filter="running")
        self.assertEqual(5, result.total)
        self.assertEqual(3, len(result.items))
        self.assertTrue(result.has_more)


class WorkflowFromEnvTests(unittest.TestCase):
    def test_from_env_creates_workflow(self) -> None:
        import os
        old_key = os.environ.get("ARK_API_KEY")
        try:
            os.environ["ARK_API_KEY"] = "env-test-key"
            wf = VideoGenerationWorkflow.from_env()
            self.assertIsNotNone(wf.client)
        finally:
            if old_key is None:
                os.environ.pop("ARK_API_KEY", None)
            else:
                os.environ["ARK_API_KEY"] = old_key


if __name__ == "__main__":
    unittest.main()
