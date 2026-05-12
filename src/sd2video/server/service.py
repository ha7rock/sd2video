"""Backend adapters and request shaping for the v1 video service."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from sd2video.ark import (
    ArkAPIError,
    ArkClient,
    ArkConfig,
    ArkParameterError,
    ArkTaskDeleteResult,
    ArkTaskDetail,
    ArkTaskListResult,
    CreateTaskRequest,
)
from sd2video.ark.task_models import (
    audio_content,
    image_content,
    text_content,
    video_content,
)

from .config import ServerConfig
from .errors import ServiceHTTPError

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "deleted"}
VALID_MODES = {"t2v", "first_frame", "first_last", "reference", "edit", "extend"}


class VideoBackend(ABC):
    """Small task API consumed by the HTTP layer."""

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self._requests: dict[str, tuple[float, dict[str, Any]]] = {}

    @abstractmethod
    def create_task(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_task(self, task_id: str) -> ArkTaskDetail:
        raise NotImplementedError

    @abstractmethod
    def list_tasks(
        self,
        *,
        page_num: int = 1,
        page_size: int = 10,
        status_filter: str | list[str] | None = None,
        task_ids: list[str] | None = None,
    ) -> ArkTaskListResult:
        raise NotImplementedError

    @abstractmethod
    def delete_task(
        self,
        task_id: str,
        *,
        current_status: str | None = None,
    ) -> ArkTaskDeleteResult:
        raise NotImplementedError

    def poll_task(
        self,
        task_id: str,
        *,
        interval_seconds: float,
        timeout_seconds: float,
    ) -> ArkTaskDetail:
        deadline = time.monotonic() + timeout_seconds
        while True:
            detail = self.get_task(task_id)
            if detail.status in TERMINAL_STATUSES:
                return detail
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Task {task_id} did not reach a terminal state within {timeout_seconds}s"
                )
            time.sleep(interval_seconds)

    def _check_duplicate(self, payload: Mapping[str, Any]) -> dict[str, Any] | None:
        client_request_id = str(payload.get("client_request_id") or "").strip()
        if not client_request_id:
            return None

        now = time.monotonic()
        cutoff = now - self.config.duplicate_window_seconds
        self._requests = {
            key: value for key, value in self._requests.items() if value[0] >= cutoff
        }
        existing = self._requests.get(client_request_id)
        if existing:
            return existing[1]
        return None

    def _remember_request(self, payload: Mapping[str, Any], created: dict[str, Any]) -> None:
        client_request_id = str(payload.get("client_request_id") or "").strip()
        if client_request_id:
            self._requests[client_request_id] = (time.monotonic(), created)


class LiveArkBackend(VideoBackend):
    """Adapter that delegates to the existing Ark SDK."""

    def __init__(self, config: ServerConfig, client: ArkClient) -> None:
        super().__init__(config)
        self._client = client

    @classmethod
    def from_env(cls, config: ServerConfig) -> "LiveArkBackend":
        return cls(config, ArkClient(ArkConfig.from_env()))

    def create_task(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        existing = self._check_duplicate(payload)
        if existing:
            _raise_duplicate(existing)

        request, summary = build_create_request(
            payload,
            default_model_id=self.config.default_model_id,
        )
        task_id = self._client.create_task(request)
        created = serialize_created_task(
            task_id,
            model=request.model,
            payload=payload,
            request_summary=summary,
        )
        self._remember_request(payload, created)
        return created

    def get_task(self, task_id: str) -> ArkTaskDetail:
        return self._client.get_task(task_id)

    def list_tasks(
        self,
        *,
        page_num: int = 1,
        page_size: int = 10,
        status_filter: str | list[str] | None = None,
        task_ids: list[str] | None = None,
    ) -> ArkTaskListResult:
        return self._client.list_tasks(
            page_num=page_num,
            page_size=page_size,
            status_filter=status_filter,
            task_ids=task_ids,
        )

    def delete_task(
        self,
        task_id: str,
        *,
        current_status: str | None = None,
    ) -> ArkTaskDeleteResult:
        return self._client.delete_task(task_id, current_status=current_status)


class MockVideoBackend(VideoBackend):
    """Deterministic in-memory backend for local development and tests."""

    def __init__(self, config: ServerConfig | None = None) -> None:
        super().__init__(config or ServerConfig())
        self._tasks: dict[str, dict[str, Any]] = {}

    def create_task(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        existing = self._check_duplicate(payload)
        if existing:
            _raise_duplicate(existing)

        request, summary = build_create_request(
            payload,
            default_model_id=self.config.default_model_id,
        )
        body = request.build()
        now = _utc_now()
        task_id = f"cgt-mock-{uuid.uuid4().hex[:16]}"
        task = {
            "id": task_id,
            "status": "queued",
            "model": body["model"],
            "content": body["content"],
            "created_at": now,
            "updated_at": now,
            "usage": {"mock": True},
            "request_summary": summary,
            "mock_poll_count": 0,
        }
        self._tasks[task_id] = task
        created = serialize_created_task(
            task_id,
            model=body["model"],
            payload=payload,
            created_at=now,
            request_summary=summary,
        )
        self._remember_request(payload, created)
        return created

    def get_task(self, task_id: str) -> ArkTaskDetail:
        task = self._get_task_data(task_id)
        self._advance_mock_task(task)
        return ArkTaskDetail.from_response({"data": deepcopy(task)})

    def list_tasks(
        self,
        *,
        page_num: int = 1,
        page_size: int = 10,
        status_filter: str | list[str] | None = None,
        task_ids: list[str] | None = None,
    ) -> ArkTaskListResult:
        if page_num < 1:
            raise ArkParameterError("page_num must be >= 1")
        if page_size < 1 or page_size > 50:
            raise ArkParameterError("page_size must be between 1 and 50")

        statuses = None
        if status_filter:
            statuses = [status_filter] if isinstance(status_filter, str) else status_filter
            for status in statuses:
                if status not in {"queued", "running", *TERMINAL_STATUSES}:
                    raise ArkParameterError(f"Invalid status filter '{status}'")
        if isinstance(task_ids, str):
            task_ids = [task_ids]
        task_id_set = set(task_ids or [])

        items = []
        for task in self._tasks.values():
            if statuses and task["status"] not in statuses:
                continue
            if task_id_set and task["id"] not in task_id_set:
                continue
            items.append(deepcopy(task))

        total = len(items)
        start = (page_num - 1) * page_size
        page = items[start:start + page_size]
        return ArkTaskListResult.from_response(
            {"total": total, "items": page},
            page_num=page_num,
            page_size=page_size,
        )

    def delete_task(
        self,
        task_id: str,
        *,
        current_status: str | None = None,
    ) -> ArkTaskDeleteResult:
        task = self._get_task_data(task_id)
        status = "cancelled" if task.get("status") in {"queued", "running"} else "deleted"
        task["status"] = status
        task["updated_at"] = _utc_now()
        return ArkTaskDeleteResult(
            task_id=task_id,
            status=status,
            deleted=True,
            response=None,
            refreshed=True,
            remote_status=status,
            remote_data=deepcopy(task),
            message=None,
        )

    def _get_task_data(self, task_id: str) -> dict[str, Any]:
        task_id = _validate_task_id(task_id)
        try:
            return self._tasks[task_id]
        except KeyError as exc:
            raise ArkAPIError(
                f"Task {task_id!r} was not found",
                status_code=404,
                code="TaskNotFound",
            ) from exc

    def _advance_mock_task(self, task: dict[str, Any]) -> None:
        if task["status"] in TERMINAL_STATUSES:
            return
        task["mock_poll_count"] += 1
        if task["mock_poll_count"] == 1:
            task["status"] = "running"
        else:
            task["status"] = "succeeded"
            task["video_url"] = "data:video/mp4;base64,AAAA"
            task["content"] = list(task["content"]) + [
                {
                    "type": "video_url",
                    "video_url": {"url": task["video_url"]},
                }
            ]
        task["updated_at"] = _utc_now()


def build_backend(config: ServerConfig) -> VideoBackend:
    if config.mock:
        return MockVideoBackend(config)
    return LiveArkBackend.from_env(config)


def build_create_request(
    payload: Mapping[str, Any],
    *,
    default_model_id: str,
) -> tuple[CreateTaskRequest, dict[str, Any]]:
    """Convert contract JSON into the SDK's validated CreateTaskRequest."""

    if not isinstance(payload, Mapping):
        raise ArkParameterError("JSON body must be an object")

    mode = str(payload.get("mode") or "").strip()
    if mode not in VALID_MODES:
        raise ServiceHTTPError(
            400,
            "parameter_invalid",
            f"mode must be one of: {', '.join(sorted(VALID_MODES))}",
            field="mode",
        )

    model = str(payload.get("model") or default_model_id).strip()
    if not model:
        raise ServiceHTTPError(400, "parameter_invalid", "model is required", field="model")
    if "content" in payload:
        raise ServiceHTTPError(
            400,
            "parameter_invalid",
            "content is generated by the backend and must not be sent",
            field="content",
        )
    if payload.get("duration") is not None and payload.get("frames") is not None:
        raise ServiceHTTPError(
            400,
            "parameter_invalid",
            "duration and frames are mutually exclusive",
            field="duration",
        )
    if payload.get("web_search") and mode != "t2v":
        raise ServiceHTTPError(
            400,
            "mode_constraint_violation",
            "web_search is only supported for t2v mode",
            field="web_search",
        )

    assets = payload.get("assets") or {}
    if not isinstance(assets, Mapping):
        raise ServiceHTTPError(400, "parameter_invalid", "assets must be an object", field="assets")

    common = _common_create_kwargs(payload)
    prompt = str(payload.get("prompt") or "").strip()
    request = CreateTaskRequest(
        model=model,
        content=_build_content(mode, prompt, assets),
        **common,
    )
    return request, _request_summary(payload, mode, model)


