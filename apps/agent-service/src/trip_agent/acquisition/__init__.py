"""Controlled acquisition boundaries for official knowledge sources."""

from trip_agent.acquisition.models import DiscoveredResource, KnowledgeSource
from trip_agent.acquisition.registry import SourceCatalog

__all__ = ["DiscoveredResource", "KnowledgeSource", "SourceCatalog"]
