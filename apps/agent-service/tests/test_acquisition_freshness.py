import asyncio
import json
from datetime import UTC, datetime, timedelta, timezone

import psycopg
import pytest

from trip_agent.acquisition.cli import main
from trip_agent.acquisition.freshness import (
    FreshnessReportService,
    ResourceFreshnessState,
    render_freshness_report,
)
from trip_agent.acquisition.models import KnowledgeSource, resource_id_for
from trip_agent.acquisition.registry import SourceCatalog


class StubFreshnessRepository:
    def __init__(self, states: tuple[ResourceFreshnessState, ...]) -> None:
        self.states = states
        self.calls = 0

    async def list_resource_freshness(self) -> tuple[ResourceFreshnessState, ...]:
        self.calls += 1
        return self.states


def _source(
    source_id: str,
    domain: str,
    urls: tuple[str, ...],
    *,
    interval_hours: int = 168,
) -> KnowledgeSource:
    return KnowledgeSource(
        source_id=source_id,
        city="广州",
        source_name=f"{source_id} display name",
        reliability_level="OFFICIAL",
        allowed_domains=(domain,),
        resource_urls=urls,
        fetch_interval_hours=interval_hours,
    )


def _state(
    source_id: str,
    source_url: str,
    *,
    last_attempted_at: datetime,
    last_verified_at: datetime | None,
    last_changed_at: datetime | None,
    latest_run_status: str,
    latest_error_code: str | None = None,
    latest_error_message: str | None = None,
) -> ResourceFreshnessState:
    return ResourceFreshnessState(
        resource_id=resource_id_for(source_id, source_url),
        source_id=source_id,
        source_url=source_url,
        last_attempted_at=last_attempted_at,
        last_verified_at=last_verified_at,
        last_changed_at=last_changed_at,
        latest_run_status=latest_run_status,
        latest_error_code=latest_error_code,
        latest_error_message=latest_error_message,
    )


def test_report_distinguishes_attempt_verification_change_and_stale_reasons() -> None:
    now = datetime(2026, 7, 23, 12, tzinfo=UTC)
    urls = tuple(f"https://example.com/{name}" for name in ("missing", "never", "old", "fresh"))
    source = _source("official-a", "example.com", urls)
    states = (
        _state(
            source.source_id,
            urls[1],
            last_attempted_at=now - timedelta(hours=1),
            last_verified_at=None,
            last_changed_at=None,
            latest_run_status="FAILED",
            latest_error_code="HTTP_STATUS_ERROR",
            latest_error_message="resource returned HTTP 503",
        ),
        _state(
            source.source_id,
            urls[2],
            last_attempted_at=now - timedelta(days=8),
            last_verified_at=now - timedelta(days=8),
            last_changed_at=now - timedelta(days=30),
            latest_run_status="NOT_MODIFIED",
        ),
        _state(
            source.source_id,
            urls[3],
            last_attempted_at=now - timedelta(minutes=30),
            last_verified_at=now - timedelta(days=1),
            last_changed_at=now - timedelta(days=5),
            latest_run_status="FAILED",
            latest_error_code="TIMEOUT",
            latest_error_message="request timed out",
        ),
    )
    repository = StubFreshnessRepository(states)
    service = FreshnessReportService(repository=repository, clock=lambda: now)

    report = asyncio.run(service.generate(SourceCatalog(sources=(source,))))

    assert repository.calls == 1
    assert report.generated_at == now
    assert report.source_count == 1
    assert report.resource_count == 4
    assert report.stale_resource_count == 3
    source_report = report.sources[0]
    assert source_report.status == "STALE"
    assert source_report.fetch_interval_hours == 168
    assert [resource.source_url for resource in source_report.resources] == list(urls)
    assert [resource.stale_reason for resource in source_report.resources] == [
        "NEVER_ATTEMPTED",
        "NEVER_VERIFIED",
        "VERIFICATION_OVERDUE",
        None,
    ]
    never_verified = source_report.resources[1]
    assert never_verified.last_attempted_at == now - timedelta(hours=1)
    assert never_verified.last_verified_at is None
    assert never_verified.last_changed_at is None
    assert never_verified.latest_run_status == "FAILED"
    assert never_verified.latest_error_code == "HTTP_STATUS_ERROR"
    overdue = source_report.resources[2]
    assert overdue.verification_due_at == now - timedelta(days=1)
    assert overdue.last_changed_at == now - timedelta(days=30)
    fresh = source_report.resources[3]
    assert fresh.status == "FRESH"
    assert fresh.latest_run_status == "FAILED"
    assert fresh.latest_error_code == "TIMEOUT"


