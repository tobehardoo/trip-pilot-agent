"""Deterministic repair decision helpers for the planning day loop.

Pure functions extracted from the AMap planning provider: they choose which
scheduled optional activity to drop after real routes exceed the deterministic
skeleton (capacity repair), which optional endpoint to drop on a
mobility-reduced day (mobility repair), and whether the bounded B17
start-relaxation may run once more.  All call sites are the provider's
orchestration method.
"""

from trip_agent.domain.planning.protocols import PlanningInfeasibleError
from trip_agent.planning.daily_schedule import DEFAULT_DAY_START_MINUTE, DayPlan
from trip_agent.worker.contracts import ItineraryDay

REDUCED_MOBILITY_MAX_HOP_METERS = 3_000
MAX_MOBILITY_REPAIR_ATTEMPTS = 2

# B17 bounded repair relaxation: after deterministic capacity repair is
# exhausted, pull a SYSTEM-DEFAULT day start earlier in fixed steps so real
# transit time can fit before a fixed departure.  The floor keeps the
# relaxation bounded; user-derived boundaries (arrival/departure anchors,
# fixed schedules, meal hard windows) are never moved.
WINDOW_RELAX_STEP_MINUTES = 30
WINDOW_RELAX_FLOOR_MINUTE = 7 * 60


def mobility_repair_candidate(
    day: ItineraryDay,
    candidates: tuple,
) -> str | None:
    candidate_by_id = {candidate.poi_id: candidate for candidate in candidates}
    for leg in day.transit_legs:
        if leg.distance_meters <= REDUCED_MOBILITY_MAX_HOP_METERS:
            continue
        endpoints = (
            day.activities[leg.to_activity_index],
            day.activities[leg.from_activity_index],
        )
        for activity in endpoints:
            poi_id = activity.provider_poi_id
            candidate = candidate_by_id.get(poi_id) if poi_id else None
            if candidate is not None and not candidate.must_include:
                return candidate.poi_id
    return None


def capacity_repair_candidate(
    error: PlanningInfeasibleError,
    day_plan: DayPlan,
    candidates: tuple,
) -> str | None:
    """Choose one scheduled optional activity to drop after real routes
    consume more time than the deterministic skeleton estimated.

    The candidate tuple is already ranked highest-first, so walking it in
    reverse removes the lowest-priority scheduled optional item.  Required
    visits and every fixed boundary remain immutable.  The outer loop is
    bounded because every retry strictly removes one candidate.
    """
    if not any(conflict.code == "INSUFFICIENT_DAY_CAPACITY" for conflict in error.conflicts):
        return None
    scheduled_ids = {
        item.poi_id
        for item in day_plan.items
        if item.kind in {"ATTRACTION", "EXPERIENCE"} and item.poi_id is not None
    }
    return next(
        (
            candidate.poi_id
            for candidate in reversed(candidates)
            if candidate.poi_id in scheduled_ids and not candidate.must_include
        ),
        None,
    )


def can_relax_window_start(
    day_plan: DayPlan,
    error: PlanningInfeasibleError,
    *,
    steps_taken: int,
) -> bool:
    """Whether the bounded B17 start-relaxation may run once more.

    The gate: only a SYSTEM-DEFAULT start boundary may be pulled earlier.
    The repair site has every input to ``day_window_minutes`` plus the
    computed plan, so provenance is exact — a start that differs from the
    default was moved by the user's arrival/departure anchor and is never
    touched.  The ARRIVAL-item check removes the boundary case where the
    arrival minute equals the default start (09:00): the anchor is still
    present, so relaxing would create time before the user actually lands.
    Fixed schedules and meal hard windows are never moved either:
    ``compute_free_windows`` splits around them and relaxing only extends
    the window's leading edge.  Relaxation only fires for the
    departure-anchored capacity conflict and is bounded by the floor.
    """
    if not any(conflict.code == "INSUFFICIENT_DAY_CAPACITY" for conflict in error.conflicts):
        return False
    if steps_taken == 0:
        if day_plan.window_start_minute != DEFAULT_DAY_START_MINUTE:
            return False
        if any(item.kind == "ARRIVAL" for item in day_plan.items):
            return False
    return (
        day_plan.window_start_minute - WINDOW_RELAX_STEP_MINUTES
        >= WINDOW_RELAX_FLOOR_MINUTE
    )
