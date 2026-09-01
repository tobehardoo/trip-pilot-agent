import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest

from trip_agent.acquisition.review import (
    KnowledgeReviewPublisher,
    KnowledgeReviewService,
    PendingReviewCandidate,
    PublicationClaim,
    PublicationNotAvailable,
    PublishedKnowledge,
    ReviewApprovalRequest,
    ReviewPersistence,
    ReviewRejectionRequest,
    ReviewWithdrawalRequest,
)
from trip_agent.retrieval.documents import KnowledgeDocument
from trip_agent.retrieval.service import KnowledgeImportResult


class CapturingReviewRepository:
    def __init__(self) -> None:
        self.actions = []
        self.pending = ()
        self.pending_limits = []

    async def list_reviews_pending(self, *, limit):
        self.pending_limits.append(limit)
        return self.pending

    async def save_review_action(self, action):
        self.actions.append(action)
        return ReviewPersistence(
            action_id=action.action_id,
            snapshot_id="s" * 64,
            review_status={
                "APPROVE": "APPROVED",
                "REJECT": "REJECTED",
                "WITHDRAW": "WITHDRAWN",
            }[action.action],
            persistence_status="created",
            document_id="acquired-" + "1" * 64 if action.action == "APPROVE" else None,
            document_version=1 if action.action == "APPROVE" else None,
        )


class StubPublicationRepository:
    def __init__(self, result) -> None:
        self.result = result
        self.succeeded = []
        self.failed = []

    async def claim_publication(self, *, review_action_id, claim_timeout):
        self.claim = (review_action_id, claim_timeout)
        return self.result

    async def mark_publication_succeeded(
        self, *, review_action_id, claim_token, result, published_at
    ):
        self.succeeded.append((review_action_id, claim_token, result, published_at))

    async def mark_publication_failed(self, *, review_action_id, claim_token, error, failed_at):
        self.failed.append((review_action_id, claim_token, error, failed_at))


class RecordingImporter:
    def __init__(self, error: Exception | None = None) -> None:
        self.documents: list[KnowledgeDocument] = []
        self.error = error

    async def import_document(self, document: KnowledgeDocument) -> KnowledgeImportResult:
        self.documents.append(document)
        if self.error is not None:
            raise self.error
        return KnowledgeImportResult(
            document_id=document.document_id,
            version=document.version,
            chunk_count=3,
            status="created",
        )


def _approval() -> ReviewApprovalRequest:
    return ReviewApprovalRequest(
        extraction_id="e" * 64,
        reviewer_id=" editor-17 ",
        note=" verified against the official page ",
        category="culture",
        valid_from=date(2026, 7, 1),
        valid_to=date(2027, 6, 30),
        applicable_seasons=("all",),
        traveler_types=("FAMILY", "SOLO"),
    )


def _claim() -> PublicationClaim:
    return PublicationClaim(
        review_action_id="a" * 64,
        claim_token=1,
        document_id="acquired-" + "1" * 64,
        document_version=2,
        city="广州",
        category="culture",
        title="广州历史街区",
        content="官方正文内容",
        content_hash="c" * 64,
        source_url="https://www.gz.gov.cn/article.html",
        source_name="广州市人民政府文旅资料",
        reliability_level="OFFICIAL",
        published_at=datetime(2026, 7, 20, 16, tzinfo=UTC),
        collected_at=datetime(2026, 7, 22, 1, tzinfo=UTC),
        valid_from=date(2026, 7, 1),
        valid_to=date(2027, 6, 30),
        applicable_seasons=("all",),
        traveler_types=("FAMILY", "SOLO"),
    )


def test_review_service_builds_normalized_stable_approval_audit() -> None:
    repository = CapturingReviewRepository()
    reviewed_at = datetime(2026, 7, 23, 1, tzinfo=UTC)
    service = KnowledgeReviewService(repository=repository, clock=lambda: reviewed_at)

    first = asyncio.run(service.approve(_approval()))
    second = asyncio.run(service.approve(_approval()))

    assert first.review_status == "APPROVED"
    assert second.action_id == first.action_id
    assert len(repository.actions) == 2
    action = repository.actions[0]
    assert action.action == "APPROVE"
    assert action.reviewer_id == "editor-17"
    assert action.note == "verified against the official page"
    assert action.reviewed_at == reviewed_at
    assert len(action.action_id) == len(action.decision_fingerprint) == 64
    assert repository.actions[1].decision_fingerprint == action.decision_fingerprint


def test_review_service_lists_bounded_pending_candidates() -> None:
    repository = CapturingReviewRepository()
    candidate = PendingReviewCandidate(
        extraction_id="e" * 64,
        snapshot_id="s" * 64,
        city="广州",
        source_url="https://www.gz.gov.cn/article.html",
        source_name="广州市人民政府文旅资料",
        title="广州历史街区",
        content="官方正文内容",
        published_at=datetime(2026, 7, 20, 16, tzinfo=UTC),
        fetched_at=datetime(2026, 7, 22, 1, tzinfo=UTC),
        extracted_at=datetime(2026, 7, 22, 2, tzinfo=UTC),
        quality_issues=(),
    )
    repository.pending = (candidate,)
    service = KnowledgeReviewService(repository=repository)

    result = asyncio.run(service.list_pending(limit=25))

    assert result == (candidate,)
    assert repository.pending_limits == [25]

    for invalid in (0, 101, True):
        with pytest.raises(ValueError, match="limit must be between 1 and 100"):
            asyncio.run(service.list_pending(limit=invalid))


