import asyncio
from datetime import UTC, datetime
from importlib import import_module

from test_planning_worker import COMMAND


def test_real_retrieval_builds_versioned_citation_snapshots() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    embeddings = import_module("trip_agent.retrieval.embeddings")
    knowledge = import_module("trip_agent.worker.knowledge")
    repository_models = import_module("trip_agent.retrieval.repository")
    command = contracts.PlanningCreateCommand.model_validate(COMMAND)

    class EmbeddingProvider:
        model_name = "production-embedding-v1"
        dimensions = 3

        async def embed_texts(self, texts: tuple[str, ...]):
            assert texts == ("广州 美食 历史 FRIENDS",)
            return (
                embeddings.EmbeddingVector(
                    values=(0.1, 0.2, 0.3),
                    model_name=self.model_name,
                ),
            )

    class Repository:
        def __init__(self) -> None:
            self.request = None

        async def search(self, request: object):
            self.request = request
            return (
                repository_models.KnowledgeCitation(
                    chunk_id="guangzhou-history-001-v2-c0",
                    document_id="guangzhou-history-001",
                    document_version=2,
                    chunk_index=0,
                    city="广州",
                    category="culture",
                    title="广州历史文化资料",
                    content="内部检索正文不应进入跨服务事件",
                    source_url="https://www.gz.gov.cn/history",
                    source_name="广州市人民政府",
                    reliability_level="official",
                    collected_at=datetime(2026, 7, 22, 2, tzinfo=UTC),
                    similarity=0.87,
                ),
            )

    class FreshnessProvider:
        async def assess(self, city: str, citations: tuple[object, ...]):
            assert city == "广州"
            assert citations[0].source_url == "https://www.gz.gov.cn/history"
            return contracts.KnowledgeFreshness(
                status="FRESH",
                checked_at=datetime(2026, 7, 23, 1, tzinfo=UTC),
            )

    repository = Repository()
    provider = knowledge.RetrievalKnowledgeEvidenceProvider(
        embedding_provider=EmbeddingProvider(),
        repository=repository,
        freshness_provider=FreshnessProvider(),
    )

    evidence = asyncio.run(provider.get_evidence(command))

    assert evidence.status == "REAL"
    assert evidence.query == "广州 美食 历史 FRIENDS"
    assert evidence.freshness.status == "FRESH"
    assert evidence.citations[0].document_version == 2
    assert evidence.citations[0].chunk_id == "guangzhou-history-001-v2-c0"
    assert not hasattr(evidence.citations[0], "content")
    assert repository.request.city == "广州"
    assert repository.request.traveler_type == "FRIENDS"
    assert repository.request.as_of.isoformat() == "2026-08-01"
    assert repository.request.limit == 5


def test_demo_embedding_never_emits_production_citations() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    embeddings = import_module("trip_agent.retrieval.embeddings")
    knowledge = import_module("trip_agent.worker.knowledge")
    command = contracts.PlanningCreateCommand.model_validate(COMMAND)

    class Repository:
        async def search(self, request: object):
            raise AssertionError("demo embedding must not query production citations")

    class FreshnessProvider:
        async def assess(self, city: str):
            raise AssertionError("demo embedding must not claim production freshness")

    provider = knowledge.RetrievalKnowledgeEvidenceProvider(
        embedding_provider=embeddings.HashEmbeddingProvider(dimensions=8),
        repository=Repository(),
        freshness_provider=FreshnessProvider(),
    )

    evidence = asyncio.run(provider.get_evidence(command))

    assert evidence.status == "DEMO"
    assert evidence.citations == ()
    assert evidence.freshness.status == "UNAVAILABLE"
    assert "生产" in evidence.message


def test_expected_embedding_failure_returns_sanitized_unavailable_evidence() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    embeddings = import_module("trip_agent.retrieval.embeddings")
    knowledge = import_module("trip_agent.worker.knowledge")
    command = contracts.PlanningCreateCommand.model_validate(COMMAND)

    class FailingEmbeddingProvider:
        model_name = "production-embedding-v1"
        dimensions = 3

        async def embed_texts(self, texts: tuple[str, ...]):
            del texts
            raise embeddings.EmbeddingProviderError("secret upstream payload")

    class Repository:
        async def search(self, request: object):
            raise AssertionError("search must not run after embedding failure")

    class FreshnessProvider:
        async def assess(self, city: str):
            raise AssertionError("freshness must not run after embedding failure")

    provider = knowledge.RetrievalKnowledgeEvidenceProvider(
        embedding_provider=FailingEmbeddingProvider(),
        repository=Repository(),
        freshness_provider=FreshnessProvider(),
    )

    evidence = asyncio.run(provider.get_evidence(command))

    assert evidence.status == "UNAVAILABLE"
    assert evidence.citations == ()
    assert "secret" not in evidence.message


