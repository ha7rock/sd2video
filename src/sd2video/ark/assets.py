"""Asset validation and Ark content construction.

The browser must never pass local blob/file paths to Ark. This module is the
backend boundary that turns user-facing asset references into Ark-ready
``content`` items, or fails before a create-task request is sent.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, Sequence
from urllib.parse import urlparse

from .errors import ArkParameterError
from .task_models import (
    CreateTaskRequest,
    audio_content,
    image_content,
    text_content,
    video_content,
)

AssetKind = Literal["image", "video", "audio"]
AssetRole = Literal[
    "first_frame",
    "last_frame",
    "reference_image",
    "reference_video",
    "reference_audio",
    "edit_video",
    "extend_video",
]

VALID_MODES = {"t2v", "first_frame", "first_last", "reference", "edit", "extend"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic", ".heif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mpeg", ".mpg", ".webm", ".m4v"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


class AssetUploader(Protocol):
    """Uploads a local file and returns an Ark-accessible URL or asset ID."""

    def upload_asset(
        self,
        path: Path,
        *,
        kind: AssetKind,
        role: AssetRole,
        content_type: str | None = None,
    ) -> str:
        """Return an ``http(s)://`` URL or ``asset://`` ID for ``path``."""


@dataclass(frozen=True)
class AssetValidationConfig:
    """Validation limits shared by the HTTP service and frontend capabilities."""

    image_max_bytes: int = 30 * 1024 * 1024
    video_max_bytes: int = 50 * 1024 * 1024
    audio_max_bytes: int = 15 * 1024 * 1024
    max_reference_images: int = 9
    max_reference_videos: int = 3
    max_reference_audios: int = 3
    max_total_video_seconds: float = 15.0
    image_min_width: int = 64
    image_min_height: int = 64
    image_max_width: int = 8192
    image_max_height: int = 8192

    def max_bytes_for(self, kind: AssetKind) -> int:
        if kind == "image":
            return self.image_max_bytes
        if kind == "video":
            return self.video_max_bytes
        return self.audio_max_bytes


@dataclass(frozen=True)
class ResolvedAsset:
    """An asset after backend-side validation and optional upload."""

    url: str
    kind: AssetKind
    role: AssetRole
    field: str
    source: str
    size_bytes: int | None = None
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    task_id: str | None = None


