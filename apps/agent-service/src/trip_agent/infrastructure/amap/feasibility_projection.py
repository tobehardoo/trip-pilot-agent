"""B5 — AMap transient validation-inputs projection (pure adapter).

Projects the AMap planning result onto :class:`ValidationInputs` without
reaching into provider internals: opening evidence comes from each POI's
own fetch batch (``evidence_from_amap_poi``), duration profiles come from
``duration_profile_for`` (category/system defaults, never hard-eligible),
and meal placements follow the DayPlan meal demands in order.

The projection is a pure function: no clocks, UUID generation, network,
database or global state.  It never invents hard-eligible evidence; AMap
provider evidence is always planning guidance (UNKNOWN in the hard rules).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from trip_agent.feasibility.inputs import (
    ActivityLocator,
    MealPlacementBinding,
    MealProjectionState,
    MealWindowType,
    OpeningHoursBinding,
    ValidationInputs,
    VisitDurationBinding,
)
from trip_agent.guide_intelligence.opening_evidence import evidence_from_amap_poi
from trip_agent.planning.daily_schedule import DayPlan
from trip_agent.planning.poi_quality import duration_profile_for
from trip_agent.providers.map import Poi
from trip_agent.worker.contracts import Itinerary


class FetchedPoiSnapshot(Protocol):
    """A POI paired with the fetch time of the batch that produced it."""

    poi: Poi
    fetched_at: datetime


def _poi_index(itinerary: Itinerary) -> dict[str, list[tuple[int, int]]]:
    """provider_poi_id -> [(day_index, activity_index)] in itinerary order."""
    index: dict[str, list[tuple[int, int]]] = {}
    for day_index, day in enumerate(itinerary.days):
        for activity_index, activity in enumerate(day.activities):
            if activity.provider_poi_id is not None:
                index.setdefault(activity.provider_poi_id, []).append((day_index, activity_index))
    return index


def project_amap_validation_inputs(
    *,
    itinerary: Itinerary,
    day_plans: tuple[DayPlan, ...],
    fetched_snapshots: tuple[FetchedPoiSnapshot, ...],
) -> ValidationInputs:
    """Build transient validation inputs for an AMap planning result."""
    poi_index = _poi_index(itinerary)
    opening_bindings: list[OpeningHoursBinding] = []
    duration_bindings: list[VisitDurationBinding] = []
    for snapshot in fetched_snapshots:
        poi = snapshot.poi
        locations = poi_index.get(poi.provider_id, ())
        if not locations:
            continue
        evidences = evidence_from_amap_poi(
            poi, poi_key=poi.provider_id, fetched_at=snapshot.fetched_at
        )
        profile = duration_profile_for(poi)
        for day_index, activity_index in locations:
            activity = itinerary.days[day_index].activities[activity_index]
            locator = ActivityLocator(day_index=day_index, activity_index=activity_index)
            if evidences:
                opening_bindings.append(
                    OpeningHoursBinding(
                        activity=locator,
                        poi_key=poi.provider_id,
                        evidences=evidences,
                    )
                )
            if activity.kind in {"ATTRACTION", "EXPERIENCE"}:
                duration_bindings.append(VisitDurationBinding(activity=locator, profile=profile))

    # Meal placements: DayPlan meal demands carry the authoritative meal
    # type; itinerary MEAL activities carry the same type in-process
    # (B13_FIX R3).  Bind by type identity — never by position.
    meal_bindings: list[MealPlacementBinding] = []
    if len(day_plans) != len(itinerary.days):
        raise ValueError("day plans must match itinerary days")
    for day_index, day_plan in enumerate(day_plans):
        meal_activities = tuple(
            (activity_index, activity)
            for activity_index, activity in enumerate(itinerary.days[day_index].activities)
            if activity.kind == "MEAL"
        )
        if len(day_plan.meal_demands) != len(meal_activities):
            raise ValueError("meal demand count must match MEAL activities on every day")
        for demand, (activity_index, activity) in zip(
            day_plan.meal_demands, meal_activities, strict=True
        ):
            if activity.meal_type is None:
                raise ValueError(
                    "AMap MEAL activities must carry an explicit meal type "
                    "for identity binding"
                )
            if activity.meal_type != demand.meal_type:
                raise ValueError(
                    f"meal demand type {demand.meal_type} does not match "
                    f"activity type {activity.meal_type}"
                )
            meal_bindings.append(
                MealPlacementBinding(
                    activity=ActivityLocator(
                        day_index=day_index,
                        activity_index=activity_index,
                    ),
                    meal_type=MealWindowType(demand.meal_type),
                )
            )
    return ValidationInputs(
        opening_hours_bindings=tuple(opening_bindings),
        visit_duration_bindings=tuple(duration_bindings),
        meal_placement_bindings=tuple(meal_bindings),
        meal_projection_state=MealProjectionState.COMPLETE,
    )
