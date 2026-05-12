"""Comprehensive ArkConfig validation tests (HOM-31).

Covers:
  - Construction and frozen dataclass behaviour
  - from_env with various env-var shapes (whitespace, aliases, missing)
  - Validation of api_key, base_url, default_model_id, timeout, tasks_path
  - API key redaction in repr
"""

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


class ArkConfigConstructionTests(unittest.TestCase):
    """Basic construction and post-init normalisation."""

    def test_minimal_construction(self) -> None:
        cfg = ArkConfig(api_key="test-key")
        self.assertEqual("test-key", cfg.api_key)
        self.assertEqual(DEFAULT_BASE_URL, cfg.base_url)
        self.assertEqual(DEFAULT_MODEL_ID, cfg.default_model_id)
        self.assertEqual(DEFAULT_TIMEOUT_SECONDS, cfg.timeout_seconds)
        self.assertEqual(DEFAULT_TASKS_PATH, cfg.tasks_path)

    def test_strips_whitespace_from_api_key(self) -> None:
        cfg = ArkConfig(api_key="  padded-key  ")
        self.assertEqual("padded-key", cfg.api_key)

    def test_strips_trailing_slash_from_base_url(self) -> None:
        cfg = ArkConfig(api_key="k", base_url="https://example.test/")
        self.assertEqual("https://example.test", cfg.base_url)

    def test_normalises_base_url(self) -> None:
        cfg = ArkConfig(api_key="k", base_url="https://host:8080/path/")
        self.assertEqual("https://host:8080/path", cfg.base_url)

    def test_strips_whitespace_from_model_id(self) -> None:
        cfg = ArkConfig(api_key="k", default_model_id="  my-model  ")
        self.assertEqual("my-model", cfg.default_model_id)

    def test_prepends_slash_to_tasks_path(self) -> None:
        cfg = ArkConfig(api_key="k", tasks_path="api/tasks")
        self.assertEqual("/api/tasks", cfg.tasks_path)

    def test_strips_whitespace_from_tasks_path(self) -> None:
        cfg = ArkConfig(api_key="k", tasks_path="  /api/tasks  ")
        self.assertEqual("/api/tasks", cfg.tasks_path)

    def test_frozen_dataclass_rejects_mutation(self) -> None:
        cfg = ArkConfig(api_key="k")
        with self.assertRaises(AttributeError):
            cfg.api_key = "new-key"  # type: ignore[misc]


class ArkConfigValidationTests(unittest.TestCase):
    """Validation rules for each config field."""

    # -- api_key --
    def test_rejects_empty_api_key(self) -> None:
        with self.assertRaises(ArkConfigError):
            ArkConfig(api_key="")

    def test_rejects_whitespace_only_api_key(self) -> None:
        with self.assertRaises(ArkConfigError):
            ArkConfig(api_key="   ")

    def test_rejects_none_api_key(self) -> None:
        with self.assertRaises(ArkConfigError):
            ArkConfig(api_key=None)  # type: ignore[arg-type]

    # -- base_url --
    def test_rejects_non_http_base_url(self) -> None:
        with self.assertRaises(ArkConfigError):
            ArkConfig(api_key="k", base_url="ftp://example.com")

    def test_rejects_empty_base_url(self) -> None:
        with self.assertRaises(ArkConfigError):
            ArkConfig(api_key="k", base_url="")

    def test_rejects_base_url_without_host(self) -> None:
        with self.assertRaises(ArkConfigError):
            ArkConfig(api_key="k", base_url="https://")

    def test_accepts_http_base_url(self) -> None:
        cfg = ArkConfig(api_key="k", base_url="http://localhost:8080")
        self.assertEqual("http://localhost:8080", cfg.base_url)

    # -- default_model_id --
    def test_rejects_empty_model_id(self) -> None:
        with self.assertRaises(ArkConfigError):
            ArkConfig(api_key="k", default_model_id="")

    def test_rejects_whitespace_only_model_id(self) -> None:
        with self.assertRaises(ArkConfigError):
            ArkConfig(api_key="k", default_model_id="   ")

    # -- timeout_seconds --
    def test_rejects_zero_timeout(self) -> None:
        with self.assertRaises(ArkConfigError):
            ArkConfig(api_key="k", timeout_seconds=0)

    def test_rejects_negative_timeout(self) -> None:
        with self.assertRaises(ArkConfigError):
            ArkConfig(api_key="k", timeout_seconds=-1)

    def test_rejects_non_numeric_timeout(self) -> None:
        with self.assertRaises(ArkConfigError):
            ArkConfig(api_key="k", timeout_seconds="not-a-number")  # type: ignore[arg-type]

    def test_accepts_string_timeout_via_post_init(self) -> None:
        # Frozen dataclass, but post_init converts string
        cfg = ArkConfig(api_key="k", timeout_seconds="15")  # type: ignore[arg-type]
        self.assertEqual(15.0, cfg.timeout_seconds)

    # -- tasks_path --
    def test_rejects_empty_tasks_path(self) -> None:
        with self.assertRaises(ArkConfigError):
            ArkConfig(api_key="k", tasks_path="")


