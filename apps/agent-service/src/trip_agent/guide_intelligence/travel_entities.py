"""Typed travel entities with explicit provenance, freshness, and UNKNOWN values."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, TypeVar

type TravelSourceType = Literal[
    "PROVIDER", "OFFICIAL", "GUIDE", "USER", "ESTIMATED", "DERIVED"
]
type FactStatus = Literal["KNOWN", "UNKNOWN"]

FactT = TypeVar("FactT")


@dataclass(frozen=True, slots=True)
class FactProvenance:
    source: str
    source_type: TravelSourceType
    fetched_at: datetime
    valid_until: datetime
    confidence: float

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("fact source cannot be empty")
        if self.fetched_at.tzinfo is None or self.fetched_at.utcoffset() is None:
            raise ValueError("fact fetched_at must be timezone-aware")
        if self.valid_until <= self.fetched_at:
            raise ValueError("fact valid_until must be after fetched_at")
        if not 0 <= self.confidence <= 1:
            raise ValueError("fact confidence must be between zero and one")


@dataclass(frozen=True, slots=True)
class FactValue[FactT]:
    value: FactT | None
    provenance: FactProvenance | None
    status: FactStatus

    @classmethod
    def known(cls, value: FactT, provenance: FactProvenance) -> "FactValue[FactT]":
        return cls(value=value, provenance=provenance, status="KNOWN")

    @classmethod
    def unknown(cls) -> "FactValue[FactT]":
        return cls(value=None, provenance=None, status="UNKNOWN")

    def at(self, checked_at: datetime) -> "FactValue[FactT]":
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise ValueError("fact lookup time must be timezone-aware")
        if (
            self.status != "KNOWN"
            or self.provenance is None
            or checked_at >= self.provenance.valid_until
        ):
            return FactValue.unknown()
        return self


@dataclass(frozen=True, slots=True)
class TravelEntityLocation:
    longitude: float
    latitude: float
    address: str


@dataclass(frozen=True, slots=True)
class Attraction:
    city_adcode: str | None
    provider_poi_id: str
    name: str
    category: str
    location: TravelEntityLocation
    opening_hours: FactValue[str]
    recommended_duration_minutes: FactValue[int]
    ticket_price: FactValue[str]
    reservation_required: FactValue[bool]
    closed_dates: FactValue[tuple[date, ...]]
    temporary_closure: FactValue[str]
    popularity: FactValue[float]
    official_url: FactValue[str]


@dataclass(frozen=True, slots=True)
class Restaurant:
    city_adcode: str
    provider_poi_id: str
    name: str
    cuisine: FactValue[str]
    location: TravelEntityLocation
    opening_hours: FactValue[str]
    price_per_person: FactValue[str]
    meal_suitability: FactValue[tuple[str, ...]]
    rating: FactValue[float]


@dataclass(frozen=True, slots=True)
class HotelContext:
    city_adcode: str
    location: TravelEntityLocation
    district: FactValue[str]
    nearby_transit: FactValue[tuple[str, ...]]
    nearby_attractions: FactValue[tuple[str, ...]]
    travel_time_to_clusters: FactValue[dict[str, int]]


@dataclass(frozen=True, slots=True)
class CityKnowledge:
    city_adcode: str
    city_name: str
    core_areas: FactValue[tuple[str, ...]]
    commercial_areas: FactValue[tuple[str, ...]]
    historic_areas: FactValue[tuple[str, ...]]
    attraction_clusters: FactValue[tuple[str, ...]]
    nightlife_areas: FactValue[tuple[str, ...]]
    breakfast_areas: FactValue[tuple[str, ...]]
    transport_hubs: FactValue[tuple[str, ...]]


def build_attraction(
    *,
    city_adcode: str | None,
    provider_poi_id: str,
    name: str,
    category: str,
    location: TravelEntityLocation,
    opening_hours: FactValue[str] | None = None,
    recommended_duration_minutes: FactValue[int] | None = None,
    ticket_price: FactValue[str] | None = None,
    reservation_required: FactValue[bool] | None = None,
    closed_dates: FactValue[tuple[date, ...]] | None = None,
    temporary_closure: FactValue[str] | None = None,
    popularity: FactValue[float] | None = None,
    official_url: FactValue[str] | None = None,
) -> Attraction:
    if city_adcode is not None and (len(city_adcode) != 6 or not city_adcode.isdecimal()):
        raise ValueError("city_adcode must be a six digit administrative code")
    if not provider_poi_id.strip() or not name.strip() or not category.strip():
        raise ValueError("attraction identity fields cannot be empty")
    unknown = FactValue.unknown
    return Attraction(
        city_adcode=city_adcode,
        provider_poi_id=provider_poi_id,
        name=name,
        category=category,
        location=location,
        opening_hours=opening_hours or unknown(),
        recommended_duration_minutes=recommended_duration_minutes or unknown(),
        ticket_price=ticket_price or unknown(),
        reservation_required=reservation_required or unknown(),
        closed_dates=closed_dates or unknown(),
        temporary_closure=temporary_closure or unknown(),
        popularity=popularity or unknown(),
        official_url=official_url or unknown(),
    )


def attraction_cache_key(
    *, city_adcode: str, provider: str, query: str, as_of: str
) -> str:
    if len(city_adcode) != 6 or not city_adcode.isdecimal():
        raise ValueError("city_adcode must be a six digit administrative code")
    normalized_query = "-".join(query.casefold().split()) or "all"
    provider_key = provider.strip().upper()
    return (
        f"travel-intel:v1:attraction:{city_adcode}:"
        f"{provider_key}:{normalized_query}:{as_of}"
    )
