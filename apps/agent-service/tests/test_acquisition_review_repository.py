import asyncio
import hashlib
import os
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import psycopg
import pytest

from trip_agent.acquisition import PsycopgAcquisitionRepository
from trip_agent.acquisition.review import (
    KnowledgeReviewPublisher,
    KnowledgeReviewService,
    PublicationClaim,
    PublicationNotAvailable,
    ReviewApprovalRequest,
    ReviewPersistence,
    ReviewRejectionRequest,
    ReviewStateConflict,
    ReviewWithdrawalRequest,
)
from trip_agent.retrieval.documents import KnowledgeDocument
from trip_agent.retrieval.service import KnowledgeImportResult


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


class RecordingImporter:
    def __init__(self, *, failures: int = 0) -> None:
        self.documents: list[KnowledgeDocument] = []
        self.failures = failures

    async def import_document(self, document: KnowledgeDocument) -> KnowledgeImportResult:
        self.documents.append(document)
        if len(self.documents) <= self.failures:
            raise RuntimeError("embedding unavailable")
        return KnowledgeImportResult(
            document_id=document.document_id,
            version=document.version,
            chunk_count=2,
            status="created",
        )


def _id(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _seed_extraction(
    *,
    label: str = "first",
    resource_id: str | None = None,
    extraction_status: str = "EXTRACTED",
) -> tuple[str, str, str]:
    resource_id = resource_id or _id("resource")
    snapshot_id = _id(f"snapshot-{label}")
    extraction_id = _id(f"extraction-{label}")
    fetched_at = datetime(2026, 7, 22, 1, tzinfo=UTC) + timedelta(hours=len(label))
    content = f"广州官方正文 {label}"
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    if extraction_status == "EXTRACTED":
        article_values = (
            f"广州资料 {label}",
            content,
            content_hash,
            datetime(2026, 7, 20, 16, tzinfo=UTC),
            "广州市人民政府文旅资料",
            "[]",
        )
    else:
        article_values = (
            None,
            None,
            None,
            None,
            None,
            '[{"code":"BODY_TOO_SHORT","severity":"ERROR","message":"too short"}]',
        )
    with psycopg.connect(database_url()) as connection:
        connection.execute(
            """
            INSERT INTO agent.knowledge_resource (
                resource_id, source_id, source_name, reliability_level, city,
                source_url, final_url, last_attempted_at, last_verified_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (resource_id) DO NOTHING
            """,
            (
                resource_id,
                "guangzhou-government-tourism",
                "广州市人民政府文旅资料",
                "OFFICIAL",
                "广州",
                "https://www.gz.gov.cn/article.html",
                "https://www.gz.gov.cn/article.html",
                fetched_at,
                fetched_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO agent.knowledge_snapshot (
                snapshot_id, resource_id, source_url, final_url, fetched_at,
                content_hash, raw_content, content_type, parser_version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                snapshot_id,
                resource_id,
                "https://www.gz.gov.cn/article.html",
                "https://www.gz.gov.cn/article.html",
                fetched_at,
                _id(f"raw-{label}"),
                f"<main>{content}</main>".encode(),
                "text/html; charset=utf-8",
                "raw-http-v1",
            ),
        )
        connection.execute(
            """
            INSERT INTO agent.knowledge_extraction (
                extraction_id, snapshot_id, parser_version, status, title, content,
                content_hash, published_at, content_source, quality_issues,
                result_fingerprint, extracted_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            """,
            (
                extraction_id,
                snapshot_id,
                "gz-government-bs4-v1",
                extraction_status,
                *article_values,
                _id(f"fingerprint-{label}"),
                fetched_at + timedelta(minutes=1),
            ),
        )
    return resource_id, snapshot_id, extraction_id


def _approval(extraction_id: str, *, note: str = "verified") -> ReviewApprovalRequest:
    return ReviewApprovalRequest(
        extraction_id=extraction_id,
        reviewer_id="reviewer-1",
        note=note,
        category="culture",
        valid_from=date(2026, 7, 1),
        applicable_seasons=("all",),
        traveler_types=("FAMILY",),
    )


def test_v3_migration_creates_review_tables_and_resource_source_metadata() -> None:
    with psycopg.connect(database_url()) as connection:
        row = connection.execute(
            """
            SELECT
                to_regclass('agent.knowledge_review_action'),
                to_regclass('agent.knowledge_publication'),
                EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'agent'
                      AND table_name = 'knowledge_resource'
                      AND column_name = 'source_name'
                ),
                (
                    SELECT is_nullable FROM information_schema.columns
                    WHERE table_schema = 'agent'
                      AND table_name = 'knowledge_resource'
                      AND column_name = 'reliability_level'
                ),
                (
                    SELECT column_default FROM information_schema.columns
                    WHERE table_schema = 'agent'
                      AND table_name = 'knowledge_resource'
                      AND column_name = 'reliability_level'
                )
            """
        ).fetchone()
        versions = connection.execute(
            "SELECT version FROM agent.acquisition_schema_migration ORDER BY version"
        ).fetchall()

    assert row == (
        "agent.knowledge_review_action",
        "agent.knowledge_publication",
        True,
        "YES",
        None,
    )
    assert versions == [("V1",), ("V2",), ("V3",)]


def test_v3_upgrade_does_not_invent_historical_source_identity_or_trust() -> None:
    resource_id = _id("historical-resource")
    attempted_at = datetime(2026, 7, 20, 1, tzinfo=UTC)
    with psycopg.connect(database_url()) as connection:
        connection.execute("DROP TABLE agent.knowledge_publication")
        connection.execute("DROP TABLE agent.knowledge_review_action")
        connection.execute(
            """
            ALTER TABLE agent.knowledge_snapshot
                DROP CONSTRAINT knowledge_snapshot_review_status_check,
                ADD CONSTRAINT knowledge_snapshot_review_status_check
                    CHECK (review_status = 'PENDING')
            """
        )
        connection.execute(
            """
            ALTER TABLE agent.knowledge_resource
                DROP COLUMN source_name,
                DROP COLUMN reliability_level
            """
        )
        connection.execute(
            "DELETE FROM agent.acquisition_schema_migration WHERE version = 'V3'"
        )
        connection.execute(
            """
            INSERT INTO agent.knowledge_resource (
                resource_id, source_id, city, source_url, final_url, last_attempted_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                resource_id,
                "legacy-curated-source",
                "广州",
                "https://example.com/legacy",
                "https://example.com/legacy",
                attempted_at,
            ),
        )

    asyncio.run(PsycopgAcquisitionRepository(database_url()).migrate())

    with psycopg.connect(database_url()) as connection:
        metadata = connection.execute(
            """
            SELECT source_name, reliability_level
            FROM agent.knowledge_resource WHERE resource_id = %s
            """,
            (resource_id,),
        ).fetchone()
    assert metadata == (None, None)


def test_approval_is_audited_idempotent_and_creates_pending_publication() -> None:
    _, snapshot_id, extraction_id = _seed_extraction()
    reviewed_at = datetime(2026, 7, 23, 1, tzinfo=UTC)
    service = KnowledgeReviewService(
        repository=PsycopgAcquisitionRepository(database_url()),
        clock=lambda: reviewed_at,
    )

    first = asyncio.run(service.approve(_approval(extraction_id)))
    second = asyncio.run(service.approve(_approval(extraction_id)))

    with psycopg.connect(database_url()) as connection:
        action = connection.execute(
            """
            SELECT action, reviewer_id, note, reviewed_at, category,
                valid_from, applicable_seasons, traveler_types,
                document_id, document_version
            FROM agent.knowledge_review_action
            """
        ).fetchone()
        publication = connection.execute(
            "SELECT status, attempt_count FROM agent.knowledge_publication"
        ).fetchone()
        status = connection.execute(
            "SELECT review_status FROM agent.knowledge_snapshot WHERE snapshot_id = %s",
            (snapshot_id,),
        ).fetchone()[0]

    assert first.persistence_status == "created"
    assert second.persistence_status == "unchanged"
    assert second.action_id == first.action_id
    assert action == (
        "APPROVE",
        "reviewer-1",
        "verified",
        reviewed_at,
        "culture",
        date(2026, 7, 1),
        ["all"],
        ["FAMILY"],
        first.document_id,
        1,
    )
    assert publication == ("PENDING", 0)
    assert status == "APPROVED"


def test_only_extracted_candidates_can_be_reviewed() -> None:
    _, snapshot_id, extraction_id = _seed_extraction(extraction_status="REJECTED")
    service = KnowledgeReviewService(
        repository=PsycopgAcquisitionRepository(database_url()),
        clock=lambda: datetime(2026, 7, 23, 1, tzinfo=UTC),
    )

    with pytest.raises(ReviewStateConflict, match="not eligible"):
        asyncio.run(service.approve(_approval(extraction_id)))

    with psycopg.connect(database_url()) as connection:
        status = connection.execute(
            "SELECT review_status FROM agent.knowledge_snapshot WHERE snapshot_id = %s",
            (snapshot_id,),
        ).fetchone()[0]
        action_count = connection.execute(
            "SELECT COUNT(*) FROM agent.knowledge_review_action"
        ).fetchone()[0]
    assert status == "PENDING"
    assert action_count == 0


def test_historical_resource_without_trust_metadata_cannot_be_approved() -> None:
    resource_id, _, extraction_id = _seed_extraction()
    with psycopg.connect(database_url()) as connection:
        connection.execute(
            "UPDATE agent.knowledge_resource SET reliability_level = NULL WHERE resource_id = %s",
            (resource_id,),
        )
    service = KnowledgeReviewService(
        repository=PsycopgAcquisitionRepository(database_url()),
        clock=lambda: datetime(2026, 7, 23, 1, tzinfo=UTC),
    )

    with pytest.raises(ReviewStateConflict, match="source metadata is incomplete"):
        asyncio.run(service.approve(_approval(extraction_id)))


def test_pending_review_queue_excludes_extraction_rejections_and_decided_snapshots() -> None:
    _, _, pending_extraction = _seed_extraction(label="pending")
    _seed_extraction(label="algorithm-rejected", extraction_status="REJECTED")
    _, _, decided_extraction = _seed_extraction(label="decided")
    repository = PsycopgAcquisitionRepository(database_url())
    service = KnowledgeReviewService(
        repository=repository,
        clock=lambda: datetime(2026, 7, 23, 1, tzinfo=UTC),
    )
    asyncio.run(service.reject(ReviewRejectionRequest(
        extraction_id=decided_extraction,
        reviewer_id="reviewer",
        note="not useful for planning",
    )))

    pending = asyncio.run(service.list_pending(limit=10))

    assert [candidate.extraction_id for candidate in pending] == [pending_extraction]
    assert pending[0].city == "广州"
    assert pending[0].source_name == "广州市人民政府文旅资料"
    assert pending[0].quality_issues == ()


def test_rejection_is_audited_without_creating_publication() -> None:
    _, snapshot_id, extraction_id = _seed_extraction()
    service = KnowledgeReviewService(
        repository=PsycopgAcquisitionRepository(database_url()),
        clock=lambda: datetime(2026, 7, 23, 2, tzinfo=UTC),
    )

    result = asyncio.run(
        service.reject(
            ReviewRejectionRequest(
                extraction_id=extraction_id,
                reviewer_id="reviewer-2",
                note="official page does not support the summary",
            )
        )
    )

    with psycopg.connect(database_url()) as connection:
        counts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM agent.knowledge_review_action),
                (SELECT COUNT(*) FROM agent.knowledge_publication)
            """
        ).fetchone()
        status = connection.execute(
            "SELECT review_status FROM agent.knowledge_snapshot WHERE snapshot_id = %s",
            (snapshot_id,),
        ).fetchone()[0]
    assert result.review_status == "REJECTED"
    assert counts == (1, 0)
    assert status == "REJECTED"


def test_document_version_increments_per_resource() -> None:
    resource_id, _, first_extraction = _seed_extraction(label="first")
    _, _, second_extraction = _seed_extraction(label="second", resource_id=resource_id)
    service = KnowledgeReviewService(
        repository=PsycopgAcquisitionRepository(database_url()),
        clock=lambda: datetime(2026, 7, 23, 3, tzinfo=UTC),
    )

    first = asyncio.run(service.approve(_approval(first_extraction)))
    second = asyncio.run(service.approve(_approval(second_extraction)))

    assert first.document_id == second.document_id == f"acquired-{resource_id}"
    assert (first.document_version, second.document_version) == (1, 2)


def test_concurrent_conflicting_reviews_commit_exactly_one_decision() -> None:
    _, snapshot_id, extraction_id = _seed_extraction()
    repository = PsycopgAcquisitionRepository(database_url())
    service = KnowledgeReviewService(
        repository=repository,
        clock=lambda: datetime(2026, 7, 23, 4, tzinfo=UTC),
    )

    async def review_concurrently():
        return await asyncio.gather(
            service.approve(_approval(extraction_id)),
            service.reject(
                ReviewRejectionRequest(
                    extraction_id=extraction_id,
                    reviewer_id="reviewer-2",
                    note="reject",
                )
            ),
            return_exceptions=True,
        )

    results = asyncio.run(review_concurrently())

    assert sum(isinstance(result, ReviewPersistence) for result in results) == 1
    assert sum(isinstance(result, ReviewStateConflict) for result in results) == 1
    with psycopg.connect(database_url()) as connection:
        action_count = connection.execute(
            "SELECT COUNT(*) FROM agent.knowledge_review_action"
        ).fetchone()[0]
        status = connection.execute(
            "SELECT review_status FROM agent.knowledge_snapshot WHERE snapshot_id = %s",
            (snapshot_id,),
        ).fetchone()[0]
    assert action_count == 1
    assert status in {"APPROVED", "REJECTED"}


def test_withdrawal_cancels_pending_publication_and_prevents_import() -> None:
    _, snapshot_id, extraction_id = _seed_extraction()
    repository = PsycopgAcquisitionRepository(database_url())
    now = datetime(2026, 7, 23, 5, tzinfo=UTC)
    service = KnowledgeReviewService(repository=repository, clock=lambda: now)
    approval = asyncio.run(service.approve(_approval(extraction_id)))

    withdrawal = asyncio.run(
        service.withdraw(
            ReviewWithdrawalRequest(
                approval_action_id=approval.action_id,
                reviewer_id="reviewer-2",
                note="new official correction arrived",
            )
        )
    )
    importer = RecordingImporter()
    publisher = KnowledgeReviewPublisher(repository=repository, importer=importer)

    with pytest.raises(PublicationNotAvailable):
        asyncio.run(publisher.publish(approval.action_id))
    with pytest.raises(ReviewStateConflict, match="withdrawn"):
        asyncio.run(service.approve(_approval(extraction_id)))

    with psycopg.connect(database_url()) as connection:
        row = connection.execute(
            """
            SELECT s.review_status, p.status
            FROM agent.knowledge_snapshot s
            JOIN agent.knowledge_review_action a ON a.snapshot_id = s.snapshot_id
                AND a.action = 'APPROVE'
            JOIN agent.knowledge_publication p ON p.review_action_id = a.action_id
            WHERE s.snapshot_id = %s
            """,
            (snapshot_id,),
        ).fetchone()
    assert withdrawal.review_status == "WITHDRAWN"
    assert row == ("WITHDRAWN", "CANCELLED")
    assert importer.documents == []


def test_claimed_publication_cannot_be_withdrawn_but_stale_claim_can_be_retried() -> None:
    _, _, extraction_id = _seed_extraction()
    repository = PsycopgAcquisitionRepository(database_url())
    now = datetime(2026, 7, 23, 6, tzinfo=UTC)
    service = KnowledgeReviewService(repository=repository, clock=lambda: now)
    approval = asyncio.run(service.approve(_approval(extraction_id)))

    claimed = asyncio.run(
        repository.claim_publication(
            review_action_id=approval.action_id,
            claim_timeout=timedelta(minutes=15),
        )
    )
    with pytest.raises(ReviewStateConflict, match="publication is in progress"):
        asyncio.run(
            service.withdraw(
                ReviewWithdrawalRequest(
                    approval_action_id=approval.action_id,
                    reviewer_id="reviewer-2",
                    note="too late",
                )
            )
        )
    still_claimed = asyncio.run(
        repository.claim_publication(
            review_action_id=approval.action_id,
            claim_timeout=timedelta(minutes=15),
        )
    )
    with psycopg.connect(database_url()) as connection:
        connection.execute(
            """
            UPDATE agent.knowledge_publication
            SET claim_started_at = CURRENT_TIMESTAMP - INTERVAL '16 minutes'
            """
        )
    reclaimed = asyncio.run(
        repository.claim_publication(
            review_action_id=approval.action_id,
            claim_timeout=timedelta(minutes=15),
        )
    )

    assert isinstance(claimed, PublicationClaim)
    assert still_claimed is None
    assert isinstance(reclaimed, PublicationClaim)
    with psycopg.connect(database_url()) as connection:
        attempts = connection.execute(
            "SELECT attempt_count FROM agent.knowledge_publication"
        ).fetchone()[0]
    assert attempts == 2


def test_stale_success_converges_after_reclaimed_failure_and_blocks_withdrawal() -> None:
    _, _, extraction_id = _seed_extraction()
    repository = PsycopgAcquisitionRepository(database_url())
    now = datetime(2026, 7, 23, 6, tzinfo=UTC)
    service = KnowledgeReviewService(repository=repository, clock=lambda: now)
    approval = asyncio.run(service.approve(_approval(extraction_id)))
    first = asyncio.run(repository.claim_publication(
        review_action_id=approval.action_id,
        claim_timeout=timedelta(minutes=15),
    ))
    with psycopg.connect(database_url()) as connection:
        connection.execute(
            """
            UPDATE agent.knowledge_publication
            SET claim_started_at = CURRENT_TIMESTAMP - INTERVAL '16 minutes'
            """
        )
    second = asyncio.run(repository.claim_publication(
        review_action_id=approval.action_id,
        claim_timeout=timedelta(minutes=15),
    ))
    assert isinstance(first, PublicationClaim)
    assert isinstance(second, PublicationClaim)
    asyncio.run(repository.mark_publication_failed(
        review_action_id=approval.action_id,
        claim_token=second.claim_token,
        error="RuntimeError: embedding unavailable",
        failed_at=now + timedelta(minutes=17),
    ))

    with pytest.raises(ReviewStateConflict, match="publication was already attempted"):
        asyncio.run(service.withdraw(ReviewWithdrawalRequest(
            approval_action_id=approval.action_id,
            reviewer_id="reviewer-2",
            note="cannot prove the external write did not happen",
        )))

    asyncio.run(repository.mark_publication_succeeded(
        review_action_id=approval.action_id,
        claim_token=first.claim_token,
        result=KnowledgeImportResult(
            document_id=first.document_id,
            version=first.document_version,
            chunk_count=2,
            status="created",
        ),
        published_at=now + timedelta(minutes=18),
    ))
    with psycopg.connect(database_url()) as connection:
        status = connection.execute(
            "SELECT status FROM agent.knowledge_publication"
        ).fetchone()[0]
    assert status == "PUBLISHED"


def test_publication_failure_is_retryable_and_success_is_not_reimported() -> None:
    _, _, extraction_id = _seed_extraction()
    repository = PsycopgAcquisitionRepository(database_url())
    times = iter(
        (
            datetime(2026, 7, 23, 7, 1, tzinfo=UTC),
            datetime(2026, 7, 23, 8, 1, tzinfo=UTC),
        )
    )
    review_service = KnowledgeReviewService(
        repository=repository,
        clock=lambda: datetime(2026, 7, 23, 6, tzinfo=UTC),
    )
    approval = asyncio.run(review_service.approve(_approval(extraction_id)))
    importer = RecordingImporter(failures=1)
    publisher = KnowledgeReviewPublisher(
        repository=repository,
        importer=importer,
        clock=lambda: next(times),
    )

    with pytest.raises(RuntimeError, match="embedding unavailable"):
        asyncio.run(publisher.publish(approval.action_id))
    succeeded = asyncio.run(publisher.publish(approval.action_id))
    repeated = asyncio.run(publisher.publish(approval.action_id))

    assert succeeded.status == "created"
    assert repeated == succeeded
    assert len(importer.documents) == 2
    with psycopg.connect(database_url()) as connection:
        publication = connection.execute(
            """
            SELECT status, attempt_count, chunk_count, importer_status,
                last_error, published_at
            FROM agent.knowledge_publication
            """
        ).fetchone()
    assert publication == (
        "PUBLISHED",
        2,
        2,
        "created",
        None,
        datetime(2026, 7, 23, 8, 1, tzinfo=UTC),
    )
