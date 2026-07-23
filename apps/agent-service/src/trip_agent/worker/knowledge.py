"""Knowledge evidence application port for planning completion events."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

import psycopg

from trip_agent.acquisition.freshness import FreshnessReportService
from trip_agent.acquisition.registry import SourceCatalog
from trip_agent.retrieval.embeddings import (
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingVector,
)
from trip_agent.retrieval.repository import (
    KnowledgeCitation,
    KnowledgeSearchRequest,
)
from trip_agent.worker.contracts import (
    KnowledgeCitationSnapshot,
    KnowledgeEvidence,
    KnowledgeFreshness,
    PlanningCreateCommand,
)


class KnowledgeSearchRepository(Protocol):
    async def search(self, request: KnowledgeSearchRequest) -> tuple[KnowledgeCitation, ...]: ...


class KnowledgeFreshnessProvider(Protocol):
    async def assess(
        self,
        city: str,
        citations: tuple[KnowledgeCitation, ...],
    ) -> KnowledgeFreshness: ...


class CatalogKnowledgeFreshnessProvider:
    def __init__(
        self,
        *,
        report_service: FreshnessReportService,
        catalog: SourceCatalog,
    ) -> None:
        self._report_service = report_service
        self._catalog = catalog

    async def assess(
        self,
        city: str,
        citations: tuple[KnowledgeCitation, ...],
    ) -> KnowledgeFreshness:
        configured_sources = self._catalog.for_city(city)
        if not configured_sources or not citations:
            return KnowledgeFreshness(status="UNAVAILABLE")
        report = await self._report_service.generate(self._catalog)
        city_sources = tuple(source for source in report.sources if source.city == city.strip())
        if not city_sources:
            return KnowledgeFreshness(status="UNAVAILABLE")
        resource_by_url = {
            resource.source_url: resource
            for source in city_sources
            for resource in source.resources
        }
        cited_resources = tuple(
            resource_by_url.get(citation.source_url) for citation in citations
        )
        if any(resource is None for resource in cited_resources):
            return KnowledgeFreshness(status="UNAVAILABLE")
        if any(resource.status == "STALE" for resource in cited_resources if resource):
            return KnowledgeFreshness(
                status="STALE",
                checked_at=report.generated_at,
                stale_reason="SOURCE_NOT_FRESH",
            )
        return KnowledgeFreshness(status="FRESH", checked_at=report.generated_at)


class StaticCatalogKnowledgeFreshnessProvider:
    """Assess imported static documents without requiring acquisition runtime tables."""

    def __init__(
        self,
        *,
        catalog: SourceCatalog,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._catalog = catalog
        self._clock = clock or (lambda: datetime.now(UTC))

    async def assess(
        self,
        city: str,
        citations: tuple[KnowledgeCitation, ...],
    ) -> KnowledgeFreshness:
        sources = self._catalog.for_city(city)
        if not sources or not citations:
            return KnowledgeFreshness(status="UNAVAILABLE")
        interval_by_url = {
            url: source.fetch_interval_hours
            for source in sources
            for url in source.resource_urls
        }
        if any(citation.source_url not in interval_by_url for citation in citations):
            return KnowledgeFreshness(status="UNAVAILABLE")
        checked_at = self._clock()
        stale = any(
            checked_at - citation.collected_at
            > timedelta(hours=interval_by_url[citation.source_url])
            for citation in citations
        )
        if stale:
            return KnowledgeFreshness(
                status="STALE",
                checked_at=checked_at,
                stale_reason="SOURCE_NOT_FRESH",
            )
        return KnowledgeFreshness(status="FRESH", checked_at=checked_at)


class RetrievalKnowledgeEvidenceProvider:
    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider,
        repository: KnowledgeSearchRepository,
        freshness_provider: KnowledgeFreshnessProvider,
        limit: int = 5,
        min_similarity: float = 0.0,
    ) -> None:
        if not 1 <= limit <= 20:
            raise ValueError("knowledge evidence limit must be between 1 and 20")
        if not -1 <= min_similarity <= 1:
            raise ValueError("knowledge evidence similarity must be between -1 and 1")
        self._embedding_provider = embedding_provider
        self._repository = repository
        self._freshness_provider = freshness_provider
        self._limit = limit
        self._min_similarity = min_similarity

    async def get_evidence(self, command: PlanningCreateCommand) -> KnowledgeEvidence:
        query = build_knowledge_query(command)
        if self._embedding_provider.model_name.startswith("demo-"):
            return _non_real_evidence(
                status="DEMO",
                query=query,
                message="演示向量不能作为生产知识引用依据",
            )

        try:
            vectors = await self._embedding_provider.embed_texts((query,))
            vector = _single_vector(vectors, self._embedding_provider)
            trip = command.payload.trip
            citations = await self._repository.search(
                KnowledgeSearchRequest(
                    city=trip.destination,
                    embedding=vector,
                    limit=self._limit,
                    min_similarity=self._min_similarity,
                    traveler_type=trip.constraints.traveler_type,
                    as_of=trip.start_date,
                )
            )
            if not citations:
                return _non_real_evidence(
                    status="UNAVAILABLE",
                    query=query,
                    message="没有找到满足条件的已发布知识引用",
                )
            freshness = await self._freshness_provider.assess(trip.destination, citations)
        except (EmbeddingProviderError, psycopg.Error):
            return _non_real_evidence(
                status="UNAVAILABLE",
                query=query,
                message="知识检索暂时不可用",
            )

        if freshness.status == "UNAVAILABLE":
            return _non_real_evidence(
                status="UNAVAILABLE",
                query=query,
                message="知识来源新鲜度暂时不可用",
            )
        return KnowledgeEvidence(
            status="REAL",
            query=query,
            citations=tuple(_snapshot(citation) for citation in citations),
            freshness=freshness,
        )


def build_knowledge_query(command: PlanningCreateCommand) -> str:
    trip = command.payload.trip
    terms = (trip.destination, *trip.constraints.preferences, trip.constraints.traveler_type)
    return " ".join(dict.fromkeys(terms))[:200].rstrip()


def _single_vector(
    vectors: tuple[EmbeddingVector, ...],
    provider: EmbeddingProvider,
) -> EmbeddingVector:
    if len(vectors) != 1:
        raise EmbeddingProviderError("embedding provider returned an unexpected vector count")
    vector = vectors[0]
    if vector.model_name != provider.model_name or len(vector.values) != provider.dimensions:
        raise EmbeddingProviderError("embedding provider returned an incompatible vector")
    return vector


def _snapshot(citation: KnowledgeCitation) -> KnowledgeCitationSnapshot:
    return KnowledgeCitationSnapshot(
        document_id=citation.document_id,
        document_version=citation.document_version,
        chunk_id=citation.chunk_id,
        chunk_index=citation.chunk_index,
        title=citation.title,
        source_url=citation.source_url,
        source_name=citation.source_name,
        collected_at=citation.collected_at,
        reliability_level=citation.reliability_level,
        similarity=citation.similarity,
    )


def _non_real_evidence(
    *,
    status: Literal["DEMO", "UNAVAILABLE"],
    query: str,
    message: str,
) -> KnowledgeEvidence:
    return KnowledgeEvidence(
        status=status,
        query=query,
        citations=(),
        freshness=KnowledgeFreshness(status="UNAVAILABLE"),
        message=message,
    )
