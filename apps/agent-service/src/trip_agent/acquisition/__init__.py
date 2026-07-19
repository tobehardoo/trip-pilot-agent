"""Controlled acquisition boundaries for official knowledge sources."""

from trip_agent.acquisition.fetching import (
    AcquisitionFetchError,
    FetchResult,
    FetchValidators,
    HttpResourceFetcher,
    ResourceFetched,
    ResourceNotModified,
)
from trip_agent.acquisition.models import DiscoveredResource, KnowledgeSource
from trip_agent.acquisition.registry import SourceCatalog

__all__ = [
    "AcquisitionFetchError",
    "DiscoveredResource",
    "FetchResult",
    "FetchValidators",
    "HttpResourceFetcher",
    "KnowledgeSource",
    "ResourceFetched",
    "ResourceNotModified",
    "SourceCatalog",
]
