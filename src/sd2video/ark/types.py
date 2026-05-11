"""Transport and response value objects for the Ark client."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, repr=False)
class ArkRequest:
    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes | None = None

    def __repr__(self) -> str:
        headers = {
            key: "<redacted>" if key.lower() == "authorization" else value
            for key, value in self.headers.items()
        }
        body = None if self.body is None else f"<{len(self.body)} bytes>"
        return (
            "ArkRequest("
            f"method={self.method!r}, "
            f"url={self.url!r}, "
            f"headers={headers!r}, "
            f"body={body!r}"
            ")"
        )


@dataclass(frozen=True)
class ArkHTTPResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes = b""


@dataclass(frozen=True)
class ArkResponse:
    status_code: int
    headers: Mapping[str, str]
    data: Any


@dataclass(frozen=True)
class ArkTaskDeleteResult:
    task_id: str
    status: str
    deleted: bool
    response: ArkResponse | None
    refreshed: bool = False
    remote_status: str | None = None
    remote_data: Any | None = None
    message: str | None = None


# ---------------------------------------------------------------------------
# Task query types
# ---------------------------------------------------------------------------

# Display labels for task statuses (user-facing)
STATUS_LABELS: dict[str, str] = {
    "queued": "排队中",
    "running": "生成中",
    "succeeded": "已完成",
    "failed": "生成失败",
    "cancelled": "已取消",
    "deleted": "已删除",
}


@dataclass
class ArkTaskDetail:
    """Parsed result from querying a single Ark video generation task."""

    task_id: str
    status: str
    model: str | None = None
    video_url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    usage: dict[str, Any] | None = None
    content: list[dict[str, Any]] | None = None
    raw: Any = field(default=None, repr=False)

    @classmethod
    def from_response(cls, data: Any) -> ArkTaskDetail:
        """Parse the Ark API response into a structured task detail."""
        if not isinstance(data, Mapping):
            raise ValueError(f"Unexpected response type: {type(data).__name__}")

        # Ark wraps the task in "data" for single-task queries
        task_data = data.get("data", data)
        if not isinstance(task_data, Mapping):
            task_data = data

        task_id = str(task_data.get("id", ""))
        status = str(task_data.get("status", "unknown")).lower()

        model = task_data.get("model")
        if isinstance(model, Mapping):
            model = model.get("id") or model.get("name")

        # Extract video_url from content array
        video_url = cls._extract_video_url(task_data)

        return cls(
            task_id=task_id,
            status=status,
            model=str(model) if model else None,
            video_url=video_url,
            created_at=task_data.get("created_at"),
            updated_at=task_data.get("updated_at"),
            usage=task_data.get("usage"),
            content=task_data.get("content"),
            raw=data,
        )

    @staticmethod
    def _extract_video_url(task_data: Mapping) -> str | None:
        """Extract video_url from various response shapes."""
        # Direct video_url field
        v = task_data.get("video_url")
        if isinstance(v, str) and v:
            return v

        # Nested in content array
        content = task_data.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, Mapping):
                    if item.get("type") == "video_url":
                        url = item.get("video_url")
                        if isinstance(url, Mapping):
                            return url.get("url")
                        elif isinstance(url, str):
                            return url
        return None

    @property
    def status_label(self) -> str:
        """Human-readable Chinese status label."""
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def is_terminal(self) -> bool:
        """True if the task has reached a final state."""
        return self.status in {"succeeded", "failed", "cancelled", "deleted"}

    @property
    def is_pending(self) -> bool:
        """True if the task is still in progress."""
        return self.status in {"queued", "running"}

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"


@dataclass
class ArkTaskListResult:
    """Parsed result from listing Ark video generation tasks."""

    items: list[ArkTaskDetail]
    total: int
    page_num: int
    page_size: int
    raw: Any = field(default=None, repr=False)

    @classmethod
    def from_response(
        cls,
        data: Any,
        *,
        page_num: int,
        page_size: int,
    ) -> ArkTaskListResult:
        """Parse the Ark API list response."""
        if not isinstance(data, Mapping):
            return cls(
                items=[], total=0, page_num=page_num, page_size=page_size, raw=data
            )

        total = data.get("total", 0)
        if not isinstance(total, int):
            total = int(total) if str(total).isdigit() else 0

        items_raw = data.get("items", data.get("data", []))
        if not isinstance(items_raw, list):
            items_raw = []

        items: list[ArkTaskDetail] = []
        for item in items_raw:
            try:
                items.append(ArkTaskDetail.from_response(item))
            except (ValueError, KeyError):
                continue

        return cls(
            items=items,
            total=total,
            page_num=page_num,
            page_size=page_size,
            raw=data,
        )

    @property
    def has_more(self) -> bool:
        return self.page_num * self.page_size < self.total
