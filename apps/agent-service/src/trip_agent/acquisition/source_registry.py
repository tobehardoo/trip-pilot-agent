"""City -> source-configuration registry (M0 second trusted source).

Reuses the existing :class:`KnowledgeSource` shape (``acquisition.models``) and
the TOML-backed :class:`SourceCatalog` loader, and is wire-compatible with
``fetching.HttpResourceFetcher`` / ``repository.PsycopgAcquisitionRepository``
through the pure resource discovery below (no network here).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from trip_agent.acquisition.models import DiscoveredResource, KnowledgeSource
from trip_agent.acquisition.registry import SourceCatalog


@dataclass(frozen=True, slots=True)
class SourceRegistry:
    catalog: SourceCatalog

    @classmethod
    def load(cls, directory: Path) -> SourceRegistry:
        return cls(catalog=SourceCatalog.load_directory(directory))

    @classmethod
    def from_catalog(cls, catalog: SourceCatalog) -> SourceRegistry:
        return cls(catalog=catalog)

    def sources(self) -> tuple[KnowledgeSource, ...]:
        return self.catalog.sources

    def sources_for_city(self, city: str) -> tuple[KnowledgeSource, ...]:
        return self.catalog.for_city(city)

    def source_by_id(self, source_id: str) -> KnowledgeSource | None:
        for source in self.catalog.sources:
            if source.source_id == source_id:
                return source
        return None

    def reliability_for(self, source_id: str) -> str | None:
        source = self.source_by_id(source_id)
        return source.reliability_level if source is not None else None


def discover_resources(source: KnowledgeSource) -> tuple[DiscoveredResource, ...]:
    """Map a source's configured URLs to fetcher-ready resources.

    Pure adapter so a caller can feed these straight to
    ``HttpResourceFetcher.fetch(source=..., resource=...)`` or persist via
    ``PsycopgAcquisitionRepository`` without re-deriving identity.
    """
    return tuple(
        DiscoveredResource(
            source_id=source.source_id,
            city=source.city,
            url=url,
        )
        for url in source.resource_urls
    )