"""Pure planning command processing."""

from datetime import UTC, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from trip_agent.worker.contracts import (
    DemoActivity,
    DemoItinerary,
    DemoItineraryDay,
    PlanningCompletedEvent,
    PlanningCompletedPayload,
    PlanningCreateCommand,
)

CHINA_TIME_ZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")


class PlanningProvider(Protocol):
    def plan(self, command: PlanningCreateCommand) -> DemoItinerary: ...


class DemoPlanningProvider:
    def plan(self, command: PlanningCreateCommand) -> DemoItinerary:
        trip = command.payload.trip
        day_count = (trip.end_date - trip.start_date).days + 1
        days = tuple(self._day(command, offset) for offset in range(day_count))
        return DemoItinerary(
            title=f"{trip.destination} Demo 行程",
            days=days,
            estimated_total_cost=Decimal("0"),
        )

    def _day(self, command: PlanningCreateCommand, offset: int) -> DemoItineraryDay:
        trip_date = command.payload.trip.start_date + timedelta(days=offset)
        start_time = datetime.combine(trip_date, time(hour=9), tzinfo=CHINA_TIME_ZONE)
        return DemoItineraryDay(
            date=trip_date,
            activities=(
                DemoActivity(
                    title=f"{command.payload.trip.destination} Demo 探索",
                    start_time=start_time,
                    end_time=start_time + timedelta(hours=2),
                    estimated_cost=Decimal("0"),
                    source="DEMO",
                ),
            ),
        )


def process_planning_create(
    command: PlanningCreateCommand,
    provider: PlanningProvider,
    *,
    occurred_at: datetime | None = None,
) -> PlanningCompletedEvent:
    itinerary = provider.plan(command)
    return PlanningCompletedEvent(
        event_type="PLANNING_COMPLETED",
        schema_version=1,
        event_id=_completed_event_id(command.event_id),
        trace_id=command.trace_id,
        task_id=command.task_id,
        trip_id=command.trip_id,
        run_id=_run_id(command.task_id),
        occurred_at=occurred_at or datetime.now(UTC),
        payload=PlanningCompletedPayload(provider="DEMO", itinerary=itinerary),
    )


def _completed_event_id(command_event_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"trip-pilot/planning-completed/{command_event_id}")


def _run_id(task_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"trip-pilot/agent-run/{task_id}")
