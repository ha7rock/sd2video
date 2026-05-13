"""Tests for backend asset resolution and HOM-23 payload construction."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sd2video.ark import (
    ArkClient,
    ArkConfig,
    ArkHTTPResponse,
    ArkParameterError,
    MediaResolver,
    VideoGenerationWorkflow,
    build_task_request_from_payload,
)


class RecordingTransport:
    def __init__(self) -> None:
        self.requests = []

    def send(self, request, timeout: float):
        self.requests.append(request)
        return ArkHTTPResponse(200, {}, b'{"id":"cgt-asset"}')


class RecordingUploader:
    def __init__(self, url: str = "https://cdn.example.com/uploaded.png") -> None:
        self.url = url
        self.calls = []

    def upload_asset(self, path: Path, *, kind: str, role: str, content_type: str | None = None) -> str:
        self.calls.append((path, kind, role, content_type))
        return self.url


def _png_bytes(width: int = 64, height: int = 64) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\r"
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
    )


class AssetPayloadTests(unittest.TestCase):
    def test_text_to_video_payload(self) -> None:
        req = build_task_request_from_payload({
            "mode": "t2v",
            "model": "doubao-seedance-2-0",
            "prompt": "A cat dancing",
            "ratio": "16:9",
            "resolution": "720p",
            "duration": 5,
            "web_search": True,
        })

        body = req.build()
        self.assertEqual("doubao-seedance-2-0", body["model"])
        self.assertEqual([{"type": "text", "text": "A cat dancing"}], body["content"])
        self.assertEqual([{"type": "web_search"}], body["tools"])

    def test_first_and_last_frame_payload(self) -> None:
        req = build_task_request_from_payload({
            "mode": "first_last",
            "model": "doubao-seedance-2-0",
            "prompt": "Smooth transition",
            "assets": {
                "first_frame": "https://cdn.example.com/start.png",
                "last_frame": {"asset_id": "last-asset"},
            },
        })

        body = req.build()
        self.assertEqual("text", body["content"][0]["type"])
        self.assertEqual("first_frame", body["content"][1]["role"])
        self.assertEqual("https://cdn.example.com/start.png", body["content"][1]["image_url"]["url"])
        self.assertEqual("last_frame", body["content"][2]["role"])
        self.assertEqual("asset://last-asset", body["content"][2]["image_url"]["url"])

    def test_image_data_url_payload(self) -> None:
        req = build_task_request_from_payload({
            "mode": "first_frame",
            "model": "doubao-seedance-2-0",
            "assets": {
                "first_frame": "data:image/png;base64,iVBORw0KGgo=",
            },
        })

        body = req.build()
        self.assertEqual("first_frame", body["content"][0]["role"])
        self.assertEqual("data:image/png;base64,iVBORw0KGgo=", body["content"][0]["image_url"]["url"])

    def test_reference_payload_with_all_media_types(self) -> None:
        req = build_task_request_from_payload({
            "mode": "reference",
            "model": "doubao-seedance-2-0",
            "prompt": "Use 图片1 and 音频1",
            "assets": {
                "reference_images": ["asset://img-1"],
                "reference_videos": [{"result_url": "https://cdn.example.com/task.mp4", "task_id": "cgt-old"}],
                "reference_audios": ["asset://aud-1"],
            },
        })

        roles = [item.get("role") for item in req.build()["content"]]
        self.assertEqual(["reference_image", "reference_video", "reference_audio"], roles[1:])

    def test_edit_and_extend_payloads(self) -> None:
        edit = build_task_request_from_payload({
            "mode": "edit",
            "model": "doubao-seedance-2-0",
            "prompt": "Replace the cup",
            "assets": {
                "edit_video": "asset://source-video",
                "reference_images": ["asset://cup-ref"],
            },
        }).build()
        self.assertEqual("reference_video", edit["content"][1]["role"])
        self.assertEqual("reference_image", edit["content"][2]["role"])

        extend = build_task_request_from_payload({
            "mode": "extend",
            "model": "doubao-seedance-2-0",
            "prompt": "Continue the scene",
            "assets": {
                "reference_videos": [{"url": "asset://source-video", "duration_seconds": 5}],
            },
        }).build()
        self.assertEqual("reference_video", extend["content"][1]["role"])


class AssetValidationTests(unittest.TestCase):
    def test_browser_blob_is_rejected_before_ark_create(self) -> None:
        transport = RecordingTransport()
        client = ArkClient(
            ArkConfig(api_key="test-key", default_model_id="doubao-seedance-2-0-fast-260128"),
            transport=transport,
        )
        workflow = VideoGenerationWorkflow(client)

        with self.assertRaises(ArkParameterError):
            workflow.submit_payload({
                "mode": "first_frame",
                "model": "doubao-seedance-2-0",
                "assets": {"first_frame": "blob:http://localhost/preview"},
            })

        self.assertEqual([], transport.requests)

    def test_local_file_requires_uploader(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frame.png"
            path.write_bytes(_png_bytes())

            with self.assertRaises(ArkParameterError):
                build_task_request_from_payload({
                    "mode": "first_frame",
                    "model": "doubao-seedance-2-0",
                    "assets": {"first_frame": str(path)},
                })

    def test_local_file_uploads_to_ark_accessible_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frame.png"
            path.write_bytes(_png_bytes())
            uploader = RecordingUploader()
            resolver = MediaResolver(uploader=uploader)

            req = build_task_request_from_payload(
                {
                    "mode": "first_frame",
                    "model": "doubao-seedance-2-0",
                    "assets": {"first_frame": str(path)},
                },
                resolver=resolver,
            )

            body = req.build()
            self.assertEqual("https://cdn.example.com/uploaded.png", body["content"][0]["image_url"]["url"])
            self.assertEqual("image", uploader.calls[0][1])
            self.assertEqual("first_frame", uploader.calls[0][2])

    def test_reference_requires_visual_media(self) -> None:
        with self.assertRaises(ArkParameterError):
            build_task_request_from_payload({
                "mode": "reference",
                "model": "doubao-seedance-2-0",
                "prompt": "Use audio only",
                "assets": {"reference_audios": ["asset://aud-1"]},
            })

    def test_reference_count_and_duration_limits(self) -> None:
        with self.assertRaises(ArkParameterError):
            build_task_request_from_payload({
                "mode": "reference",
                "model": "doubao-seedance-2-0",
                "assets": {"reference_images": [f"asset://img-{i}" for i in range(10)]},
            })

        with self.assertRaises(ArkParameterError):
            build_task_request_from_payload({
                "mode": "extend",
                "model": "doubao-seedance-2-0",
                "assets": {
                    "reference_videos": [
                        {"url": "asset://v1", "duration_seconds": 10},
                        {"url": "asset://v2", "duration_seconds": 10},
                    ],
                },
            })


if __name__ == "__main__":
    unittest.main()
