"""HTTP transport boundary for the Ark client."""

from __future__ import annotations

import socket
import urllib.error
import urllib.request
from typing import Protocol

from .errors import ArkNetworkError, ArkTimeoutError
from .types import ArkHTTPResponse, ArkRequest


class ArkTransport(Protocol):
    """Mockable transport contract used by ArkClient."""

    def send(self, request: ArkRequest, timeout: float) -> ArkHTTPResponse:
        """Send an HTTP request and return the raw HTTP response."""


class UrllibArkTransport:
    """Stdlib urllib implementation of the Ark transport contract."""

    def __init__(self, opener: urllib.request.OpenerDirector | None = None) -> None:
        self._opener = opener or urllib.request.build_opener()

    def send(self, request: ArkRequest, timeout: float) -> ArkHTTPResponse:
        urllib_request = urllib.request.Request(
            request.url,
            data=request.body,
            headers=dict(request.headers),
            method=request.method,
        )
        try:
            with self._opener.open(urllib_request, timeout=timeout) as response:
                return ArkHTTPResponse(
                    status_code=response.status,
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except urllib.error.HTTPError as exc:
            headers = dict(exc.headers.items()) if exc.headers else {}
            return ArkHTTPResponse(
                status_code=exc.code,
                headers=headers,
                body=exc.read(),
            )
        except (TimeoutError, socket.timeout) as exc:
            raise ArkTimeoutError("Ark request timed out") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise ArkTimeoutError("Ark request timed out") from exc
            raise ArkNetworkError("Ark network request failed") from exc
