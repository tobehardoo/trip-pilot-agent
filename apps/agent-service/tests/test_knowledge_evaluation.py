import asyncio
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from trip_agent.retrieval.documents import parse_markdown_document
from trip_agent.retrieval.embeddings import EmbeddingVector
from trip_agent.retrieval.evaluation import (
    KnowledgeRetrievalEvaluator,
    RetrievalEvaluationSuite,
    render_evaluation_report,
)
from trip_agent.retrieval.repository import KnowledgeCitation

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class FixedEmbeddingProvider:
    model_name = "real-test-model"
    dimensions = 3

    async def embed_texts(self, texts: tuple[str, ...]) -> tuple[EmbeddingVector, ...]:
        return tuple(
            EmbeddingVector(model_name=self.model_name, values=(1.0, 0.0, 0.0))
            for _ in texts
        )


class RankedRepository:
    def __init__(self, rankings: dict[str, tuple[str, ...]]) -> None:
        self.rankings = rankings
        self.queries = []

    async def search_distinct_documents(self, request):
        self.queries.append(request)
        return tuple(
            _citation(document_id, rank)
            for rank, document_id in enumerate(self.rankings.get(request.city, ()))
        )


def _citation(document_id: str, rank: int) -> KnowledgeCitation:
    return KnowledgeCitation(
        chunk_id=f"chunk-{document_id}-{rank}",
        document_id=document_id,
        document_version=1,
        chunk_index=rank,
        city="广州",
        category="culture",
        title=document_id,
        content="评测片段",
        source_url="https://example.com/source",
        source_name="Test source",
        reliability_level="OFFICIAL",
        collected_at=datetime(2026, 7, 23, tzinfo=UTC),
        similarity=0.9 - rank * 0.1,
    )


def test_versioned_guangzhou_suite_loads_deterministically() -> None:
    suite = RetrievalEvaluationSuite.load(
        PROJECT_ROOT / "knowledge" / "evaluations" / "guangzhou-retrieval-v1.toml"
    )

    assert suite.suite_id == "guangzhou-retrieval-v1"
    assert suite.version == 1
    assert suite.as_of == date(2026, 7, 23)
    assert dict(suite.corpus_versions) == {
        "guangzhou-chen-clan-museum": 1,
        "guangzhou-shamian-history": 1,
        "guangzhou-xiguan-citywalk": 1,
    }
    assert len(suite.cases) >= 6
    assert [case.case_id for case in suite.cases] == sorted(case.case_id for case in suite.cases)
    assert {document_id for case in suite.cases for document_id in case.expected_document_ids} == {
        "guangzhou-chen-clan-museum",
        "guangzhou-shamian-history",
        "guangzhou-xiguan-citywalk",
    }
    documents = {
        document.document_id: document
        for document in (
            parse_markdown_document(path.read_text(encoding="utf-8"))
            for path in (PROJECT_ROOT / "knowledge" / "guangzhou").glob("*.md")
        )
    }
    for case in suite.cases:
        for document_id in case.expected_document_ids:
            assert documents[document_id].city == case.city
            if case.category is not None:
                assert documents[document_id].category == case.category