def serialize_created_task(
    task_id: str,
    *,
    model: str,
    payload: Mapping[str, Any],
    created_at: str | None = None,
    request_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "status": "queued",
        "model": model,
        "created_at": created_at or _utc_now(),
        "submitted_payload_digest": _payload_digest(payload),
        "request_summary": dict(request_summary or {}),
    }


def serialize_task(detail: ArkTaskDetail) -> dict[str, Any]:
    updated_at = detail.updated_at or detail.created_at
    return {
        "task_id": detail.task_id,
        "status": detail.status,
        "model": detail.model,
        "video_url": detail.video_url,
        "video_url_expires_at": _expires_at(updated_at) if detail.video_url else None,
        "last_frame_url": _extract_last_frame_url(detail.raw),
        "created_at": detail.created_at,
        "updated_at": detail.updated_at,
        "usage": detail.usage,
        "error_message": _extract_task_error_message(detail.raw),
        "request_summary": _extract_request_summary(detail.raw),
    }


def serialize_list(result: ArkTaskListResult) -> dict[str, Any]:
    return {
        "items": [
            {
                "task_id": item.task_id,
                "status": item.status,
                "model": item.model,
                "video_url": item.video_url,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
                "request_summary": _extract_request_summary(item.raw),
            }
            for item in result.items
        ],
        "total": result.total,
        "page_num": result.page_num,
        "page_size": result.page_size,
        "has_more": result.has_more,
    }


