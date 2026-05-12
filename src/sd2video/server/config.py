"""Configuration for the frontend-facing sd2video service."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from sd2video.ark.config import DEFAULT_MODEL_ID

DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "file://",
)
DEFAULT_BIND = "127.0.0.1:8787"


@dataclass(frozen=True)
class ServerConfig:
    """Runtime settings that are safe to expose only in reduced form."""

    mock: bool = True
    default_model_id: str = DEFAULT_MODEL_ID
    cors_origins: tuple[str, ...] = field(default_factory=lambda: DEFAULT_CORS_ORIGINS)
    bind: str = DEFAULT_BIND
    poll_interval_seconds: float = 5.0
    poll_timeout_seconds: float = 600.0
    version: str = "0.1.0"
    duplicate_window_seconds: float = 300.0

    def __post_init__(self) -> None:
        default_model_id = self.default_model_id.strip()
        if not default_model_id:
            raise ValueError("Default model id is required")
        object.__setattr__(self, "default_model_id", default_model_id)

        origins = tuple(
            _normalize_origin(origin)
            for origin in self.cors_origins
            if origin.strip()
        )
        object.__setattr__(self, "cors_origins", origins)

        for name in (
            "poll_interval_seconds",
            "poll_timeout_seconds",
            "duplicate_window_seconds",
        ):
            value = float(getattr(self, name))
            if value <= 0:
                raise ValueError(f"{name} must be positive")
            object.__setattr__(self, name, value)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "ServerConfig":
        environ = os.environ if environ is None else environ
        return cls(
            mock=_bool_env(environ.get("SD2VIDEO_MOCK"), default=False),
            default_model_id=(
                environ.get("ARK_DEFAULT_MODEL_ID")
                or environ.get("ARK_MODEL_ID")
                or DEFAULT_MODEL_ID
            ),
            cors_origins=_parse_origins(environ.get("SD2VIDEO_CORS_ORIGINS")),
            bind=environ.get("SD2VIDEO_BIND", DEFAULT_BIND),
            poll_interval_seconds=_float_env(
                environ,
                "SD2VIDEO_POLL_INTERVAL_SECONDS",
                5.0,
            ),
            poll_timeout_seconds=_float_env(
                environ,
                "SD2VIDEO_POLL_TIMEOUT_SECONDS",
                600.0,
            ),
        )

    def bind_host_port(self) -> tuple[str, int]:
        host, _, port = self.bind.rpartition(":")
        if not host:
            host = "127.0.0.1"
        return host, int(port or "8787")


def _parse_origins(raw: str | None) -> tuple[str, ...]:
    if raw is None or not raw.strip():
        return DEFAULT_CORS_ORIGINS
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _normalize_origin(origin: str) -> str:
    origin = origin.strip()
    if origin == "file://":
        return origin
    return origin.rstrip("/")


def _float_env(environ: Mapping[str, str], key: str, default: float) -> float:
    raw = environ.get(key, "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be a positive number") from exc


def _bool_env(raw: str | None, *, default: bool) -> bool:
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
