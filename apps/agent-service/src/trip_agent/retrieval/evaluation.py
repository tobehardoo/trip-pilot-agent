"""Versioned retrieval quality evaluation independent from model vendors."""

import json
import re
import tomllib
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Literal, Protocol

from trip_agent.retrieval.documents import KnowledgeCategory
from trip_agent.retrieval.embeddings import EmbeddingProvider
from trip_agent.retrieval.repository import (
    KnowledgeCitation,
    KnowledgeSearchRequest,
)

type EvaluationStatus = Literal["PASSED", "FAILED", "DEMO_ONLY"]

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]+$")
_CATEGORIES = {"accommodation", "culture", "food", "poi", "season", "theme", "travel_tip"}


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationCase:
    case_id: str
    query: str
    city: str
    expected_document_ids: tuple[str, ...]
    category: KnowledgeCategory | None = None

    def __post_init__(self) -> None:
        _validate_id(self.case_id, "case_id")
        object.__setattr__(self, "query", _text(self.query, "query"))
        object.__setattr__(self, "city", _text(self.city, "city"))
        expected = tuple(self.expected_document_ids)
        if not expected:
            raise ValueError(f"case {self.case_id} expected_document_ids cannot be empty")
        if len(expected) != len(set(expected)):
            raise ValueError(f"case {self.case_id} expected_document_ids must be unique")
        for document_id in expected:
            _validate_id(document_id, "expected_document_id")
        if self.category is not None and self.category not in _CATEGORIES:
            raise ValueError(f"unsupported category: {self.category}")
        object.__setattr__(self, "expected_document_ids", expected)


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationSuite:
    suite_id: str
    version: int
    as_of: date
    corpus_versions: tuple[tuple[str, int], ...]
    cases: tuple[RetrievalEvaluationCase, ...]

    @classmethod
    def load(cls, path: Path) -> "RetrievalEvaluationSuite":
        try:
            payload = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise ValueError(f"cannot read retrieval evaluation suite {path}: {error}") from error
        unknown = set(payload) - {"suite_id", "version", "as_of", "corpus_versions", "cases"}
        if unknown:
            raise ValueError(f"unknown retrieval evaluation suite fields: {sorted(unknown)}")
        records = payload.get("cases")
        if not isinstance(records, list):
            raise ValueError("retrieval evaluation suite requires a cases array")
        return cls.from_records(
            suite_id=payload.get("suite_id"),
            version=payload.get("version"),
            as_of=payload.get("as_of"),
            corpus_versions=payload.get("corpus_versions"),
            records=tuple(records),
        )

    @classmethod
    def from_records(
        cls,
        *,
        suite_id: object,
        version: object,
        as_of: object,
        corpus_versions: object,
        records: tuple[object, ...],
    ) -> "RetrievalEvaluationSuite":
        if not isinstance(suite_id, str):
            raise ValueError("suite_id must be a string")
        _validate_id(suite_id, "suite_id")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ValueError("evaluation suite version must be a positive integer")
        if not isinstance(as_of, date):
            raise ValueError("evaluation suite as_of must be a TOML date")
        if not isinstance(corpus_versions, dict) or not corpus_versions:
            raise ValueError("evaluation suite corpus_versions must be a non-empty table")
        for document_id, document_version in corpus_versions.items():
            _validate_id(document_id, "corpus document_id")
            if (
                not isinstance(document_version, int)
                or isinstance(document_version, bool)
                or document_version < 1
            ):
                raise ValueError("corpus document versions must be positive integers")
        if not records:
            raise ValueError("retrieval evaluation suite cannot be empty")
        if any(not isinstance(record, dict) for record in records):
            raise ValueError("each retrieval evaluation case must be a table")
        allowed_case_fields = {
            "case_id", "query", "city", "expected_document_ids", "category"
        }
        for record in records:
            unknown = set(record) - allowed_case_fields
            if unknown:
                raise ValueError(f"unknown retrieval evaluation case fields: {sorted(unknown)}")
        raw_ids = tuple(record.get("case_id") for record in records)
        if len(raw_ids) != len(set(raw_ids)):
            raise ValueError("duplicate case_id in retrieval evaluation suite")
        try:
            cases = tuple(
                RetrievalEvaluationCase(
                    case_id=record["case_id"],
                    query=record["query"],
                    city=record["city"],
                    expected_document_ids=tuple(record["expected_document_ids"]),
                    category=record.get("category"),
                )
                for record in records
            )
        except (KeyError, TypeError) as error:
            raise ValueError(f"invalid retrieval evaluation case: {error}") from error
        expected_ids = {document_id for case in cases for document_id in case.expected_document_ids}
        missing_versions = expected_ids - set(corpus_versions)
        if missing_versions:
            raise ValueError(
                f"corpus_versions missing expected documents: {sorted(missing_versions)}"
            )
        return cls(
            suite_id=suite_id,
            version=version,
            as_of=as_of,
            corpus_versions=tuple(sorted(corpus_versions.items())),
            cases=tuple(sorted(cases, key=lambda case: case.case_id)),
        )


