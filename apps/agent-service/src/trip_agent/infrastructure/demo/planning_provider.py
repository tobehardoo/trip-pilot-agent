"""Demo planning provider — generates a skeleton itinerary for offline use.

Extracted from ``worker/processor.py``.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from trip_agent.domain.planning.protocols import (
    OptimizationConflict,
    PlanningInfeasibleError,
    PlanningRepairRequest,
    PlanningResult,
    RelaxationSuggestion,
)
from trip_agent.domain.shared import (
    CHINA_TIME_ZONE,
    available_minutes,
    minute_datetime,
)
from trip_agent.feasibility.inputs import MealProjectionState
from trip_agent.planning.daily_schedule import classify_day_type
from trip_agent.planning.validation_projection import project_validation_state
from trip_agent.providers._demo_route import DemoRouteProvider
from trip_agent.worker.contracts import (
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
    PlanningCreateCommand,
    PlanningReplanCommand,
)
from trip_agent.worker.progress import report_planning_progress


class DemoPlanningProvider:
    """Generates placeholder activities per day — no real map data.

    Used in PROVIDER_MODE=DEMO_ONLY or as an explicitly allowed fallback
    when the AMap provider fails with an expected error.  Demo days are
    classified (ARRIVAL/FULL/DEPARTURE) and include arrival/departure
    placeholder nodes.
    """

    async def plan(self, command: PlanningCreateCommand) -> PlanningResult:
        trip = command.payload.trip
        if trip.constraints.must_visit_places:
            raise PlanningInfeasibleError(
                conflicts=(
                    OptimizationConflict(
                        "MUST_VISIT_UNVERIFIABLE_IN_DEMO",
                        "演示降级无法验证必去地点，已停止生成以避免返回不符合约束的行程",
                        trip.constraints.must_visit_places,
                    ),
                ),
                relaxations=(
                    RelaxationSuggestion(
                        "RETRY_REAL_PROVIDER",
                        "地图服务恢复后重试，或移除必去地点约束",
                    ),
                ),
            )
        day_count = (trip.end_date - trip.start_date).days + 1
        await report_planning_progress(
            "CONSTRAINTS_SOLVING",
            "Solving the requested schedule constraints",
            {"tripDays": day_count},
        )
        days = tuple(self._day_skeleton(command, offset) for offset in range(day_count))
        itinerary = Itinerary(
            title=f"{trip.destination} Demo 行程",
            days=days,
            estimated_total_cost=Decimal("0"),
        )
        # B9.1: Demo derives the same projection as every other entry point
        # but never fabricates evidence: overnights stay UNRESOLVED, no
        # opening evidence is attached and the meal projection is explicitly
        # UNAVAILABLE because Demo cannot resolve real restaurants.
        skeleton, inputs = project_validation_state(
            itinerary,
            requested_accommodation_label=(
                trip.constraints.accommodation.place_name
                if trip.constraints.accommodation is not None
                else None
            ),
            meal_windows=tuple(trip.constraints.meal_windows),
            facts=(),
            meal_projection_state=MealProjectionState.UNAVAILABLE,
        )
        return PlanningResult(
            provider="DEMO",
            itinerary=itinerary,
            requested_provider_mode="DEMO_ONLY",
            primary_provider="DEMO",
            actual_providers=("DEMO",),
            trip_skeleton=skeleton,
            validation_inputs=inputs,
        )

    async def replan(self, command: PlanningReplanCommand) -> PlanningResult:
        from trip_agent.application.replan_service import (  # noqa: PLC0415
            LocalReplanningProvider,
        )
        from trip_agent.providers.errors import ProviderExecutionMode  # noqa: PLC0415

        return await LocalReplanningProvider(
            DemoRouteProvider(), provider_mode=ProviderExecutionMode.DEMO_ONLY
        ).replan(command)

    async def repair(self, request: PlanningRepairRequest) -> PlanningResult:
        from trip_agent.application.replan_service import (  # noqa: PLC0415
            LocalReplanningProvider,
        )
        from trip_agent.providers.errors import ProviderExecutionMode  # noqa: PLC0415

        return await LocalReplanningProvider(
            DemoRouteProvider(), provider_mode=ProviderExecutionMode.DEMO_ONLY
        ).repair(request)

    def _day_skeleton(self, command: PlanningCreateCommand, offset: int) -> ItineraryDay:
        trip = command.payload.trip
        trip_date = trip.start_date + timedelta(days=offset)
        constraints = trip.constraints
        arrival = constraints.arrival.time if constraints.arrival is not None else None
        departure = constraints.departure.time if constraints.departure is not None else None
        day_type = classify_day_type(trip_date, trip.start_date, trip.end_date, arrival, departure)
        available_start, available_end = available_minutes(
            trip_date,
            trip.start_date,
            trip.end_date,
            arrival,
            departure,
        )
        activities: list[ItineraryActivity] = []
        if day_type == "ARRIVAL_DAY" and arrival is not None:
            local = arrival.astimezone(CHINA_TIME_ZONE)
            start = datetime.combine(
                trip_date,
                time(hour=local.hour, minute=local.minute),
                tzinfo=CHINA_TIME_ZONE,
            )
            activities.append(
                ItineraryActivity(
                    title="到达",
                    start_time=start,
                    end_time=start + timedelta(minutes=30),
                    estimated_cost=Decimal("0"),
                    source="DEMO",
                    kind="ARRIVAL",
                    time_fixed=True,
                )
            )
        if day_type == "DEPARTURE_DAY" and departure is not None:
            local = departure.astimezone(CHINA_TIME_ZONE)
            end = datetime.combine(
                trip_date,
                time(hour=local.hour, minute=local.minute),
                tzinfo=CHINA_TIME_ZONE,
            )
            activities.append(
                ItineraryActivity(
                    title="离开",
                    start_time=end - timedelta(minutes=60),
                    end_time=end,
                    estimated_cost=Decimal("0"),
                    source="DEMO",
                    kind="DEPARTURE",
                    time_fixed=True,
                )
            )
        cursor = minute_datetime(trip_date, available_start)
        window_end = minute_datetime(trip_date, available_end)
        if day_type == "ARRIVAL_DAY" and activities:
            cursor = max(cursor, max(activity.end_time for activity in activities))
        # B9.4: Demo keeps guaranteed meal placeholders even without real
        # restaurants — eating time is never silently removed.
        activities.extend(
            self._meal_placeholders(trip_date, available_start, available_end, day_type)
        )
        if window_end - cursor >= timedelta(hours=2):
            activities.append(
                ItineraryActivity(
                    title="自主探索时段（演示）",
                    start_time=cursor,
                    end_time=cursor + timedelta(hours=2),
                    estimated_cost=Decimal("0"),
                    source="DEMO",
                )
            )
        if not activities:
            activities.append(
                ItineraryActivity(
                    title="自主探索时段（演示）",
                    start_time=minute_datetime(trip_date, available_start),
                    end_time=minute_datetime(trip_date, available_end),
                    estimated_cost=Decimal("0"),
                    source="DEMO",
                )
            )
        return ItineraryDay(
            date=trip_date,
            day_type=day_type,
            activities=tuple(activities),
            transit_legs=(),
        )

    @staticmethod
    def _meal_placeholders(
        trip_date: date,
        available_start: int,
        available_end: int,
        day_type: str,
    ) -> list[ItineraryActivity]:
        """Place LUNCH/DINNER placeholders inside the available day window."""
        placeholders: list[ItineraryActivity] = []
        for label, anchor in (("午餐时段（演示）", 12 * 60), ("晚餐时段（演示）", 18 * 60)):
            if day_type == "ARRIVAL_DAY" and anchor == 12 * 60:
                continue
            if day_type == "DEPARTURE_DAY" and anchor == 18 * 60:
                continue
            if not (available_start <= anchor and anchor + 60 <= available_end):
                continue
            start = minute_datetime(trip_date, anchor)
            placeholders.append(
                ItineraryActivity(
                    title=label,
                    start_time=start,
                    end_time=start + timedelta(minutes=60),
                    estimated_cost=Decimal("0"),
                    source="DEMO",
                    kind="MEAL",
                )
            )
        return placeholders
