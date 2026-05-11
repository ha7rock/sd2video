"""Error hierarchy for Volcengine Ark API access."""

from __future__ import annotations


class ArkError(Exception):
    """Base class for Ark client errors."""


class ArkConfigError(ArkError):
    """Raised when Ark configuration is invalid."""


class ArkNetworkError(ArkError):
    """Raised when an Ark request fails before receiving an HTTP response."""


class ArkTimeoutError(ArkNetworkError):
    """Raised when an Ark request times out."""


class ArkAPIError(ArkError):
    """Raised for non-successful Ark API HTTP responses."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.request_id = request_id

    def __str__(self) -> str:
        parts = ["Ark API error"]
        if self.status_code is not None:
            parts[0] = f"{parts[0]} ({self.status_code})"
        if self.code:
            parts.append(f"code={self.code}")
        if self.message:
            parts.append(self.message)
        if self.request_id:
            parts.append(f"request_id={self.request_id}")
        return ": ".join(parts)


class ArkAuthenticationError(ArkAPIError):
    """Raised for 401/403 Ark authentication or authorization failures."""


class ArkParameterError(ArkAPIError):
    """Raised for Ark request validation failures."""