def test_review_service_builds_rejection_and_withdrawal_actions() -> None:
    repository = CapturingReviewRepository()
    service = KnowledgeReviewService(
        repository=repository,
        clock=lambda: datetime(2026, 7, 23, 2, tzinfo=UTC),
    )

    rejected = asyncio.run(
        service.reject(
            ReviewRejectionRequest(
                extraction_id="e" * 64,
                reviewer_id="reviewer",
                note="contains an unsupported claim",
            )
        )
    )
    withdrawn = asyncio.run(
        service.withdraw(
            ReviewWithdrawalRequest(
                approval_action_id="a" * 64,
                reviewer_id="reviewer",
                note="approval superseded before publication",
            )
        )
    )

    assert rejected.review_status == "REJECTED"
    assert withdrawn.review_status == "WITHDRAWN"
    assert [action.action for action in repository.actions] == ["REJECT", "WITHDRAW"]
    assert repository.actions[1].parent_action_id == "a" * 64


@pytest.mark.parametrize(
    ("request_factory", "message"),
    [
        (
            lambda: ReviewApprovalRequest(
                extraction_id="e" * 64,
                reviewer_id=" ",
                note="verified",
                category="culture",
            ),
            "reviewer_id cannot be empty",
        ),
        (
            lambda: ReviewApprovalRequest(
                extraction_id="e" * 64,
                reviewer_id="reviewer",
                note="verified",
                category="culture",
                valid_from=date(2027, 1, 1),
                valid_to=date(2026, 1, 1),
            ),
            "valid_from cannot be after valid_to",
        ),
        (
            lambda: ReviewApprovalRequest(
                extraction_id="e" * 64,
                reviewer_id="reviewer",
                note="verified",
                category="culture",
                applicable_seasons=("all", "all"),
            ),
            "applicable_seasons must be unique",
        ),
    ],
)
def test_review_request_rejects_invalid_audit_or_metadata(request_factory, message) -> None:
    with pytest.raises(ValueError, match=message):
        request_factory()


def test_review_service_rejects_naive_clock_before_writing() -> None:
    repository = CapturingReviewRepository()
    service = KnowledgeReviewService(
        repository=repository,
        clock=lambda: datetime(2026, 7, 23, 1),
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        asyncio.run(service.approve(_approval()))

    assert repository.actions == []


def test_publisher_maps_frozen_approval_to_knowledge_document() -> None:
    published_at = datetime(2026, 7, 23, 3, 0, 30, tzinfo=UTC)
    repository = StubPublicationRepository(_claim())
    importer = RecordingImporter()
    publisher = KnowledgeReviewPublisher(
        repository=repository,
        importer=importer,
        clock=lambda: published_at,
        claim_timeout=timedelta(minutes=10),
        publication_timezone="Asia/Shanghai",
    )

    result = asyncio.run(publisher.publish("a" * 64))

    assert result.status == "created"
    assert repository.claim == (
        "a" * 64,
        timedelta(minutes=10),
    )
    assert len(importer.documents) == 1
    document = importer.documents[0]
    assert document.model_dump() == {
        "document_id": "acquired-" + "1" * 64,
        "city": "广州",
        "category": "culture",
        "title": "广州历史街区",
        "content": "官方正文内容",
        "content_hash": "c" * 64,
        "source_url": document.source_url,
        "source_name": "广州市人民政府文旅资料",
        "published_at": date(2026, 7, 21),
        "collected_at": datetime(2026, 7, 22, 1, tzinfo=UTC),
        "valid_from": date(2026, 7, 1),
        "valid_to": date(2027, 6, 30),
        "applicable_seasons": ("all",),
        "traveler_types": ("FAMILY", "SOLO"),
        "reliability_level": "OFFICIAL",
        "version": 2,
    }
    assert repository.succeeded == [("a" * 64, 1, result, published_at)]
    assert repository.failed == []


def test_publisher_records_failure_and_preserves_original_exception() -> None:
    failed_at = datetime(2026, 7, 23, 4, tzinfo=UTC)
    repository = StubPublicationRepository(_claim())
    importer = RecordingImporter(error=RuntimeError("embedding unavailable"))
    publisher = KnowledgeReviewPublisher(
        repository=repository,
        importer=importer,
        clock=lambda: failed_at,
    )

    with pytest.raises(RuntimeError, match="embedding unavailable"):
        asyncio.run(publisher.publish("a" * 64))

    assert repository.succeeded == []
    assert repository.failed == [
        ("a" * 64, 1, "RuntimeError: embedding unavailable", failed_at)
    ]


def test_publisher_returns_completed_result_without_reimporting() -> None:
    completed = PublishedKnowledge(
        review_action_id="a" * 64,
        document_id="acquired-" + "1" * 64,
        document_version=2,
        chunk_count=3,
        importer_status="unchanged",
    )
    repository = StubPublicationRepository(completed)
    importer = RecordingImporter()
    publisher = KnowledgeReviewPublisher(repository=repository, importer=importer)

    result = asyncio.run(publisher.publish("a" * 64))

    assert result == KnowledgeImportResult(
        document_id=completed.document_id,
        version=2,
        chunk_count=3,
        status="unchanged",
    )
    assert importer.documents == []
    assert repository.succeeded == []


def test_publisher_does_not_import_unavailable_or_withdrawn_review() -> None:
    repository = StubPublicationRepository(None)
    importer = RecordingImporter()
    def unexpected_clock():
        raise AssertionError("application clock must not decide publication lease state")

    publisher = KnowledgeReviewPublisher(
        repository=repository,
        importer=importer,
        clock=unexpected_clock,
    )

    with pytest.raises(PublicationNotAvailable):
        asyncio.run(publisher.publish("a" * 64))

    assert importer.documents == []
