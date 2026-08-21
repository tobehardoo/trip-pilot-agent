"""Shared domain utilities — timezone, text matching, coordinate and schedule helpers.

These were previously scattered across worker/contracts.py, worker/processor.py,
and planning/optimization.py.  Consolidating them here eliminates drift and allows
provider implementations to be extracted without circular imports.
"""

import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from math import cos, radians, sqrt
from typing import TYPE_CHECKING, Literal
from unicodedata import normalize
from uuid import UUID

if TYPE_CHECKING:
    from trip_agent.providers.map import Poi
    from trip_agent.worker.contracts import PlanningCreateCommand

# All trip dates use China Standard Time (Asia/Shanghai, UTC+8).
CHINA_TIME_ZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")

# Shared schedule-model literal types (single source for contracts and the
# pure daily-schedule module).
type DayType = Literal["ARRIVAL_DAY", "FULL_DAY", "DEPARTURE_DAY", "SPECIAL_ACTIVITY_DAY"]
type ActivityKind = Literal[
    "ATTRACTION", "EXPERIENCE", "MEAL", "ACCOMMODATION", "ARRIVAL", "DEPARTURE"
]
type Magnitude = Literal["LIGHT", "NORMAL", "HALF_DAY", "FULL_DAY"]
type Pace = Literal["RELAXED", "BALANCED", "INTENSIVE"]
type MealType = Literal["LUNCH", "DINNER"]

# Planning constants — upper bounds set by external API budgets and trip limits.
COORDINATE_SCALE = Decimal("0.0000001")
DEFAULT_POI_KEYWORDS: tuple[str, ...] = ("景点", "博物馆", "公园", "美食")
MAX_POI_QUERIES = 6
MAX_TRIP_DAYS = 7
AMAP_ACTIVITY_ESTIMATED_COST = Decimal("100.00")

# Derived planning budget constants — upper bounds on computational effort.
MAX_ROUTE_CALLS_PER_PLAN = 96

_PLACE_DETAIL_SEPARATOR = re.compile(r"[\(\uff08\-\u2013\u2014_/]")
_PLACE_DETAIL_SUFFIXES = (
    "旅游区游客中心",
    "游客中心",
    "售票处",
    "停车场",
    "东广场",
    "西广场",
    "南广场",
    "北广场",
    "广场",
    "正门",
    "南门",
    "北门",
    "东门",
    "西门",
    "入口",
    "出口",
)
_PLACE_ZONE_SUFFIX = re.compile(r"(?:[a-z0-9]+|[一二三四五六七八九十]+)区$")
_SAME_PLACE_MAX_DISTANCE_KM = 0.5


def text_matches(expected: str, actual: str) -> bool:
    """Case‑folded, alphanumeric‑only substring match (bidirectional).

    Used by candidate ranking to compare place names and by the planning
    pipeline to match guide‑fact statements against candidate POIs.
    """
    expected_key = "".join(character for character in expected.casefold() if character.isalnum())
    actual_key = "".join(character for character in actual.casefold() if character.isalnum())
    return bool(expected_key) and (expected_key in actual_key or actual_key in expected_key)


def normalize_text(value: str) -> str:
    """Case‑folded, alphanumeric‑only representation.

    Used by Pydantic validators in message contracts for fuzzy comparison.
    """
    return "".join(character for character in value.casefold() if character.isalnum())


def canonical_place_name(name: str) -> str:
    """Return the stable parent-place name used for semantic comparison."""
    nfkc_name = normalize("NFKC", name).strip()
    base_name = _PLACE_DETAIL_SEPARATOR.split(nfkc_name, maxsplit=1)[0]
    base_key = normalize_text(base_name)
    for suffix in _PLACE_DETAIL_SUFFIXES:
        suffix_key = normalize_text(suffix)
        if base_key.endswith(suffix_key) and len(base_key) > len(suffix_key) + 1:
            base_key = base_key[: -len(suffix_key)]
            break
    if _PLACE_ZONE_SUFFIX.search(base_key):
        base_key = _PLACE_ZONE_SUFFIX.sub("", base_key)
    if base_key.endswith("祠堂") and len(base_key) > 2:
        base_key = f"{base_key[:-2]}祠"
    return base_key


def _place_category(type_code: str) -> str:
    digits = "".join(character for character in type_code if character.isdigit())
    family = digits[:2]
    if family == "15":
        return "transport"
    if family in {"05", "06"}:
        return "food"
    if family == "10":
        return "accommodation"
    return "activity"


def mapped_places_match(
    left_name: str,
    left_type_code: str,
    left_longitude: Decimal | float,
    left_latitude: Decimal | float,
    right_name: str,
    right_type_code: str,
    right_longitude: Decimal | float,
    right_latitude: Decimal | float,
) -> bool:
    """Return whether two provider records describe the same mapped place.

    Parent attractions, plazas and named halls can have different provider
    IDs and category codes.  A canonical name plus a real distance check
    handles those records while keeping a nearby transport child distinct.
    Non-transport category codes are not authoritative enough to separate a
    parent place: AMap can classify the same attraction plaza as a shopping
    centre.  For attraction records, a nearby longer name beginning with the
    exact parent name is also a sub-place; canonical name and distance remain
    the decisive signals.
    """
    left_key = canonical_place_name(left_name)
    right_key = canonical_place_name(right_name)
    left_category = _place_category(left_type_code)
    right_category = _place_category(right_type_code)
    same_name = left_key == right_key
    attraction_subplace = (
        left_category == right_category == "activity"
        and min(len(left_key), len(right_key)) >= 3
        and (left_key.startswith(right_key) or right_key.startswith(left_key))
    )
    if not same_name and not attraction_subplace:
        return False
    if "transport" in {left_category, right_category} and left_category != right_category:
        return False
    left_lon = float(left_longitude)
    left_lat = float(left_latitude)
    right_lon = float(right_longitude)
    right_lat = float(right_latitude)
    mean_latitude = radians((left_lat + right_lat) / 2)
    longitude_delta = radians(right_lon - left_lon) * cos(mean_latitude)
    latitude_delta = radians(right_lat - left_lat)
    distance_km = 6371.0088 * sqrt(longitude_delta**2 + latitude_delta**2)
    return distance_km <= _SAME_PLACE_MAX_DISTANCE_KM


