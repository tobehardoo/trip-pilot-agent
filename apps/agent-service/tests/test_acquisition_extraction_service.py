import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from trip_agent.acquisition import (
    ArticleExtractionPassed,
    ArticleExtractionRejected,
    ExtractedArticle,
    ExtractionPersisted,
    ExtractionQualityIssue,
    PendingSnapshot,
    SnapshotExtractionRecord,
    SnapshotExtractionService,
)


class _Repository:
    def __init__(self, snapshots: tuple[PendingSnapshot, ...]) -> None:
        self.snapshots = snapshots
        self.records: list[SnapshotExtractionRecord] = []
        self.requested_parser_version: str | None = None

    async def list_snapshots_pending_extraction(
        self,
        *,
        parser_version: str,
        limit: int,
    ) -> tuple[PendingSnapshot, ...]:
        self.requested_parser_version = parser_version
        return self.snapshots[:limit]

    async def save_extraction(self, record: SnapshotExtractionRecord) -> ExtractionPersisted:
        self.records.append(record)
        return ExtractionPersisted(
            extraction_id=record.extraction_id,
            snapshot_id=record.snapshot_id,
            status="created",
        )


class _Extractor:
    parser_version = "test-parser-v1"

    def extract(
        self,
        *,
        content: bytes,
        content_type: str | None,
        fetched_at: datetime,
    ) -> ArticleExtractionPassed | ArticleExtractionRejected:
        if content == b"reject":
            return ArticleExtractionRejected(
                status="REJECTED",
                parser_version=self.parser_version,
                issues=(
                    ExtractionQualityIssue(
                        code="CONTENT_TOO_SHORT",
                        severity="ERROR",
                        message="too short",
                    ),
                ),
            )
        return ArticleExtractionPassed(
            status="EXTRACTED",
            article=ExtractedArticle(
                title="广州正文",
                content=content.decode(),
                published_at=datetime(2026, 7, 20, tzinfo=UTC),
                content_source="广州文旅",
                parser_version=self.parser_version,
            ),
            issues=(
                ExtractionQualityIssue(
                    code="DYNAMIC_FACTS_PRESENT",
                    severity="WARNING",
                    message="verify dynamically",
                ),
            ),
        )


def _snapshot(snapshot_id: str, content: bytes) -> PendingSnapshot:
    return PendingSnapshot(
        snapshot_id=snapshot_id,
        raw_content=content,
        content_type="text/html",
        fetched_at=datetime(2026, 7, 22, tzinfo=UTC),
    )


def test_service_persists_passed_and_rejected_results_without_stopping_the_batch() -> None:
    repository = _Repository(
        (
            _snapshot("a" * 64, "稳定正文".encode()),
            _snapshot("b" * 64, b"reject"),
        )
    )
    service = SnapshotExtractionService(
        repository=repository,
        extractor=_Extractor(),
        clock=lambda: datetime(2026, 7, 22, 3, tzinfo=UTC),
    )

    processed = asyncio.run(service.process_pending(limit=10))

    assert repository.requested_parser_version == "test-parser-v1"
    assert [item.extraction_status for item in processed] == ["EXTRACTED", "REJECTED"]
    assert [item.persistence.status for item in processed] == ["created", "created"]
    passed, rejected = repository.records
    assert passed.title == "广州正文"
    assert passed.content_hash is not None
    assert passed.issues[0].code == "DYNAMIC_FACTS_PRESENT"
    assert rejected.title is None
    assert rejected.content is None
    assert rejected.content_hash is None
    assert rejected.issues[0].code == "CONTENT_TOO_SHORT"
    assert passed.extracted_at == datetime(2026, 7, 22, 3, tzinfo=UTC)


