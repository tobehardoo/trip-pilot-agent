"""Validated Markdown knowledge documents and stable heading-aware chunking."""

import hashlib
import json
import re
import tomllib
from datetime import UTC, date, datetime
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)

from trip_agent.retrieval.embeddings import EmbeddingVector

type DocumentId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=100,
        pattern=r"^[a-z0-9][a-z0-9-]+$",
    ),
]
type KnowledgeCategory = Literal[
    "accommodation",
    "culture",
    "food",
    "poi",
    "season",
    "theme",
    "travel_tip",
]
type ReliabilityLevel = Literal["OFFICIAL", "CURATED", "COMMUNITY"]
type ApplicableSeason = Literal["all", "spring", "summer", "autumn", "winter"]
type TravelerType = Literal["SOLO", "COUPLE", "FAMILY", "FRIENDS", "BUSINESS"]
type NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_TOKEN_PATTERN = re.compile(r"[\u3400-\u9fff]|[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*")


class KnowledgeDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: DocumentId
    city: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    category: KnowledgeCategory
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    content: NonEmptyText
    content_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    source_url: HttpUrl
    source_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    published_at: date | None = None
    collected_at: datetime
    valid_from: date | None = None
    valid_to: date | None = None
    applicable_seasons: tuple[ApplicableSeason, ...] = ()
    traveler_types: tuple[TravelerType, ...] = ()
    reliability_level: ReliabilityLevel
    version: int = Field(strict=True, ge=1)

    @field_validator("collected_at")
    @classmethod
    def normalize_collected_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("collected_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_validity_order(self) -> "KnowledgeDocument":
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValueError("valid_from cannot be after valid_to")
        return self


class KnowledgeChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str
    document_id: DocumentId
    document_version: int = Field(strict=True, ge=1)
    chunk_index: int = Field(strict=True, ge=0)
    heading_path: tuple[str, ...]
    content: NonEmptyText
    content_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    token_count: int = Field(strict=True, ge=1)
    embedding: EmbeddingVector | None = None


def document_version_fingerprint(document: KnowledgeDocument) -> str:
    """Hash all immutable document metadata plus the normalized content hash."""

    payload = document.model_dump(mode="json", exclude={"content"})
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def parse_markdown_document(markdown: str) -> KnowledgeDocument:
    normalized = markdown.replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = normalized.splitlines()
    if not lines or lines[0].strip() != "+++":
        raise ValueError("knowledge Markdown must start with TOML front matter")

    try:
        closing_index = next(
            index for index, line in enumerate(lines[1:], start=1) if line.strip() == "+++"
        )
    except StopIteration as error:
        raise ValueError("knowledge Markdown front matter is not closed") from error

    front_matter = "\n".join(lines[1:closing_index])
    content = "\n".join(lines[closing_index + 1 :]).strip()
    if not content:
        raise ValueError("knowledge Markdown content cannot be empty")

    metadata = tomllib.loads(front_matter)
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return KnowledgeDocument.model_validate(
        {**metadata, "content": content, "content_hash": content_hash}
    )


def chunk_document(
    document: KnowledgeDocument,
    *,
    max_characters: int = 1000,
    overlap_characters: int = 100,
) -> tuple[KnowledgeChunk, ...]:
    if max_characters <= 0:
        raise ValueError("max_characters must be positive")
    if overlap_characters < 0 or overlap_characters >= max_characters:
        raise ValueError("overlap_characters must be between zero and max_characters")

    pieces = _heading_aware_pieces(
        document.content,
        max_characters=max_characters,
        overlap_characters=overlap_characters,
    )
    return tuple(
        _to_chunk(document=document, chunk_index=index, heading_path=headings, content=content)
        for index, (headings, content) in enumerate(pieces)
    )


def _heading_aware_pieces(
    content: str,
    *,
    max_characters: int,
    overlap_characters: int,
) -> tuple[tuple[tuple[str, ...], str], ...]:
    headings: list[str] = []
    paragraph_lines: list[str] = []
    blocks: list[tuple[tuple[str, ...], str]] = []

    def flush_paragraph() -> None:
        paragraph = " ".join(line.strip() for line in paragraph_lines if line.strip())
        if paragraph:
            blocks.append((tuple(headings), paragraph))
        paragraph_lines.clear()

    for line in content.splitlines():
        heading = _HEADING_PATTERN.match(line)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            headings[:] = headings[: level - 1]
            headings.append(heading.group(2).strip())
        elif not line.strip():
            flush_paragraph()
        else:
            paragraph_lines.append(line)
    flush_paragraph()

    pieces: list[tuple[tuple[str, ...], str]] = []
    for heading_path, paragraph in blocks:
        prefix = " > ".join(heading_path)
        separator = "\n\n" if prefix else ""
        available = max_characters - len(prefix) - len(separator)
        if available <= 0:
            raise ValueError("heading path is too long for max_characters")
        step = available - min(overlap_characters, max(0, available - 1))
        for start in range(0, len(paragraph), step):
            body = paragraph[start : start + available].strip()
            if body:
                pieces.append((heading_path, f"{prefix}{separator}{body}"))
            if start + available >= len(paragraph):
                break
    return tuple(pieces)


def _to_chunk(
    *,
    document: KnowledgeDocument,
    chunk_index: int,
    heading_path: tuple[str, ...],
    content: str,
) -> KnowledgeChunk:
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    chunk_id = str(
        uuid5(
            NAMESPACE_URL,
            f"trip-pilot:knowledge:{document.document_id}:{document.version}:{chunk_index}:{content_hash}",
        )
    )
    return KnowledgeChunk(
        chunk_id=chunk_id,
        document_id=document.document_id,
        document_version=document.version,
        chunk_index=chunk_index,
        heading_path=heading_path,
        content=content,
        content_hash=content_hash,
        token_count=len(_TOKEN_PATTERN.findall(content)),
    )
