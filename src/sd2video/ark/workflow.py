"""End-to-end video generation workflow for Ark.

Ties together create → poll → get result → cancel/delete into a user-facing flow.
No API key is ever exposed in logs, errors, or UI output.
"""

from __future__ import annotations

import hashlib
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
# Cost thresholds — tasks exceeding these are considered "expensive"
# ---------------------------------------------------------------------------

_COST_HIGH_DURATION_SECONDS = 10
_COST_HIGH_RESOLUTION = "1080p"


# ---------------------------------------------------------------------------
# Workflow configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WorkflowConfig:
    """Configuration for the video generation workflow."""

    poll_interval_seconds: float = 5.0
    poll_timeout_seconds: float = 600.0
    default_model: str | None = None


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
    on_confirm_delete: Callable[[str, str], bool] | None = None  # (task_id, status) -> confirmed
    on_confirm_cancel: Callable[[str, str], bool] | None = None  # (task_id, status) -> confirmed
    on_confirm_submit: Callable[[dict[str, Any]], tuple[bool, str | None]] | None = None  # (params) -> (proceed, warning)
    on_submit_error: Callable[[str, Exception], None] | None = None  # (task_id, error)
    on_delete_error: Callable[[str, Exception], None] | None = None  # (task_id, error)


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
        self._submitting: bool = False
        self._recent_submissions: list[tuple[float, str]] = []  # (timestamp, fingerprint)
        self._duplicate_window_seconds: float = 5.0

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

        Raises:
            ArkParameterError: If a duplicate submission is detected.
        """
        # Guard: prevent concurrent submissions
        if self._submitting:
            raise ArkParameterError(
                "A submission is already in progress. Please wait for it to complete."
            )

        # Build params dict for cost check and fingerprinting
        params: dict[str, Any] = {
            "prompt": prompt,
            "model": model or self._config.default_model or "",
            "image_url": image_url,
            "last_frame_url": last_frame_url,
            "resolution": resolution,
            "ratio": ratio,
            "duration": duration,
            "frames": frames,
            "seed": seed,
            "camera_fixed": camera_fixed,
            "watermark": watermark,
            "generate_audio": generate_audio,
            "service_tier": service_tier,
        }

        # Check for duplicate submission
        self._check_duplicate_submission(params)

        # Cost confirmation
        cost_warning = self._check_cost(params)
        if cost_warning:
            cb = self._callbacks.on_confirm_submit
            if cb:
                proceed, _warning = cb(params)
                if not proceed:
                    raise ArkParameterError("Submission cancelled by user due to cost warning.")

        effective_model = model or self._config.default_model or ""

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

        self._submitting = True
        try:
            task_id = self._client.create_task(request)
        except Exception as exc:
            cb = self._callbacks.on_submit_error
            if cb:
                cb("", exc)
            raise
        finally:
            self._submitting = False

        # Record submission fingerprint for duplicate detection
        self._record_submission(params)

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
    ) -> TaskState:
        """Cancel a pending (queued/running) video generation task.

        Args:
            task_id: The Ark task ID.
            confirm: If True, calls on_confirm_cancel callback before proceeding.

        Returns:
            Updated :class:`TaskState` (status will be "cancelled").

        Raises:
            ArkParameterError: If the task is not in a cancellable state.
        """
        state = self._get_or_create_state(task_id)

        if state.status not in {"queued", "running"}:
            raise ArkParameterError(
                f"Cannot cancel task {task_id!r}: status is {state.status!r}. "
                "Only queued or running tasks can be cancelled."
            )

        if confirm:
            cb = self._callbacks.on_confirm_cancel
            if cb and not cb(task_id, state.status):
                return state  # User declined

        old_status = state.status
        try:
            result = self._client.delete_task(
                task_id,
                current_status=state.status,
                refresh=True,
            )
        except ArkError as exc:
            cb = self._callbacks.on_delete_error
            if cb:
                cb(task_id, exc)
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
    ) -> TaskState:
        """Delete a video generation task in a terminal state.

        Args:
            task_id: The Ark task ID.
            confirm: If True, calls on_confirm_delete callback before proceeding.

        Returns:
            Updated :class:`TaskState` (status will be "cancelled" or "deleted").

        Raises:
            ArkParameterError: If the task is still pending (use cancel() instead).
        """
        state = self._get_or_create_state(task_id)

        # Warn if task is still pending — suggest cancel() instead
        if state.status in {"queued", "running"}:
            raise ArkParameterError(
                f"Task {task_id!r} is still {state.status!r}. "
                "Use cancel() to stop a running task, or delete(confirm=False) to force."
            )

        if confirm:
            cb = self._callbacks.on_confirm_delete
            if cb and not cb(task_id, state.status):
                return state  # User declined

        old_status = state.status
        try:
            result = self._client.delete_task(
                task_id,
                current_status=state.status,
                refresh=True,
            )
        except ArkError as exc:
            cb = self._callbacks.on_delete_error
            if cb:
                cb(task_id, exc)
            raise

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

    # ------------------------------------------------------------------
    # Cost protection
    # ------------------------------------------------------------------

    @staticmethod
    def _check_cost(params: dict[str, Any]) -> str | None:
        """Return a warning message if the task is expensive, else None."""
        warnings: list[str] = []

        resolution = params.get("resolution")
        if resolution == _COST_HIGH_RESOLUTION:
            warnings.append(f"分辨率 {resolution} 会消耗更多算力")

        duration = params.get("duration")
        if duration is not None and isinstance(duration, int) and duration >= _COST_HIGH_DURATION_SECONDS:
            warnings.append(f"时长 {duration}s 较长")

        generate_audio = params.get("generate_audio")
        if generate_audio is True:
            warnings.append("生成音频会增加费用")

        # Count material items (images + videos)
        image_url = params.get("image_url")
        last_frame_url = params.get("last_frame_url")
        material_count = sum(1 for u in [image_url, last_frame_url] if u)
        if material_count >= 2:
            warnings.append(f"使用了 {material_count} 个素材")

        return "; ".join(warnings) if warnings else None

    # ------------------------------------------------------------------
    # Duplicate submission detection
    # ------------------------------------------------------------------

    @staticmethod
    def _fingerprint(params: dict[str, Any]) -> str:
        """Compute a stable fingerprint for a set of submission params."""
        # Only include meaningful params, skip None values
        parts = []
        for key in sorted(params.keys()):
            val = params[key]
            if val is not None:
                parts.append(f"{key}={val!r}")
        raw = "|".join(parts)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _check_duplicate_submission(self, params: dict[str, Any]) -> None:
        """Raise if a matching submission was made within the duplicate window."""
        now = time.monotonic()
        fp = self._fingerprint(params)

        # Prune stale entries
        cutoff = now - self._duplicate_window_seconds
        self._recent_submissions = [
            (ts, f) for ts, f in self._recent_submissions if ts > cutoff
        ]

        for _ts, recent_fp in self._recent_submissions:
            if recent_fp == fp:
                raise ArkParameterError(
                    "检测到重复提交：相同参数的任务刚刚已提交，请勿重复操作。"
                )

    def _record_submission(self, params: dict[str, Any]) -> None:
        """Record a successful submission for duplicate detection."""
        fp = self._fingerprint(params)
        self._recent_submissions.append((time.monotonic(), fp))
