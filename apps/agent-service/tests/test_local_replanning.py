import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from importlib import import_module

import pytest
from pydantic import ValidationError

REPLAN_COMMAND = {
    "eventType": "PLANNING_REPLAN_REQUESTED",
    "schemaVersion": 1,
    "eventId": "c75013d4-b83a-4d11-a52c-66138751d75b",
    "traceId": "6f24951e-94bb-4d9a-9446-043698479f24",
    "taskId": "fb204eed-1484-4ccb-855e-af72d914b987",
    "tripId": "fb21f112-d17f-4e4f-8598-b1cd1c64ca04",
    "occurredAt": "2026-07-24T04:00:00Z",
    "payload": {
        "taskType": "REPLAN",
        "baselineTripVersion": 0,
        "baselineItineraryVersionId": "5ed1e169-04ec-45ed-9102-f75d833f2b8c",
        "idempotencyKey": "1439eeb2-104f-41b8-872f-bca3127fc56d",
        "impactedDates": ["2026-08-01"],
        "trip": {
            "title": "Guangzhou weekend",
            "destination": "Guangzhou",
            "startDate": "2026-08-01",
            "endDate": "2026-08-02",
            "status": "DRAFT",
            "version": 0,
            "constraints": {
                "budgetAmount": 1000,
                "travelers": 2,
                "travelerType": "FRIENDS",
                "pace": "BALANCED",
                "preferences": ["history"],
                "fixedSchedules": [],
                "arrival": None,
                "departure": None,
                "accommodation": None,
                "mustVisitPlaces": [],
                "avoidPlaces": [],
                "mealWindows": [],
                "mobilityLevel": "STANDARD",
                "schemaVersion": 2,
            },
        },
        "itinerary": {
            "title": "Guangzhou route",
            "provider": "AMAP",
            "estimatedTotalCost": 0,
            "days": [
                {
                    "date": "2026-08-01",
                    "activities": [
                        {
                            "title": "Museum",
                            "startTime": "2026-08-01T09:00:00+08:00",
                            "endTime": "2026-08-01T11:00:00+08:00",
                            "estimatedCost": 0,
                            "source": "AMAP",
                            "providerPoiId": "museum",
                            "coordinates": {"longitude": 113.31, "latitude": 23.11},
                            "address": "Museum Road",
                        },
                        {
                            "title": "Tower",
                            "startTime": "2026-08-01T13:00:00+08:00",
                            "endTime": "2026-08-01T15:00:00+08:00",
                            "estimatedCost": 0,
                            "source": "AMAP",
                            "providerPoiId": "tower",
                            "coordinates": {"longitude": 113.32, "latitude": 23.12},
                            "address": "Tower Road",
                        },
                    ],
                    "transitLegs": [],
                },
                {
                    "date": "2026-08-02",
                    "activities": [
                        {
                            "title": "Park",
                            "startTime": "2026-08-02T09:00:00+08:00",
                            "endTime": "2026-08-02T11:00:00+08:00",
                            "estimatedCost": 0,
                            "source": "AMAP",
                            "providerPoiId": "park",
                            "coordinates": {"longitude": 113.33, "latitude": 23.13},
                            "address": "Park Road",
                        },
                        {
                            "title": "Temple",
                            "startTime": "2026-08-02T13:00:00+08:00",
                            "endTime": "2026-08-02T15:00:00+08:00",
                            "estimatedCost": 0,
                            "source": "AMAP",
                            "providerPoiId": "temple",
                            "coordinates": {"longitude": 113.34, "latitude": 23.14},
                            "address": "Temple Road",
                        },
                    ],
                    "transitLegs": [
                        {
                            "fromActivityIndex": 0,
                            "toActivityIndex": 1,
                            "mode": "WALKING",
                            "distanceMeters": 910,
                            "durationSeconds": 600,
                            "provider": "AMAP",
                            "estimated": False,
                            "polyline": [
                                {"longitude": 113.33, "latitude": 23.13},
                                {"longitude": 113.34, "latitude": 23.14},
                            ],
                        }
                    ],
                },
            ],
        },
        "knowledge": {
            "status": "DEMO",
            "query": "Guangzhou history FRIENDS",
            "citations": [],
            "freshness": {"status": "UNAVAILABLE"},
            "message": "No production knowledge was used",
        },
    },
}


