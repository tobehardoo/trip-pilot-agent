"""Deterministic resource discovery adapters."""

from trip_agent.acquisition.models import DiscoveredResource, KnowledgeSource


class StaticUrlDiscoverer:
    """Discover only URLs explicitly approved in a source configuration."""

    def discover(self, source: KnowledgeSource) -> tuple[DiscoveredResource, ...]:
        return tuple(
            DiscoveredResource(source_id=source.source_id, city=source.city, url=url)
            for url in source.resource_urls
        )
