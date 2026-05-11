"""Transport and response value objects for the Ark client."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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
