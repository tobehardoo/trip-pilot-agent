import asyncio
from contextlib import suppress
from datetime import UTC, datetime

from trip_agent.acquisition import AcquisitionScheduler, FetchValidators
from trip_agent.acquisition.fetch_models import FetchResult, ResourceFetched
from trip_agent.acquisition.models import DiscoveredResource, KnowledgeSource


def _source(source_id: str = "official-source") -> KnowledgeSource:
    domain = f"{source_id}.example.com"
    return KnowledgeSource(
        source_id=source_id,
        city="广州",
        source_name="官方来源",
        reliability_level="OFFICIAL",
        allowed_domains=(domain,),
        resource_urls=(f"https://{domain}/article",),
        min_request_interval_seconds=1.0,
        max_response_bytes=64 * 1024,
    )


def _resource(source: KnowledgeSource) -> DiscoveredResource:
    return DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )


class _RecordingFetcher:
    def __init__(self, monotonic) -> None:
        self._monotonic = monotonic
        self.started: list[tuple[str, float]] = []

    async def fetch(
        self,
        *,
        source: KnowledgeSource,
        resource: DiscoveredResource,
        validators: FetchValidators | None = None,
    ) -> FetchResult:
        self.started.append((source.source_id, self._monotonic()))
        return ResourceFetched(
            status="FETCHED",
            requested_url=resource.url,
            final_url=resource.url,
            fetched_at=datetime(2026, 7, 22, tzinfo=UTC),
            content=b"content",
            content_type="text/html",
            validators=FetchValidators(),
        )


class _LateWakeTime:
    def __init__(self) -> None:
        self.seconds = 0.0
        self.sleep_started = asyncio.Event()
        self.release_late = asyncio.Event()
        self._late_released = False

    def monotonic(self) -> float:
        return self.seconds

    def now(self) -> datetime:
        return datetime(2026, 7, 22, tzinfo=UTC)

    async def sleep(self, seconds: float) -> None:
        if not self._late_released:
            self.sleep_started.set()
            await self.release_late.wait()
            self._late_released = True
            return
        self.seconds += seconds

    def wake_at(self, seconds: float) -> None:
        self.seconds = seconds
        self.release_late.set()


class _CancellableTime:
    def __init__(self) -> None:
        self.seconds = 0.0
        self.block = True
        self.sleep_started = asyncio.Event()
        self._release = asyncio.Event()

    def monotonic(self) -> float:
        return self.seconds

    def now(self) -> datetime:
        return datetime(2026, 7, 22, tzinfo=UTC)

    async def sleep(self, seconds: float) -> None:
        if self.block:
            self.sleep_started.set()
            await self._release.wait()
            return
        self.seconds += seconds


def test_same_source_attempts_remain_spaced_after_late_wakeup() -> None:
    source = _source()
    resource = _resource(source)
    fake_time = _LateWakeTime()
    fetcher = _RecordingFetcher(fake_time.monotonic)
    scheduler = AcquisitionScheduler(
        fetcher=fetcher,
        sleeper=fake_time,
        monotonic=fake_time.monotonic,
        clock=fake_time.now,
    )

    async def execute_concurrently() -> None:
        await scheduler.execute(source=source, resource=resource)
        second = asyncio.create_task(scheduler.execute(source=source, resource=resource))
        third = asyncio.create_task(scheduler.execute(source=source, resource=resource))
        await fake_time.sleep_started.wait()
        fake_time.wake_at(10.0)
        await asyncio.gather(second, third)

    asyncio.run(execute_concurrently())

    assert fetcher.started == [
        (source.source_id, 0.0),
        (source.source_id, 10.0),
        (source.source_id, 11.0),
    ]


def test_waiting_source_does_not_block_another_source() -> None:
    first_source = _source()
    other_source = _source("other-source")
    first_resource = _resource(first_source)
    other_resource = _resource(other_source)
    fake_time = _LateWakeTime()
    fetcher = _RecordingFetcher(fake_time.monotonic)
    scheduler = AcquisitionScheduler(
        fetcher=fetcher,
        sleeper=fake_time,
        monotonic=fake_time.monotonic,
        clock=fake_time.now,
    )

    async def execute_concurrently() -> None:
        await scheduler.execute(source=first_source, resource=first_resource)
        waiting = asyncio.create_task(
            scheduler.execute(source=first_source, resource=first_resource)
        )
        await fake_time.sleep_started.wait()
        other = await asyncio.wait_for(
            scheduler.execute(source=other_source, resource=other_resource),
            timeout=0.1,
        )
        assert other.status == "SUCCEEDED"
        fake_time.wake_at(10.0)
        await waiting

    asyncio.run(execute_concurrently())

    assert fetcher.started[1] == (other_source.source_id, 0.0)


def test_cancelled_wait_does_not_consume_a_future_source_slot() -> None:
    source = _source()
    resource = _resource(source)
    fake_time = _CancellableTime()
    fetcher = _RecordingFetcher(fake_time.monotonic)
    scheduler = AcquisitionScheduler(
        fetcher=fetcher,
        sleeper=fake_time,
        monotonic=fake_time.monotonic,
        clock=fake_time.now,
    )

    async def execute_with_cancellation() -> None:
        await scheduler.execute(source=source, resource=resource)
        cancelled = asyncio.create_task(scheduler.execute(source=source, resource=resource))
        await fake_time.sleep_started.wait()
        cancelled.cancel()
        with suppress(asyncio.CancelledError):
            await cancelled
        fake_time.block = False
        resumed = await scheduler.execute(source=source, resource=resource)
        assert resumed.status == "SUCCEEDED"

    asyncio.run(execute_with_cancellation())

    assert fetcher.started == [
        (source.source_id, 0.0),
        (source.source_id, 1.0),
    ]
