"""Tests for creating Ark video generation tasks (HOM-15)."""

from __future__ import annotations

import json
import unittest

from sd2video.ark import (
    ArkAPIError,
    ArkClient,
    ArkConfig,
    ArkHTTPResponse,
    ArkParameterError,
    CreateTaskRequest,
    image_content,
    text_content,
)
from sd2video.ark.task_models import (
    VALID_RATIOS,
    VALID_RESOLUTIONS,
    audio_content,
    video_content,
)


class RecordingTransport:
    """Test double that records requests and returns a canned response."""

    def __init__(
        self,
        response: ArkHTTPResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response or ArkHTTPResponse(200, {}, b"{}")
        self.error = error
        self.requests = []

    def send(self, request, timeout: float):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.response


def _make_client(transport) -> ArkClient:
    return ArkClient(
        ArkConfig(api_key="test-key", default_model_id="doubao-seedance-2-0-fast-260128"),
        transport=transport,
    )


# ---------------------------------------------------------------------------
# Content item builders
# ---------------------------------------------------------------------------

class TextContentTests(unittest.TestCase):
    def test_basic_text(self) -> None:
        item = text_content("A cat dancing")
        self.assertEqual({"type": "text", "text": "A cat dancing"}, item)

    def test_strips_whitespace(self) -> None:
        item = text_content("  hello world  ")
        self.assertEqual("hello world", item["text"])

    def test_rejects_empty(self) -> None:
        with self.assertRaises(ArkParameterError):
            text_content("")
        with self.assertRaises(ArkParameterError):
            text_content("   ")


class ImageContentTests(unittest.TestCase):
    def test_basic_url(self) -> None:
        item = image_content("https://example.com/img.png")
        self.assertEqual("image_url", item["type"])
        self.assertEqual("https://example.com/img.png", item["image_url"]["url"])
        self.assertNotIn("role", item)

    def test_with_role_first_frame(self) -> None:
        item = image_content("https://example.com/img.png", role="first_frame")
        self.assertEqual("first_frame", item["role"])

    def test_with_role_last_frame(self) -> None:
        item = image_content("https://example.com/img.png", role="last_frame")
        self.assertEqual("last_frame", item["role"])

    def test_with_role_reference_image(self) -> None:
        item = image_content("https://example.com/img.png", role="reference_image")
        self.assertEqual("reference_image", item["role"])

    def test_rejects_invalid_role(self) -> None:
        with self.assertRaises(ArkParameterError):
            image_content("https://example.com/img.png", role="middle_frame")

    def test_accepts_base64_data_uri(self) -> None:
        item = image_content("data:image/png;base64,AAAA")
        self.assertEqual("data:image/png;base64,AAAA", item["image_url"]["url"])

    def test_rejects_bad_base64_format(self) -> None:
        with self.assertRaises(ArkParameterError):
            image_content("data:image/png,AAAA")

    def test_rejects_unsupported_image_format(self) -> None:
        with self.assertRaises(ArkParameterError):
            image_content("data:image/svg;base64,AAAA")

    def test_accepts_asset_id(self) -> None:
        item = image_content("asset://abc-123")
        self.assertEqual("asset://abc-123", item["image_url"]["url"])

    def test_rejects_empty_url(self) -> None:
        with self.assertRaises(ArkParameterError):
            image_content("")

    def test_rejects_non_http_url(self) -> None:
        with self.assertRaises(ArkParameterError):
            image_content("ftp://example.com/img.png")


class VideoContentTests(unittest.TestCase):
    def test_basic(self) -> None:
        item = video_content("https://example.com/vid.mp4")
        self.assertEqual("video_url", item["type"])
        self.assertEqual("reference_video", item["role"])

    def test_rejects_empty(self) -> None:
        with self.assertRaises(ArkParameterError):
            video_content("")


class AudioContentTests(unittest.TestCase):
    def test_basic(self) -> None:
        item = audio_content("https://example.com/audio.wav")
        self.assertEqual("audio_url", item["type"])
        self.assertEqual("reference_audio", item["role"])

    def test_rejects_empty(self) -> None:
        with self.assertRaises(ArkParameterError):
            audio_content("")


# ---------------------------------------------------------------------------
# CreateTaskRequest — text-to-video
# ---------------------------------------------------------------------------

class TextToVideoTests(unittest.TestCase):
    def test_minimal(self) -> None:
        req = CreateTaskRequest.text_to_video("A cat dancing", model="doubao-seedance-2-0")
        body = req.build()
        self.assertEqual("doubao-seedance-2-0", body["model"])
        self.assertEqual(1, len(body["content"]))
        self.assertEqual("text", body["content"][0]["type"])
        self.assertEqual("A cat dancing", body["content"][0]["text"])

    def test_with_generation_params(self) -> None:
        req = CreateTaskRequest.text_to_video(
            "A cat",
            model="doubao-seedance-2-0",
            resolution="720p",
            ratio="16:9",
            duration=5,
            seed=42,
            watermark=True,
            generate_audio=False,
        )
        body = req.build()
        self.assertEqual("720p", body["resolution"])
        self.assertEqual("16:9", body["ratio"])
        self.assertEqual(5, body["duration"])
        self.assertEqual(42, body["seed"])
        self.assertIs(True, body["watermark"])
        self.assertIs(False, body["generate_audio"])

    def test_omit_null_params(self) -> None:
        req = CreateTaskRequest.text_to_video("A cat", model="m")
        body = req.build()
        self.assertNotIn("resolution", body)
        self.assertNotIn("ratio", body)
        self.assertNotIn("duration", body)
        self.assertNotIn("seed", body)
        self.assertNotIn("camera_fixed", body)
        self.assertNotIn("watermark", body)

    def test_rejects_empty_model(self) -> None:
        req = CreateTaskRequest.text_to_video("A cat", model="")
        with self.assertRaises(ArkParameterError):
            req.build()

    def test_rejects_empty_content(self) -> None:
        req = CreateTaskRequest(model="m", content=[])
        with self.assertRaises(ArkParameterError):
            req.build()

    def test_rejects_invalid_resolution(self) -> None:
        req = CreateTaskRequest.text_to_video("A cat", model="m", resolution="4K")
        with self.assertRaises(ArkParameterError):
            req.build()

    def test_rejects_invalid_ratio(self) -> None:
        req = CreateTaskRequest.text_to_video("A cat", model="m", ratio="5:4")
        with self.assertRaises(ArkParameterError):
            req.build()

    def test_rejects_duration_out_of_range(self) -> None:
        req = CreateTaskRequest.text_to_video(
            "A cat", model="doubao-seedance-2-0", duration=1,
        )
        with self.assertRaises(ArkParameterError):
            req.build()

    def test_allows_duration_negative_one(self) -> None:
        req = CreateTaskRequest.text_to_video(
            "A cat", model="doubao-seedance-2-0", duration=-1,
        )
        body = req.build()
        self.assertEqual(-1, body["duration"])

    def test_rejects_frames_out_of_range(self) -> None:
        req = CreateTaskRequest.text_to_video("A cat", model="m", frames=10)
        with self.assertRaises(ArkParameterError):
            req.build()

    def test_rejects_seed_out_of_range(self) -> None:
        req = CreateTaskRequest.text_to_video("A cat", model="m", seed=-5)
        with self.assertRaises(ArkParameterError):
            req.build()

    def test_rejects_invalid_service_tier(self) -> None:
        req = CreateTaskRequest.text_to_video("A cat", model="m", service_tier="premium")
        with self.assertRaises(ArkParameterError):
            req.build()

    def test_rejects_execution_expires_after_too_low(self) -> None:
        req = CreateTaskRequest.text_to_video("A cat", model="m", execution_expires_after=100)
        with self.assertRaises(ArkParameterError):
            req.build()


# ---------------------------------------------------------------------------
# CreateTaskRequest — image-to-video
# ---------------------------------------------------------------------------

class ImageToVideoTests(unittest.TestCase):
    def test_first_frame_only(self) -> None:
        req = CreateTaskRequest.image_to_video(
            "https://example.com/frame1.png",
            prompt="Animate this cat",
            model="doubao-seedance-2-0",
        )
        body = req.build()
        self.assertEqual("doubao-seedance-2-0", body["model"])
        self.assertEqual(2, len(body["content"]))
        # First item is text prompt
        self.assertEqual("text", body["content"][0]["type"])
        self.assertEqual("Animate this cat", body["content"][0]["text"])
        # Second item is first frame image
        self.assertEqual("image_url", body["content"][1]["type"])
        self.assertEqual("first_frame", body["content"][1]["role"])

    def test_first_frame_without_prompt(self) -> None:
        req = CreateTaskRequest.image_to_video(
            "https://example.com/frame1.png",
            model="doubao-seedance-2-0",
        )
        body = req.build()
        self.assertEqual(1, len(body["content"]))
        self.assertEqual("image_url", body["content"][0]["type"])
        self.assertEqual("first_frame", body["content"][0]["role"])

    def test_first_and_last_frame(self) -> None:
        req = CreateTaskRequest.image_to_video(
            "https://example.com/first.png",
            prompt="Smooth transition",
            model="doubao-seedance-2-0",
            last_frame_url="https://example.com/last.png",
        )
        body = req.build()
        self.assertEqual(3, len(body["content"]))
        # Text prompt
        self.assertEqual("text", body["content"][0]["type"])
        # First frame
        self.assertEqual("image_url", body["content"][1]["type"])
        self.assertEqual("first_frame", body["content"][1]["role"])
        self.assertIn("first.png", body["content"][1]["image_url"]["url"])
        # Last frame
        self.assertEqual("image_url", body["content"][2]["type"])
        self.assertEqual("last_frame", body["content"][2]["role"])
        self.assertIn("last.png", body["content"][2]["image_url"]["url"])

    def test_i2v_with_base64_image(self) -> None:
        req = CreateTaskRequest.image_to_video(
            "data:image/png;base64,iVBOR",
            model="doubao-seedance-2-0",
        )
        body = req.build()
        self.assertIn("data:image/png;base64,iVBOR", body["content"][0]["image_url"]["url"])

    def test_i2v_with_all_generation_params(self) -> None:
        req = CreateTaskRequest.image_to_video(
            "https://example.com/img.png",
            model="doubao-seedance-2-0",
            resolution="1080p",
            ratio="adaptive",
            duration=10,
            generate_audio=True,
            return_last_frame=True,
        )
        body = req.build()
        self.assertEqual("1080p", body["resolution"])
        self.assertEqual("adaptive", body["ratio"])
        self.assertEqual(10, body["duration"])
        self.assertIs(True, body["generate_audio"])
        self.assertIs(True, body["return_last_frame"])


# ---------------------------------------------------------------------------
# ArkClient.create_task integration
# ---------------------------------------------------------------------------

class CreateTaskClientTests(unittest.TestCase):
    def test_create_task_returns_id(self) -> None:
        transport = RecordingTransport(
            ArkHTTPResponse(200, {}, b'{"id":"cgt-abc123"}')
        )
        client = _make_client(transport)

        req = CreateTaskRequest.text_to_video("A cat", model="doubao-seedance-2-0")
        task_id = client.create_task(req)

        self.assertEqual("cgt-abc123", task_id)
        # Verify the request body was sent
        sent = json.loads(transport.requests[0].body)
        self.assertEqual("doubao-seedance-2-0", sent["model"])
        self.assertEqual("text", sent["content"][0]["type"])

    def test_create_task_fills_default_model_when_blank(self) -> None:
        transport = RecordingTransport(
            ArkHTTPResponse(200, {}, b'{"id":"cgt-def456"}')
        )
        client = _make_client(transport)

        req = CreateTaskRequest.text_to_video("A dog")
        task_id = client.create_task(req)

        self.assertEqual("cgt-def456", task_id)
        sent = json.loads(transport.requests[0].body)
        self.assertEqual("doubao-seedance-2-0-fast-260128", sent["model"])

    def test_create_task_raises_on_missing_id(self) -> None:
        transport = RecordingTransport(
            ArkHTTPResponse(200, {}, b'{"status":"ok"}')
        )
        client = _make_client(transport)

        req = CreateTaskRequest.text_to_video("A cat", model="m")
        with self.assertRaises(ArkAPIError):
            client.create_task(req)

    def test_create_task_propagates_parameter_error(self) -> None:
        transport = RecordingTransport(
            ArkHTTPResponse(400, {}, b'{"error":{"code":"InvalidParameter","message":"bad"}}')
        )
        client = _make_client(transport)

        req = CreateTaskRequest.text_to_video("A cat", model="m")
        from sd2video.ark import ArkParameterError
        with self.assertRaises(ArkParameterError):
            client.create_task(req)

    def test_create_task_image_to_video_sends_correct_payload(self) -> None:
        transport = RecordingTransport(
            ArkHTTPResponse(200, {}, b'{"id":"cgt-img123"}')
        )
        client = _make_client(transport)

        req = CreateTaskRequest.image_to_video(
            "https://example.com/start.png",
            prompt="Make it move",
            model="doubao-seedance-2-0",
            last_frame_url="https://example.com/end.png",
            ratio="9:16",
            duration=8,
        )
        task_id = client.create_task(req)

        self.assertEqual("cgt-img123", task_id)
        sent = json.loads(transport.requests[0].body)
        self.assertEqual(3, len(sent["content"]))
        self.assertEqual("text", sent["content"][0]["type"])
        self.assertEqual("first_frame", sent["content"][1]["role"])
        self.assertEqual("last_frame", sent["content"][2]["role"])
        self.assertEqual("9:16", sent["ratio"])
        self.assertEqual(8, sent["duration"])

    def test_create_task_method_is_post(self) -> None:
        transport = RecordingTransport(
            ArkHTTPResponse(200, {}, b'{"id":"cgt-1"}')
        )
        client = _make_client(transport)
        req = CreateTaskRequest.text_to_video("test", model="m")
        client.create_task(req)
        self.assertEqual("POST", transport.requests[0].method)


if __name__ == "__main__":
    unittest.main()