def test_suite_rejects_duplicate_cases_and_empty_expectations(tmp_path: Path) -> None:
    path = tmp_path / "invalid.toml"
    path.write_text(
        """
suite_id = "invalid-suite"
version = 1
as_of = 2026-07-23
[corpus_versions]
doc-a = 1

[[cases]]
case_id = "duplicate"
query = "广州文化"
city = "广州"
expected_document_ids = ["doc-a"]

[[cases]]
case_id = "duplicate"
query = "广州历史"
city = "广州"
expected_document_ids = []
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate case_id"):
        RetrievalEvaluationSuite.load(path)

    with pytest.raises(ValueError, match="cannot be empty"):
        RetrievalEvaluationSuite.from_records(
            suite_id="empty-expectation",
            version=1,
            as_of=date(2026, 7, 23),
            corpus_versions={"doc-a": 1},
            records=(
                {
                    "case_id": "empty",
                    "query": "广州文化",
                    "city": "广州",
                    "expected_document_ids": (),
                },
            ),
        )
    with pytest.raises(ValueError, match="must be a table"):
        RetrievalEvaluationSuite.from_records(
            suite_id="scalar-case",
            version=1,
            as_of=date(2026, 7, 23),
            corpus_versions={"doc-a": 1},
            records=("not-a-table",),
        )
    with pytest.raises(ValueError, match="unknown.*fields"):
        RetrievalEvaluationSuite.from_records(
            suite_id="unknown-field",
            version=1,
            as_of=date(2026, 7, 23),
            corpus_versions={"doc-a": 1},
            records=(
                {
                    "case_id": "unknown",
                    "query": "广州",
                    "city": "广州",
                    "expected_document_ids": ("doc-a",),
                    "catgory": "culture",
                },
            ),
        )


def test_evaluator_calculates_recall_mrr_and_case_rankings() -> None:
    suite = RetrievalEvaluationSuite.from_records(
        suite_id="test-suite",
        version=1,
        as_of=date(2026, 7, 23),
        corpus_versions={"expected-a": 1, "expected-b": 1, "also-b": 1},
        records=(
            {
                "case_id": "case-a",
                "query": "岭南工艺",
                "city": "case-a",
                "expected_document_ids": ("expected-a",),
            },
            {
                "case_id": "case-b",
                "query": "历史街区",
                "city": "case-b",
                "expected_document_ids": ("expected-b", "also-b"),
            },
        ),
    )
    repository = RankedRepository(
        {
            "case-a": ("other", "expected-a", "expected-a"),
            "case-b": ("expected-b", "other"),
        }
    )
    evaluator = KnowledgeRetrievalEvaluator(
        embedding_provider=FixedEmbeddingProvider(),
        repository=repository,
    )

    report = asyncio.run(
        evaluator.evaluate(
            suite,
            top_k=3,
            minimum_recall=0.7,
            minimum_mrr=0.7,
        )
    )

    assert report.status == "PASSED"
    assert report.model_name == "real-test-model"
    assert report.dimensions == 3
    assert report.as_of == date(2026, 7, 23)
    assert dict(report.corpus_versions)["expected-a"] == 1
    assert report.recall_at_k == pytest.approx(0.75)
    assert report.mean_reciprocal_rank == pytest.approx(0.75)
    assert report.hit_case_count == 2
    assert report.cases[0].ranked_document_ids == ("other", "expected-a")
    assert report.cases[0].first_relevant_rank == 2
    assert report.cases[1].recall_at_k == pytest.approx(0.5)
    assert [query.limit for query in repository.queries] == [3, 3]
    assert [query.min_similarity for query in repository.queries] == [-1, -1]
    assert [query.as_of for query in repository.queries] == [date(2026, 7, 23)] * 2


def test_demo_model_can_never_pass_authoritative_quality_gate() -> None:
    provider = FixedEmbeddingProvider()
    provider.model_name = "demo-hash-v1:3"
    suite = RetrievalEvaluationSuite.from_records(
        suite_id="demo-suite",
        version=1,
        as_of=date(2026, 7, 23),
        corpus_versions={"expected": 1},
        records=(
            {
                "case_id": "case-a",
                "query": "文化",
                "city": "case-a",
                "expected_document_ids": ("expected",),
            },
        ),
    )
    evaluator = KnowledgeRetrievalEvaluator(
        embedding_provider=provider,
        repository=RankedRepository({"case-a": ("expected",)}),
    )

    report = asyncio.run(
        evaluator.evaluate(suite, top_k=1, minimum_recall=1, minimum_mrr=1)
    )

    assert report.recall_at_k == report.mean_reciprocal_rank == 1
    assert report.status == "DEMO_ONLY"
    payload = json.loads(render_evaluation_report(report))
    assert payload["status"] == "DEMO_ONLY"
    assert payload["cases"][0]["first_relevant_rank"] == 1


def test_real_model_fails_when_metrics_are_below_either_threshold() -> None:
    suite = RetrievalEvaluationSuite.from_records(
        suite_id="failed-suite",
        version=1,
        as_of=date(2026, 7, 23),
        corpus_versions={"expected": 1},
        records=(
            {
                "case_id": "miss",
                "query": "文化",
                "city": "miss",
                "expected_document_ids": ("expected",),
            },
        ),
    )
    evaluator = KnowledgeRetrievalEvaluator(
        embedding_provider=FixedEmbeddingProvider(),
        repository=RankedRepository({"miss": ("other",)}),
    )

    report = asyncio.run(
        evaluator.evaluate(suite, top_k=1, minimum_recall=0.1, minimum_mrr=0.1)
    )

    assert report.status == "FAILED"
    assert report.hit_case_count == 0
