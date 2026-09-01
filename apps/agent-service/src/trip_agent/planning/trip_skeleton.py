"""B3 — Trip skeleton and the three-state accommodation domain foundation.

This module defines the immutable, planning-time domain aggregation that
links consecutive :class:`~trip_agent.planning.daily_schedule.DayPlan`
objects with explicit overnight accommodation semantics.  It is pure Python:
no clocks, UUIDs, providers, network, database or mutable state.

The three accommodation states are the only legal ways to express where a
traveller stays overnight:

* ``CONFIRMED`` — a real provider POI plus coordinates.
* ``AREA_ESTIMATED`` — a structured region estimate, never a fake hotel.
* ``UNRESOLVED`` — no locatable anchor; may still carry a requested label.

``None`` is never used to carry overnight semantics.  Illegal combinations
are unrepresentable at the type level instead of being guarded by many
optional fields.

B3 established the domain foundation; B4A added the AMap transient
projection (infrastructure/amap/accommodation_projection.py) and B4B added
the ROUTE_ENDPOINT_CONTINUITY / CROSS_DAY_CONTINUITY assessors in
feasibility/rules/continuity.py.  The skeleton itself remains a transient
Python planning aggregate: it has not entered the worker runtime, message
contracts, database or API.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum
from math import isfinite

from trip_agent.planning.daily_schedule import DayPlan


class AccommodationState(StrEnum):
    """The only three legal overnight accommodation semantics."""

    CONFIRMED = "CONFIRMED"
    AREA_ESTIMATED = "AREA_ESTIMATED"
    UNRESOLVED = "UNRESOLVED"


class AreaEstimateSource(StrEnum):
    """Where an AREA_ESTIMATED region claim comes from.

    B3 does not derive the source; callers must pass it explicitly.
    """

    USER_REGION = "USER_REGION"
    PROVIDER_DISTRICT = "PROVIDER_DISTRICT"
    DAY_PRIMARY_REGION = "DAY_PRIMARY_REGION"


def _normalise(value: str) -> str:
    return value.strip()


@dataclass(frozen=True, slots=True)
class GeoPoint:
    """A real, finite geographic point (a hotel coordinate or a region
    centroid).  Never NaN/Infinity, never bool, never out of range."""

    longitude: float
    latitude: float

    def __post_init__(self) -> None:
        if isinstance(self.longitude, bool) or isinstance(self.latitude, bool):
            raise ValueError("coordinates must be numbers, not booleans")
        if not isfinite(self.longitude) or not isfinite(self.latitude):
            raise ValueError("coordinates must be finite numbers")
        if not -180 <= self.longitude <= 180:
            raise ValueError("longitude must be within [-180, 180]")
        if not -90 <= self.latitude <= 90:
            raise ValueError("latitude must be within [-90, 90]")


@dataclass(frozen=True, slots=True)
class ConfirmedAccommodation:
    """A real, resolved hotel: a genuine provider POI plus coordinates.

    A name-only accommodation cannot be constructed as CONFIRMED — both
    ``provider_poi_id`` and ``coordinates`` are mandatory fields.
    """

    label: str
    provider_poi_id: str
    coordinates: GeoPoint
    region: str | None = None
    state: AccommodationState = field(
        default=AccommodationState.CONFIRMED,
        init=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.coordinates, GeoPoint):
            raise ValueError("coordinates must be a GeoPoint")
        if not self.label.strip():
            raise ValueError("label must not be empty")
        if not self.provider_poi_id.strip():
            raise ValueError("provider_poi_id must not be empty")
        if self.region is not None and not self.region.strip():
            raise ValueError("region must not be empty")
        object.__setattr__(self, "label", _normalise(self.label))
        object.__setattr__(self, "provider_poi_id", _normalise(self.provider_poi_id))
        if self.region is not None:
            object.__setattr__(self, "region", _normalise(self.region))


@dataclass(frozen=True, slots=True)
class AreaEstimatedAccommodation:
    """A structured region estimate, never a fake hotel.

    ``centroid`` is a region centroid / estimation point, not a hotel
    coordinate.  This type intentionally has no ``provider_poi_id``; B3 only
    models the state, actual derivation belongs to a later provider
    projection.
    """

    region: str
    source: AreaEstimateSource
    centroid: GeoPoint | None = None
    requested_label: str | None = None
    state: AccommodationState = field(
        default=AccommodationState.AREA_ESTIMATED,
        init=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.source, AreaEstimateSource):
            raise ValueError("source must be an AreaEstimateSource instance")
        if self.centroid is not None and not isinstance(self.centroid, GeoPoint):
            raise ValueError("centroid must be None or a GeoPoint")
        if not self.region.strip():
            raise ValueError("region must not be empty")
        if self.requested_label is not None and not self.requested_label.strip():
            raise ValueError("requested_label must not be empty")
        object.__setattr__(self, "region", _normalise(self.region))
        if self.requested_label is not None:
            object.__setattr__(self, "requested_label", _normalise(self.requested_label))


@dataclass(frozen=True, slots=True)
class UnresolvedAccommodation:
    """No locatable anchor.

    Both "user never chose accommodation" and "user typed a hotel that could
    not be resolved" land here; ``requested_label`` distinguishes whether an
    original input existed.  Never carries a POI, coordinates or centroid.
    """

    requested_label: str | None = None
    display_label: str = "住宿地点待确认"
    state: AccommodationState = field(
        default=AccommodationState.UNRESOLVED,
        init=False,
    )

    def __post_init__(self) -> None:
        if not self.display_label.strip():
            raise ValueError("display_label must not be empty")
        if self.requested_label is not None and not self.requested_label.strip():
            raise ValueError("requested_label must not be empty")
        object.__setattr__(self, "display_label", _normalise(self.display_label))
        if self.requested_label is not None:
            object.__setattr__(self, "requested_label", _normalise(self.requested_label))


AccommodationResolution = (
    ConfirmedAccommodation | AreaEstimatedAccommodation | UnresolvedAccommodation
)


@dataclass(frozen=True, slots=True)
class OvernightBoundary:
    """The overnight bridge between two consecutive days.

    ``accommodation`` explicitly carries one of the three accommodation
    states for the night from ``from_date`` to ``to_date``; it can never be
    None and a missing boundary never stands in for UNRESOLVED.
    """

    from_date: date
    to_date: date
    accommodation: AccommodationResolution

    def __post_init__(self) -> None:
        if not isinstance(self.accommodation, AccommodationResolution):
            raise ValueError(
                "accommodation must be a Confirmed, AreaEstimated or Unresolved accommodation"
            )
        if self.to_date != self.from_date + timedelta(days=1):
            raise ValueError("to_date must be the day after from_date")


@dataclass(frozen=True, slots=True)
class TripSkeleton:
    """Immutable, planning-time aggregation of the whole trip.

    Invariants enforced at construction: days are non-empty, strictly
    ascending, gap-free and duplicate-free; every adjacent pair carries
    exactly one :class:`OvernightBoundary` with an explicit accommodation
    state.  This is a transient Python planning aggregate, not a
    persistence format.
    """

    days: tuple[DayPlan, ...]
    overnights: tuple[OvernightBoundary, ...]

    def __post_init__(self) -> None:
        canonical_days = tuple(self.days)
        canonical_overnights = tuple(self.overnights)
        if not canonical_days:
            raise ValueError("days must not be empty")
        for day in canonical_days:
            if not isinstance(day, DayPlan):
                raise TypeError("days must contain only DayPlan instances")
        for overnight in canonical_overnights:
            if not isinstance(overnight, OvernightBoundary):
                raise TypeError("overnights must contain only OvernightBoundary instances")
        for previous, current in zip(canonical_days, canonical_days[1:], strict=False):
            if current.date <= previous.date:
                raise ValueError("days must be strictly ascending and unique")
            if current.date != previous.date + timedelta(days=1):
                raise ValueError("days must be consecutive")
        if len(canonical_overnights) != len(canonical_days) - 1:
            raise ValueError(
                f"expected {len(canonical_days) - 1} overnights, got {len(canonical_overnights)}"
            )
        for index, overnight in enumerate(canonical_overnights):
            if overnight.from_date != canonical_days[index].date:
                raise ValueError("overnight from_date must match the day plan date")
            if overnight.to_date != canonical_days[index + 1].date:
                raise ValueError("overnight to_date must match the next day plan date")
        object.__setattr__(self, "days", canonical_days)
        object.__setattr__(self, "overnights", canonical_overnights)

    @property
    def start_date(self) -> date:
        return self.days[0].date

    @property
    def end_date(self) -> date:
        return self.days[-1].date

    @property
    def day_count(self) -> int:
        return len(self.days)

    @property
    def night_count(self) -> int:
        return len(self.overnights)

    @property
    def accommodation_states(self) -> tuple[AccommodationState, ...]:
        return tuple(overnight.accommodation.state for overnight in self.overnights)


def build_trip_skeleton(
    days: Sequence[DayPlan],
    overnight_accommodations: Sequence[AccommodationResolution],
) -> TripSkeleton:
    """Build an immutable :class:`TripSkeleton` from consecutive day plans.

    Single-day trips require zero overnight accommodations; multi-day trips
    require exactly ``len(days) - 1``.  Every night gets its own state, so
    changing hotels mid-trip and edit re-validation stay possible.  Pure
    function: no clocks, UUIDs, providers, network or database; never
    mutates its inputs and snapshots mutable containers at the entry.
    """
    canonical_days = tuple(days)
    canonical_accommodations = tuple(overnight_accommodations)
    if len(canonical_days) == 1 and canonical_accommodations:
        raise ValueError("a single-day trip cannot have overnights")
    if len(canonical_days) > 1 and len(canonical_accommodations) != len(canonical_days) - 1:
        raise ValueError(
            f"expected {len(canonical_days) - 1} overnight accommodations, "
            f"got {len(canonical_accommodations)}"
        )
    overnights = tuple(
        OvernightBoundary(
            from_date=canonical_days[index].date,
            to_date=canonical_days[index + 1].date,
            accommodation=canonical_accommodations[index],
        )
        for index in range(len(canonical_days) - 1)
    )
    return TripSkeleton(days=canonical_days, overnights=overnights)
