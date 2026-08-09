"""B4A — AMap accommodation projection (transient, pure).

Projects the AMap-resolved travel anchors plus the per-day primary regions
onto an immutable :class:`~trip_agent.planning.trip_skeleton.TripSkeleton`.

Priority per night:

1. ``resolved_accommodation`` (a real provider Poi) → CONFIRMED, reused for
   every night of the trip.
2. No resolution but an explicit ``requested_accommodation_label`` →
   UNRESOLVED with the user's label preserved; never downgraded to a region
   estimate.
3. No request at all → each night uses the primary region of its own
   ``from_date`` day plan (DAY_PRIMARY_REGION Area Estimated), or
   UNRESOLVED when that day carries no region.

This module is deliberately dependency-light: pure Python, no clocks, UUIDs,
network, database, cache or global mutable state; it imports no feasibility,
evaluation or worker processor code.  It never invents fake hotels, city
centres, provider POI IDs or centroids.
"""

from __future__ import annotations

from collections.abc import Sequence

from trip_agent.planning.daily_schedule import DayPlan
from trip_agent.planning.trip_skeleton import (
    AccommodationResolution,
    AreaEstimatedAccommodation,
    AreaEstimateSource,
    ConfirmedAccommodation,
    GeoPoint,
    TripSkeleton,
    UnresolvedAccommodation,
    build_trip_skeleton,
)
from trip_agent.providers.map import Poi


def _confirmed_from_poi(poi: Poi) -> ConfirmedAccommodation:
    return ConfirmedAccommodation(
        label=poi.name,
        provider_poi_id=poi.provider_id,
        coordinates=GeoPoint(
            longitude=float(poi.coordinates.longitude),
            latitude=float(poi.coordinates.latitude),
        ),
        region=poi.district.strip() or None,
    )


def _night_accommodation(
    day_plan: DayPlan,
    requested_accommodation_label: str | None,
    resolved_accommodation: Poi | None,
) -> AccommodationResolution:
    if resolved_accommodation is not None:
        return _confirmed_from_poi(resolved_accommodation)
    if requested_accommodation_label is not None:
        return UnresolvedAccommodation(
            requested_label=requested_accommodation_label,
        )
    if day_plan.primary_region is not None:
        return AreaEstimatedAccommodation(
            region=day_plan.primary_region,
            source=AreaEstimateSource.DAY_PRIMARY_REGION,
        )
    return UnresolvedAccommodation()


def project_amap_trip_skeleton(
    *,
    day_plans: Sequence[DayPlan],
    requested_accommodation_label: str | None,
    resolved_accommodation: Poi | None,
) -> TripSkeleton:
    """Build the transient trip skeleton for an AMap planning result.

    Every night between consecutive day plans receives exactly one
    accommodation resolution.  Confirmed accommodation is derived from the
    real resolved POI and reused for all nights; the returned skeleton is
    immutable and never mutates its inputs.
    """
    canonical_days = tuple(day_plans)
    overnights_count = len(canonical_days) - 1
    if resolved_accommodation is not None:
        confirmed = _confirmed_from_poi(resolved_accommodation)
        accommodations: tuple[AccommodationResolution, ...] = tuple(
            confirmed for _ in range(overnights_count)
        )
    else:
        accommodations = tuple(
            _night_accommodation(
                canonical_days[index],
                requested_accommodation_label,
                None,
            )
            for index in range(overnights_count)
        )
    return build_trip_skeleton(canonical_days, accommodations)
