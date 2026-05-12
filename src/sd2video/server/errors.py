"""HTTP error mapping for Ark and service exceptions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sd2video.ark import (
    ArkAPIError,
    ArkAuthenticationError,
    ArkConfigError,
    ArkNetworkError,
    ArkParameterError,
    ArkTaskDeleteError,
    ArkTimeoutError,
)


@dataclass
class ServiceHTTPError(Exception):
    status: int
    code: str
    message: str
    field: str | None = None
    retryable: bool = False
    extra: dict[str, Any] | None = None


def map_exception(exc: Exception, *, request_id: str | None = None) -> tuple[int, dict[str, Any]]:
    """Map internal exceptions to the v1 contract error shape."""

    if isinstance(exc, ServiceHTTPError):
        return _error(
            exc.status,
            exc.code,
            exc.message,
            request_id=request_id,
            field=exc.field,
            retryable=exc.retryable,
            extra=exc.extra,
        )
    if isinstance(exc, ArkAuthenticationError):
        return _error(401, "upstream_unauthorized", str(exc), request_id=request_id)
    if isinstance(exc, ArkParameterError):
        return _error(400, "parameter_invalid", str(exc), request_id=request_id)
    if isinstance(exc, ArkTaskDeleteError):
        if exc.status_code == 404:
            return _error(404, "task_not_found", str(exc), request_id=request_id, exc=exc)
        return _error(409, "task_state_conflict", str(exc), request_id=request_id, exc=exc)
    if isinstance(exc, ArkTimeoutError) or isinstance(exc, TimeoutError):
        return _error(
            504,
            "upstream_timeout",
            str(exc),
            request_id=request_id,
            retryable=True,
        )
    if isinstance(exc, ArkNetworkError):
        return _error(
            502,
            "upstream_failed",
            str(exc),
            request_id=request_id,
            retryable=True,
        )
    if isinstance(exc, ArkConfigError):
        return _error(500, "internal_error", str(exc), request_id=request_id)
    if isinstance(exc, ArkAPIError):
        if exc.status_code == 404:
            return _error(404, "task_not_found", str(exc), request_id=request_id, exc=exc)
        if exc.status_code == 429:
            return _error(
                429,
                "rate_limited",
                str(exc),
                request_id=request_id,
                retryable=True,
                exc=exc,
            )
        if exc.status_code in {400, 422}:
            return _error(400, "parameter_invalid", str(exc), request_id=request_id, exc=exc)
        if exc.status_code and exc.status_code >= 500:
            return _error(
                502,
                "upstream_failed",
                str(exc),
                request_id=request_id,
                retryable=True,
                exc=exc,
            )
        return _error(500, "internal_error", str(exc), request_id=request_id, exc=exc)
    if isinstance(exc, ValueError):
        return _error(400, "parameter_invalid", str(exc), request_id=request_id)
    return _error(500, "internal_error", "Internal server error", request_id=request_id)


def _error(
    status: int,
    code: str,
    message: str,
    *,
    request_id: str | None,
    field: str | None = None,
    retryable: bool | None = None,
    extra: dict[str, Any] | None = None,
    exc: ArkAPIError | None = None,
) -> tuple[int, dict[str, Any]]:
    error: dict[str, Any] = {"code": code, "message": message}
    if field:
        error["field"] = field
    if request_id:
        error["request_id"] = request_id
    if retryable is not None:
        error["retryable"] = retryable
    if exc and exc.request_id and "request_id" not in error:
        error["request_id"] = exc.request_id
    body: dict[str, Any] = {"error": error}
    if extra:
        body.update(extra)
    return status, body