class ArkConfigFromEnvTests(unittest.TestCase):
    """from_env with various environment variable shapes."""

    def test_all_env_vars(self) -> None:
        cfg = ArkConfig.from_env({
            "ARK_API_KEY": "env-key",
            "ARK_BASE_URL": "https://env.test",
            "ARK_DEFAULT_MODEL_ID": "env-model",
            "ARK_TIMEOUT_SECONDS": "10",
        })
        self.assertEqual("env-key", cfg.api_key)
        self.assertEqual("https://env.test", cfg.base_url)
        self.assertEqual("env-model", cfg.default_model_id)
        self.assertEqual(10.0, cfg.timeout_seconds)

    def test_uses_ark_model_id_alias(self) -> None:
        cfg = ArkConfig.from_env({
            "ARK_API_KEY": "k",
            "ARK_MODEL_ID": "alias-model",
        })
        self.assertEqual("alias-model", cfg.default_model_id)

    def test_prefers_default_model_id_over_alias(self) -> None:
        cfg = ArkConfig.from_env({
            "ARK_API_KEY": "k",
            "ARK_DEFAULT_MODEL_ID": "primary",
            "ARK_MODEL_ID": "alias",
        })
        self.assertEqual("primary", cfg.default_model_id)

    def test_uses_defaults_when_optional_vars_missing(self) -> None:
        cfg = ArkConfig.from_env({"ARK_API_KEY": "k"})
        self.assertEqual(DEFAULT_BASE_URL, cfg.base_url)
        self.assertEqual(DEFAULT_MODEL_ID, cfg.default_model_id)
        self.assertEqual(DEFAULT_TIMEOUT_SECONDS, cfg.timeout_seconds)

    def test_rejects_missing_api_key_from_env(self) -> None:
        with self.assertRaises(ArkConfigError):
            ArkConfig.from_env({})

    def test_rejects_empty_api_key_from_env(self) -> None:
        with self.assertRaises(ArkConfigError):
            ArkConfig.from_env({"ARK_API_KEY": ""})

    def test_rejects_invalid_timeout_from_env(self) -> None:
        with self.assertRaises(ArkConfigError):
            ArkConfig.from_env({
                "ARK_API_KEY": "k",
                "ARK_TIMEOUT_SECONDS": "abc",
            })

    def test_strips_whitespace_from_env_values(self) -> None:
        cfg = ArkConfig.from_env({
            "ARK_API_KEY": "  env-key  ",
            "ARK_BASE_URL": "  https://env.test/  ",
        })
        self.assertEqual("env-key", cfg.api_key)
        self.assertEqual("https://env.test", cfg.base_url)


class ArkConfigReprTests(unittest.TestCase):
    """API key redaction in repr."""

    def test_repr_redacts_api_key(self) -> None:
        cfg = ArkConfig(api_key="super-secret")
        r = repr(cfg)
        self.assertNotIn("super-secret", r)
        self.assertIn("super-secret", cfg.api_key)  # actual key still accessible


if __name__ == "__main__":
    unittest.main()
