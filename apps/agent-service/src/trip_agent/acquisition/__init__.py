"""Controlled acquisition boundaries for official knowledge sources."""

from trip_agent.acquisition.dns import HostResolver, SystemHostResolver
from trip_agent.acquisition.fetch_models import (
    AcquisitionFetchError,
    FetchResult,
    FetchValidators,
    ResourceFetched,
    ResourceNotModified,
)
from trip_agent.acquisition.fetching import HttpResourceFetcher
from trip_agent.acquisition.models import DiscoveredResource, KnowledgeSource
from trip_agent.acquisition.registry import SourceCatalog

__all__ = [
    "AcquisitionFetchError",
    "DiscoveredResource",
    "FetchResult",
    "FetchValidators",
    "HttpResourceFetcher",
    "HostResolver",
    "KnowledgeSource",
    "ResourceFetched",
    "ResourceNotModified",
    "SourceCatalog",
    "SystemHostResolver",
]
