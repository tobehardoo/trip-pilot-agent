"""TOML-backed source registry with deterministic validation."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from trip_agent.acquisition.models import KnowledgeSource
from trip_agent.acquisition.security import SourceSecurityError


class SourceConfigurationError(ValueError):
    """Raised when source configuration cannot be safely loaded."""


@dataclass(frozen=True, slots=True)
class SourceCatalog:
    sources: tuple[KnowledgeSource, ...]

    @classmethod
    def load_directory(cls, directory: Path) -> "SourceCatalog":
        if not directory.exists() or not directory.is_dir():
            raise SourceConfigurationError(f"source directory does not exist: {directory}")
        paths = tuple(sorted(directory.glob("*.toml")))
        if not paths:
            raise SourceConfigurationError(f"source directory contains no TOML files: {directory}")

        sources: list[KnowledgeSource] = []
        for path in paths:
            sources.extend(_load_file(path))

        source_ids = [source.source_id for source in sources]
        if len(source_ids) != len(set(source_ids)):
            raise SourceConfigurationError("duplicate source_id in source registry")
        resource_urls = [url for source in sources for url in source.resource_urls]
        if len(resource_urls) != len(set(resource_urls)):
            raise SourceConfigurationError("duplicate resource URL in source registry")
        return cls(sources=tuple(sorted(sources, key=lambda source: source.source_id)))

    def for_city(self, city: str) -> tuple[KnowledgeSource, ...]:
        normalized_city = city.strip()
        return tuple(source for source in self.sources if source.city == normalized_city)


def _load_file(path: Path) -> tuple[KnowledgeSource, ...]:
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise SourceConfigurationError(f"cannot read source file {path.name}: {error}") from error
    records = payload.get("sources")
    if not isinstance(records, list) or not records:
        raise SourceConfigurationError(f"source file has no sources array: {path.name}")

    sources: list[KnowledgeSource] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise SourceConfigurationError(f"source record {index} is not a table: {path.name}")
        try:
            sources.append(KnowledgeSource(**record))
        except SourceSecurityError as error:
            raise SourceConfigurationError(
                f"invalid source record {index} in {path.name}: {error}"
            ) from error
        except (TypeError, ValueError) as error:
            raise SourceConfigurationError(
                f"invalid source record {index} in {path.name}: {error}"
            ) from error
    return tuple(sources)
