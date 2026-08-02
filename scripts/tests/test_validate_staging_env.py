from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from validate_staging_env import load_env, validate_staging_environment


def valid_environment() -> dict[str, str]:
    return {
        "APP_ENV": "staging",
        "IMAGE_TAG": "7b99b85",
        "PROVIDER_MODE": "REAL_ONLY",
        "PROVIDER_FALLBACK_CATEGORIES": "[]",
        "POSTGRES_PASSWORD": "postgres-password-123",
        "REDIS_PASSWORD": "redis-password-12345",
        "RABBITMQ_PASSWORD": "rabbit-password-1234",
        "JWT_SECRET": "j" * 40,
        "AGENT_INTERNAL_TOKEN": "a" * 40,
        "INTERNAL_DIAGNOSTICS_TOKEN": "d" * 40,
        "REFRESH_COOKIE_SECURE": "true",
        "TRUSTED_PROXY_CIDR": "10.20.30.40/32",
        "AMAP_WEB_SERVICE_KEY": "amap-server-credential",
        "QWEATHER_API_KEY": "qweather-server-credential",
        "QWEATHER_API_HOST": "abc123.qweatherapi.com",
        "VITE_AMAP_WEB_JS_KEY": "amap-browser-credential",
        "VITE_AMAP_SECURITY_CODE": "amap-browser-security-code",
    }


class ValidateStagingEnvironmentTest(unittest.TestCase):
    def test_accepts_a_strict_real_staging_configuration(self) -> None:
        self.assertEqual(validate_staging_environment(valid_environment()), [])

    def test_rejects_demo_fallback_and_partial_qweather_configuration(self) -> None:
        values = valid_environment()
        values["PROVIDER_MODE"] = "REAL_WITH_EXPLICIT_FALLBACK"
        values["PROVIDER_FALLBACK_CATEGORIES"] = '["QUOTA_EXCEEDED"]'
        values["QWEATHER_API_HOST"] = ""

        errors = validate_staging_environment(values)

        self.assertTrue(any("PROVIDER_MODE" in error for error in errors))
        self.assertTrue(any("PROVIDER_FALLBACK_CATEGORIES" in error for error in errors))
        self.assertTrue(any("QWEATHER_API_HOST" in error for error in errors))

    def test_rejects_placeholders_reused_secrets_and_unsafe_network_values(self) -> None:
        values = valid_environment()
        values["POSTGRES_PASSWORD"] = "replace-with-password"
        values["JWT_SECRET"] = "shared-secret-that-is-long-enough-123456"
        values["AGENT_INTERNAL_TOKEN"] = values["JWT_SECRET"]
        values["REFRESH_COOKIE_SECURE"] = "false"
        values["TRUSTED_PROXY_CIDR"] = "0.0.0.0/0"
        values["IMAGE_TAG"] = "latest"

        errors = validate_staging_environment(values)

        for variable in (
            "POSTGRES_PASSWORD",
            "JWT_SECRET",
            "AGENT_INTERNAL_TOKEN",
            "REFRESH_COOKIE_SECURE",
            "TRUSTED_PROXY_CIDR",
            "IMAGE_TAG",
        ):
            self.assertTrue(any(variable in error for error in errors), variable)
        self.assertFalse(any(values["JWT_SECRET"] in error for error in errors))

    def test_rejects_non_dedicated_qweather_hosts_and_reused_amap_keys(self) -> None:
        values = valid_environment()
        values["QWEATHER_API_HOST"] = "https://api.qweather.com/v7/weather"
        values["VITE_AMAP_WEB_JS_KEY"] = values["AMAP_WEB_SERVICE_KEY"]
        values["VITE_AMAP_SECURITY_CODE"] = values["QWEATHER_API_KEY"]

        errors = validate_staging_environment(values)

        self.assertTrue(any("QWEATHER_API_HOST" in error for error in errors))
        self.assertTrue(any("AMAP_WEB_SERVICE_KEY" in error for error in errors))
        self.assertTrue(any("QWEATHER_API_KEY" in error for error in errors))
        self.assertFalse(any(values["AMAP_WEB_SERVICE_KEY"] in error for error in errors))

    def test_rejects_secret_interpolation_before_compose_can_alias_values(self) -> None:
        values = valid_environment()
        values["JWT_SECRET"] = "${A_VERY_LONG_STAGING_SECRET_REFERENCE}"

        errors = validate_staging_environment(values)

        self.assertTrue(
            any("JWT_SECRET" in error and "interpolation" in error for error in errors)
        )
        self.assertFalse(any(values["JWT_SECRET"] in error for error in errors))

    def test_load_env_ignores_comments_and_preserves_equals_in_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "# private staging configuration\n"
                "TOKEN=prefix=value # operator note\n"
                'QUOTED="value # kept"\n'
                "EMPTY=\n",
                encoding="utf-8",
            )

            self.assertEqual(
                load_env(env_file),
                {"TOKEN": "prefix=value", "QUOTED": "value # kept", "EMPTY": ""},
            )


if __name__ == "__main__":
    unittest.main()
