"""Configuration for Volcengine Ark API access."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .errors import ArkConfigError

DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com"
DEFAULT_TASKS_PATH = "/api/v3/contents/generations/tasks"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MODEL_ID = "doubao-seedance-2-0-fast-260128"


@dataclass(frozen=True)
class ArkConfig:
    """Runtime configuration for all Ark video generation requests."""

    api_key: str = field(repr=False)
    base_url: str = DEFAULT_BASE_URL
    default_model_id: str = DEFAULT_MODEL_ID
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    tasks_path: str = DEFAULT_TASKS_PATH

    def __post_init__(self) -> None:
        api_key = (self.api_key or "").strip()
        if not api_key:
            raise ArkConfigError("ARK_API_KEY is required")

        base_url = _normalize_base_url(self.base_url)
        default_model_id = (self.default_model_id or "").strip()
        if not default_model_id:
            raise ArkConfigError("Ark default model id is required")

        try:
            timeout_seconds = float(self.timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise ArkConfigError("Ark timeout must be a positive number") from exc
        if timeout_seconds <= 0:
            raise ArkConfigError("Ark timeout must be a positive number")

        tasks_path = (self.tasks_path or "").strip()
        if not tasks_path:
            raise ArkConfigError("Ark tasks path is required")
        if not tasks_path.startswith("/"):
            tasks_path = f"/{tasks_path}"

        object.__setattr__(self, "api_key", api_key)
        object.__setattr__(self, "base_url", base_url)
        object.__setattr__(self, "default_model_id", default_model_id)
        object.__setattr__(self, "timeout_seconds", timeout_seconds)
        object.__setattr__(self, "tasks_path", tasks_path)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "ArkConfig":
        """Build configuration from environment variables without logging secrets."""

        environ = os.environ if environ is None else environ
        timeout = _timeout_from_env(environ)
        return cls(
            api_key=environ.get("ARK_API_KEY", ""),
            base_url=environ.get("ARK_BASE_URL", DEFAULT_BASE_URL),
            default_model_id=(
                environ.get("ARK_DEFAULT_MODEL_ID")
                or environ.get("ARK_MODEL_ID")
                or DEFAULT_MODEL_ID
            ),
            timeout_seconds=timeout,
        )


def _normalize_base_url(value: str) -> str:
    base_url = (value or "").strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ArkConfigError("Ark base URL must be an absolute HTTP(S) URL")
    return base_url


def _timeout_from_env(environ: Mapping[str, str]) -> float:
    raw_timeout = environ.get("ARK_TIMEOUT_SECONDS", "")
    if not raw_timeout:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return float(raw_timeout)
    except ValueError as exc:
        raise ArkConfigError("ARK_TIMEOUT_SECONDS must be a positive number") from exc
