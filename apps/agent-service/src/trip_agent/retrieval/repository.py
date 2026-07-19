"""PostgreSQL/pgvector repository for immutable city knowledge snapshots."""

import asyncio
import hashlib
from datetime import date, datetime
from pathlib import Path
from typing import Literal

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from trip_agent.retrieval.documents import (
    ApplicableSeason,
    KnowledgeCategory,
    KnowledgeChunk,
    KnowledgeDocument,
    TravelerType,
    document_version_fingerprint,
)
from trip_agent.retrieval.embeddings import EmbeddingVector

type ImportStatus = Literal["created", "embedded", "unchanged"]


class KnowledgeVersionConflict(ValueError):
    """Raised when an immutable document version is imported with new content."""


class KnowledgeSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    city: str
    embedding: EmbeddingVector
    limit: int = Field(default=10, strict=True, ge=1, le=50)
    min_similarity: float = Field(default=0.0, ge=-1.0, le=1.0)
    category: KnowledgeCategory | None = None
    applicable_season: ApplicableSeason | None = None
    traveler_type: TravelerType | None = None
    as_of: date = Field(default_factory=date.today)


class KnowledgeCitation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str
    document_id: str
    document_version: int
    chunk_index: int
    city: str
    category: KnowledgeCategory
    title: str
    content: str
    source_url: str
    source_name: str
    reliability_level: str
    collected_at: datetime
    similarity: float


