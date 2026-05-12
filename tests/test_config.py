from __future__ import annotations

import unittest

from sd2video.ark.config import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL_ID,
    DEFAULT_TASKS_PATH,
    DEFAULT_TIMEOUT_SECONDS,
    ArkConfig,
)
from sd2video.ark.errors import ArkConfigError
from sd2video.server import ServerConfig


class ArkConfigTests(unittest.TestCase):
    def test_defaults_and_normalization(self) -> None:
        cfg = ArkConfig(
            api_key="  test-key  ",
            base_url="https://example.test/",
            default_model_id="  model-id  ",
            timeout_seconds="12.5",  # type: ignore[arg-type]
            tasks_path="api/tasks",
        )

        self.assertEqual("test-key", cfg.api_key)
        self.assertEqual("https://example.test", cfg.base_url)
        self.assertEqual("model-id", cfg.default_model_id)
        self.assertEqual(12.5, cfg.timeout_seconds)
        self.assertEqual("/api/tasks", cfg.tasks_path)

    def test_minimal_config_uses_safe_defaults(self) -> None:
        cfg = ArkConfig(api_key="test-key")

        self.assertEqual(DEFAULT_BASE_URL, cfg.base_url)
        self.assertEqual(DEFAULT_MODEL_ID, cfg.default_model_id)
        self.assertEqual(DEFAULT_TASKS_PATH, cfg.tasks_path)
        self.assertEqual(DEFAULT_TIMEOUT_SECONDS, cfg.timeout_seconds)
        self.assertNotIn("test-key", repr(cfg))

    def test_invalid_ark_config_values_are_rejected(self) -> None:
        invalid_cases = [
            {"api_key": ""},
            {"api_key": "   "},
            {"api_key": "k", "base_url": "ftp://example.test"},
            {"api_key": "k", "base_url": "https://"},
            {"api_key": "k", "default_model_id": ""},
            {"api_key": "k", "timeout_seconds": 0},
            {"api_key": "k", "timeout_seconds": "abc"},
            {"api_key": "k", "tasks_path": ""},
        ]

        for kwargs in invalid_cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ArkConfigError):
                    ArkConfig(**kwargs)  # type: ignore[arg-type]

    def test_from_env_uses_aliases_and_rejects_missing_secret(self) -> None:
        cfg = ArkConfig.from_env(
            {
                "ARK_API_KEY": "env-key",
                "ARK_BASE_URL": " https://env.test/ ",
                "ARK_MODEL_ID": "alias-model",
                "ARK_TIMEOUT_SECONDS": "9",
            }
        )

        self.assertEqual("env-key", cfg.api_key)
        self.assertEqual("https://env.test", cfg.base_url)
        self.assertEqual("alias-model", cfg.default_model_id)
        self.assertEqual(9.0, cfg.timeout_seconds)

        with self.assertRaises(ArkConfigError):
            ArkConfig.from_env({})

    def test_from_env_prefers_default_model_id_alias(self) -> None:
        cfg = ArkConfig.from_env(
            {
                "ARK_API_KEY": "env-key",
                "ARK_DEFAULT_MODEL_ID": "primary",
                "ARK_MODEL_ID": "alias",
            }
        )

        self.assertEqual("primary", cfg.default_model_id)


class ServerConfigTests(unittest.TestCase):
    def test_from_env_normalizes_mock_cors_and_poll_settings(self) -> None:
        cfg = ServerConfig.from_env(
            {
                "SD2VIDEO_MOCK": "true",
                "SD2VIDEO_CORS_ORIGINS": "http://localhost:5173/, file://",
                "SD2VIDEO_BIND": "0.0.0.0:9000",
                "SD2VIDEO_POLL_INTERVAL_SECONDS": "1.5",
                "SD2VIDEO_POLL_TIMEOUT_SECONDS": "20",
                "ARK_DEFAULT_MODEL_ID": " env-model ",
            }
        )

        self.assertTrue(cfg.mock)
        self.assertEqual(("http://localhost:5173", "file://"), cfg.cors_origins)
        self.assertEqual(("0.0.0.0", 9000), cfg.bind_host_port())
        self.assertEqual(1.5, cfg.poll_interval_seconds)
        self.assertEqual(20.0, cfg.poll_timeout_seconds)
        self.assertEqual("env-model", cfg.default_model_id)

    def test_server_config_rejects_invalid_values(self) -> None:
        invalid_cases = [
            {"default_model_id": ""},
            {"poll_interval_seconds": 0},
            {"poll_timeout_seconds": -1},
            {"duplicate_window_seconds": "abc"},
        ]

        for kwargs in invalid_cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises((TypeError, ValueError)):
                    ServerConfig(**kwargs)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
