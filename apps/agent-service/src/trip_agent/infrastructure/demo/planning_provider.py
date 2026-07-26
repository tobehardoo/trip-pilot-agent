"""Demo planning provider — generates a skeleton itinerary for offline use.

Extracted from ``worker/processor.py``.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

from trip_agent.domain.planning.protocols import (
    PlanningInfeasibleError,
    PlanningResult,
)
from trip_agent.domain.shared import (
    CHINA_TIME_ZONE,
    available_minutes,
    minute_datetime,
)
from trip_agent.planning.optimization import OptimizationConflict, RelaxationSuggestion
from trip_agent.providers._demo_route import DemoRouteProvider
from trip_agent.worker.contracts import (
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
    PlanningCreateCommand,
    PlanningReplanCommand,
)


class DemoPlanningProvider:
    """Generates a single placeholder activity per day — no real map data.

    Used when no AMap key is configured (DEMO_MODE=true) or as a fallback
    when the AMap provider fails with an expected error.
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
        days = tuple(self._day(command, offset) for offset in range(day_count))
        return PlanningResult(
            provider="DEMO",
            itinerary=Itinerary(
                title=f"{trip.destination} Demo 行程",
                days=days,
                estimated_total_cost=Decimal("0"),
            ),
        )

    async def replan(self, command: PlanningReplanCommand) -> PlanningResult:
        from trip_agent.application.replan_service import (  # noqa: PLC0415
            LocalReplanningProvider,
        )

        return await LocalReplanningProvider(DemoRouteProvider()).replan(command)

    def _day(self, command: PlanningCreateCommand, offset: int) -> ItineraryDay:
        trip = command.payload.trip
        trip_date = trip.start_date + timedelta(days=offset)
        constraints = trip.constraints
        available_start, available_end = available_minutes(
            trip_date,
            trip.start_date,
            trip.end_date,
            constraints.arrival.time if constraints.arrival is not None else None,
            constraints.departure.time if constraints.departure is not None else None,
        )
        blocked = [
            (
                max(
                    available_start,
                    int(
                        (
                            schedule.start_time.astimezone(CHINA_TIME_ZONE)
                            - datetime.combine(trip_date, time.min, tzinfo=CHINA_TIME_ZONE)
                        ).total_seconds()
                        // 60
                    ),
                ),
                min(
                    available_end,
                    int(
                        (
                            schedule.end_time.astimezone(CHINA_TIME_ZONE)
                            - datetime.combine(trip_date, time.min, tzinfo=CHINA_TIME_ZONE)
                        ).total_seconds()
                        // 60
                    ),
                ),
            )
            for schedule in constraints.fixed_schedules
            if (
                schedule.start_time.astimezone(CHINA_TIME_ZONE)
                < datetime.combine(
                    trip_date + timedelta(days=1),
                    time.min,
                    tzinfo=CHINA_TIME_ZONE,
                )
                and schedule.end_time.astimezone(CHINA_TIME_ZONE)
                > datetime.combine(trip_date, time.min, tzinfo=CHINA_TIME_ZONE)
            )
        ]
        blocked.extend(
            (
                max(available_start, window.start_time.hour * 60 + window.start_time.minute),
                min(available_end, window.end_time.hour * 60 + window.end_time.minute),
            )
            for window in constraints.meal_windows
        )
        cursor = available_start
        for block_start, block_end in sorted(blocked):
            if block_start - cursor >= 120:
                break
            if block_end > cursor:
                cursor = block_end
        if available_end - cursor < 120:
            raise PlanningInfeasibleError(
                conflicts=(
                    OptimizationConflict(
                        "INSUFFICIENT_DAY_CAPACITY",
                        "到返时间、固定安排和用餐时段之间没有两小时可用窗口",
                        (trip_date.isoformat(),),
                    ),
                ),
                relaxations=(
                    RelaxationSuggestion(
                        "EXTEND_AVAILABLE_TIME",
                        "调整到返时间、固定安排或用餐时段后重试",
                    ),
                ),
            )
        start_time = minute_datetime(trip_date, cursor)
        return ItineraryDay(
            date=trip_date,
            activities=(
                ItineraryActivity(
                    title="自主探索时段（演示）",
                    start_time=start_time,
                    end_time=start_time + timedelta(hours=2),
                    estimated_cost=Decimal("0"),
                    source="DEMO",
                ),
            ),
            transit_legs=(),
        )