def canonical_place_identity(
    name: str,
    type_code: str,
    longitude: Decimal | float,
    latitude: Decimal | float,
) -> str:
    """Return a conservative, hashable identity for a mapped place.

    Provider records frequently split one attraction into a parent, gates,
    plazas and named halls with different provider IDs.  Only explicit detail
    separators and a small allow-list of facility suffixes are collapsed.  A
    provider taxonomy family and a roughly one-kilometre coordinate cell stay
    in the key, so a metro/bus child can never satisfy an attraction visit and
    similarly named places in different areas remain distinct.
    """
    base_key = canonical_place_name(name)
    taxonomy_family = _place_category(type_code)
    coordinate_scale = Decimal("0.01")
    lon = Decimal(str(longitude)).quantize(coordinate_scale)
    lat = Decimal(str(latitude)).quantize(coordinate_scale)
    return f"{taxonomy_family}:{base_key}:{lon}:{lat}"


def available_minutes(
    trip_date: date,
    start_date: date,
    end_date: date,
    arrival: datetime | None,
    departure: datetime | None,
) -> tuple[int, int]:
    """Compute the available time window (in minutes from midnight) for a trip day.

    Defaults to 09:00–18:00, tightened by arrival/departure times on the first
    and last day respectively.
    """
    start_minute = 9 * 60
    end_minute = 18 * 60
    if trip_date == start_date and arrival is not None:
        local_arrival = arrival.astimezone(CHINA_TIME_ZONE)
        start_minute = max(start_minute, local_arrival.hour * 60 + local_arrival.minute)
    if trip_date == end_date and departure is not None:
        local_departure = departure.astimezone(CHINA_TIME_ZONE)
        end_minute = min(end_minute, local_departure.hour * 60 + local_departure.minute)
    return start_minute, end_minute


def minute_datetime(day: date, minute_of_day: int) -> datetime:
    """Convert a date and minute-of-day offset to a China-timezone-aware datetime."""
    return datetime.combine(day, time.min, tzinfo=CHINA_TIME_ZONE) + timedelta(
        minutes=minute_of_day
    )


def coordinate_decimal(value: float) -> Decimal:
    """Quantize a float coordinate to the project's standard scale."""
    return Decimal(str(value)).quantize(COORDINATE_SCALE)


def candidate_keywords(
    preferences: tuple[str, ...],
    must_visit_places: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Build an ordered, deduplicated keyword list for progressive POI search."""
    return tuple(dict.fromkeys((*must_visit_places, *preferences, *DEFAULT_POI_KEYWORDS)))[
        :MAX_POI_QUERIES
    ]


def snapshot_boundary_times(trip: object) -> tuple[datetime | None, datetime | None]:
    """B13_FIX R1 (P0-1): authoritative boundary times from the snapshot.

    Snapshot ``arrival_at``/``departure_at`` are the single authority for
    when the traveller arrives/leaves.  Legacy commands (v1–v3, or v4 with
    null fields) fall back to the legacy constraint anchor times so old
    behaviour is preserved — never both at once, never fabricated.
    """
    arrival_at = getattr(trip, "arrival_at", None)
    departure_at = getattr(trip, "departure_at", None)
    constraints = getattr(trip, "constraints", None)
    if arrival_at is None and constraints is not None:
        anchor = getattr(constraints, "arrival", None)
        if anchor is not None:
            arrival_at = getattr(anchor, "time", None)
    if departure_at is None and constraints is not None:
        anchor = getattr(constraints, "departure", None)
        if anchor is not None:
            departure_at = getattr(anchor, "time", None)
    return arrival_at, departure_at


def matched_guide_fact_ids(
    command: "PlanningCreateCommand",
    pois: tuple["Poi", ...],
) -> tuple[UUID, ...]:
    """Return guide-fact IDs whose statements matched any of the selected POIs."""
    from trip_agent.planning.candidates import (  # noqa: PLC0415
        is_adverse_weather_statement,
        is_positive_guide_statement,
    )

    return tuple(
        fact.fact_id
        for fact in command.payload.guide_evidence.facts
        if (
            fact.category == "WEATHER"
            and fact.effective_date is not None
            and command.payload.trip.start_date
            <= fact.effective_date
            <= command.payload.trip.end_date
            and is_adverse_weather_statement(f"{fact.statement} {fact.evidence}")
        )
        or (
            is_positive_guide_statement(f"{fact.statement} {fact.evidence}")
            and any(text_matches(poi.name, f"{fact.statement} {fact.evidence}") for poi in pois)
        )
    )
