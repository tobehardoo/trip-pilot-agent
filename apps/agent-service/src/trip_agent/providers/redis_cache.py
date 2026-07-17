"""Redis-backed JSON cache adapter used by external data providers."""

from typing import Protocol, Self


class AsyncRedisClient(Protocol):
    async def get(self, name: str) -> bytes | str | None: ...

    async def set(self, name: str, value: str, *, ex: int) -> object: ...

    async def aclose(self) -> None: ...


class RedisJsonCache:
    def __init__(self, client: AsyncRedisClient) -> None:
        self._client = client

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        socket_connect_timeout: float = 2.0,
        socket_timeout: float = 2.0,
    ) -> Self:
        from redis.asyncio import Redis

        if socket_connect_timeout <= 0 or socket_timeout <= 0:
            raise ValueError("Redis socket timeouts must be positive")
        return cls(
            Redis.from_url(
                url,
                socket_connect_timeout=socket_connect_timeout,
                socket_timeout=socket_timeout,
            )
        )

    async def get(self, key: str) -> str | None:
        value = await self._client.get(key)
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return value

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            raise ValueError("cache TTL must be positive")
        await self._client.set(key, value, ex=ttl_seconds)

    async def aclose(self) -> None:
        await self._client.aclose()