@dataclass
class MediaResolver:
    """Resolve frontend asset values into Ark-ready URLs."""

    uploader: AssetUploader | None = None
    validation: AssetValidationConfig = field(default_factory=AssetValidationConfig)

    def resolve(
        self,
        value: Any,
        *,
        kind: AssetKind,
        role: AssetRole,
        field: str,
    ) -> ResolvedAsset:
        """Validate and resolve a single frontend asset reference."""

        raw, metadata = _extract_asset_value(value, field)
        if not raw:
            raise ArkParameterError(f"{field} is required")

        if raw.startswith("blob:"):
            raise ArkParameterError(
                f"{field} is a browser preview URL; upload it first and send the returned asset:// ID"
            )

        if raw.startswith("file://"):
            return self._resolve_local(Path(urlparse(raw).path), kind=kind, role=role, field=field, metadata=metadata)

        path = Path(raw).expanduser()
        if _looks_like_local_path(raw) or path.exists():
            return self._resolve_local(path, kind=kind, role=role, field=field, metadata=metadata)

        self._validate_reference_url(raw, kind=kind, field=field)
        self._validate_metadata(metadata, kind=kind, field=field)
        return ResolvedAsset(
            url=raw.strip(),
            kind=kind,
            role=role,
            field=field,
            source=_source_type(raw),
            width=_optional_int(metadata.get("width"), field=f"{field}.width"),
            height=_optional_int(metadata.get("height"), field=f"{field}.height"),
            duration_seconds=_optional_float(metadata.get("duration_seconds"), field=f"{field}.duration_seconds"),
            task_id=_optional_str(metadata.get("task_id")),
        )

    def resolve_many(
        self,
        values: Sequence[Any] | None,
        *,
        kind: AssetKind,
        role: AssetRole,
        field: str,
        max_count: int,
    ) -> list[ResolvedAsset]:
        items = list(values or [])
        if len(items) > max_count:
            raise ArkParameterError(f"{field} allows at most {max_count} asset(s)")
        return [
            self.resolve(item, kind=kind, role=role, field=f"{field}[{idx}]")
            for idx, item in enumerate(items)
        ]

    def _resolve_local(
        self,
        path: Path,
        *,
        kind: AssetKind,
        role: AssetRole,
        field: str,
        metadata: Mapping[str, Any],
    ) -> ResolvedAsset:
        if not path.exists() or not path.is_file():
            raise ArkParameterError(f"{field} local file does not exist")
        size = path.stat().st_size
        max_bytes = self.validation.max_bytes_for(kind)
        if size > max_bytes:
            raise ArkParameterError(f"{field} exceeds {max_bytes} bytes")
        content_type = _validate_local_file(path, kind=kind, field=field)
        width, height = _image_dimensions(path) if kind == "image" else (None, None)
        merged = dict(metadata)
        if width is not None:
            merged.setdefault("width", width)
        if height is not None:
            merged.setdefault("height", height)
        self._validate_metadata(merged, kind=kind, field=field)
        if self.uploader is None:
            raise ArkParameterError(
                f"{field} is a local file; configure an AssetUploader before creating an Ark task"
            )
        resolved_url = self.uploader.upload_asset(
            path,
            kind=kind,
            role=role,
            content_type=content_type,
        )
        self._validate_reference_url(resolved_url, kind=kind, field=field)
        return ResolvedAsset(
            url=resolved_url.strip(),
            kind=kind,
            role=role,
            field=field,
            source="local_upload",
            size_bytes=size,
            width=_optional_int(merged.get("width"), field=f"{field}.width"),
            height=_optional_int(merged.get("height"), field=f"{field}.height"),
            duration_seconds=_optional_float(merged.get("duration_seconds"), field=f"{field}.duration_seconds"),
            task_id=_optional_str(merged.get("task_id")),
        )

    def _validate_reference_url(self, url: str, *, kind: AssetKind, field: str) -> None:
        value = url.strip()
        if value.startswith("asset://"):
            if len(value) <= len("asset://"):
                raise ArkParameterError(f"{field} asset:// ID must not be empty")
            return
        if kind == "image" and value.startswith("data:image/"):
            _validate_data_image(value, field=field, max_bytes=self.validation.image_max_bytes)
            return
        if value.startswith("data:"):
            raise ArkParameterError(f"{field} only supports data: URLs for images")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ArkParameterError(f"{field} must be http(s)://, asset://, or an uploaded local file")

    def _validate_metadata(self, metadata: Mapping[str, Any], *, kind: AssetKind, field: str) -> None:
        if kind == "image":
            width = _optional_int(metadata.get("width"), field=f"{field}.width")
            height = _optional_int(metadata.get("height"), field=f"{field}.height")
            if width is not None:
                if not (self.validation.image_min_width <= width <= self.validation.image_max_width):
                    raise ArkParameterError(f"{field}.width must be between {self.validation.image_min_width} and {self.validation.image_max_width}")
            if height is not None:
                if not (self.validation.image_min_height <= height <= self.validation.image_max_height):
                    raise ArkParameterError(f"{field}.height must be between {self.validation.image_min_height} and {self.validation.image_max_height}")
        if kind == "video":
            duration = _optional_float(metadata.get("duration_seconds"), field=f"{field}.duration_seconds")
            if duration is not None and duration > self.validation.max_total_video_seconds:
                raise ArkParameterError(
                    f"{field}.duration_seconds must be <= {self.validation.max_total_video_seconds}"
                )


def build_task_request_from_payload(
    payload: Mapping[str, Any],
    *,
    resolver: MediaResolver | None = None,
    default_model: str = "",
) -> CreateTaskRequest:
    """Build a :class:`CreateTaskRequest` from the HOM-23 frontend payload."""

    mode = str(payload.get("mode") or "").strip()
    if mode not in VALID_MODES:
        raise ArkParameterError(
            f"invalid mode '{mode}'; expected one of: {', '.join(sorted(VALID_MODES))}"
        )
    prompt = str(payload.get("prompt") or "").strip()
    model = str(payload.get("model") or default_model).strip()
    assets = _coerce_assets(payload)
    resolver = resolver or MediaResolver()
    content = build_ark_content(mode, prompt=prompt, assets=assets, resolver=resolver)

    if payload.get("web_search") is True and mode != "t2v":
        raise ArkParameterError("web_search is only allowed for t2v mode")

    return CreateTaskRequest(
        model=model,
        content=content,
        resolution=_optional_str(payload.get("resolution")),
        ratio=_optional_str(payload.get("ratio") or payload.get("ar")),
        duration=_optional_int(payload.get("duration"), field="duration"),
        frames=_optional_int(payload.get("frames"), field="frames"),
        seed=_optional_int(payload.get("seed"), field="seed"),
        camera_fixed=_optional_bool(payload.get("camera_fixed")),
        watermark=_optional_bool(payload.get("watermark")),
        generate_audio=_optional_bool(payload.get("generate_audio")),
        return_last_frame=_optional_bool(payload.get("return_last_frame")),
        service_tier=_optional_str(payload.get("service_tier")),
        tools=[{"type": "web_search"}] if payload.get("web_search") is True else None,
    )


