"""Knowledge ingestion use case independent from storage and model providers."""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from trip_agent.retrieval.documents import (
    KnowledgeChunk,
    KnowledgeDocument,
    chunk_document,
    parse_markdown_document,
)
from trip_agent.retrieval.embeddings import EmbeddingProvider

type ImportStatus = Literal["created", "embedded", "unchanged"]


class KnowledgeRepository(Protocol):
    async def save_document(
        self,
        document: KnowledgeDocument,
        chunks: tuple[KnowledgeChunk, ...],
    ) -> ImportStatus: ...


class KnowledgeImportResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    version: int
    chunk_count: int
    status: ImportStatus


class KnowledgeImporter:
    def __init__(
        self,
        *,
        repository: KnowledgeRepository,
        embedding_provider: EmbeddingProvider,
        max_characters: int = 1000,
        overlap_characters: int = 100,
    ) -> None:
        self._repository = repository
        self._embedding_provider = embedding_provider
        self._max_characters = max_characters
        self._overlap_characters = overlap_characters

    async def import_markdown(self, markdown: str) -> KnowledgeImportResult:
        return await self.import_document(parse_markdown_document(markdown))

    async def import_document(self, document: KnowledgeDocument) -> KnowledgeImportResult:
        chunks = chunk_document(
            document,
            max_characters=self._max_characters,
            overlap_characters=self._overlap_characters,
        )
        vectors = await self._embedding_provider.embed_texts(
            tuple(chunk.content for chunk in chunks)
        )
        if len(vectors) != len(chunks):
            raise ValueError("embedding provider returned an unexpected vector count")
        if any(len(vector.values) != self._embedding_provider.dimensions for vector in vectors):
            raise ValueError("embedding provider returned an unexpected vector dimension")
        if any(vector.model_name != self._embedding_provider.model_name for vector in vectors):
            raise ValueError("embedding provider returned an unexpected model name")

        embedded_chunks = tuple(
            chunk.model_copy(update={"embedding": vector})
            for chunk, vector in zip(chunks, vectors, strict=True)
        )
        status = await self._repository.save_document(document, embedded_chunks)
        return KnowledgeImportResult(
            document_id=document.document_id,
            version=document.version,
            chunk_count=len(embedded_chunks),
            status=status,
        )