def test_report_sorts_sources_and_normalizes_generation_time_to_utc() -> None:
    source_b = _source("source-b", "example.org", ("https://example.org/b",))
    source_a = _source("source-a", "example.com", ("https://example.com/a",))
    local_time = datetime(2026, 7, 23, 20, tzinfo=timezone(timedelta(hours=8)))
    service = FreshnessReportService(
        repository=StubFreshnessRepository(()),
        clock=lambda: local_time,
    )

    report = asyncio.run(service.generate(SourceCatalog(sources=(source_b, source_a))))

    assert report.generated_at == datetime(2026, 7, 23, 12, tzinfo=UTC)
    assert [source.source_id for source in report.sources] == ["source-a", "source-b"]
    assert report.stale_resource_count == 2


def test_report_does_not_accept_mismatched_database_resource_identity() -> None:
    source_url = "https://example.com/a"
    source = _source("source-a", "example.com", (source_url,))
    now = datetime(2026, 7, 23, 12, tzinfo=UTC)
    mismatched = ResourceFreshnessState(
        resource_id="0" * 64,
        source_id=source.source_id,
        source_url=source_url,
        last_attempted_at=now,
        last_verified_at=now,
        last_changed_at=now,
        latest_run_status="FETCHED",
        latest_error_code=None,
        latest_error_message=None,
    )

    report = asyncio.run(
        FreshnessReportService(
            repository=StubFreshnessRepository((mismatched,)),
            clock=lambda: now,
        ).generate(SourceCatalog(sources=(source,)))
    )

    resource = report.sources[0].resources[0]
    assert resource.resource_id == resource_id_for(source.source_id, source_url)
    assert resource.status == "STALE"
    assert resource.stale_reason == "NEVER_ATTEMPTED"

    metadata_drift = ResourceFreshnessState(
        resource_id=resource_id_for(source.source_id, source_url),
        source_id=source.source_id,
        source_url="https://example.com/different",
        last_attempted_at=now,
        last_verified_at=now,
        last_changed_at=now,
        latest_run_status="FETCHED",
        latest_error_code=None,
        latest_error_message=None,
    )
    drift_report = asyncio.run(
        FreshnessReportService(
            repository=StubFreshnessRepository((metadata_drift, mismatched)),
            clock=lambda: now,
        ).generate(SourceCatalog(sources=(source,)))
    )
    drifted = drift_report.sources[0].resources[0]
    assert drifted.status == "STALE"
    assert drifted.stale_reason == "IDENTITY_MISMATCH"


def test_report_rejects_naive_clock_before_reading_repository() -> None:
    repository = StubFreshnessRepository(())
    service = FreshnessReportService(
        repository=repository,
        clock=lambda: datetime(2026, 7, 23, 12),
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        asyncio.run(service.generate(SourceCatalog(sources=())))

    assert repository.calls == 0


def test_render_freshness_report_is_structured_json() -> None:
    source = _source("source-a", "example.com", ("https://example.com/a",), interval_hours=24)
    now = datetime(2026, 7, 23, 12, tzinfo=UTC)
    report = asyncio.run(
        FreshnessReportService(
            repository=StubFreshnessRepository(()),
            clock=lambda: now,
        ).generate(SourceCatalog(sources=(source,)))
    )

    payload = json.loads(render_freshness_report(report))

    assert payload["generated_at"] == "2026-07-23T12:00:00Z"
    assert payload["status"] == "STALE"
    assert payload["sources"][0]["resources"][0]["stale_reason"] == "NEVER_ATTEMPTED"
    assert payload["sources"][0]["resources"][0]["resource_id"] == resource_id_for(
        "source-a", "https://example.com/a"
    )


def test_freshness_cli_is_read_only_and_returns_sanitized_database_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    (tmp_path / "source.toml").write_text(
        """
[[sources]]
source_id = "source-a"
city = "广州"
source_name = "Source A"
reliability_level = "OFFICIAL"
allowed_domains = ["example.com"]
resource_urls = ["https://example.com/a"]
""",
        encoding="utf-8",
    )

    class ReadOnlyRepository:
        def __init__(self, database_url: str) -> None:
            assert database_url == "postgresql://configured"

        async def list_resource_freshness(self):
            return ()

    monkeypatch.setenv("KNOWLEDGE_DATABASE_URL", "postgresql://configured")
    monkeypatch.setattr(
        "trip_agent.acquisition.cli.PsycopgAcquisitionRepository",
        ReadOnlyRepository,
    )

    assert main(["freshness", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["resource_count"] == 1

    class FailingRepository(ReadOnlyRepository):
        async def list_resource_freshness(self):
            raise psycopg.OperationalError("password=must-not-leak")

    monkeypatch.setattr(
        "trip_agent.acquisition.cli.PsycopgAcquisitionRepository",
        FailingRepository,
    )
    assert main(["freshness", str(tmp_path)]) == 2
    error = json.loads(capsys.readouterr().out)
    assert error == {"message": "knowledge database operation failed", "status": "error"}
    assert "must-not-leak" not in json.dumps(error)