def test_extraction_record_is_deterministic_for_the_same_result() -> None:
    snapshot = _snapshot("a" * 64, b"body")
    extractor = _Extractor()
    result = extractor.extract(
        content=snapshot.raw_content,
        content_type=snapshot.content_type,
        fetched_at=snapshot.fetched_at,
    )
    service = SnapshotExtractionService(
        repository=_Repository(()),
        extractor=extractor,
        clock=lambda: datetime(2026, 7, 22, tzinfo=UTC),
    )

    first = service.build_record(snapshot=snapshot, result=result)
    second = service.build_record(snapshot=snapshot, result=result)

    assert first.extraction_id == second.extraction_id
    assert first.result_fingerprint == second.result_fingerprint
    assert first.content_hash == second.content_hash


def test_service_rejects_error_issues_labeled_as_extracted() -> None:
    snapshot = _snapshot("a" * 64, b"body")
    result = ArticleExtractionPassed(
        status="EXTRACTED",
        article=ExtractedArticle(
            title="title",
            content="content",
            published_at=None,
            content_source=None,
            parser_version="test-parser-v1",
        ),
        issues=(
            ExtractionQualityIssue(
                code="CONTENT_TOO_SHORT",
                severity="ERROR",
                message="invalid",
            ),
        ),
    )
    service = SnapshotExtractionService(repository=_Repository(()), extractor=_Extractor())

    with pytest.raises(ValueError, match="cannot contain ERROR"):
        service.build_record(snapshot=snapshot, result=result)


def test_service_rejects_rejection_without_an_error_issue() -> None:
    snapshot = _snapshot("a" * 64, b"body")
    result = ArticleExtractionRejected(
        status="REJECTED",
        parser_version="test-parser-v1",
        issues=(
            ExtractionQualityIssue(
                code="PUBLISHED_AT_MISSING",
                severity="WARNING",
                message="warning only",
            ),
        ),
    )
    service = SnapshotExtractionService(repository=_Repository(()), extractor=_Extractor())

    with pytest.raises(ValueError, match="requires an ERROR"):
        service.build_record(snapshot=snapshot, result=result)


def test_service_canonicalizes_equivalent_publication_times_for_fingerprinting() -> None:
    snapshot = _snapshot("a" * 64, b"body")
    service = SnapshotExtractionService(repository=_Repository(()), extractor=_Extractor())
    base = _Extractor().extract(
        content=snapshot.raw_content,
        content_type=snapshot.content_type,
        fetched_at=snapshot.fetched_at,
    )
    assert base.status == "EXTRACTED"
    china_time = datetime(2026, 7, 20, 8, tzinfo=timezone(timedelta(hours=8)))
    utc_result = replace(
        base,
        article=replace(base.article, published_at=datetime(2026, 7, 20, tzinfo=UTC)),
    )
    china_result = replace(base, article=replace(base.article, published_at=china_time))

    utc_record = service.build_record(snapshot=snapshot, result=utc_result)
    china_record = service.build_record(snapshot=snapshot, result=china_result)

    assert utc_record.published_at == china_record.published_at
    assert utc_record.result_fingerprint == china_record.result_fingerprint


def test_service_rejects_naive_publication_time() -> None:
    snapshot = _snapshot("a" * 64, b"body")
    service = SnapshotExtractionService(repository=_Repository(()), extractor=_Extractor())
    base = _Extractor().extract(
        content=snapshot.raw_content,
        content_type=snapshot.content_type,
        fetched_at=snapshot.fetched_at,
    )
    assert base.status == "EXTRACTED"
    naive = replace(base, article=replace(base.article, published_at=datetime(2026, 7, 20)))

    with pytest.raises(ValueError, match="published_at must be timezone-aware"):
        service.build_record(snapshot=snapshot, result=naive)


@pytest.mark.parametrize("limit", [0, 101, True])
def test_service_rejects_invalid_batch_limits(limit: int) -> None:
    service = SnapshotExtractionService(
        repository=_Repository(()),
        extractor=_Extractor(),
    )

    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        asyncio.run(service.process_pending(limit=limit))
