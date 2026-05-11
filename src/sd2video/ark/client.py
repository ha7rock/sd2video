"""Unified Volcengine Ark client entrypoint."""

from __future__ import annotations

import json as jsonlib
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, urlencode

from .config import ArkConfig
from .errors import (
    ArkAPIError,
    ArkAuthenticationError,
    ArkError,
    ArkNetworkError,
    ArkParameterError,
    ArkTaskDeleteError,
    ArkTimeoutError,
)
from .task_models import CreateTaskRequest
from .transport import ArkTransport, UrllibArkTransport
from .types import (
    ArkHTTPResponse,
    ArkRequest,
    ArkResponse,
    ArkTaskDeleteResult,
    ArkTaskDetail,
    ArkTaskListResult,
)

_VALID_LOCAL_TASK_STATUSES = {
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "deleted",
}
_REMOTE_TASK_STATUSES = _VALID_LOCAL_TASK_STATUSES - {"deleted"}
_MAX_TASK_ID_LENGTH = 256


class ArkClient:
    """Single client for Ark video generation task requests."""

    def __init__(
        self,
        config: ArkConfig,
        *,
        transport: ArkTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport or UrllibArkTransport()

    @classmethod
    def from_env(
        cls,
        *,
        transport: ArkTransport | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> "ArkClient":
        return cls(ArkConfig.from_env(environ), transport=transport)

    @property
    def config(self) -> ArkConfig:
        return self._config

    # ------------------------------------------------------------------
    # High-level task operations
    # ------------------------------------------------------------------

    def create_task(
        self,
        request: CreateTaskRequest,
    ) -> str:
        """Create a video generation task and return the task ID.

        Args:
            request: A :class:`CreateTaskRequest` describing the video to generate.

        Returns:
            The Ark task ID (e.g. ``cgt-xxxxxxxx``).

        Raises:
            ArkParameterError: If required fields are missing or values are invalid.
            ArkAPIError: If the Ark API returns an error response.
        """
        if not request.model or not request.model.strip():
            request.model = self._config.default_model_id

        payload = request.build()
        response = self.request_tasks("POST", json=payload)
        data = response.data

        task_id: str | None = None
        if isinstance(data, dict):
            task_id = data.get("id")
        if not task_id:
            raise ArkAPIError(
                "Ark create-task response missing 'id' field",
                status_code=response.status_code,
            )
        return task_id

    def get_task(
        self,
        task_id: str,
    ) -> ArkTaskDetail:
        """Query a single video generation task by ID.

        Args:
            task_id: The Ark task ID (e.g. ``cgt-xxxxxxxx``).

        Returns:
            An :class:`ArkTaskDetail` with status, video_url, usage, etc.

        Raises:
            ArkParameterError: If task_id is invalid.
            ArkAPIError: If the Ark API returns an error response.
        """
        task_id = self._validate_task_id(task_id)
        response = self.request_tasks("GET", task_id=task_id)
        return ArkTaskDetail.from_response(response.data)

    def list_tasks(
        self,
        *,
        page_num: int = 1,
        page_size: int = 10,
        status_filter: str | list[str] | None = None,
        task_ids: list[str] | None = None,
    ) -> ArkTaskListResult:
        """List video generation tasks with pagination and optional filters.

        Args:
            page_num: Page number (1-based).
            page_size: Number of items per page (max 50).
            status_filter: Filter by status(es) — e.g. "queued", ["running", "succeeded"].
            task_ids: Filter by specific task IDs.

        Returns:
            An :class:`ArkTaskListResult` with items and total count.

        Raises:
            ArkParameterError: If pagination params are invalid.
            ArkAPIError: If the Ark API returns an error response.
        """
        if page_num < 1:
            raise ArkParameterError("page_num must be >= 1")
        if page_size < 1 or page_size > 50:
            raise ArkParameterError("page_size must be between 1 and 50")

        query: dict[str, Any] = {
            "page_num": page_num,
            "page_size": page_size,
        }

        if status_filter:
            statuses = (
                [status_filter] if isinstance(status_filter, str) else status_filter
            )
            for s in statuses:
                if s not in _REMOTE_TASK_STATUSES:
                    raise ArkParameterError(
                        f"Invalid status filter '{s}'; "
                        f"expected one of: {', '.join(sorted(_REMOTE_TASK_STATUSES))}"
                    )
            query["filter.status"] = ",".join(statuses)

        if task_ids:
            for tid in task_ids:
                self._validate_task_id(tid)
            query["filter.task_ids"] = ",".join(task_ids)

        response = self.request_tasks("GET", query=query)
        return ArkTaskListResult.from_response(response.data, page_num=page_num, page_size=page_size)

    def delete_task(
        self,
        task_id: str,
        *,
        current_status: str | None = None,
        refresh: bool = True,
    ) -> ArkTaskDeleteResult:
        """Cancel or delete an Ark video generation task by id."""

        task_id = self._validate_task_id(task_id)
        local_status = self._validate_local_task_status(current_status)
        if local_status == "deleted":
            return ArkTaskDeleteResult(
                task_id=task_id,
                status="deleted",
                deleted=True,
                response=None,
                message="Task is already marked deleted locally.",
            )

        try:
            delete_response = self.request_tasks("DELETE", task_id=task_id)
        except ArkAPIError as exc:
            raise self._task_delete_error(task_id, exc) from exc

        remote_status = self._extract_task_status(delete_response.data)
        refreshed = False
        remote_data: Any | None = None
        message: str | None = None

        if refresh:
            try:
                refresh_response = self.request_tasks("GET", task_id=task_id)
            except ArkAPIError as exc:
                if exc.status_code == 404:
                    refreshed = True
                    remote_status = "deleted"
                    message = "Task was deleted and is no longer returned by Ark."
                else:
                    raise
            else:
                refreshed = True
                remote_data = refresh_response.data
                remote_status = self._extract_task_status(remote_data) or remote_status

        status = self._delete_display_status(remote_status)
        return ArkTaskDeleteResult(
            task_id=task_id,
            status=status,
            deleted=True,
            response=delete_response,
            refreshed=refreshed,
            remote_status=remote_status,
            remote_data=remote_data,
            message=message,
        )

    def deleteTask(
        self,
        task_id: str,
        *,
        current_status: str | None = None,
        refresh: bool = True,
    ) -> ArkTaskDeleteResult:
        """CamelCase compatibility wrapper for callers that expect deleteTask(id)."""

        return self.delete_task(
            task_id,
            current_status=current_status,
            refresh=refresh,
        )

    # ------------------------------------------------------------------
    # Low-level request methods
    # ------------------------------------------------------------------

    def request_tasks(
        self,
        method: str,
        *,
        task_id: str | None = None,
        query: Mapping[str, Any] | None = None,
        json: Any | None = None,
    ) -> ArkResponse:
        """Request the Ark video generation task resource without caller URL work."""

        return self.request(
            method,
            self._task_path(task_id),
            query=query,
            json=json,
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        json: Any | None = None,
    ) -> ArkResponse:
        request = ArkRequest(
            method=method.upper(),
            url=self._build_url(path, query=query),
            headers=self._headers(),
            body=self._encode_body(json),
        )

        try:
            http_response = self._transport.send(
                request,
                timeout=self._config.timeout_seconds,
            )
        except ArkError:
            raise
        except TimeoutError as exc:
            raise ArkTimeoutError("Ark request timed out") from exc
        except OSError as exc:
            raise ArkNetworkError("Ark network request failed") from exc

        data = self._decode_body(http_response.body)
        if http_response.status_code >= 400:
            raise self._map_error(http_response, data)
        return ArkResponse(
            status_code=http_response.status_code,
            headers=http_response.headers,
            data=data,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _task_path(self, task_id: str | None) -> str:
        path = self._config.tasks_path
        if task_id is None:
            return path
        return f"{path}/{quote(task_id, safe='')}"

    def _validate_task_id(self, task_id: str) -> str:
        if not isinstance(task_id, str):
            raise ArkParameterError("Ark task id must be a string")

        task_id = task_id.strip()
        if not task_id:
            raise ArkParameterError("Ark task id is required")
        if len(task_id) > _MAX_TASK_ID_LENGTH:
            raise ArkParameterError("Ark task id is too long")
        if any(
            char.isspace() or ord(char) < 32 or ord(char) == 127
            for char in task_id
        ):
            raise ArkParameterError("Ark task id must not contain whitespace or controls")
        if "/" in task_id or "\\" in task_id:
            raise ArkParameterError("Ark task id must not contain path separators")
        return task_id

    def _validate_local_task_status(self, current_status: str | None) -> str | None:
        if current_status is None:
            return None
        status = str(current_status).strip().lower()
        if not status:
            raise ArkParameterError("Local task status must not be empty")
        if status not in _VALID_LOCAL_TASK_STATUSES:
            expected = ", ".join(sorted(_VALID_LOCAL_TASK_STATUSES))
            raise ArkParameterError(
                f"Unsupported local task status {status!r}; expected one of {expected}"
            )
        return status

    def _extract_task_status(self, data: Any) -> str | None:
        for value in self._status_candidates(data):
            status = str(value).strip().lower()
            if status in _REMOTE_TASK_STATUSES:
                return status
            if status == "deleted":
                return status
        return None

    def _status_candidates(self, data: Any) -> list[Any]:
        if not isinstance(data, Mapping):
            return []

        candidates: list[Any] = []
        for key in ("status", "state", "task_status"):
            if key in data:
                candidates.append(data[key])

        for key in ("task", "data", "result"):
            nested = data.get(key)
            if isinstance(nested, Mapping):
                candidates.extend(self._status_candidates(nested))
        return candidates

    def _delete_display_status(self, remote_status: str | None) -> str:
        if remote_status == "cancelled":
            return "cancelled"
        return "deleted"

    def _task_delete_error(self, task_id: str, error: ArkAPIError) -> ArkTaskDeleteError:
        status_code = error.status_code
        if status_code == 404:
            message = f"Task {task_id!r} was not found or has already been deleted."
        elif status_code in {401, 403}:
            message = (
                f"No permission to delete task {task_id!r}, "
                "or the Ark API key is invalid."
            )
        elif status_code == 409:
            message = f"Task {task_id!r} cannot be deleted in its current remote state."
        elif status_code in {400, 422}:
            message = f"Ark rejected task id {task_id!r} for deletion: {error.message}"
        else:
            message = f"Failed to delete task {task_id!r}: {error.message}"
        return ArkTaskDeleteError(
            message,
            task_id=task_id,
            status_code=error.status_code,
            code=error.code,
            request_id=error.request_id,
        )

    def _build_url(
        self,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
    ) -> str:
        normalized_path = path if path.startswith("/") else f"/{path}"
        url = f"{self._config.base_url}{normalized_path}"
        if query:
            filtered_query = {key: value for key, value in query.items() if value is not None}
            if filtered_query:
                url = f"{url}?{urlencode(filtered_query, doseq=True)}"
        return url

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _encode_body(payload: Any | None) -> bytes | None:
        if payload is None:
            return None
        return jsonlib.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )

    @staticmethod
    def _decode_body(body: bytes) -> Any:
        if not body:
            return None
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            return body
        try:
            return jsonlib.loads(text)
        except jsonlib.JSONDecodeError:
            return text

    def _map_error(self, response: ArkHTTPResponse, data: Any) -> ArkAPIError:
        code, message, request_id = self._extract_error(data, response.headers)
        status_code = response.status_code
        error_type: type[ArkAPIError]
        if status_code in {401, 403}:
            error_type = ArkAuthenticationError
        elif status_code in {400, 422}:
            error_type = ArkParameterError
        else:
            error_type = ArkAPIError
        return error_type(
            message or "Ark API request failed",
            status_code=status_code,
            code=code,
            request_id=request_id,
        )

    def _extract_error(
        self,
        data: Any,
        headers: Mapping[str, str],
    ) -> tuple[str | None, str | None, str | None]:
        source: Mapping[str, Any] = {}
        message: str | None = None
        if isinstance(data, Mapping):
            error = data.get("error")
            if isinstance(error, Mapping):
                source = error
            else:
                source = data
                if isinstance(error, str):
                    message = error
        elif isinstance(data, str):
            message = data

        code = (source.get("code") or source.get("type")) if source else None
        message = (
            message
            or (source.get("message") if source else None)
            or (source.get("msg") if source else None)
            or (source.get("error_description") if source else None)
        )
        request_id = (
            _header(headers, "x-request-id")
            or _header(headers, "x-tt-logid")
            or (source.get("request_id") if source else None)
        )
        return (
            self._sanitize(code),
            self._sanitize(message),
            self._sanitize(request_id),
        )

    def _sanitize(self, value: Any | None) -> str | None:
        if value is None:
            return None
        text = str(value)
        if self._config.api_key:
            text = text.replace(self._config.api_key, "<redacted>")
        return text


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None
