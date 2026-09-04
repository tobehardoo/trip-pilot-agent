"""Per-user provider API credentials (BYOK) resolved from ``user_api_config``.

The settings page lets a user store third-party API keys (WEATHER / AMAP /
KNOWLEDGE embedding / PLANNER) in ``user_api_config``.  These providers'
Python runtimes are constructed from environment variables today; this module
defines a resolved ``ProviderCredentials`` bundle so a planning run can use the
*user's* keys with a server-environment fallback.

Semantics are the same as the settings page: a user value wins over the
environment default; an absent user value falls back.  Nothing here is fatal
when a user has configured nothing.

Honest scope note (kept in the dataclass docstring): which consumers actually
accept the resolved keys:
- AMAP  -> worker/runtime.build_planning_provider (Amap map / route / transit)
- KNOWLEDGE -> worker/runtime embedding (DashScope), including base_url/model
- WEATHER -> resolved but its runtime consumer (guide_intelligence qweather)
             still reads the environment at call time; wiring is out of scope
             here and documented as pending.
- PLANNER -> there is no separate external "planner" provider in the runtime
             (planning is the deterministic AMap pipeline); this key currently
             has no runtime consumer.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from trip_agent.worker.runtime import WorkerSettings

# Providers stored in user_api_config (public schema) — must match travel-server
# UserApiConfigService.WEATHER/AMAP/KNOWLEDGE/PLANNER.
AMAP = "AMAP"
WEATHER = "WEATHER"
KNOWLEDGE = "KNOWLEDGE"
PLANNER = "PLANNER"


class ProviderCredentials:
    """Resolved, optional per-provider credentials (user value, else env)."""

    __slots__ = (
        "amap_key",
        "qweather_key",
        "dashscope_key",
        "dashscope_base_url",
        "dashscope_model",
    )

    def __init__(
        self,
        *,
        amap_key: str | None = None,
        qweather_key: str | None = None,
        dashscope_key: str | None = None,
        dashscope_base_url: str | None = None,
        dashscope_model: str | None = None,
    ) -> None:
        self.amap_key = amap_key
        self.qweather_key = qweather_key
        self.dashscope_key = dashscope_key
        self.dashscope_base_url = dashscope_base_url
        self.dashscope_model = dashscope_model

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ProviderCredentials):
            return NotImplemented
        return tuple(getattr(self, name) for name in self.__slots__) == tuple(
            getattr(other, name) for name in self.__slots__
        )

    def has_user_overrides(self) -> bool:
        """True when any provider carries a concrete key value."""
        return any(
            value is not None
            for value in (
                self.amap_key,
                self.qweather_key,
                self.dashscope_key,
            )
        )


def env_credentials(settings: WorkerSettings) -> ProviderCredentials:
    """Credentials derived purely from the running environment (server default)."""
    return ProviderCredentials(
        amap_key=(
            settings.amap_web_service_key.get_secret_value()
            if settings.amap_web_service_key is not None
            else None
        ),
        qweather_key=os.getenv("QWEATHER_API_KEY", "").strip() or None,
        dashscope_key=(
            settings.dashscope_api_key.get_secret_value()
            if settings.dashscope_api_key is not None
            else None
        ),
        dashscope_base_url=settings.dashscope_embedding_base_url or None,
        dashscope_model=settings.knowledge_embedding_model or None,
    )


def merge_credentials(env: ProviderCredentials, user: ProviderCredentials) -> ProviderCredentials:
    """User-configured values take precedence over the environment defaults."""
    return ProviderCredentials(
        amap_key=user.amap_key or env.amap_key,
        qweather_key=user.qweather_key or env.qweather_key,
        dashscope_key=user.dashscope_key or env.dashscope_key,
        dashscope_base_url=user.dashscope_base_url or env.dashscope_base_url,
        dashscope_model=user.dashscope_model or env.dashscope_model,
    )


class UserCredentialStore(Protocol):
    def fetch(self, owner_id: str) -> tuple[tuple[str, str], ...]:
        """Return (provider, api_key) rows for one owner."""
        ...


class PsycopgUserCredentialStore:
    """Read ``user_api_config`` from the shared database (public schema)."""

    def __init__(self, connection_url: str) -> None:
        if not connection_url.strip():
            raise ValueError("database connection URL cannot be empty")
        self._connection_url = connection_url.strip()

    def fetch(self, owner_id: str) -> tuple[tuple[str, str], ...]:
        import psycopg

        with psycopg.connect(self._connection_url, row_factory=psycopg.rows.dict_row) as connection:
            rows = connection.execute(
                """
                SELECT provider, api_key, api_base_url, model
                FROM user_api_config
                WHERE user_id = %s
                """,
                (owner_id,),
            ).fetchall()
        overrides: dict[str, tuple[str, str, str]] = {}
        for row in rows:
            provider = row["provider"]
            key = (row["api_key"] or "").strip()
            if not key:
                continue
            overrides[provider] = (
                key,
                (row["api_base_url"] or "").strip() or "",
                (row["model"] or "").strip() or "",
            )
        return tuple(
            (provider, key)
            for provider, (key, _, _) in overrides.items()
        )


def resolve_user_credentials(
    connection_url: str,
    owner_id: str | None,
    *,
    env: ProviderCredentials,
    store: UserCredentialStore | None = None,
) -> ProviderCredentials:
    """Merge the owner's ``user_api_config`` over the environment defaults.

    ``owner_id`` ``None`` (no known owner) or an empty result falls back to the
    environment credentials untouched.
    """
    if not owner_id:
        return env
    active = store or PsycopgUserCredentialStore(connection_url)
    user_overrides = active.fetch(owner_id)
    by_provider = dict((provider, key) for provider, key in user_overrides)
    user = ProviderCredentials(
        amap_key=by_provider.get(AMAP),
        qweather_key=by_provider.get(WEATHER),
        dashscope_key=by_provider.get(KNOWLEDGE),
    )
    return merge_credentials(env, user)


def command_credential_overrides(command: object) -> ProviderCredentials:
    """Extract the optional ``credentialOverrides`` carried on a planning command.

    Returns an empty :class:`ProviderCredentials` when the command carries none
    (the common case), so callers can fast-path to the default environment
    providers.
    """
    payload = getattr(command, "payload", None)
    overrides = getattr(payload, "credential_overrides", None) or {}
    amap = overrides.get(AMAP)
    weather = overrides.get(WEATHER)
    knowledge = overrides.get(KNOWLEDGE)
    return ProviderCredentials(
        amap_key=_override_key(amap),
        qweather_key=_override_key(weather),
        dashscope_key=_override_key(knowledge),
        dashscope_base_url=(
            _override_text(knowledge.api_base_url) if knowledge is not None else None
        ),
        dashscope_model=(_override_text(knowledge.model) if knowledge is not None else None),
    )


def _override_key(data: object | None) -> str | None:
    if data is None:
        return None
    return _override_text(getattr(data, "api_key", None))


def _override_text(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None