class PsycopgKnowledgeRepository:
    """Sync Psycopg adapter exposed as async methods for worker composition."""

    _migration_directory = Path(__file__).with_name("migrations")

    def __init__(self, database_url: str) -> None:
        if not database_url.strip():
            raise ValueError("knowledge database URL cannot be empty")
        self._database_url = database_url.strip()

    async def migrate(self) -> None:
        await asyncio.to_thread(self._migrate_sync)

    async def save_document(
        self,
        document: KnowledgeDocument,
        chunks: tuple[KnowledgeChunk, ...],
    ) -> ImportStatus:
        return await asyncio.to_thread(self._save_document_sync, document, chunks)

    async def search(self, request: KnowledgeSearchRequest) -> tuple[KnowledgeCitation, ...]:
        return await asyncio.to_thread(self._search_sync, request)

    def _connect(self, *, register_types: bool = True) -> psycopg.Connection:
        connection = psycopg.connect(self._database_url, row_factory=dict_row)
        if register_types:
            register_vector(connection)
        return connection

    def _migrate_sync(self) -> None:
        migrations = sorted(
            self._migration_directory.glob("V*__*.sql"),
            key=self._migration_number,
        )
        if not migrations:
            raise RuntimeError("knowledge migration directory is empty")

        with self._connect(register_types=False) as connection:
            vector_type = connection.execute(
                "SELECT to_regtype('vector') AS vector_type"
            ).fetchone()
            if vector_type is None or vector_type["vector_type"] is None:
                raise RuntimeError("pgvector extension must be installed before migration")
            register_vector(connection)
            connection.execute("CREATE SCHEMA IF NOT EXISTS agent")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent.knowledge_schema_migration (
                    version TEXT PRIMARY KEY,
                    checksum CHAR(64) NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            for migration in migrations:
                version = migration.name.split("__", maxsplit=1)[0]
                checksum = hashlib.sha256(migration.read_bytes()).hexdigest()
                existing = connection.execute(
                    "SELECT checksum FROM agent.knowledge_schema_migration WHERE version = %s",
                    (version,),
                ).fetchone()
                if existing:
                    if existing["checksum"] != checksum:
                        raise RuntimeError(f"knowledge migration checksum mismatch: {version}")
                    continue
                connection.execute(migration.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO agent.knowledge_schema_migration "
                    "(version, checksum) VALUES (%s, %s)",
                    (version, checksum),
                )

    def _save_document_sync(
        self,
        document: KnowledgeDocument,
        chunks: tuple[KnowledgeChunk, ...],
    ) -> ImportStatus:
        self._validate_chunks(document, chunks)
        version_fingerprint = document_version_fingerprint(document)
        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT version_fingerprint FROM agent.knowledge_document
                WHERE document_id = %s AND version = %s
                """,
                (document.document_id, document.version),
            ).fetchone()
            if existing:
                if existing["version_fingerprint"] != version_fingerprint:
                    raise KnowledgeVersionConflict(
                        f"document {document.document_id} version {document.version} is immutable"
                    )
                self._validate_existing_chunks(connection, document, chunks)
                inserted_embeddings = self._save_embeddings(connection, chunks)
                return "embedded" if inserted_embeddings else "unchanged"

            connection.execute(
                """
                INSERT INTO agent.knowledge_document (
                    document_id, version, city, category, title, content, content_hash,
                    version_fingerprint,
                    source_url, source_name, published_at, collected_at, valid_from, valid_to,
                    applicable_seasons, traveler_types, reliability_level
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    document.document_id,
                    document.version,
                    document.city,
                    document.category,
                    document.title,
                    document.content,
                    document.content_hash,
                    version_fingerprint,
                    str(document.source_url),
                    document.source_name,
                    document.published_at,
                    document.collected_at,
                    document.valid_from,
                    document.valid_to,
                    list(document.applicable_seasons),
                    list(document.traveler_types),
                    document.reliability_level,
                ),
            )
            for chunk in chunks:
                connection.execute(
                    """
                    INSERT INTO agent.knowledge_chunk (
                        chunk_id, document_id, document_version, chunk_index, heading_path,
                        chunk_content, content_hash, token_count, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        chunk.chunk_id,
                        chunk.document_id,
                        chunk.document_version,
                        chunk.chunk_index,
                        list(chunk.heading_path),
                        chunk.content,
                        chunk.content_hash,
                        chunk.token_count,
                        Jsonb({"heading_path": list(chunk.heading_path)}),
                    ),
                )
            self._save_embeddings(connection, chunks)
        return "created"

    @staticmethod
    def _validate_existing_chunks(
        connection: psycopg.Connection,
        document: KnowledgeDocument,
        chunks: tuple[KnowledgeChunk, ...],
    ) -> None:
        rows = connection.execute(
            """
            SELECT chunk_id, chunk_index, content_hash
            FROM agent.knowledge_chunk
            WHERE document_id = %s AND document_version = %s
            ORDER BY chunk_index
            """,
            (document.document_id, document.version),
        ).fetchall()
        existing_layout = tuple(
            (row["chunk_id"], row["chunk_index"], row["content_hash"]) for row in rows
        )
        requested_layout = tuple(
            (chunk.chunk_id, chunk.chunk_index, chunk.content_hash) for chunk in chunks
        )
        if existing_layout != requested_layout:
            raise KnowledgeVersionConflict(
                f"document {document.document_id} version {document.version} chunk layout changed"
            )

    @staticmethod
    def _save_embeddings(
        connection: psycopg.Connection,
        chunks: tuple[KnowledgeChunk, ...],
    ) -> int:
        inserted = 0
        for chunk in chunks:
            vector = chunk.embedding
            if vector is None:
                raise ValueError("knowledge chunks must be embedded before persistence")
            row = connection.execute(
                """
                INSERT INTO agent.knowledge_chunk_embedding (
                    chunk_id, embedding_model, embedding_dimensions, embedding
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT (chunk_id, embedding_model, embedding_dimensions) DO NOTHING
                RETURNING chunk_id
                """,
                (
                    chunk.chunk_id,
                    vector.model_name,
                    len(vector.values),
                    Vector(list(vector.values)),
                ),
            ).fetchone()
            inserted += row is not None
        return inserted

    def _search_sync(self, request: KnowledgeSearchRequest) -> tuple[KnowledgeCitation, ...]:
        category_values = [request.category] if request.category else None
        vector = Vector(list(request.embedding.values))
        with self._connect() as connection:
            rows = connection.execute(
                """
                WITH valid_versions AS (
                    SELECT
                        d.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY d.document_id
                            ORDER BY d.version DESC
                        ) AS version_rank
                    FROM agent.knowledge_document d
                    WHERE (d.valid_from IS NULL OR d.valid_from <= %s)
                      AND (d.valid_to IS NULL OR d.valid_to >= %s)
                ),
                current_documents AS (
                    SELECT *
                    FROM valid_versions d
                    WHERE d.version_rank = 1
                      AND d.city = %s
                      AND (%s::text[] IS NULL OR d.category = ANY(%s::text[]))
                      AND (
                          %s::text IS NULL
                          OR cardinality(d.applicable_seasons) = 0
                          OR 'all' = ANY(d.applicable_seasons)
                          OR %s::text = ANY(d.applicable_seasons)
                      )
                      AND (
                          %s::text IS NULL
                          OR cardinality(d.traveler_types) = 0
                          OR %s::text = ANY(d.traveler_types)
                      )
                ),
                ranked AS (
                    SELECT
                        c.chunk_id, c.document_id, c.document_version, c.chunk_index,
                        d.city, d.category, d.title, c.chunk_content AS content, d.source_url,
                        d.source_name, d.reliability_level, d.collected_at,
                        1 - (e.embedding <=> %s) AS similarity
                    FROM agent.knowledge_chunk c
                    JOIN current_documents d
                      ON d.document_id = c.document_id
                     AND d.version = c.document_version
                    JOIN agent.knowledge_chunk_embedding e
                      ON e.chunk_id = c.chunk_id
                    WHERE e.embedding_model = %s
                      AND e.embedding_dimensions = %s
                )
                SELECT * FROM ranked
                WHERE similarity >= %s
                ORDER BY similarity DESC, document_id ASC, document_version DESC, chunk_index ASC
                LIMIT %s
                """,
                (
                    request.as_of,
                    request.as_of,
                    request.city,
                    category_values,
                    category_values,
                    request.applicable_season,
                    request.applicable_season,
                    request.traveler_type,
                    request.traveler_type,
                    vector,
                    request.embedding.model_name,
                    len(request.embedding.values),
                    request.min_similarity,
                    request.limit,
                ),
            ).fetchall()
        return tuple(KnowledgeCitation.model_validate(row) for row in rows)

    @staticmethod
    def _validate_chunks(
        document: KnowledgeDocument,
        chunks: tuple[KnowledgeChunk, ...],
    ) -> None:
        if not chunks:
            raise ValueError("knowledge document must contain at least one chunk")
        indexes = tuple(chunk.chunk_index for chunk in chunks)
        if indexes != tuple(range(len(chunks))):
            raise ValueError("knowledge chunk indexes must be contiguous")
        if any(
            chunk.document_id != document.document_id or chunk.document_version != document.version
            for chunk in chunks
        ):
            raise ValueError("knowledge chunks must belong to the document version")
        if any(chunk.embedding is None for chunk in chunks):
            raise ValueError("knowledge chunks must be embedded before persistence")

    @staticmethod
    def _migration_number(path: Path) -> int:
        version = path.name.split("__", maxsplit=1)[0]
        number = version.removeprefix("V")
        if not number.isdigit():
            raise RuntimeError(f"invalid knowledge migration filename: {path.name}")
        return int(number)
