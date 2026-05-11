"""Request models and validation for creating Ark video generation tasks.

Covers three main input modes:
  - Text-to-video: prompt only
  - Image-to-video (first frame): one image + optional prompt
  - Image-to-video (first + last frame): two images + optional prompt

Reference:
  POST https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import ArkParameterError

# Valid enum values
VALID_RESOLUTIONS = {"480p", "720p", "1080p"}
VALID_RATIOS = {"16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "adaptive"}
VALID_SERVICE_TIERS = {"default", "flex"}
VALID_CONTENT_TYPES = {"text", "image_url", "video_url", "audio_url", "draft_task"}
VALID_IMAGE_ROLES = {"first_frame", "last_frame", "reference_image"}
VALID_VIDEO_ROLES = {"reference_video"}
VALID_AUDIO_ROLES = {"reference_audio"}

# Supported image formats (for user-facing validation)
SUPPORTED_IMAGE_FORMATS = {"jpeg", "jpg", "png", "webp", "bmp", "tiff", "gif", "heic", "heif"}

# Duration ranges by model family
_DURATION_RANGES: dict[str, tuple[int, int]] = {
    "seedance-1-0-pro": (2, 12),
    "seedance-1-0-pro-fast": (2, 12),
    "seedance-1-0-lite": (2, 12),
    "seedance-1-5-pro": (4, 12),
    "seedance-2-0": (4, 15),
    "seedance-2-0-fast": (4, 15),
}

# Frames range
FRAMES_MIN = 29
FRAMES_MAX = 289


def _resolve_duration_range(model_id: str) -> tuple[int, int] | None:
    """Return (min, max) duration seconds for the model, or None if unknown."""
    model_lower = model_id.lower()
    for key, rng in _DURATION_RANGES.items():
        if key in model_lower:
            return rng
    return None


def validate_image_url(url: str) -> None:
    """Validate image URL or base64 data URI."""
    if not url or not url.strip():
        raise ArkParameterError("image_url.url must not be empty")
    url = url.strip()
    if url.startswith("asset://"):
        return
    if url.startswith("data:image/"):
        # base64 data URI — check format
        prefix_end = url.find(";base64,")
        if prefix_end == -1:
            raise ArkParameterError(
                "image base64 must follow format: data:image/<format>;base64,<data>"
            )
        fmt = url[len("data:image/"):prefix_end].lower()
        if fmt not in SUPPORTED_IMAGE_FORMATS:
            raise ArkParameterError(
                f"unsupported image format '{fmt}'; "
                f"expected one of: {', '.join(sorted(SUPPORTED_IMAGE_FORMATS))}"
            )
        return
    # Otherwise assume it's a URL — basic scheme check
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ArkParameterError(
            "image_url.url must be an http(s) URL, data:image/... base64, or asset:// ID"
        )


# ---------------------------------------------------------------------------
# Content item builders
# ---------------------------------------------------------------------------

def text_content(text: str) -> dict[str, Any]:
    """Build a text content item."""
    if not text or not text.strip():
        raise ArkParameterError("text prompt must not be empty")
    return {"type": "text", "text": text.strip()}


def image_content(
    url: str,
    *,
    role: str | None = None,
) -> dict[str, Any]:
    """Build an image_url content item.

    Args:
        url: Image URL, base64 data URI, or asset:// ID.
        role: Optional role — 'first_frame', 'last_frame', or 'reference_image'.
              Omit for simple first-frame usage.
    """
    validate_image_url(url)
    item: dict[str, Any] = {
        "type": "image_url",
        "image_url": {"url": url.strip()},
    }
    if role is not None:
        if role not in VALID_IMAGE_ROLES:
            raise ArkParameterError(
                f"invalid image role '{role}'; "
                f"expected one of: {', '.join(sorted(VALID_IMAGE_ROLES))}"
            )
        item["role"] = role
    return item


def video_content(url: str, *, role: str = "reference_video") -> dict[str, Any]:
    """Build a video_url content item (seedance 2.0+ only)."""
    if not url or not url.strip():
        raise ArkParameterError("video_url.url must not be empty")
    if role not in VALID_VIDEO_ROLES:
        raise ArkParameterError(
            f"invalid video role '{role}'; expected one of: {', '.join(sorted(VALID_VIDEO_ROLES))}"
        )
    return {
        "type": "video_url",
        "video_url": {"url": url.strip()},
        "role": role,
    }


def audio_content(url: str, *, role: str = "reference_audio") -> dict[str, Any]:
    """Build an audio_url content item (seedance 2.0+ only)."""
    if not url or not url.strip():
        raise ArkParameterError("audio_url.url must not be empty")
    if role not in VALID_AUDIO_ROLES:
        raise ArkParameterError(
            f"invalid audio role '{role}'; expected one of: {', '.join(sorted(VALID_AUDIO_ROLES))}"
        )
    return {
        "type": "audio_url",
        "audio_url": {"url": url.strip()},
        "role": role,
    }


# ---------------------------------------------------------------------------
# CreateTaskRequest
# ---------------------------------------------------------------------------

@dataclass
class CreateTaskRequest:
    """Structured request to create an Ark video generation task.

    Call :meth:`build` to produce the JSON-serialisable dict to POST.
    """

    model: str
    content: list[dict[str, Any]]

    # Optional generation parameters (new-style, top-level in request body)
    resolution: str | None = None
    ratio: str | None = None
    duration: int | None = None
    frames: int | None = None
    seed: int | None = None
    camera_fixed: bool | None = None
    watermark: bool | None = None
    generate_audio: bool | None = None
    draft: bool | None = None
    service_tier: str | None = None
    execution_expires_after: int | None = None
    callback_url: str | None = None
    return_last_frame: bool | None = None
    safety_identifier: str | None = None
    tools: list[dict[str, Any]] | None = None

    # ----- convenience constructors -----

    @classmethod
    def text_to_video(
        cls,
        prompt: str,
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> CreateTaskRequest:
        """Build a text-to-video request."""
        return cls(
            model=model or "",
            content=[text_content(prompt)],
            **kwargs,
        )

    @classmethod
    def image_to_video(
        cls,
        image_url: str,
        *,
        prompt: str | None = None,
        model: str | None = None,
        last_frame_url: str | None = None,
        **kwargs: Any,
    ) -> CreateTaskRequest:
        """Build an image-to-video request (first frame, or first+last frame)."""
        items: list[dict[str, Any]] = []
        if prompt:
            items.append(text_content(prompt))
        if last_frame_url:
            # First + last frame mode
            items.append(image_content(image_url, role="first_frame"))
            items.append(image_content(last_frame_url, role="last_frame"))
        else:
            # First frame only
            items.append(image_content(image_url, role="first_frame"))
        return cls(
            model=model or "",
            content=items,
            **kwargs,
        )

    # ----- validation & serialisation -----

    def validate(self) -> None:
        """Validate all fields, raising ArkParameterError on problems."""
        if not self.model or not self.model.strip():
            raise ArkParameterError("model is required")
        if not self.content:
            raise ArkParameterError("content must contain at least one item")

        has_text = any(item.get("type") == "text" for item in self.content)
        has_image = any(item.get("type") == "image_url" for item in self.content)
        has_video = any(item.get("type") == "video_url" for item in self.content)
        has_audio = any(item.get("type") == "audio_url" for item in self.content)
        has_draft = any(item.get("type") == "draft_task" for item in self.content)

        if not (has_text or has_image or has_video or has_audio or has_draft):
            raise ArkParameterError(
                "content must include at least one text, image_url, video_url, audio_url, or draft_task item"
            )

        # Audio requires at least one image or video
        if has_audio and not (has_image or has_video):
            raise ArkParameterError(
                "audio input requires at least one image or video in content"
            )

        # First/last frame roles: must have exactly 2 images with these roles
        roles = [
            item.get("role")
            for item in self.content
            if item.get("type") == "image_url"
        ]
        if "last_frame" in roles and roles.count("first_frame") + roles.count("last_frame") != 2:
            raise ArkParameterError(
                "first+last frame mode requires exactly 2 images: one first_frame and one last_frame"
            )

        # Validate optional params
        if self.resolution is not None:
            if self.resolution not in VALID_RESOLUTIONS:
                raise ArkParameterError(
                    f"invalid resolution '{self.resolution}'; "
                    f"expected one of: {', '.join(sorted(VALID_RESOLUTIONS))}"
                )

        if self.ratio is not None:
            if self.ratio not in VALID_RATIOS:
                raise ArkParameterError(
                    f"invalid ratio '{self.ratio}'; "
                    f"expected one of: {', '.join(sorted(VALID_RATIOS))}"
                )

        if self.duration is not None:
            rng = _resolve_duration_range(self.model)
            if rng and self.duration != -1:
                lo, hi = rng
                if not (lo <= self.duration <= hi):
                    raise ArkParameterError(
                        f"duration {self.duration}s out of range for model; "
                        f"expected [{lo}, {hi}] or -1"
                    )

        if self.frames is not None:
            if self.frames != -1 and not (FRAMES_MIN <= self.frames <= FRAMES_MAX):
                raise ArkParameterError(
                    f"frames {self.frames} out of range; expected [{FRAMES_MIN}, {FRAMES_MAX}] or -1"
                )

        if self.seed is not None:
            if self.seed < -1 or self.seed > 2**32 - 1:
                raise ArkParameterError(
                    f"seed {self.seed} out of range; expected [-1, 2^32-1]"
                )

        if self.service_tier is not None:
            if self.service_tier not in VALID_SERVICE_TIERS:
                raise ArkParameterError(
                    f"invalid service_tier '{self.service_tier}'; "
                    f"expected one of: {', '.join(sorted(VALID_SERVICE_TIERS))}"
                )

        if self.execution_expires_after is not None:
            if not (3600 <= self.execution_expires_after <= 259200):
                raise ArkParameterError(
                    f"execution_expires_after {self.execution_expires_after}s out of range; "
                    f"expected [3600, 259200]"
                )

    def build(self) -> dict[str, Any]:
        """Validate and return the JSON-serialisable request body."""
        self.validate()
        body: dict[str, Any] = {
            "model": self.model.strip(),
            "content": list(self.content),
        }
        # Include optional params only when set (avoid sending defaults)
        _optional = {
            "resolution": self.resolution,
            "ratio": self.ratio,
            "duration": self.duration,
            "frames": self.frames,
            "seed": self.seed,
            "camera_fixed": self.camera_fixed,
            "watermark": self.watermark,
            "generate_audio": self.generate_audio,
            "draft": self.draft,
            "service_tier": self.service_tier,
            "execution_expires_after": self.execution_expires_after,
            "callback_url": self.callback_url,
            "return_last_frame": self.return_last_frame,
            "safety_identifier": self.safety_identifier,
            "tools": self.tools,
        }
        for key, value in _optional.items():
            if value is not None:
                body[key] = value
        return body
