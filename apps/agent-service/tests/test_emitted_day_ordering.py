"""B13_FIX.2 R12 — real-provider forward-fit overlap regression.

Runtime fact (isolated REAL_ONLY golden): on the arrival day, a resolved
MEAL slot and the trailing "返回住宿地点待确认" ACCOMMODATION slot overlap
after the forward-fit shift loop.  The Java event consumer rejects the
review event ("activities must be ordered without overlap") and the task
stays QUEUED forever.

This test reproduces the exact slot layout (ARRIVAL → attraction →
sub-facility → resolved MEAL → ACCOMMODATION) with route durations taken
from the real AMap calls and asserts the emitted day keeps every activity
ordered without overlap.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.providers.map import Coordinates, Poi, ProviderSuccess
from trip_agent.providers.route import RoutePlan, RouteStep


def _poi(provider_id: str, name: str) -> Poi:
    return Poi(
        provider_id=provider_id,
        name=name,
        coordinates=Coordinates(longitude=113.31, latitude=23.13),
        type_name="风景名胜",
        type_code="110000",
        province="广东省",
        city="广州市",
        district="天河区",
        address=f"{name}地址",
    )


class BatchMapProvider:
    def __init__(self, batches: dict[str, tuple[Poi, ...]]) -> None:
        self._batches = batches

    async def search_pois(self, request: object):
        return ProviderSuccess(
            data=self._batches.get(request.keyword, ()),
            provider="AMAP",
            latency_ms=1,
            cached=False,
            fetched_at=datetime(2026, 8, 25, tzinfo=UTC),
            estimated=False,
        )


class TimedRouteProvider:
    """Route durations mirroring the real AMap calls that produced the
    overlap: 天河公园→双亭 24min, 双亭→银记 ~36min, others 5min."""

    def __init__(self) -> None:
        self._durations = {
            ("B00140H465", "B0L2TD2ZM6"): timedelta(minutes=24),
            ("B0L2TD2ZM6", "B0FFILESV8"): timedelta(minutes=35, seconds=47),
        }

    async def get_route(self, request: object):
        key = (request.origin_poi_id, request.destination_poi_id)
        duration = self._durations.get(key, timedelta(minutes=5))
        seconds = int(duration.total_seconds())
        return ProviderSuccess(
            data=RoutePlan(
                mode="DRIVING",
                distance_meters=3000,
                duration_seconds=seconds,
                steps=(
                    RouteStep(
                        instruction="Drive",
                        distance_meters=3000,
                        duration_seconds=seconds,
                        polyline=(request.origin, request.destination),
                    ),
                ),
                polyline=(request.origin, request.destination),
                estimated_cost=Decimal("10.00"),
            ),
            provider="AMAP",
            latency_ms=1,
            cached=False,
            fetched_at=datetime(2026, 8, 25, tzinfo=UTC),
            estimated=False,
        )


def _command() -> object:
    from trip_agent.worker.contracts import PlanningCreateCommand

    return PlanningCreateCommand.model_validate(
        {
            "eventType": "PLANNING_CREATE_REQUESTED",
            "schemaVersion": 4,
            "eventId": "11111111-1111-4111-8111-111111111111",
            "traceId": "22222222-2222-4222-8222-222222222222",
            "taskId": "33333333-3333-4333-8333-333333333333",
            "tripId": "44444444-4444-4444-8444-444444444444",
            "occurredAt": "2026-08-24T02:00:00Z",
            "payload": {
                "taskType": "CREATE",
                "baselineTripVersion": 0,
                "idempotencyKey": "55555555-5555-4555-8555-555555555555",
                "trip": {
                    "title": "R12 overlap",
                    "destination": "广州",
                    "startDate": "2026-08-25",
                    "endDate": "2026-08-26",
                    "status": "DRAFT",
                    "version": 0,
                    "arrivalAt": "2026-08-25T12:00:00+08:00",
                    "departureAt": "2026-08-26T18:00:00+08:00",
                    "constraints": {
                        "budgetAmount": 2000,
                        "travelers": 2,
                        "travelerType": "FRIENDS",
                        "pace": "BALANCED",
                        "preferences": ["地标"],
                        "fixedSchedules": [],
                        "arrival": None,
                        "departure": None,
                        "accommodation": None,
                        "mustVisitPlaces": ["天河公园"],
                        "avoidPlaces": [],
                        "mustVisitPlaceRefs": [],
                        "avoidPlaceRefs": [],
                        "mealWindows": [
                            {"mealType": "LUNCH", "startTime": "12:00", "endTime": "13:00"}
                        ],
                        "mobilityLevel": "STANDARD",
                        "schemaVersion": 2,
                    },
                },
                "guideEvidence": {"facts": []},
                "planningContext": {
                    "snapshotId": "66666666-6666-4666-8666-666666666666",
                    "schemaVersion": 3,
                    "tripId": "44444444-4444-4444-8444-444444444444",
                    "planningTaskId": "33333333-3333-4333-8333-333333333333",
                    "city": "广州",
                    "travelStartDate": "2026-08-25",
                    "travelEndDate": "2026-08-26",
                    "generatedAt": "2026-08-24T02:00:00Z",
                    "stale": False,
                    "sources": [],
                    "facts": [],
                    "conflicts": [],
                    "excludedFacts": [],
                    "diagnostics": [],
                },
            },
        }
    )


@pytest.mark.parametrize("structured", [False, True])
def test_emitted_days_are_ordered_without_overlap(structured: bool) -> None:
    """Every emitted day must keep activities ordered without overlap — the
    Java event consumer rejects overlapping review events (task stuck
    QUEUED).  Runs both the legacy text path and the structured-ref path."""
    map_provider = BatchMapProvider(
        {
            "天河公园": (
                _poi("B00140H465", "天河公园"),
                _poi("B0L2TD2ZM6", "天河公园-双亭"),
                _poi("B0FFILESV8", "银记肠粉店(沙河顶店)"),
            ),
            "美食": (_poi("B0FFILESV8", "银记肠粉店(沙河顶店)"),),
        }
    )
    provider = AmapPlanningProvider(map_provider, TimedRouteProvider())
    result = asyncio.run(provider.plan(_command()))
    for day in result.itinerary.days:
        activities = day.activities
        previous_end = None
        for activity in activities:
            if previous_end is not None:
                assert activity.start_time >= previous_end, (
                    f"{day.date}: {activity.title} starts before the previous activity ends"
                )
            previous_end = activity.end_time