def build_ark_content(
    mode: str,
    *,
    prompt: str,
    assets: Mapping[str, Any],
    resolver: MediaResolver,
) -> list[dict[str, Any]]:
    """Build Ark ``content`` from normalized mode/prompt/assets fields."""

    items: list[dict[str, Any]] = []
    if prompt:
        items.append(text_content(prompt))

    if mode == "t2v":
        if not prompt:
            raise ArkParameterError("prompt is required for t2v mode")
        return items

    if mode == "first_frame":
        first = resolver.resolve(
            assets.get("first_frame"),
            kind="image",
            role="first_frame",
            field="assets.first_frame",
        )
        items.append(image_content(first.url, role="first_frame"))
        return items

    if mode == "first_last":
        first = resolver.resolve(
            assets.get("first_frame"),
            kind="image",
            role="first_frame",
            field="assets.first_frame",
        )
        last = resolver.resolve(
            assets.get("last_frame"),
            kind="image",
            role="last_frame",
            field="assets.last_frame",
        )
        items.append(image_content(first.url, role="first_frame"))
        items.append(image_content(last.url, role="last_frame"))
        return items

    if mode == "reference":
        refs = _reference_assets(assets, resolver)
        if not any(asset.kind in {"image", "video"} for asset in refs):
            raise ArkParameterError("reference mode requires at least one reference image or video")
        items.extend(_content_for_resolved_assets(refs))
        return items

    if mode == "edit":
        edit_video = resolver.resolve(
            assets.get("edit_video"),
            kind="video",
            role="edit_video",
            field="assets.edit_video",
        )
        items.append(video_content(edit_video.url, role="reference_video"))
        refs = _edit_reference_assets(assets, resolver)
        items.extend(_content_for_resolved_assets(refs))
        return items

    if mode == "extend":
        videos = resolver.resolve_many(
            assets.get("reference_videos"),
            kind="video",
            role="extend_video",
            field="assets.reference_videos",
            max_count=resolver.validation.max_reference_videos,
        )
        if not videos:
            raise ArkParameterError("extend mode requires at least one reference video")
        total = sum(asset.duration_seconds or 0 for asset in videos)
        if total and total > resolver.validation.max_total_video_seconds:
            raise ArkParameterError(
                f"assets.reference_videos total duration must be <= {resolver.validation.max_total_video_seconds}"
            )
        items.extend(_content_for_resolved_assets(videos))
        return items

    raise ArkParameterError(f"invalid mode '{mode}'")


def _reference_assets(assets: Mapping[str, Any], resolver: MediaResolver) -> list[ResolvedAsset]:
    result: list[ResolvedAsset] = []
    result.extend(resolver.resolve_many(
        assets.get("reference_images"),
        kind="image",
        role="reference_image",
        field="assets.reference_images",
        max_count=resolver.validation.max_reference_images,
    ))
    result.extend(resolver.resolve_many(
        assets.get("reference_videos"),
        kind="video",
        role="reference_video",
        field="assets.reference_videos",
        max_count=resolver.validation.max_reference_videos,
    ))
    result.extend(resolver.resolve_many(
        assets.get("reference_audios"),
        kind="audio",
        role="reference_audio",
        field="assets.reference_audios",
        max_count=resolver.validation.max_reference_audios,
    ))
    return result


def _edit_reference_assets(assets: Mapping[str, Any], resolver: MediaResolver) -> list[ResolvedAsset]:
    result: list[ResolvedAsset] = []
    result.extend(resolver.resolve_many(
        assets.get("reference_images"),
        kind="image",
        role="reference_image",
        field="assets.reference_images",
        max_count=resolver.validation.max_reference_images,
    ))
    result.extend(resolver.resolve_many(
        assets.get("reference_audios"),
        kind="audio",
        role="reference_audio",
        field="assets.reference_audios",
        max_count=resolver.validation.max_reference_audios,
    ))
    return result