def serialize_delete(result: ArkTaskDeleteResult) -> dict[str, Any]:
    return {
        "task_id": result.task_id,
        "status": result.status,
        "deleted": result.deleted,
        "message": result.message,
    }


def _build_content(
    mode: str,
    prompt: str,
    assets: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if mode == "t2v":
        if not prompt:
            raise ServiceHTTPError(400, "parameter_invalid", "prompt is required", field="prompt")
        return [text_content(prompt)]

    items: list[dict[str, Any]] = []
    if prompt:
        items.append(text_content(prompt))

    if mode == "first_frame":
        first_frame = _required_asset(assets, "first_frame")
        items.append(image_content(first_frame, role="first_frame"))
    elif mode == "first_last":
        items.append(image_content(_required_asset(assets, "first_frame"), role="first_frame"))
        items.append(image_content(_required_asset(assets, "last_frame"), role="last_frame"))
    elif mode == "reference":
        images = _asset_list(assets, "reference_images", limit=9)
        videos = _asset_list(assets, "reference_videos", limit=3)
        audios = _asset_list(assets, "reference_audios", limit=3)
        if not images and not videos:
            raise ServiceHTTPError(
                400,
                "mode_constraint_violation",
                "reference mode requires at least one image or video",
                field="assets",
            )
        items.extend(image_content(url, role="reference_image") for url in images)
        items.extend(video_content(url) for url in videos)
        items.extend(audio_content(url) for url in audios)
    elif mode == "edit":
        items.append(video_content(_required_asset(assets, "edit_video")))
        items.extend(
            image_content(url, role="reference_image")
            for url in _asset_list(assets, "reference_images", limit=9)
        )
        items.extend(audio_content(url) for url in _asset_list(assets, "reference_audios", limit=3))
    elif mode == "extend":
        videos = _asset_list(assets, "reference_videos", limit=3)
        if not videos:
            raise ServiceHTTPError(
                400,
                "mode_constraint_violation",
                "extend mode requires at least one reference video",
                field="assets.reference_videos",
            )
        items.extend(video_content(url) for url in videos)

    if not items:
        raise ServiceHTTPError(400, "mode_constraint_violation", "mode has no valid input")
    return items


def _common_create_kwargs(payload: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "resolution",
        "ratio",
        "duration",
        "frames",
        "seed",
        "camera_fixed",
        "watermark",
        "generate_audio",
        "service_tier",
        "return_last_frame",
        "safety_identifier",
    )
    kwargs = {key: payload[key] for key in keys if payload.get(key) is not None}
    if payload.get("web_search"):
        kwargs["tools"] = [{"type": "web_search"}]
    return kwargs


def _request_summary(payload: Mapping[str, Any], mode: str, model: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "model": model,
        "ratio": payload.get("ratio"),
        "resolution": payload.get("resolution"),
        "duration": payload.get("duration"),
        "generate_audio": bool(payload.get("generate_audio", False)),
    }


def _required_asset(assets: Mapping[str, Any], key: str) -> str:
    value = assets.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ServiceHTTPError(
            400,
            "mode_constraint_violation",
            f"assets.{key} is required",
            field=f"assets.{key}",
        )
    return value.strip()


def _asset_list(assets: Mapping[str, Any], key: str, *, limit: int) -> list[str]:
    value = assets.get(key) or []
    if not isinstance(value, list):
        raise ServiceHTTPError(
            400,
            "parameter_invalid",
            f"assets.{key} must be a list",
            field=f"assets.{key}",
        )
    if len(value) > limit:
        raise ServiceHTTPError(
            400,
            "mode_constraint_violation",
            f"assets.{key} exceeds the limit of {limit}",
            field=f"assets.{key}",
        )
    return [str(item).strip() for item in value if str(item).strip()]


def _raise_duplicate(existing: Mapping[str, Any]) -> None:
    raise ServiceHTTPError(
        409,
        "duplicate_request",
        "A task with the same client_request_id already exists.",
        extra={"existing": {"task_id": existing["task_id"], "status": existing["status"]}},
    )


def _payload_digest(payload: Mapping[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(body.encode('utf-8')).hexdigest()}"


def _extract_request_summary(raw: Any) -> dict[str, Any] | None:
    task_data = _task_data(raw)
    summary = task_data.get("request_summary") if isinstance(task_data, Mapping) else None
    return dict(summary) if isinstance(summary, Mapping) else None


def _extract_task_error_message(raw: Any) -> str | None:
    task_data = _task_data(raw)
    if not isinstance(task_data, Mapping):
        return None
    error = task_data.get("error")
    if isinstance(error, Mapping):
        return error.get("message") or error.get("msg")
    message = task_data.get("status_message") or task_data.get("message")
    return message if isinstance(message, str) and message else None


def _extract_last_frame_url(raw: Any) -> str | None:
    task_data = _task_data(raw)
    if not isinstance(task_data, Mapping):
        return None
    for key in ("last_frame_url", "last_image_url"):
        value = task_data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _task_data(raw: Any) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        return {}
    data = raw.get("data", raw)
    return data if isinstance(data, Mapping) else raw


def _expires_at(updated_at: str | None) -> str | None:
    if not updated_at:
        return None
    try:
        base = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (base + timedelta(hours=24)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_task_id(task_id: str) -> str:
    if not isinstance(task_id, str) or not task_id.strip():
        raise ArkParameterError("task id is required")
    task_id = task_id.strip()
    if "/" in task_id or "\\" in task_id or any(char.isspace() for char in task_id):
        raise ArkParameterError("task id is invalid")
    return task_id


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
