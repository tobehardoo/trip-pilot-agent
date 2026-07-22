import asyncio
from datetime import UTC, datetime, timedelta

import httpx

from trip_agent.acquisition import AcquisitionScheduler, HttpResourceFetcher, RetryPolicy
from trip_agent.acquisition.models import DiscoveredResource, KnowledgeSource


class _BytesStream(httpx.AsyncByteStream):
    def __init__(self, content: bytes) -> None:
        self._content = content

    async def __aiter__(self):
        yield self._content


class _StaticHostResolver:
    async def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        return ("93.184.216.34",)


class _FakeTime:
    def __init__(self) -> None:
        self.seconds = 0.0
        self.sleep_calls: list[float] = []
        self._started_at = datetime(2026, 7, 22, tzinfo=UTC)

    def monotonic(self) -> float:
        return self.seconds

    def now(self) -> datetime:
        return self._started_at + timedelta(seconds=self.seconds)

    async def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self.seconds += seconds


def test_scheduler_retries_retryable_http_fetch_and_returns_success() -> None:
    source = KnowledgeSource(
        source_id="official-source",
        city="广州",
        source_name="官方来源",
        reliability_level="OFFICIAL",
        allowed_domains=("example.com",),
        resource_urls=("https://example.com/article",),
        min_request_interval_seconds=0.5,
        max_response_bytes=64 * 1024,
    )
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )
    request_count = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(200, stream=_BytesStream(b"recovered"), request=request)

    fake_time = _FakeTime()
    scheduler = AcquisitionScheduler(
        fetcher=HttpResourceFetcher(
            http_transport_factory=lambda: httpx.MockTransport(handle),
            host_resolver=_StaticHostResolver(),
        ),
        retry_policy=RetryPolicy(
            max_attempts=2,
            initial_backoff_seconds=1.0,
            max_backoff_seconds=1.0,
        ),
        sleeper=fake_time,
        monotonic=fake_time.monotonic,
        clock=fake_time.now,
    )

    execution = asyncio.run(scheduler.execute(source=source, resource=resource))

    assert execution.status == "SUCCEEDED"
    assert execution.result.content == b"recovered"
    assert [attempt.status for attempt in execution.attempts] == ["FAILED", "SUCCEEDED"]
    assert request_count == 2
    assert fake_time.sleep_calls == [1.0]
