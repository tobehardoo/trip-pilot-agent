"""Dialog state store — Redis with a transparent in-memory fallback.

v0.1 slice: conversation state is disposable scratch data, so a Redis outage
degrades to per-process memory instead of failing the endpoint.  Durable
``agent_run`` persistence arrives with the MQ-driven phase (design §4).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Protocol
from urllib.parse import quote

from trip_agent.agent.persistence import PsycopgAgentRunRepository
from trip_agent.agent.state import agent_state_from_dict, agent_state_to_dict
from trip_agent.providers.redis_cache import RedisJsonCache

logger = logging.getLogger(__name__)

KEY_PREFIX = "agent:dialog:"
TTL_SECONDS = 7 * 24 * 3600


class DialogStore(Protocol):
    async def load(self, trip_id: str) -> dict | None: ...

    async def save(self, trip_id: str, state: dict) -> None: ...

    async def close(self) -> None: ...


class RedisDialogStore:
    def __init__(self, cache: RedisJsonCache) -> None:
        self._cache = cache

    async def load(self, trip_id: str) -> dict | None:
        raw = await self._cache.get(KEY_PREFIX + trip_id)
        if raw is None or raw == "null":
            return None
        return json.loads(raw)

    async def save(self, trip_id: str, state: dict) -> None:
        await self._cache.set(
            KEY_PREFIX + trip_id,
            json.dumps(state, ensure_ascii=False),
            ttl_seconds=TTL_SECONDS,
        )

    async def close(self) -> None:
        await self._cache.aclose()


class InMemoryDialogStore:
    def __init__(self) -> None:
        self._states: dict[str, dict | None] = {}

    async def load(self, trip_id: str) -> dict | None:
        return self._states.get(trip_id)

    async def save(self, trip_id: str, state: dict) -> None:
        self._states[trip_id] = state

    async def close(self) -> None:
        self._states.clear()


class PsycopgDialogStore:
    """PostgreSQL-backed dialog checkpoint store (single constraint state).

    Reuses the exact ``agent.agent_checkpoint`` table and ``AgentState``
    snapshot format as the planning agent, so creation-mode dialogs and
    trip-mode agent runs persist through one durable store instead of a
    disposable Redis scratch key.  A run row is ensured idempotently before
    saving so the checkpoint's FK is satisfied.
    """

    def __init__(self, repository: PsycopgAgentRunRepository) -> None:
        self._repo = repository

    @staticmethod
    def _run_id(scope_key: str) -> str:
        # scope keys are unique text ids ("create:{sessionId}" / "trip:{tripId}")
        return scope_key

    async def load(self, scope_key: str) -> dict | None:
        state = await self._repo.load_checkpoint(self._run_id(scope_key))
        return None if state is None else agent_state_to_dict(state)

    async def save(self, scope_key: str, state: dict) -> None:
        run_id = self._run_id(scope_key)
        await self._repo.ensure_run(run_id=run_id)
        await self._repo.save_checkpoint(run_id=run_id, state=agent_state_from_dict(state))

    async def close(self) -> None:
        # PsycopgAgentRunRepository opens a short-lived connection per op.
        return None


async def build_store() -> DialogStore:
    """Postgres-preferred, then Redis, then in-memory dialog state store.

    The conversation checkpoint is the same one the planning agent persists,
    so Postgres is the durable authority when available; a DB outage degrades
    to Redis (loud), and a Redis outage to per-process memory (loud) — never
    failing the endpoint over scratch checkpoint data.
    """
    postgres = await _build_postgres_store()
    if postgres is not None:
        return postgres
    return await _build_redis_or_memory_store()


async def _build_postgres_store() -> PsycopgDialogStore | None:
    try:
        from trip_agent.acquisition.cli import AcquisitionSettings

        database_url = AcquisitionSettings().database_url()
    except Exception as error:  # noqa: BLE001 - configuration probing must not raise
        logger.warning("dialog_postgres_unavailable missing_config error=%s", type(error).__name__)
        return None
    if not database_url:
        return None
    try:
        repository = PsycopgAgentRunRepository(database_url)
        await repository.migrate()
        return PsycopgDialogStore(repository)
    except Exception as error:  # noqa: BLE001 - any provider failure degrades
        logger.warning("dialog_postgres_unavailable fallback=redis error=%s", type(error).__name__)
        return None


async def _build_redis_or_memory_store() -> DialogStore:
    """Redis-backed store when configured; in-memory fallback when not.

    The probe keeps a silently-broken Redis from swallowing every turn —
    the dialog falls back loudly (one warning) instead.
    """
    host = os.getenv("REDIS_HOST", "").strip()
    if not host:
        return InMemoryDialogStore()
    password = os.getenv("REDIS_PASSWORD", "")
    port = os.getenv("REDIS_PORT", "6379").strip() or "6379"
    db = os.getenv("REDIS_DB", "0").strip() or "0"
    credentials = f":{quote(password)}@" if password else ""
    url = f"redis://{credentials}{host}:{port}/{db}"
    timeout = float(os.getenv("REDIS_TIMEOUT_SECONDS", "2") or 2)
    cache = RedisJsonCache.from_url(url, socket_connect_timeout=timeout, socket_timeout=timeout)
    try:
        await cache.get(KEY_PREFIX + "__probe__")
    except Exception as error:  # noqa: BLE001 - any provider failure degrades
        logger.warning("dialog_redis_unavailable fallback=memory error=%s", type(error).__name__)
        await cache.aclose()
        return InMemoryDialogStore()
    return RedisDialogStore(cache)