def test_replan_contract_accepts_an_incomplete_impacted_day_snapshot() -> None:
    contracts = import_module("trip_agent.worker.contracts")

    command = contracts.PlanningReplanCommand.model_validate(REPLAN_COMMAND)

    assert command.payload.task_type == "REPLAN"
    assert tuple(map(str, command.payload.impacted_dates)) == ("2026-08-01",)
    assert command.payload.itinerary.days[0].transit_legs == ()


@pytest.mark.parametrize("mutation", ["outside_date", "duplicate_date", "version_mismatch"])
def test_replan_contract_rejects_invalid_scope(mutation: str) -> None:
    contracts = import_module("trip_agent.worker.contracts")
    invalid = deepcopy(REPLAN_COMMAND)
    if mutation == "outside_date":
        invalid["payload"]["impactedDates"] = ["2026-08-03"]
    elif mutation == "duplicate_date":
        invalid["payload"]["impactedDates"] = ["2026-08-01", "2026-08-01"]
    else:
        invalid["payload"]["baselineTripVersion"] = 7

    with pytest.raises(ValidationError):
        contracts.PlanningReplanCommand.model_validate(invalid)


def test_local_replanning_only_rebuilds_impacted_transit() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    map_contracts = import_module("trip_agent.providers.map")
    route_contracts = import_module("trip_agent.providers.route")
    processor = import_module("trip_agent.worker.processor")
    command = contracts.PlanningReplanCommand.model_validate(REPLAN_COMMAND)

    class RouteProvider:
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def get_route(self, request: object):
            self.requests.append(request)
            return map_contracts.ProviderSuccess(
                data=route_contracts.RoutePlan(
                    mode="WALKING",
                    distance_meters=777,
                    duration_seconds=480,
                    steps=(
                        route_contracts.RouteStep(
                            instruction="Walk to the next activity",
                            distance_meters=777,
                            duration_seconds=480,
                            polyline=(request.origin, request.destination),
                        ),
                    ),
                    polyline=(request.origin, request.destination),
                ),
                provider="AMAP",
                latency_ms=2,
                cached=False,
                fetched_at=datetime(2026, 7, 24, 4, 1, tzinfo=UTC),
                estimated=False,
            )

    route_provider = RouteProvider()
    completed = asyncio.run(
        processor.process_planning_replan(
            command,
            processor.LocalReplanningProvider(route_provider),
            occurred_at=datetime(2026, 7, 24, 4, 2, tzinfo=UTC),
        )
    )

    assert len(route_provider.requests) == 1
    first_day, second_day = completed.payload.itinerary.days
    assert first_day.transit_legs[0].distance_meters == 777
    assert second_day == command.payload.itinerary.days[1].to_itinerary_day()
    assert completed.payload.knowledge == command.payload.knowledge
    assert completed.payload.provider == "AMAP"


def test_local_replanning_preserves_the_existing_transit_mode() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    map_contracts = import_module("trip_agent.providers.map")
    route_contracts = import_module("trip_agent.providers.route")
    processor = import_module("trip_agent.worker.processor")
    command_data = deepcopy(REPLAN_COMMAND)
    command_data["payload"]["itinerary"]["days"][0]["transitLegs"] = [{
        "fromActivityIndex": 0,
        "toActivityIndex": 1,
        "mode": "DRIVING",
        "distanceMeters": 900,
        "durationSeconds": 600,
        "provider": "AMAP",
        "estimated": False,
        "polyline": [
            {"longitude": 113.31, "latitude": 23.11},
            {"longitude": 113.32, "latitude": 23.12},
        ],
    }]
    command = contracts.PlanningReplanCommand.model_validate(command_data)

    class RouteProvider:
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def get_route(self, request: object):
            self.requests.append(request)
            return map_contracts.ProviderSuccess(
                data=route_contracts.RoutePlan(
                    mode="DRIVING",
                    distance_meters=777,
                    duration_seconds=480,
                    steps=(
                        route_contracts.RouteStep(
                            instruction="Drive to the next activity",
                            distance_meters=777,
                            duration_seconds=480,
                            polyline=(request.origin, request.destination),
                        ),
                    ),
                    polyline=(request.origin, request.destination),
                ),
                provider="AMAP",
                latency_ms=2,
                cached=False,
                fetched_at=datetime(2026, 7, 24, 4, 1, tzinfo=UTC),
                estimated=False,
            )

    route_provider = RouteProvider()
    asyncio.run(
        processor.process_planning_replan(
            command,
            processor.LocalReplanningProvider(route_provider),
            occurred_at=datetime(2026, 7, 24, 4, 2, tzinfo=UTC),
        )
    )

    assert route_provider.requests[0].mode == "DRIVING"
