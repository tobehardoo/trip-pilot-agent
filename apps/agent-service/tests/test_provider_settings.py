"""F-2b — provider mode resolution is a single helper.

``providers/settings.resolve_provider_mode`` is the one place that turns
the environment (``PROVIDER_MODE`` + ``AMAP_WEB_SERVICE_KEY``) into a
``ProviderExecutionMode``.  ``tool_capabilities._mode`` and the places API
both delegate here; the AMQP worker's ``WorkerSettings`` deliberately keeps
its own fail-closed policy (B12) and is out of scope for this helper.
"""

from __future__ import annotations

import pytest

from trip_agent.providers.errors import ProviderExecutionMode
from trip_agent.providers.settings import (
    DEFAULT_STRUCTURED_MODEL_MAX_INPUT_CHARACTERS,
    DEFAULT_STRUCTURED_MODEL_MAX_RETRIES,
    DEFAULT_STRUCTURED_MODEL_TIMEOUT_SECONDS,
    resolve_provider_mode,
    structured_model_config,
)


def test_explicit_demo_mode_wins_over_a_present_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDER_MODE", "DEMO_ONLY")
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-key")
    assert resolve_provider_mode() is ProviderExecutionMode.DEMO_ONLY


def test_explicit_real_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDER_MODE", "REAL_ONLY")
    monkeypatch.delenv("AMAP_WEB_SERVICE_KEY", raising=False)
    assert resolve_provider_mode() is ProviderExecutionMode.REAL_ONLY


def test_explicit_fallback_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDER_MODE", "REAL_WITH_EXPLICIT_FALLBACK")
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-key")
    assert resolve_provider_mode() is ProviderExecutionMode.REAL_WITH_EXPLICIT_FALLBACK


def test_mode_is_case_and_whitespace_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDER_MODE", "  demo_only ")
    monkeypatch.delenv("AMAP_WEB_SERVICE_KEY", raising=False)
    assert resolve_provider_mode() is ProviderExecutionMode.DEMO_ONLY


def test_unset_mode_without_key_falls_back_to_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROVIDER_MODE", raising=False)
    monkeypatch.delenv("AMAP_WEB_SERVICE_KEY", raising=False)
    assert resolve_provider_mode() is ProviderExecutionMode.DEMO_ONLY


def test_unset_mode_with_blank_key_falls_back_to_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROVIDER_MODE", raising=False)
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "   ")
    assert resolve_provider_mode() is ProviderExecutionMode.DEMO_ONLY


def test_unset_mode_with_key_selects_real(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROVIDER_MODE", raising=False)
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-key")
    assert resolve_provider_mode() is ProviderExecutionMode.REAL_ONLY


def test_invalid_mode_value_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDER_MODE", "FLYING_MODE")
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-key")
    with pytest.raises(ValueError, match="FLYING_MODE"):
        resolve_provider_mode()


# ── structured_model_config: the single STRUCTURED_MODEL_* reader ──────────


def _identity_env() -> dict[str, str]:
    return {
        "STRUCTURED_MODEL_ENDPOINT": "https://model.example/v1",
        "STRUCTURED_MODEL_API_KEY": "secret-key",
        "STRUCTURED_MODEL_NAME": "qwen-plus",
    }


def test_structured_config_reads_all_three_identity_fields() -> None:
    shared = structured_model_config(_identity_env())
    assert shared is not None
    assert shared.endpoint == "https://model.example/v1"
    assert shared.api_key == "secret-key"
    assert shared.model == "qwen-plus"


def test_structured_config_default_knobs() -> None:
    shared = structured_model_config(_identity_env())
    assert shared is not None
    assert shared.timeout_seconds == DEFAULT_STRUCTURED_MODEL_TIMEOUT_SECONDS
    assert shared.max_retries == DEFAULT_STRUCTURED_MODEL_MAX_RETRIES
    assert shared.max_input_characters == DEFAULT_STRUCTURED_MODEL_MAX_INPUT_CHARACTERS


def test_structured_config_parses_explicit_knobs() -> None:
    env = {
        **_identity_env(),
        "STRUCTURED_MODEL_TIMEOUT_SECONDS": "12",
        "STRUCTURED_MODEL_MAX_RETRIES": "3",
        "STRUCTURED_MODEL_MAX_INPUT_CHARACTERS": "5000",
    }
    shared = structured_model_config(env)
    assert shared is not None
    assert shared.timeout_seconds == 12.0
    assert shared.max_retries == 3
    assert shared.max_input_characters == 5_000


def test_structured_config_missing_endpoint_is_unconfigured() -> None:
    assert structured_model_config({}) is None
    partial = _identity_env()
    del partial["STRUCTURED_MODEL_API_KEY"]
    assert structured_model_config(partial) is None


def test_structured_config_blank_identity_is_unconfigured() -> None:
    env = _identity_env()
    env["STRUCTURED_MODEL_NAME"] = "   "
    assert structured_model_config(env) is None


def test_structured_config_blank_knob_falls_back_to_default() -> None:
    """The one reader that previously raised on a blank knob now joins the
    majority 'blank → default' behavior instead of crashing."""
    env = {
        **_identity_env(),
        "STRUCTURED_MODEL_TIMEOUT_SECONDS": "",
        "STRUCTURED_MODEL_MAX_RETRIES": "",
    }
    shared = structured_model_config(env)
    assert shared is not None
    assert shared.timeout_seconds == DEFAULT_STRUCTURED_MODEL_TIMEOUT_SECONDS
    assert shared.max_retries == DEFAULT_STRUCTURED_MODEL_MAX_RETRIES


def test_structured_config_from_real_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRUCTURED_MODEL_ENDPOINT", "https://model.example/v1")
    monkeypatch.setenv("STRUCTURED_MODEL_API_KEY", "secret-key")
    monkeypatch.setenv("STRUCTURED_MODEL_NAME", "qwen-plus")
    shared = structured_model_config()
    assert shared is not None
    assert shared.model == "qwen-plus"
