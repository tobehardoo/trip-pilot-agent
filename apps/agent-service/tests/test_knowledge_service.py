import asyncio
from dataclasses import dataclass, field
from textwrap import dedent
from typing import Any

from trip_agent.retrieval.documents import parse_markdown_document
from trip_agent.retrieval.embeddings import EmbeddingVector
from trip_agent.retrieval.service import KnowledgeImporter

MARKDOWN = dedent(
    """
    +++
    document_id = "guangzhou-food"
    city = "广州"
    category = "food"
    title = "西关饮食"
    source_url = "https://example.com/guangzhou/food"
    source_name = "广州文旅"
    collected_at = "2026-07-19T08:00:00+08:00"
    reliability_level = "CURATED"
    version = 1
    +++

    # 西关饮食

    西关片区适合安排早茶和传统小吃。
    """
).strip()


@dataclass
class RecordingRepository:
    calls: list[tuple[Any, tuple[Any, ...]]] = field(default_factory=list)

    async def save_document(self, document: Any, chunks: tuple[Any, ...]) -> str:
        self.calls.append((document, chunks))
        return "created"


class FixedEmbeddingProvider:
    model_name = "test-embedding"
    dimensions = 3

    async def embed_texts(self, texts: tuple[str, ...]) -> tuple[EmbeddingVector, ...]:
        return tuple(
            EmbeddingVector(values=(float(index + 1), 0.0, 0.0), model_name=self.model_name)
            for index, _ in enumerate(texts)
        )


def test_importer_chunks_and_embeds_before_persisting() -> None:
    repository = RecordingRepository()
    importer = KnowledgeImporter(
        repository=repository,
        embedding_provider=FixedEmbeddingProvider(),
        max_characters=100,
        overlap_characters=10,
    )

    result = asyncio.run(importer.import_markdown(MARKDOWN))

    assert result.status == "created"
    assert result.document_id == "guangzhou-food"
    assert len(repository.calls) == 1
    document, chunks = repository.calls[0]
    assert document.city == "广州"
    assert len(chunks) == 1
    assert chunks[0].embedding is not None
    assert chunks[0].embedding.model_name == "test-embedding"


def test_importer_keeps_repository_idempotency_result() -> None:
    class IdempotentRepository(RecordingRepository):
        async def save_document(self, document: Any, chunks: tuple[Any, ...]) -> str:
            self.calls.append((document, chunks))
            return "unchanged"

    repository = IdempotentRepository()
    importer = KnowledgeImporter(repository=repository, embedding_provider=FixedEmbeddingProvider())

    result = asyncio.run(importer.import_document(parse_markdown_document(MARKDOWN)))

    assert result.status == "unchanged"
