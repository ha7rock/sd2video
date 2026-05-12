"""End-to-end video generation workflow for Ark.

Ties together create → poll → get result → delete into a user-facing flow.
No API key is ever exposed in logs, errors, or UI output.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .client import ArkClient
from .errors import ArkError, ArkParameterError
from .task_models import CreateTaskRequest
from .types import (
    STATUS_LABELS,
    ArkTaskDetail,
    ArkTaskListResult,
)


# ---------------------------------------------------------------------------
# Workflow configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WorkflowConfig:
    """Configuration for the video generation workflow."""

    poll_interval_seconds: float = 5.0
    poll_timeout_seconds: float = 600.0
    default_model: str | None = None
    duplicate_submit_window_seconds: float = 5.0


# ---------------------------------------------------------------------------
# Task state tracking
# ---------------------------------------------------------------------------

@dataclass
class TaskState:
    """Local representation of a video generation task."""

    task_id: str
    status: str = "queued"
    model: str | None = None
    video_url: str | None = None
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    usage: dict[str, Any] | None = None
    raw_detail: ArkTaskDetail | None = field(default=None, repr=False)

    @property
    def status_label(self) -> str:
        """Human-readable Chinese status label."""
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def is_terminal(self) -> bool:
        return self.status in {"succeeded", "failed", "cancelled", "deleted"}

    @property
    def is_pending(self) -> bool:
        return self.status in {"queued", "running"}

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"

    def update_from_detail(self, detail: ArkTaskDetail) -> None:
        """Update local state from an Ark task detail response."""
        self.status = detail.status
        self.model = detail.model or self.model
        self.video_url = detail.video_url or self.video_url
        self.created_at = detail.created_at or self.created_at
        self.updated_at = detail.updated_at or self.updated_at
        self.usage = detail.usage or self.usage
        self.raw_detail = detail

        # Extract error info from failed tasks
        if detail.status == "failed" and not self.error_message:
            self.error_message = self._extract_error_message(detail)

    @staticmethod
    def _extract_error_message(detail: ArkTaskDetail) -> str | None:
        """Try to extract a human-readable error message from the raw response."""
        raw = detail.raw
        if not isinstance(raw, dict):
            return None

        task_data = raw.get("data", raw)

        # Check for error field
        error = task_data.get("error")
        if isinstance(error, dict):
            return error.get("message") or error.get("msg")

        # Check for status_message
        msg = task_data.get("status_message") or task_data.get("message")
        if isinstance(msg, str) and msg:
            return msg

        return None


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@dataclass
class WorkflowCallbacks:
    """Optional callbacks for workflow progress reporting.

    All callbacks are optional. Set any to None to skip.
    """

    on_task_created: Callable[[str], None] | None = None
    on_status_change: Callable[[str, str], None] | None = None  # (task_id, status_label)
    on_poll: Callable[[TaskState], None] | None = None
    on_succeeded: Callable[[TaskState], None] | None = None
    on_failed: Callable[[TaskState], None] | None = None
    on_cancelled: Callable[[TaskState], None] | None = None
    on_confirm_submit: Callable[[list[str], dict[str, Any]], bool] | None = None
    on_confirm_cancel: Callable[[str, str], bool] | None = None  # (task_id, status) -> confirmed
    on_confirm_delete: Callable[[str, str], bool] | None = None  # (task_id, status) -> confirmed
    on_delete_error: Callable[[str, str, Exception], None] | None = None


# ---------------------------------------------------------------------------
# VideoGenerationWorkflow
# ---------------------------------------------------------------------------

class VideoGenerationWorkflow:
    """User-facing video generation workflow.

    Covers: submit → wait → view result → cancel/delete.
    """

    def __init__(
        self,
        client: ArkClient,
        *,
        config: WorkflowConfig | None = None,
        callbacks: WorkflowCallbacks | None = None,
    ) -> None:
        self._client = client
        self._config = config or WorkflowConfig()
        self._callbacks = callbacks or WorkflowCallbacks()
        self._tasks: dict[str, TaskState] = {}
        self._submitting = False
        self._last_submit: tuple[str, float] | None = None

    @classmethod
    def from_env(
        cls,
        *,
        config: WorkflowConfig | None = None,
        callbacks: WorkflowCallbacks | None = None,
    ) -> VideoGenerationWorkflow:
        """Create a workflow from environment variables."""
        return cls(ArkClient.from_env(), config=config, callbacks=callbacks)

    @property
    def client(self) -> ArkClient:
        return self._client

    # ------------------------------------------------------------------
    # Create task
    # ------------------------------------------------------------------

    def submit(
        self,
        prompt: str,
        *,
        model: str | None = None,
        image_url: str | None = None,
        last_frame_url: str | None = None,
        resolution: str | None = None,
        ratio: str | None = None,
        duration: int | None = None,
        frames: int | None = None,
        seed: int | None = None,
        camera_fixed: bool | None = None,
        watermark: bool | None = None,
        generate_audio: bool | None = None,
        service_tier: str | None = None,
    ) -> TaskState:
        """Submit a video generation task.

        Args:
            prompt: Text prompt for the video.
            model: Model ID (defaults to client config's default).
            image_url: First-frame image URL for image-to-video.
            last_frame_url: Last-frame image URL for first+last frame mode.
            resolution: Output resolution (480p/720p/1080p).
            ratio: Aspect ratio (16:9, 1:1, 9:16, etc.).
            duration: Duration in seconds.
            frames: Number of frames.
            seed: Random seed for reproducibility.
            camera_fixed: Whether camera is fixed.
            watermark: Whether to add watermark.
            generate_audio: Whether to generate audio.
            service_tier: Service tier (default/flex).

        Returns:
            A :class:`TaskState` tracking the submitted task.
        """
        effective_model = (
            model
            or self._config.default_model
            or self._client.config.default_model_id
            or ""
        )

        # Build request based on input type
        if image_url:
            request = CreateTaskRequest.image_to_video(
                image_url,
                prompt=prompt,
                model=effective_model,
                last_frame_url=last_frame_url,
                resolution=resolution,
                ratio=ratio,
                duration=duration,
                frames=frames,
                seed=seed,
                camera_fixed=camera_fixed,
                watermark=watermark,
                generate_audio=generate_audio,
                service_tier=service_tier,
            )
        else:
            request = CreateTaskRequest.text_to_video(
                prompt,
                model=effective_model,
                resolution=resolution,
                ratio=ratio,
                duration=duration,
                frames=frames,
                seed=seed,
                camera_fixed=camera_fixed,
                watermark=watermark,
                generate_audio=generate_audio,
                service_tier=service_tier,
            )

        request_payload = request.build()
        self._guard_submission(request_payload)
        try:
            task_id = self._client.create_task(request)
        finally:
            self._submitting = False

        self._last_submit = (
            self._submission_fingerprint(request_payload),
            time.monotonic(),
        )

        state = TaskState(
            task_id=task_id,
            status="queued",
            model=effective_model,
        )
        self._tasks[task_id] = state

        cb = self._callbacks.on_task_created
        if cb:
            cb(task_id)

        return state

    # ------------------------------------------------------------------
    # Query single task
    # ------------------------------------------------------------------

    def refresh(self, task_id: str) -> TaskState:
        """Refresh a single task's status from the API.

        Args:
            task_id: The Ark task ID.

        Returns:
            Updated :class:`TaskState`.
        """
        detail = self._client.get_task(task_id)
        state = self._get_or_create_state(task_id)
        old_status = state.status

        state.update_from_detail(detail)

        if old_status != state.status:
            cb = self._callbacks.on_status_change
            if cb:
                cb(task_id, state.status_label)

        self._fire_terminal_callback(state)
        return state

    # ------------------------------------------------------------------
    # Poll until terminal
    # ------------------------------------------------------------------

    def wait(
        self,
        task_id: str,
        *,
        on_poll: Callable[[TaskState], None] | None = None,
        timeout_override: float | None = None,
    ) -> TaskState:
        """Poll a task until it reaches a terminal state or timeout.

        Args:
            task_id: The Ark task ID.
            on_poll: Per-iteration callback (overrides WorkflowCallbacks.on_poll).
            timeout_override: Override the default poll timeout.

        Returns:
            Final :class:`TaskState`.

        Raises:
            TimeoutError: If the task doesn't reach a terminal state in time.
        """
        interval = self._config.poll_interval_seconds
        timeout = timeout_override or self._config.poll_timeout_seconds
        deadline = time.monotonic() + timeout
        poll_cb = on_poll or self._callbacks.on_poll

        state = self._get_or_create_state(task_id)

        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Task {task_id} did not reach a terminal state "
                    f"within {timeout}s (current: {state.status_label})"
                )

            detail = self._client.get_task(task_id)
            old_status = state.status
            state.update_from_detail(detail)

            if old_status != state.status:
                cb = self._callbacks.on_status_change
                if cb:
                    cb(task_id, state.status_label)

            if poll_cb:
                poll_cb(state)

            if state.is_terminal:
                self._fire_terminal_callback(state)
                return state

            time.sleep(interval)

    # ------------------------------------------------------------------
    # Submit + wait (full flow)
    # ------------------------------------------------------------------

    def run(
        self,
        prompt: str,
        *,
        model: str | None = None,
        image_url: str | None = None,
        last_frame_url: str | None = None,
        resolution: str | None = None,
        ratio: str | None = None,
        duration: int | None = None,
        **kwargs: Any,
    ) -> TaskState:
        """Submit a task and wait for the result (full end-to-end flow).

        This is the primary entry point for simple use cases.

        Returns:
            Final :class:`TaskState` with video_url on success.

        Raises:
            TimeoutError: If polling times out.
            ArkError: On API errors.
        """
        state = self.submit(
            prompt,
            model=model,
            image_url=image_url,
            last_frame_url=last_frame_url,
            resolution=resolution,
            ratio=ratio,
            duration=duration,
            **kwargs,
        )
        return self.wait(state.task_id)

    # ------------------------------------------------------------------
    # List tasks (history)
    # ------------------------------------------------------------------

    def list(
        self,
        *,
        page_num: int = 1,
        page_size: int = 10,
        status_filter: str | list[str] | None = None,
        task_ids: list[str] | None = None,
    ) -> ArkTaskListResult:
        """List tasks with optional status filter and pagination.

        Args:
            page_num: Page number (1-based).
            page_size: Items per page.
            status_filter: Filter by status(es).
            task_ids: Filter by specific task IDs.

        Returns:
            :class:`ArkTaskListResult` with items and pagination info.
        """
        return self._client.list_tasks(
            page_num=page_num,
            page_size=page_size,
            status_filter=status_filter,
            task_ids=task_ids,
        )

    # ------------------------------------------------------------------
    # Delete / cancel
    # ------------------------------------------------------------------

    def cancel(
        self,
        task_id: str,
        *,
        confirm: bool = True,
        current_status: str | None = None,
    ) -> TaskState:
        """Cancel a queued or running video generation task.

        Args:
            task_id: The Ark task ID.
            confirm: If True, calls on_confirm_cancel callback before proceeding.
            current_status: Optional known status from history/list UI state.

        Returns:
            Updated :class:`TaskState` (normally "cancelled").
        """
        state = self._state_for_action(task_id, current_status=current_status)

        if not state.is_pending:
            raise ArkParameterError(
                f"Task {task_id!r} is {state.status!r}; only queued/running tasks can be cancelled"
            )

        if confirm:
            cb = self._callbacks.on_confirm_cancel or self._callbacks.on_confirm_delete
            if cb and not cb(task_id, state.status):
                return state  # User declined

        try:
            result = self._client.delete_task(
                task_id,
                current_status=state.status,
                refresh=True,
            )
        except Exception as exc:
            self._fire_delete_error(task_id, "cancel", exc)
            raise

        state.status = result.status
        state.updated_at = None  # Will be refreshed

        self._fire_terminal_callback(state)
        return state

    def delete(
        self,
        task_id: str,
        *,
        confirm: bool = True,
        current_status: str | None = None,
    ) -> TaskState:
        """Delete or hide a terminal video generation task.

        Args:
            task_id: The Ark task ID.
            confirm: If True, calls on_confirm_delete callback before proceeding.
            current_status: Optional known terminal status from history/list UI state.

        Returns:
            Updated :class:`TaskState` (status will be "deleted").
        """
        state = self._state_for_action(task_id, current_status=current_status)

        if state.is_pending:
            raise ArkParameterError(
                f"Task {task_id!r} is {state.status!r}; use cancel() for queued/running tasks"
            )
        if not state.is_terminal:
            raise ArkParameterError(
                f"Task {task_id!r} is {state.status!r}; only terminal tasks can be deleted"
            )

        if confirm:
            cb = self._callbacks.on_confirm_delete
            if cb and not cb(task_id, state.status):
                return state  # User declined

        try:
            result = self._client.delete_task(
                task_id,
                current_status=state.status,
                refresh=True,
            )
        except Exception as exc:
            self._fire_delete_error(task_id, "delete", exc)
            raise

        if result.remote_data is not None:
            try:
                state.update_from_detail(ArkTaskDetail.from_response(result.remote_data))
            except ValueError:
                state.status = result.status
        else:
            state.status = result.status
        state.updated_at = None  # Will be refreshed

        self._fire_terminal_callback(state)
        return state

    # ------------------------------------------------------------------
    # Access tracked tasks
    # ------------------------------------------------------------------

    def get_state(self, task_id: str) -> TaskState | None:
        """Get the locally tracked state for a task."""
        return self._tasks.get(task_id)

    def all_tasks(self) -> list[TaskState]:
        """Return all locally tracked tasks."""
        return list(self._tasks.values())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_or_create_state(self, task_id: str) -> TaskState:
        if task_id not in self._tasks:
            self._tasks[task_id] = TaskState(task_id=task_id)
        return self._tasks[task_id]

    def _state_for_action(
        self,
        task_id: str,
        *,
        current_status: str | None = None,
    ) -> TaskState:
        state = self._tasks.get(task_id)
        if state is None:
            if current_status is None:
                return self.refresh(task_id)
            state = self._get_or_create_state(task_id)

        if current_status is not None:
            status = str(current_status).strip().lower()
            if not status:
                raise ArkParameterError("Task status must not be empty")
            state.status = status
        return state

    def _guard_submission(self, payload: dict[str, Any]) -> None:
        if self._submitting:
            raise ArkParameterError("A video generation task is already being submitted")

        warnings = self._submission_warnings(payload)
        fingerprint = self._submission_fingerprint(payload)
        last = self._last_submit
        if last is not None:
            last_fingerprint, last_time = last
            window = self._config.duplicate_submit_window_seconds
            if fingerprint == last_fingerprint and time.monotonic() - last_time <= window:
                warnings.append(
                    f"Same generation parameters were submitted within {window:g}s"
                )

        if warnings:
            cb = self._callbacks.on_confirm_submit
            if cb and not cb(warnings, payload):
                raise ArkParameterError("Task submission was cancelled by confirmation")

        self._submitting = True

    def _submission_warnings(self, payload: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        if payload.get("resolution") == "1080p":
            warnings.append("1080p resolution may increase generation cost")
        duration = payload.get("duration")
        if isinstance(duration, int) and duration >= 10:
            warnings.append(f"{duration}s duration may increase generation cost")
        if payload.get("generate_audio") is True:
            warnings.append("Audio generation may increase generation cost")
        content = payload.get("content")
        if isinstance(content, list):
            media_count = sum(
                1
                for item in content
                if isinstance(item, dict)
                and item.get("type") in {"image_url", "video_url", "audio_url"}
            )
            if media_count > 1:
                warnings.append("Multiple media inputs may increase generation cost")
        return warnings

    def _submission_fingerprint(self, payload: dict[str, Any]) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def _fire_delete_error(self, task_id: str, action: str, exc: Exception) -> None:
        cb = self._callbacks.on_delete_error
        if cb:
            cb(task_id, action, exc)

    def _fire_terminal_callback(self, state: TaskState) -> None:
        if state.status == "succeeded":
            cb = self._callbacks.on_succeeded
            if cb:
                cb(state)
        elif state.status == "failed":
            cb = self._callbacks.on_failed
            if cb:
                cb(state)
        elif state.status in {"cancelled", "deleted"}:
            cb = self._callbacks.on_cancelled
            if cb:
                cb(state)
