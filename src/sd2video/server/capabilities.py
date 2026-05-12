"""Frontend-visible generation capability metadata."""

from __future__ import annotations

from typing import Any

from sd2video.ark.config import DEFAULT_MODEL_ID
from sd2video.ark.task_models import VALID_RATIOS, VALID_RESOLUTIONS

SUPPORTED_MODELS: tuple[dict[str, Any], ...] = (
    {
        "id": "doubao-seedance-2-0-260128",
        "label": "Seedance 2.0",
        "max_resolution": "1080p",
        "supports_audio": True,
        "supports_web_search": True,
        "supports_modes": [
            "t2v",
            "first_frame",
            "first_last",
            "reference",
            "edit",
            "extend",
        ],
    },
    {
        "id": "doubao-seedance-2-0-fast-260128",
        "label": "Seedance 2.0 Fast",
        "max_resolution": "720p",
        "supports_audio": True,
        "supports_web_search": True,
        "supports_modes": [
            "t2v",
            "first_frame",
            "first_last",
            "reference",
            "edit",
            "extend",
        ],
    },
)


def build_capabilities(
    *,
    default_model_id: str = DEFAULT_MODEL_ID,
    poll_interval_seconds: float = 5.0,
    poll_timeout_seconds: float = 600.0,
) -> dict[str, Any]:
    """Return capability metadata safe for browsers."""

    models = [dict(model) for model in SUPPORTED_MODELS]
    if default_model_id and all(model["id"] != default_model_id for model in models):
        models.insert(
            0,
            {
                "id": default_model_id,
                "label": default_model_id,
                "max_resolution": "720p",
                "supports_audio": True,
                "supports_web_search": True,
                "supports_modes": [
                    "t2v",
                    "first_frame",
                    "first_last",
                    "reference",
                    "edit",
                    "extend",
                ],
            },
        )

    return {
        "models": models,
        "ratios": _ordered(
            ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"],
            VALID_RATIOS,
        ),
        "resolutions": _ordered(["480p", "720p", "1080p"], VALID_RESOLUTIONS),
        "duration": {"min": 4, "max": 15, "step": 1, "unit": "second"},
        "limits": {
            "max_reference_images": 9,
            "max_reference_videos": 3,
            "max_reference_audios": 3,
            "max_total_video_seconds": 15,
            "image_max_bytes": 31_457_280,
            "video_max_bytes": 52_428_800,
            "audio_max_bytes": 15_728_640,
            "request_body_max_bytes": 67_108_864,
        },
        "default_model": default_model_id,
        "poll_interval_seconds": poll_interval_seconds,
        "poll_timeout_seconds": poll_timeout_seconds,
    }


def _ordered(preferred: list[str], values: set[str]) -> list[str]:
    ordered = [value for value in preferred if value in values]
    ordered.extend(sorted(values - set(ordered)))
    return ordered