@dataclass(frozen=True, slots=True)
class RetrievalCaseResult:
    case_id: str
    ranked_document_ids: tuple[str, ...]
    ranked_document_versions: tuple[int, ...]
    expected_document_ids: tuple[str, ...]
    recall_at_k: float
    first_relevant_rank: int | None
    reciprocal_rank: float


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationReport:
    suite_id: str
    suite_version: int
    as_of: date
    corpus_versions: tuple[tuple[str, int], ...]
    status: EvaluationStatus
    model_name: str
    dimensions: int
    top_k: int
    case_count: int
    hit_case_count: int
    recall_at_k: float
    mean_reciprocal_rank: float
    minimum_recall: float
    minimum_mrr: float
    cases: tuple[RetrievalCaseResult, ...]


class KnowledgeSearchRepository(Protocol):
    async def search_distinct_documents(
        self, request: KnowledgeSearchRequest
    ) -> tuple[KnowledgeCitation, ...]: ...


class KnowledgeRetrievalEvaluator:
    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider,
        repository: KnowledgeSearchRepository,
    ) -> None:
        self._embedding_provider = embedding_provider
        self._repository = repository

    async def evaluate(
        self,
        suite: RetrievalEvaluationSuite,
        *,
        top_k: int = 5,
        minimum_recall: float = 0.8,
        minimum_mrr: float = 0.7,
    ) -> RetrievalEvaluationReport:
        if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 50:
            raise ValueError("top_k must be between 1 and 50")
        _threshold(minimum_recall, "minimum_recall")
        _threshold(minimum_mrr, "minimum_mrr")
        vectors = await self._embedding_provider.embed_texts(
            tuple(case.query for case in suite.cases)
        )
        if len(vectors) != len(suite.cases):
            raise ValueError("embedding provider returned an unexpected vector count")

        results: list[RetrievalCaseResult] = []
        corpus_versions = dict(suite.corpus_versions)
        for case, vector in zip(suite.cases, vectors, strict=True):
            if vector.model_name != self._embedding_provider.model_name:
                raise ValueError("embedding provider returned an unexpected model name")
            if len(vector.values) != self._embedding_provider.dimensions:
                raise ValueError("embedding provider returned an unexpected vector dimension")
            citations = await self._repository.search_distinct_documents(
                KnowledgeSearchRequest(
                    city=case.city,
                    category=case.category,
                    embedding=vector,
                    limit=top_k,
                    min_similarity=-1,
                    as_of=suite.as_of,
                )
            )
            ranked_pairs = tuple(
                dict.fromkeys(
                    (citation.document_id, citation.document_version) for citation in citations
                )
            )[:top_k]
            ranked = tuple(document_id for document_id, _ in ranked_pairs)
            expected = {
                (document_id, corpus_versions[document_id])
                for document_id in case.expected_document_ids
            }
            relevant_ranks = tuple(
                rank for rank, document in enumerate(ranked_pairs, start=1) if document in expected
            )
            recall = len(expected.intersection(ranked_pairs)) / len(expected)
            first_rank = relevant_ranks[0] if relevant_ranks else None
            results.append(
                RetrievalCaseResult(
                    case_id=case.case_id,
                    ranked_document_ids=ranked,
                    ranked_document_versions=tuple(version for _, version in ranked_pairs),
                    expected_document_ids=case.expected_document_ids,
                    recall_at_k=recall,
                    first_relevant_rank=first_rank,
                    reciprocal_rank=1 / first_rank if first_rank else 0.0,
                )
            )
        recall_at_k = sum(result.recall_at_k for result in results) / len(results)
        mrr = sum(result.reciprocal_rank for result in results) / len(results)
        if self._embedding_provider.model_name.startswith("demo-"):
            status: EvaluationStatus = "DEMO_ONLY"
        elif recall_at_k >= minimum_recall and mrr >= minimum_mrr:
            status = "PASSED"
        else:
            status = "FAILED"
        return RetrievalEvaluationReport(
            suite_id=suite.suite_id,
            suite_version=suite.version,
            as_of=suite.as_of,
            corpus_versions=suite.corpus_versions,
            status=status,
            model_name=self._embedding_provider.model_name,
            dimensions=self._embedding_provider.dimensions,
            top_k=top_k,
            case_count=len(results),
            hit_case_count=sum(result.first_relevant_rank is not None for result in results),
            recall_at_k=recall_at_k,
            mean_reciprocal_rank=mrr,
            minimum_recall=float(minimum_recall),
            minimum_mrr=float(minimum_mrr),
            cases=tuple(results),
        )


def render_evaluation_report(report: RetrievalEvaluationReport) -> str:
    return json.dumps(
        asdict(report),
        ensure_ascii=False,
        indent=2,
        default=lambda value: value.isoformat() if isinstance(value, date) else None,
    )


def _validate_id(value: object, field_name: str) -> None:
    if not isinstance(value, str) or _ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be lowercase kebab-case")


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} cannot be empty")
    return value.strip()


def _threshold(value: float, field_name: str) -> None:
    if not isinstance(value, int | float) or isinstance(value, bool) or not 0 <= value <= 1:
        raise ValueError(f"{field_name} must be between 0 and 1")
