import asyncio
import hashlib
import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from trip_agent.acquisition import (
    AcquisitionExecutionRecorder,
    ExtractionVersionConflict,
    FetchAttemptFailed,
    FetchAttemptSucceeded,
    FetchExecutionFailed,
    FetchExecutionSucceeded,
    FetchValidators,
    GuangzhouGovernmentArticleExtractor,
    PsycopgAcquisitionRepository,
    ResourceFetched,
    ResourceNotModified,
    SnapshotExtractionService,
)
from trip_agent.acquisition.models import DiscoveredResource, KnowledgeSource


def database_url() -> str:
    value = os.environ.get("KNOWLEDGE_TEST_DATABASE_URL", "").strip()
    if not value:
        pytest.skip("KNOWLEDGE_TEST_DATABASE_URL is not configured")
    return value


@pytest.fixture(autouse=True)
def reset_acquisition_tables() -> Iterator[None]:
    url = database_url()
    asyncio.run(PsycopgAcquisitionRepository(url).migrate())
    with psycopg.connect(url) as connection:
        connection.execute(
            "TRUNCATE agent.knowledge_fetch_run, agent.knowledge_snapshot, "
            "agent.knowledge_resource RESTART IDENTITY CASCADE"
        )
    yield


def _source() -> KnowledgeSource:
    return KnowledgeSource(
        source_id="guangzhou-official",
        city="广州",
        source_name="广州文旅",
        reliability_level="OFFICIAL",
        allowed_domains=("wglj.gz.gov.cn",),
        resource_urls=("https://wglj.gz.gov.cn/visit/article.html",),
        max_response_bytes=64 * 1024,
    )


def _resource() -> DiscoveredResource:
    source = _source()
    return DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )


def _success(at: datetime) -> FetchAttemptSucceeded:
    return FetchAttemptSucceeded(
        status="SUCCEEDED",
        attempt_number=1,
        started_at=at,
        completed_at=at + timedelta(seconds=1),
    )


def _recorder(run_ids: Iterator[str]) -> AcquisitionExecutionRecorder:
    return AcquisitionExecutionRecorder(
        repository=PsycopgAcquisitionRepository(database_url()),
        run_id_factory=lambda: next(run_ids),
    )


def test_migration_creates_acquisition_tables() -> None:
    with psycopg.connect(database_url()) as connection:
        row = connection.execute(
            """
            SELECT
                to_regclass('agent.knowledge_resource') AS resource_table,
                to_regclass('agent.knowledge_snapshot') AS snapshot_table,
                to_regclass('agent.knowledge_fetch_run') AS run_table
            """
        ).fetchone()

    assert row == (
        "agent.knowledge_resource",
        "agent.knowledge_snapshot",
        "agent.knowledge_fetch_run",
    )


