"""Environment-driven provider configuration (single source of truth).

F-2b: the provider execution mode used to be resolved independently in
``places/api._resolved_provider_mode`` (and previously the removed agent
``tool_capabilities`` module) with identical logic.  This module owns that
decision exactly once; the remaining call site delegates here.

Note on scope: this is the *tool/endpoint* policy.  The AMQP worker's
``WorkerSettings.resolved_provider_mode`` deliberately fails closed to
DEMO_ONLY when unset (B12 acceptance contract); it is NOT routed through
this helper because a missing key must never auto-select a real provider
in the worker process.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from trip_agent.providers.errors import ProviderExecutionMode

# Shared structured-model defaults.  These mirror the historical values of
# every reader (agent factory, dialog extractor, guide intelligence) so the
# consolidation below never changes behavior.
DEFAULT_STRUCTURED_MODEL_TIMEOUT_SECONDS = 8.0
DEFAULT_STRUCTURED_MODEL_MAX_RETRIES = 1
DEFAULT_STRUCTURED_MODEL_MAX_INPUT_CHARACTERS = 30_000


def resolve_provider_mode() -> ProviderExecutionMode:
    """Resolve the provider execution mode from the environment.

    ``PROVIDER_MODE`` wins when set (must be a valid member name, otherwise
    ``ValueError``).  Without it, the presence of a non-empty
    ``AMAP_WEB_SERVICE_KEY`` selects REAL_ONLY (a key signals intent to use
    real provider data) and its absence DEMO_ONLY.
    """
    raw = (os.getenv("PROVIDER_MODE") or "").strip().upper()
    if raw:
        return ProviderExecutionMode(raw)
    if not (os.getenv("AMAP_WEB_SERVICE_KEY") or "").strip():
        return ProviderExecutionMode.DEMO_ONLY
    return ProviderExecutionMode.REAL_ONLY


@dataclass(frozen=True, slots=True)
class StructuredModelConfig:
    """Identity and bounded knobs of the shared structured-model endpoint."""

    endpoint: str
    api_key: str
    model: str
    timeout_seconds: float = DEFAULT_STRUCTURED_MODEL_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_STRUCTURED_MODEL_MAX_RETRIES
    max_input_characters: int = DEFAULT_STRUCTURED_MODEL_MAX_INPUT_CHARACTERS


def structured_model_config(
    env: Mapping[str, str] | None = None,
) -> StructuredModelConfig | None:
    """Read the shared ``STRUCTURED_MODEL_*`` surface exactly once.

    All three identity fields are required — a partially configured
    endpoint must not half-start.  Returns ``None`` when unconfigured, which
    every caller maps to its deterministic fallback.  Empty optional knobs
    fall back to the shared defaults (this also fixes the one reader that
    previously raised on an explicitly-blank value).
    """
    source = os.environ if env is None else env
    endpoint = source.get("STRUCTURED_MODEL_ENDPOINT", "").strip()
    api_key = source.get("STRUCTURED_MODEL_API_KEY", "").strip()
    model = source.get("STRUCTURED_MODEL_NAME", "").strip()
    if not endpoint or not api_key or not model:
        return None
    return StructuredModelConfig(
        endpoint=endpoint,
        api_key=api_key,
        model=model,
        timeout_seconds=float(
            source.get("STRUCTURED_MODEL_TIMEOUT_SECONDS", "").strip()
            or DEFAULT_STRUCTURED_MODEL_TIMEOUT_SECONDS
        ),
        max_retries=int(
            source.get("STRUCTURED_MODEL_MAX_RETRIES", "").strip()
            or DEFAULT_STRUCTURED_MODEL_MAX_RETRIES
        ),
        max_input_characters=int(
            source.get("STRUCTURED_MODEL_MAX_INPUT_CHARACTERS", "").strip()
            or DEFAULT_STRUCTURED_MODEL_MAX_INPUT_CHARACTERS
        ),
    )
