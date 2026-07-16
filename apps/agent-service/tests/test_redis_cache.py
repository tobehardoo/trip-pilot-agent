import asyncio
from importlib import import_module
from importlib.util import find_spec


class FakeRedisClient:
    def __init__(self) -> None:
        self.values: dict[str, bytes | str] = {}
        self.writes: list[tuple[str, str, int]] = []
        self.closed = False

    async def get(self, name: str) -> bytes | str | None:
        return self.values.get(name)

    async def set(self, name: str, value: str, *, ex: int) -> bool:
        self.values[name] = value
        self.writes.append((name, value, ex))
        return True

    async def aclose(self) -> None:
        self.closed = True


def test_redis_json_cache_decodes_bytes_and_preserves_ttl() -> None:
    assert find_spec("trip_agent.providers.redis_cache") is not None
    module = import_module("trip_agent.providers.redis_cache")
    client = FakeRedisClient()
    client.values["existing"] = b'{"cached":true}'
    cache = module.RedisJsonCache(client)

    async def run_scenario() -> tuple[str | None, str | None]:
        existing = await cache.get("existing")
        await cache.set("new", '{"fresh":true}', ttl_seconds=3600)
        new = await cache.get("new")
        await cache.aclose()
        return existing, new

    existing, new = asyncio.run(run_scenario())

    assert existing == '{"cached":true}'
    assert new == '{"fresh":true}'
    assert client.writes == [("new", '{"fresh":true}', 3600)]
    assert client.closed is True
