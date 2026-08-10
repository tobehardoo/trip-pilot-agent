from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from test_planning_worker import COMMAND

from trip_agent.domain.planning.protocols import PlanningResult
from trip_agent.worker.contracts import (
    ActivityCoordinates,
    FallbackOperation,
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
    PlanningCreateCommand,
    TransitLeg,
)

ACTIVITY_NAMESPACE = UUID("3d76fb9e-362e-4b28-8a9e-18e8ac7050ad")
TRANSIT_NAMESPACE = UUID("61f3d628-8c83-4c51-986d-8e87353a2d69")


def make_command(
    *,
    budget_amount: Decimal | None = Decimal("1000.00"),
    preferences: tuple[str, ...] = (),
    fixed_schedules: tuple[dict[str, object], ...] = (),
    must_visit_places: tuple[str, ...] = (),
    meal_windows: tuple[dict[str, object], ...] = (),
) -> PlanningCreateCommand:
    raw = deepcopy(COMMAND)
    raw["schemaVersion"] = 2
    constraints = raw["payload"]["trip"]["constraints"]
    constraints.update(
        {
            "budgetAmount": budget_amount,
            "preferences": list(preferences),
            "fixedSchedules": list(fixed_schedules),
            "mustVisitPlaces": list(must_visit_places),
            "mealWindows": list(meal_windows),
            "schemaVersion": 2,
        }
    )
    return PlanningCreateCommand.model_validate(raw)


def make_activity(
    index: int,
    *,
    title: str | None = None,
    start_hour: int | None = None,
    start_minute: int = 0,
    duration_minutes: int = 60,
    estimated_cost: Decimal = Decimal("0.00"),
    source: str = "DEMO",
    kind: str | None = None,
    type_code: str | None = None,
) -> ItineraryActivity:
    start = datetime(
        2026,
        8,
        1,
        start_hour if start_hour is not None else 9 + index * 2,
        start_minute,
        tzinfo=UTC,
    )
    activity_id = UUID(int=ACTIVITY_NAMESPACE.int + index + 1)
    if source == "AMAP":
        return ItineraryActivity(
            activity_id=activity_id,
            title=title or f"Activity {index + 1}",
            start_time=start,
            end_time=start + timedelta(minutes=duration_minutes),
            estimated_cost=estimated_cost,
            source="AMAP",
            provider_poi_id=f"POI-{index + 1}",
            coordinates=ActivityCoordinates(longitude=113, latitude=23),
            address=f"Address {index + 1}",
            kind=kind,
            type_code=type_code,
        )
    return ItineraryActivity(
        activity_id=activity_id,
        title=title or f"Activity {index + 1}",
        start_time=start,
        end_time=start + timedelta(minutes=duration_minutes),
        estimated_cost=estimated_cost,
        source="DEMO",
        kind=kind,
        type_code=type_code,
    )


def make_transit(
    index: int,
    *,
    duration_seconds: int = 300,
    distance_meters: int = 300,
    provider: str = "DEMO",
    mode: str = "WALKING",
    fallback: FallbackOperation | None = None,
) -> TransitLeg:
    return TransitLeg(
        transit_id=UUID(int=TRANSIT_NAMESPACE.int + index + 1),
        from_activity_index=index,
        to_activity_index=index + 1,
        mode=mode,
        distance_meters=distance_meters,
        duration_seconds=duration_seconds,
        provider=provider,
        estimated=provider == "DEMO",
        polyline=(ActivityCoordinates(longitude=113, latitude=23),),
        estimated_cost=Decimal("0.00"),
        cost_source="DEMO" if provider == "DEMO" else "RULE_ESTIMATE",
        fallback_operation=fallback,
    )


def make_result(
    *,
    activities: tuple[ItineraryActivity, ...] | None = None,
    transit_legs: tuple[TransitLeg, ...] | None = None,
    estimated_total_cost: Decimal = Decimal("500.00"),
    provider: str = "DEMO",
    fallback_operations: tuple[FallbackOperation, ...] = (),
) -> PlanningResult:
    resolved_activities = activities or (make_activity(0), make_activity(1))
    resolved_legs = transit_legs
    if resolved_legs is None:
        resolved_legs = tuple(make_transit(index) for index in range(len(resolved_activities) - 1))
    return PlanningResult(
        provider=provider,
        itinerary=Itinerary(
            title="Benchmark itinerary",
            days=(
                ItineraryDay(
                    date=date(2026, 8, 1),
                    activities=resolved_activities,
                    transit_legs=resolved_legs,
                ),
            ),
            estimated_total_cost=estimated_total_cost,
        ),
        fallback_operations=fallback_operations,
    )
