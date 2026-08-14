"""B11_FIX_2 — Demo itinerary activities must be ordered by start time.

The Java review parser fail-closes on "activities must be ordered without
overlap"; the Demo provider used to emit meal placeholders (12:00) before the
exploration block (09:00), which the real Java consumer rejects.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from test_planning_worker import COMMAND

from trip_agent.infrastructure.demo.planning_provider import DemoPlanningProvider
from trip_agent.worker.contracts import PlanningCreateCommand
from trip_agent.worker.processor import process_planning_create


def test_demo_days_are_ordered_by_start_time() -> None:
    command = PlanningCreateCommand.model_validate(COMMAND)
    provider = DemoPlanningProvider()

    event = asyncio.run(
        process_planning_create(
            command,
            provider,
            occurred_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
        )
    )

    for day in event.payload.itinerary.days:
        starts = [activity.start_time for activity in day.activities]
        assert starts == sorted(starts), (
            f"day {day.date} activities are not ordered by start time: {starts}"
        )
        # No overlap: each activity starts after the previous one ends.
        for previous, current in zip(day.activities, day.activities[1:], strict=False):
            assert current.start_time >= previous.end_time, (
                f"day {day.date} has overlapping activities: "
                f"{previous.title} ends {previous.end_time}, "
                f"{current.title} starts {current.start_time}"
            )
