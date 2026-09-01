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


async def build_store() -> DialogStore:
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