def _content_for_resolved_assets(assets: Sequence[ResolvedAsset]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for asset in assets:
        if asset.kind == "image":
            items.append(image_content(asset.url, role="reference_image" if asset.role == "reference_image" else asset.role))
        elif asset.kind == "video":
            items.append(video_content(asset.url, role="reference_video"))
        else:
            items.append(audio_content(asset.url, role="reference_audio"))
    return items


def _coerce_assets(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    assets = payload.get("assets")
    if isinstance(assets, Mapping):
        return assets
    return {
        "first_frame": payload.get("startImg") or payload.get("first_frame"),
        "last_frame": payload.get("endImg") or payload.get("last_frame"),
        "reference_images": payload.get("refImages") or payload.get("reference_images") or [],
        "reference_videos": payload.get("refVideos") or payload.get("reference_videos") or [],
        "reference_audios": payload.get("refAudios") or payload.get("reference_audios") or [],
        "edit_video": _first_or_none(payload.get("editVideo") or payload.get("edit_video")),
    }


def _extract_asset_value(value: Any, field: str) -> tuple[str, Mapping[str, Any]]:
    if value is None:
        return "", {}
    if isinstance(value, Mapping):
        metadata = dict(value)
        if value.get("asset_id"):
            asset_id = str(value["asset_id"]).strip()
            return (asset_id if asset_id.startswith("asset://") else f"asset://{asset_id}"), metadata
        if value.get("asset_url"):
            return str(value["asset_url"]).strip(), metadata
        if value.get("upload_url"):
            return str(value["upload_url"]).strip(), metadata
        if value.get("url"):
            return str(value["url"]).strip(), metadata
        if value.get("result_url"):
            return str(value["result_url"]).strip(), metadata
        if value.get("path"):
            return str(value["path"]).strip(), metadata
        if value.get("file_path"):
            return str(value["file_path"]).strip(), metadata
        raise ArkParameterError(f"{field} must include url, asset_id, result_url, or path")
    return str(value).strip(), {}


def _first_or_none(value: Any) -> Any:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value[0] if value else None
    return value


def _source_type(value: str) -> str:
    if value.startswith("asset://"):
        return "asset"
    if value.startswith("data:image/"):
        return "data_image"
    return "remote_url"


def _looks_like_local_path(value: str) -> bool:
    if value.startswith(("./", "../", "/", "~")):
        return True
    parsed = urlparse(value)
    return parsed.scheme == "" and any(sep in value for sep in ("/", "\\"))


def _validate_data_image(value: str, *, field: str, max_bytes: int) -> None:
    marker = ";base64,"
    prefix_end = value.find(marker)
    if prefix_end == -1:
        raise ArkParameterError(f"{field} image data URL must use data:image/<format>;base64,<data>")
    payload = value[prefix_end + len(marker):]
    try:
        size = len(base64.b64decode(payload, validate=True))
    except (binascii.Error, ValueError) as exc:
        raise ArkParameterError(f"{field} image data URL is not valid base64") from exc
    if size > max_bytes:
        raise ArkParameterError(f"{field} exceeds {max_bytes} bytes")


def _validate_local_file(path: Path, *, kind: AssetKind, field: str) -> str | None:
    ext = path.suffix.lower()
    if kind == "image" and ext not in IMAGE_EXTENSIONS:
        raise ArkParameterError(f"{field} unsupported image file type '{ext}'")
    if kind == "video" and ext not in VIDEO_EXTENSIONS:
        raise ArkParameterError(f"{field} unsupported video file type '{ext}'")
    if kind == "audio" and ext not in AUDIO_EXTENSIONS:
        raise ArkParameterError(f"{field} unsupported audio file type '{ext}'")
    if kind == "image":
        return f"image/{'jpeg' if ext in {'.jpg', '.jpeg'} else ext.lstrip('.')}"
    if kind == "video":
        return f"video/{'mp4' if ext == '.m4v' else ext.lstrip('.')}"
    return f"audio/{ext.lstrip('.')}"


def _image_dimensions(path: Path) -> tuple[int | None, int | None]:
    data = path.read_bytes()[:65536]
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data.startswith((b"GIF87a", b"GIF89a")) and len(data) >= 10:
        return int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return _webp_dimensions(data)
    if data.startswith(b"\xff\xd8"):
        return _jpeg_dimensions(data)
    return None, None


def _jpeg_dimensions(data: bytes) -> tuple[int | None, int | None]:
    idx = 2
    while idx + 9 < len(data):
        if data[idx] != 0xFF:
            idx += 1
            continue
        marker = data[idx + 1]
        idx += 2
        if marker in {0xD8, 0xD9}:
            continue
        if idx + 2 > len(data):
            break
        length = int.from_bytes(data[idx:idx + 2], "big")
        if length < 2 or idx + length > len(data):
            break
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            height = int.from_bytes(data[idx + 3:idx + 5], "big")
            width = int.from_bytes(data[idx + 5:idx + 7], "big")
            return width, height
        idx += length
    return None, None


def _webp_dimensions(data: bytes) -> tuple[int | None, int | None]:
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        return width, height
    if chunk == b"VP8 " and len(data) >= 30:
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        return width, height
    return None, None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    raise ArkParameterError(f"boolean value expected, got {value!r}")


def _optional_int(value: Any, *, field: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ArkParameterError(f"{field} must be an integer") from exc


def _optional_float(value: Any, *, field: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ArkParameterError(f"{field} must be a number") from exc
