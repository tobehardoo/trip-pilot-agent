"""Trip-scoped intelligence extracted from user-submitted public guide URLs."""

from trip_agent.guide_intelligence.extraction import GenericGuideExtractor
from trip_agent.guide_intelligence.models import ExtractedGuide, GuideImportResult, TravelFact
from trip_agent.guide_intelligence.service import GuideImportService
from trip_agent.guide_intelligence.travel_entities import (
    Attraction,
    CityKnowledge,
    FactProvenance,
    FactValue,
    HotelContext,
    Restaurant,
    TravelEntityLocation,
    attraction_cache_key,
)

__all__ = [
    "ExtractedGuide",
    "GenericGuideExtractor",
    "GuideImportResult",
    "GuideImportService",
    "TravelFact",
    "Attraction",
    "CityKnowledge",
    "FactProvenance",
    "FactValue",
    "HotelContext",
    "Restaurant",
    "TravelEntityLocation",
    "attraction_cache_key",
]