def test_fetched_content_is_idempotent_but_each_execution_has_a_run() -> None:
    source = _source()
    resource = _resource()
    fetched_at = datetime(2026, 7, 22, 1, tzinfo=UTC)
    execution = FetchExecutionSucceeded(
        status="SUCCEEDED",
        result=ResourceFetched(
            status="FETCHED",
            requested_url=resource.url,
            final_url=resource.url,
            fetched_at=fetched_at,
            content=b"official candidate",
            content_type="text/html",
            validators=FetchValidators(etag='"revision-1"'),
        ),
        attempts=(_success(fetched_at),),
    )
    recorder = _recorder(iter(("run-first", "run-second")))

    first = asyncio.run(
        recorder.record(
            source=source,
            resource=resource,
            execution=execution,
            parser_version="raw-http-v1",
        )
    )
    second = asyncio.run(
        recorder.record(
            source=source,
            resource=resource,
            execution=execution,
            parser_version="raw-http-v1",
        )
    )

    with psycopg.connect(database_url()) as connection:
        resource_row = connection.execute(
            "SELECT source_id, last_verified_at, etag FROM agent.knowledge_resource"
        ).fetchone()
        snapshot_row = connection.execute(
            """
            SELECT review_status, parser_version, raw_content, content_hash
            FROM agent.knowledge_snapshot
            """
        ).fetchone()
        counts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM agent.knowledge_snapshot),
                (SELECT COUNT(*) FROM agent.knowledge_fetch_run)
            """
        ).fetchone()

    assert first.snapshot_created is True
    assert second.snapshot_created is False
    assert second.snapshot_id == first.snapshot_id
    assert resource_row == (source.source_id, fetched_at, '"revision-1"')
    assert snapshot_row[0:3] == ("PENDING", "raw-http-v1", b"official candidate")
    assert len(snapshot_row[3]) == 64
    assert counts == (1, 2)


def test_not_modified_updates_verification_without_creating_a_snapshot() -> None:
    source = _source()
    resource = _resource()
    first_at = datetime(2026, 7, 22, 1, tzinfo=UTC)
    verified_at = datetime(2026, 7, 22, 2, tzinfo=UTC)
    recorder = _recorder(iter(("run-fetched", "run-304")))
    fetched = FetchExecutionSucceeded(
        status="SUCCEEDED",
        result=ResourceFetched(
            status="FETCHED",
            requested_url=resource.url,
            final_url=resource.url,
            fetched_at=first_at,
            content=b"official candidate",
            content_type="text/html",
            validators=FetchValidators(etag='"revision-1"'),
        ),
        attempts=(_success(first_at),),
    )
    not_modified = FetchExecutionSucceeded(
        status="SUCCEEDED",
        result=ResourceNotModified(
            status="NOT_MODIFIED",
            requested_url=resource.url,
            final_url=resource.url,
            fetched_at=verified_at,
            validators=FetchValidators(etag='"revision-2"'),
        ),
        attempts=(_success(verified_at),),
    )

    asyncio.run(
        recorder.record(
            source=source,
            resource=resource,
            execution=fetched,
            parser_version="raw-http-v1",
        )
    )
    result = asyncio.run(
        recorder.record(
            source=source,
            resource=resource,
            execution=not_modified,
            parser_version="raw-http-v1",
            base_content_hash=hashlib.sha256(b"official candidate").hexdigest(),
        )
    )

    with psycopg.connect(database_url()) as connection:
        resource_row = connection.execute(
            """
            SELECT last_verified_at, last_changed_at, etag
            FROM agent.knowledge_resource
            """
        ).fetchone()
        run_row = connection.execute(
            """
            SELECT status, snapshot_id, attempt_count
            FROM agent.knowledge_fetch_run WHERE run_id = 'run-304'
            """
        ).fetchone()
        snapshot_count = connection.execute(
            "SELECT COUNT(*) FROM agent.knowledge_snapshot"
        ).fetchone()[0]

    assert result.snapshot_id is None
    assert resource_row == (verified_at, first_at, '"revision-2"')
    assert run_row == ("NOT_MODIFIED", None, 1)
    assert snapshot_count == 1


def test_failure_records_error_without_marking_resource_verified() -> None:
    source = _source()
    resource = _resource()
    started_at = datetime(2026, 7, 22, 1, tzinfo=UTC)
    failure = FetchAttemptFailed(
        status="FAILED",
        attempt_number=1,
        started_at=started_at,
        completed_at=started_at + timedelta(seconds=1),
        error_code="HTTP_STATUS_ERROR",
        message="resource returned HTTP 404",
        retryable=False,
        status_code=404,
    )
    execution = FetchExecutionFailed(
        status="FAILED",
        failure=failure,
        attempts=(failure,),
    )

    asyncio.run(
        _recorder(iter(("run-failed",))).record(
            source=source,
            resource=resource,
            execution=execution,
            parser_version="raw-http-v1",
        )
    )

    with psycopg.connect(database_url()) as connection:
        resource_row = connection.execute(
            """
            SELECT last_attempted_at, last_verified_at, last_changed_at
            FROM agent.knowledge_resource
            """
        ).fetchone()
        run_row = connection.execute(
            """
            SELECT status, error_code, error_message, retryable, http_status, attempts
            FROM agent.knowledge_fetch_run
            """
        ).fetchone()
        snapshot_count = connection.execute(
            "SELECT COUNT(*) FROM agent.knowledge_snapshot"
        ).fetchone()[0]

    assert resource_row == (failure.completed_at, None, None)
    assert run_row[0:5] == (
        "FAILED",
        "HTTP_STATUS_ERROR",
        "resource returned HTTP 404",
        False,
        404,
    )
    assert run_row[5][0]["error_code"] == "HTTP_STATUS_ERROR"
    assert snapshot_count == 0


def test_older_completion_cannot_replace_newer_resource_verification() -> None:
    source = _source()
    resource = _resource()
    older_at = datetime(2026, 7, 22, 1, tzinfo=UTC)
    newer_at = datetime(2026, 7, 22, 2, tzinfo=UTC)
    recorder = _recorder(iter(("run-newer", "run-older")))
    newer = FetchExecutionSucceeded(
        status="SUCCEEDED",
        result=ResourceFetched(
            status="FETCHED",
            requested_url=resource.url,
            final_url="https://wglj.gz.gov.cn/visit/current.html",
            fetched_at=newer_at,
            content=b"newer completion",
            content_type="text/html",
            validators=FetchValidators(etag='"newer"'),
        ),
        attempts=(_success(newer_at),),
    )
    older = FetchExecutionSucceeded(
        status="SUCCEEDED",
        result=ResourceFetched(
            status="FETCHED",
            requested_url=resource.url,
            final_url="https://wglj.gz.gov.cn/visit/old.html",
            fetched_at=older_at,
            content=b"older completion",
            content_type="text/html",
            validators=FetchValidators(etag='"older"'),
        ),
        attempts=(_success(older_at),),
    )

    asyncio.run(
        recorder.record(
            source=source,
            resource=resource,
            execution=newer,
            parser_version="raw-http-v1",
        )
    )
    asyncio.run(
        recorder.record(
            source=source,
            resource=resource,
            execution=older,
            parser_version="raw-http-v1",
        )
    )

    with psycopg.connect(database_url()) as connection:
        row = connection.execute(
            """
            SELECT final_url, etag, current_content_hash,
                last_attempted_at, last_verified_at, last_changed_at
            FROM agent.knowledge_resource
            """
        ).fetchone()

    assert row == (
        "https://wglj.gz.gov.cn/visit/current.html",
        '"newer"',
        hashlib.sha256(b"newer completion").hexdigest(),
        newer_at + timedelta(seconds=1),
        newer_at,
        newer_at,
    )


def test_parser_upgrade_creates_a_candidate_without_reporting_content_change() -> None:
    source = _source()
    resource = _resource()
    first_at = datetime(2026, 7, 22, 1, tzinfo=UTC)
    second_at = datetime(2026, 7, 22, 2, tzinfo=UTC)
    recorder = _recorder(iter(("run-parser-v1", "run-parser-v2")))

    def execution(at: datetime) -> FetchExecutionSucceeded:
        return FetchExecutionSucceeded(
            status="SUCCEEDED",
            result=ResourceFetched(
                status="FETCHED",
                requested_url=resource.url,
                final_url=resource.url,
                fetched_at=at,
                content=b"same official body",
                content_type="text/html",
                validators=FetchValidators(etag='"same"'),
            ),
            attempts=(_success(at),),
        )

    first = asyncio.run(
        recorder.record(
            source=source,
            resource=resource,
            execution=execution(first_at),
            parser_version="raw-http-v1",
        )
    )
    second = asyncio.run(
        recorder.record(
            source=source,
            resource=resource,
            execution=execution(second_at),
            parser_version="raw-http-v2",
        )
    )

    with psycopg.connect(database_url()) as connection:
        snapshot_count = connection.execute(
            "SELECT COUNT(*) FROM agent.knowledge_snapshot"
        ).fetchone()[0]
        last_changed_at = connection.execute(
            "SELECT last_changed_at FROM agent.knowledge_resource"
        ).fetchone()[0]

    assert first.snapshot_created is True
    assert second.snapshot_created is True
    assert first.snapshot_id != second.snapshot_id
    assert snapshot_count == 2
    assert last_changed_at == first_at


def test_content_reversion_updates_last_changed_while_reusing_snapshot() -> None:
    source = _source()
    resource = _resource()
    times = tuple(datetime(2026, 7, 22, hour, tzinfo=UTC) for hour in (1, 2, 3))
    recorder = _recorder(iter(("run-a1", "run-b", "run-a2")))

    def execution(at: datetime, content: bytes) -> FetchExecutionSucceeded:
        return FetchExecutionSucceeded(
            status="SUCCEEDED",
            result=ResourceFetched(
                status="FETCHED",
                requested_url=resource.url,
                final_url=resource.url,
                fetched_at=at,
                content=content,
                content_type="text/html",
                validators=FetchValidators(etag=f'"{content.decode()}"'),
            ),
            attempts=(_success(at),),
        )

    results = [
        asyncio.run(
            recorder.record(
                source=source,
                resource=resource,
                execution=execution(at, content),
                parser_version="raw-http-v1",
            )
        )
        for at, content in zip(times, (b"A", b"B", b"A"), strict=True)
    ]

    with psycopg.connect(database_url()) as connection:
        row = connection.execute(
            """
            SELECT current_content_hash, last_changed_at, last_verified_at
            FROM agent.knowledge_resource
            """
        ).fetchone()
        snapshot_count = connection.execute(
            "SELECT COUNT(*) FROM agent.knowledge_snapshot"
        ).fetchone()[0]

    assert [result.snapshot_created for result in results] == [True, True, False]
    assert row[0] == hashlib.sha256(b"A").hexdigest()
    assert row[1:] == (times[2], times[2])
    assert snapshot_count == 2


def test_concurrent_results_keep_the_newest_verified_resource_state() -> None:
    source = _source()
    resource = _resource()
    older_at = datetime(2026, 7, 22, 1, tzinfo=UTC)
    newer_at = datetime(2026, 7, 22, 2, tzinfo=UTC)

    def execution(at: datetime, content: bytes) -> FetchExecutionSucceeded:
        return FetchExecutionSucceeded(
            status="SUCCEEDED",
            result=ResourceFetched(
                status="FETCHED",
                requested_url=resource.url,
                final_url=resource.url,
                fetched_at=at,
                content=content,
                content_type="text/html",
                validators=FetchValidators(etag=f'"{content.decode()}"'),
            ),
            attempts=(_success(at),),
        )

    async def persist_concurrently() -> None:
        older = AcquisitionExecutionRecorder(
            repository=PsycopgAcquisitionRepository(database_url()),
            run_id_factory=lambda: "run-concurrent-older",
        )
        newer = AcquisitionExecutionRecorder(
            repository=PsycopgAcquisitionRepository(database_url()),
            run_id_factory=lambda: "run-concurrent-newer",
        )
        await asyncio.gather(
            older.record(
                source=source,
                resource=resource,
                execution=execution(older_at, b"older"),
                parser_version="raw-http-v1",
            ),
            newer.record(
                source=source,
                resource=resource,
                execution=execution(newer_at, b"newer"),
                parser_version="raw-http-v1",
            ),
        )

    asyncio.run(persist_concurrently())

    with psycopg.connect(database_url()) as connection:
        row = connection.execute(
            """
            SELECT current_content_hash, etag, last_verified_at, last_changed_at
            FROM agent.knowledge_resource
            """
        ).fetchone()

    assert row == (
        hashlib.sha256(b"newer").hexdigest(),
        '"newer"',
        newer_at,
        newer_at,
    )


def test_run_insert_failure_rolls_back_resource_and_snapshot_changes() -> None:
    source = _source()
    resource = _resource()
    first_at = datetime(2026, 7, 22, 1, tzinfo=UTC)
    second_at = datetime(2026, 7, 22, 2, tzinfo=UTC)
    recorder = _recorder(iter(("duplicate-run", "duplicate-run")))

    def execution(at: datetime, content: bytes) -> FetchExecutionSucceeded:
        return FetchExecutionSucceeded(
            status="SUCCEEDED",
            result=ResourceFetched(
                status="FETCHED",
                requested_url=resource.url,
                final_url=resource.url,
                fetched_at=at,
                content=content,
                content_type="text/html",
                validators=FetchValidators(etag=f'"{content.decode()}"'),
            ),
            attempts=(_success(at),),
        )

    asyncio.run(
        recorder.record(
            source=source,
            resource=resource,
            execution=execution(first_at, b"first"),
            parser_version="raw-http-v1",
        )
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        asyncio.run(
            recorder.record(
                source=source,
                resource=resource,
                execution=execution(second_at, b"second"),
                parser_version="raw-http-v1",
            )
        )

    with psycopg.connect(database_url()) as connection:
        row = connection.execute(
            """
            SELECT current_content_hash, etag, last_verified_at, last_changed_at
            FROM agent.knowledge_resource
            """
        ).fetchone()
        snapshot_count = connection.execute(
            "SELECT COUNT(*) FROM agent.knowledge_snapshot"
        ).fetchone()[0]

    assert row == (
        hashlib.sha256(b"first").hexdigest(),
        '"first"',
        first_at,
        first_at,
    )
    assert snapshot_count == 1


def test_repository_returns_versioned_conditional_request_state() -> None:
    source = _source()
    resource = _resource()
    at = datetime(2026, 7, 22, 1, tzinfo=UTC)
    recorder = _recorder(iter(("run-validators",)))
    asyncio.run(
        recorder.record(
            source=source,
            resource=resource,
            execution=FetchExecutionSucceeded(
                status="SUCCEEDED",
                result=ResourceFetched(
                    status="FETCHED",
                    requested_url=resource.url,
                    final_url=resource.url,
                    fetched_at=at,
                    content=b"candidate",
                    content_type="text/html",
                    validators=FetchValidators(
                        etag='"current"',
                        last_modified="Wed, 22 Jul 2026 01:00:00 GMT",
                    ),
                ),
                attempts=(_success(at),),
            ),
            parser_version="raw-http-v1",
        )
    )

    state = asyncio.run(
        PsycopgAcquisitionRepository(database_url()).get_conditional_state(
            hashlib.sha256(f"{source.source_id}\0{resource.url}".encode()).hexdigest()
        )
    )

    assert state is not None
    assert state.validators == FetchValidators(
        etag='"current"',
        last_modified="Wed, 22 Jul 2026 01:00:00 GMT",
    )
    assert state.content_hash == hashlib.sha256(b"candidate").hexdigest()


def test_concurrent_fetched_and_stale_edge_304_keep_validators_and_hash_coherent() -> None:
    source = _source()
    resource = _resource()
    baseline_at = datetime(2026, 7, 22, 1, tzinfo=UTC)
    fetched_at = datetime(2026, 7, 22, 2, tzinfo=UTC)
    not_modified_at = datetime(2026, 7, 22, 3, tzinfo=UTC)
    baseline_hash = hashlib.sha256(b"A").hexdigest()
    baseline = _recorder(iter(("run-baseline",)))
    asyncio.run(
        baseline.record(
            source=source,
            resource=resource,
            execution=FetchExecutionSucceeded(
                status="SUCCEEDED",
                result=ResourceFetched(
                    status="FETCHED",
                    requested_url=resource.url,
                    final_url=resource.url,
                    fetched_at=baseline_at,
                    content=b"A",
                    content_type="text/html",
                    validators=FetchValidators(etag='"A"'),
                ),
                attempts=(_success(baseline_at),),
            ),
            parser_version="raw-http-v1",
        )
    )

    async def persist_concurrently() -> None:
        fetched = AcquisitionExecutionRecorder(
            repository=PsycopgAcquisitionRepository(database_url()),
            run_id_factory=lambda: "run-fetched-b",
        )
        stale_edge_304 = AcquisitionExecutionRecorder(
            repository=PsycopgAcquisitionRepository(database_url()),
            run_id_factory=lambda: "run-stale-edge-304-a",
        )
        await asyncio.gather(
            fetched.record(
                source=source,
                resource=resource,
                execution=FetchExecutionSucceeded(
                    status="SUCCEEDED",
                    result=ResourceFetched(
                        status="FETCHED",
                        requested_url=resource.url,
                        final_url=resource.url,
                        fetched_at=fetched_at,
                        content=b"B",
                        content_type="text/html",
                        validators=FetchValidators(etag='"B"'),
                    ),
                    attempts=(_success(fetched_at),),
                ),
                parser_version="raw-http-v1",
            ),
            stale_edge_304.record(
                source=source,
                resource=resource,
                execution=FetchExecutionSucceeded(
                    status="SUCCEEDED",
                    result=ResourceNotModified(
                        status="NOT_MODIFIED",
                        requested_url=resource.url,
                        final_url=resource.url,
                        fetched_at=not_modified_at,
                        validators=FetchValidators(etag='"A"'),
                    ),
                    attempts=(_success(not_modified_at),),
                ),
                parser_version="raw-http-v1",
                base_content_hash=baseline_hash,
            ),
        )

    asyncio.run(persist_concurrently())

    with psycopg.connect(database_url()) as connection:
        row = connection.execute(
            """
            SELECT current_content_hash, etag, last_verified_at, last_changed_at
            FROM agent.knowledge_resource
            """
        ).fetchone()

    assert row == (baseline_hash, '"A"', not_modified_at, not_modified_at)


def test_concurrent_migration_is_serialized() -> None:
    with psycopg.connect(database_url()) as connection:
        connection.execute(
            """
            DROP TABLE agent.knowledge_extraction, agent.knowledge_fetch_run,
                agent.knowledge_snapshot, agent.knowledge_resource,
                agent.acquisition_schema_migration
            """
        )

    async def migrate_twice() -> None:
        await asyncio.gather(
            PsycopgAcquisitionRepository(database_url()).migrate(),
            PsycopgAcquisitionRepository(database_url()).migrate(),
        )

    asyncio.run(migrate_twice())

    with psycopg.connect(database_url()) as connection:
        versions = connection.execute(
            "SELECT version FROM agent.acquisition_schema_migration"
        ).fetchall()

    assert versions == [("V1",), ("V2",)]


def test_extraction_service_persists_result_and_removes_snapshot_from_pending() -> None:
    source = _source()
    resource = _resource()
    at = datetime(2026, 7, 22, 1, tzinfo=UTC)
    html = (
        '<html><head><meta name="ArticleTitle" content="广州文化">'
        '<meta name="PubDate" content="2026-07-20"></head>'
        "<body><main><p>广州历史街区连接传统工艺与城市生活，资料介绍保护范围、"
        "文化价值和步行观察方式，为主题行程提供稳定的背景信息。沿途建筑、园林与"
        "街巷共同呈现城市历史脉络，也适合用于文化主题的行程说明。</p></main></body></html>"
    ).encode()
    recorder = _recorder(iter(("run-extraction",)))
    persisted = asyncio.run(
        recorder.record(
            source=source,
            resource=resource,
            execution=FetchExecutionSucceeded(
                status="SUCCEEDED",
                result=ResourceFetched(
                    status="FETCHED",
                    requested_url=resource.url,
                    final_url=resource.url,
                    fetched_at=at,
                    content=html,
                    content_type="text/html; charset=utf-8",
                    validators=FetchValidators(etag='"extract"'),
                ),
                attempts=(_success(at),),
            ),
            parser_version="raw-http-v1",
        )
    )
    repository = PsycopgAcquisitionRepository(database_url())
    service = SnapshotExtractionService(
        repository=repository,
        clock=lambda: datetime(2026, 7, 22, 2, tzinfo=UTC),
    )

    pending = asyncio.run(
        repository.list_snapshots_pending_extraction(
            parser_version=service.parser_version,
            limit=10,
        )
    )
    processed = asyncio.run(service.process_pending(limit=10))
    repeated = asyncio.run(service.process_pending(limit=10))

    with psycopg.connect(database_url()) as connection:
        row = connection.execute(
            """
            SELECT snapshot_id, parser_version, status, title, content_hash,
                result_fingerprint, quality_issues
            FROM agent.knowledge_extraction
            """
        ).fetchone()

    assert [item.snapshot_id for item in pending] == [persisted.snapshot_id]
    assert len(processed) == 1
    assert processed[0].extraction_status == "EXTRACTED"
    assert repeated == ()
    assert row[0:4] == (
        persisted.snapshot_id,
        service.parser_version,
        "EXTRACTED",
        "广州文化",
    )
    assert len(row[4]) == len(row[5]) == 64
    assert row[6] == []

    extraction_result = GuangzhouGovernmentArticleExtractor().extract(
        content=pending[0].raw_content,
        content_type=pending[0].content_type,
        fetched_at=pending[0].fetched_at,
    )
    record = service.build_record(snapshot=pending[0], result=extraction_result)
    unchanged = asyncio.run(repository.save_extraction(record))
    assert extraction_result.status == "EXTRACTED"
    changed_result = replace(
        extraction_result,
        article=replace(
            extraction_result.article,
            content=extraction_result.article.content + "变更",
        ),
    )
    conflicting_record = service.build_record(snapshot=pending[0], result=changed_result)
    with pytest.raises(ExtractionVersionConflict):
        asyncio.run(repository.save_extraction(conflicting_record))
    next_parser_pending = asyncio.run(
        repository.list_snapshots_pending_extraction(
            parser_version="gz-government-bs4-v2",
            limit=10,
        )
    )

    assert unchanged.status == "unchanged"
    assert [item.snapshot_id for item in next_parser_pending] == [persisted.snapshot_id]