def test_catalog_freshness_only_assesses_the_cited_resources() -> None:
    from types import SimpleNamespace

    contracts = import_module("trip_agent.worker.contracts")
    knowledge = import_module("trip_agent.worker.knowledge")
    repository_models = import_module("trip_agent.retrieval.repository")
    citation = repository_models.KnowledgeCitation(
        chunk_id="doc-v1-c0",
        document_id="doc",
        document_version=1,
        chunk_index=0,
        city="广州",
        category="culture",
        title="广州资料",
        content="content",
        source_url="https://www.gz.gov.cn/cited",
        source_name="广州市人民政府",
        reliability_level="official",
        collected_at=datetime(2026, 7, 22, 2, tzinfo=UTC),
        similarity=0.9,
    )
    report = SimpleNamespace(
        generated_at=datetime(2026, 7, 23, 1, tzinfo=UTC),
        sources=(
            SimpleNamespace(
                city="广州",
                resources=(
                    SimpleNamespace(
                        source_url="https://www.gz.gov.cn/cited",
                        status="FRESH",
                    ),
                    SimpleNamespace(
                        source_url="https://www.gz.gov.cn/unrelated",
                        status="STALE",
                    ),
                ),
            ),
        ),
    )

    class ReportService:
        async def generate(self, catalog: object):
            del catalog
            return report

    class Catalog:
        def for_city(self, city: str):
            return (object(),) if city == "广州" else ()

    provider = knowledge.CatalogKnowledgeFreshnessProvider(
        report_service=ReportService(),
        catalog=Catalog(),
    )

    fresh = asyncio.run(provider.assess("广州", (citation,)))
    unknown = citation.model_copy(
        update={"source_url": "https://unknown.example/document"}
    )
    unavailable = asyncio.run(provider.assess("广州", (unknown,)))

    assert fresh == contracts.KnowledgeFreshness(
        status="FRESH",
        checked_at=report.generated_at,
    )
    assert unavailable == contracts.KnowledgeFreshness(status="UNAVAILABLE")


def test_static_catalog_freshness_uses_citation_collection_time_and_source_interval() -> None:
    from types import SimpleNamespace

    contracts = import_module("trip_agent.worker.contracts")
    knowledge = import_module("trip_agent.worker.knowledge")
    repository_models = import_module("trip_agent.retrieval.repository")
    now = datetime(2026, 7, 23, 1, tzinfo=UTC)
    citation = repository_models.KnowledgeCitation(
        chunk_id="doc-v1-c0",
        document_id="doc",
        document_version=1,
        chunk_index=0,
        city="广州",
        category="culture",
        title="广州资料",
        content="content",
        source_url="https://www.gz.gov.cn/cited",
        source_name="广州市人民政府",
        reliability_level="official",
        collected_at=datetime(2026, 7, 22, 2, tzinfo=UTC),
        similarity=0.9,
    )

    class Catalog:
        def for_city(self, city: str):
            if city != "广州":
                return ()
            return (SimpleNamespace(
                resource_urls=("https://www.gz.gov.cn/cited",),
                fetch_interval_hours=168,
            ),)

    provider = knowledge.StaticCatalogKnowledgeFreshnessProvider(
        catalog=Catalog(),
        clock=lambda: now,
    )

    fresh = asyncio.run(provider.assess("广州", (citation,)))
    stale = asyncio.run(provider.assess(
        "广州",
        (citation.model_copy(update={"collected_at": datetime(2026, 7, 1, tzinfo=UTC)}),),
    ))
    unknown = asyncio.run(provider.assess(
        "广州",
        (citation.model_copy(update={"source_url": "https://unknown.example/doc"}),),
    ))

    assert fresh == contracts.KnowledgeFreshness(status="FRESH", checked_at=now)
    assert stale == contracts.KnowledgeFreshness(
        status="STALE",
        checked_at=now,
        stale_reason="SOURCE_NOT_FRESH",
    )
    assert unknown == contracts.KnowledgeFreshness(status="UNAVAILABLE")


def test_unavailable_freshness_rejects_stale_details() -> None:
    import pytest
    from pydantic import ValidationError

    contracts = import_module("trip_agent.worker.contracts")

    with pytest.raises(ValidationError, match="unavailable freshness"):
        contracts.KnowledgeFreshness(
            status="UNAVAILABLE",
            stale_reason="SOURCE_VERIFICATION_OVERDUE",
        )
