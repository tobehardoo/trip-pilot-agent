import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from importlib import import_module
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

COMMAND = {
    "eventType": "PLANNING_CREATE_REQUESTED",
    "schemaVersion": 1,
    "eventId": "08db18af-3dfe-4e3f-9e3e-2900d43385b4",
    "traceId": "8f5ef9c2-c194-4292-b847-5b9dcfda978b",
    "taskId": "b0642d34-e24f-4b24-9ea7-82a68a4be781",
    "tripId": "08be9aca-fb30-4309-aa4b-93c240f19d75",
    "occurredAt": "2026-07-14T03:00:00Z",
    "payload": {
        "taskType": "CREATE",
        "baselineTripVersion": 0,
        "idempotencyKey": "d05b381a-39af-47b5-9925-52f412629f8f",
        "trip": {
            "title": "广州四日慢游",
            "destination": "广州",
            "startDate": "2026-08-01",
            "endDate": "2026-08-04",
            "status": "DRAFT",
            "version": 0,
            "constraints": {
                "budgetAmount": 6000.00,
                "travelers": 2,
                "travelerType": "FRIENDS",
                "pace": "BALANCED",
                "preferences": ["美食", "历史"],
                "fixedSchedules": [],
                "schemaVersion": 1,
            },
        },
    },
}


def test_contract_parses_java_command_and_rejects_unknown_fields() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    command_type = getattr(contracts, "PlanningCreateCommand", None)
    assert command_type is not None

    command = command_type.model_validate(COMMAND)

    assert str(command.task_id) == COMMAND["taskId"]
    assert command.payload.trip.destination == "广州"
    assert command.payload.trip.constraints.budget_amount == 6000
    with pytest.raises(ValidationError):
        command_type.model_validate({**COMMAND, "unexpected": True})


@pytest.mark.parametrize("travelers", [0, 51])
def test_contract_rejects_out_of_range_traveler_counts(travelers: int) -> None:
    contracts = import_module("trip_agent.worker.contracts")
    command_type = contracts.PlanningCreateCommand
    invalid = deepcopy(COMMAND)
    invalid["payload"]["trip"]["constraints"]["travelers"] = travelers

    with pytest.raises(ValidationError):
        command_type.model_validate(invalid)


def test_contract_rejects_schema_incompatible_coercions_and_empty_strings() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    command_type = contracts.PlanningCreateCommand
    coerced_travelers = deepcopy(COMMAND)
    coerced_travelers["payload"]["trip"]["constraints"]["travelers"] = "2"
    coerced_budget = deepcopy(COMMAND)
    coerced_budget["payload"]["trip"]["constraints"]["budgetAmount"] = "6000"
    coerced_version = deepcopy(COMMAND)
    coerced_version["payload"]["trip"]["version"] = "0"
    empty_title = deepcopy(COMMAND)
    empty_title["payload"]["trip"]["title"] = ""

    for invalid in (coerced_travelers, coerced_budget, coerced_version, empty_title):
        with pytest.raises(ValidationError):
            command_type.model_validate(invalid)


def test_contract_rejects_internal_field_names_on_the_wire() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    command_type = contracts.PlanningCreateCommand
    snake_case = deepcopy(COMMAND)
    snake_case["event_type"] = snake_case.pop("eventType")

    with pytest.raises(ValidationError):
        command_type.model_validate(snake_case)


def test_contract_rejects_mismatched_baseline_trip_version() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    command_type = contracts.PlanningCreateCommand
    mismatched = deepcopy(COMMAND)
    mismatched["payload"]["baselineTripVersion"] = 99

    with pytest.raises(ValidationError):
        command_type.model_validate(mismatched)


def test_contract_enforces_committed_string_limits() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    command_type = contracts.PlanningCreateCommand
    long_title = deepcopy(COMMAND)
    long_title["payload"]["trip"]["title"] = "x" * 121
    long_preference = deepcopy(COMMAND)
    long_preference["payload"]["trip"]["constraints"]["preferences"] = ["x" * 61]
    long_place = deepcopy(COMMAND)
    long_place["payload"]["trip"]["constraints"]["fixedSchedules"] = [
        {
            "placeName": "x" * 121,
            "startTime": "2026-08-02T19:00:00+08:00",
            "endTime": "2026-08-02T21:00:00+08:00",
        }
    ]

    for invalid in (long_title, long_preference, long_place):
        with pytest.raises(ValidationError):
            command_type.model_validate(invalid)


def test_contract_rejects_reversed_trip_dates_and_fixed_schedules() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    command_type = contracts.PlanningCreateCommand
    reversed_trip = deepcopy(COMMAND)
    reversed_trip["payload"]["trip"]["endDate"] = "2026-07-31"
    reversed_schedule = deepcopy(COMMAND)
    reversed_schedule["payload"]["trip"]["constraints"]["fixedSchedules"] = [
        {
            "placeName": "广州塔",
            "startTime": "2026-08-02T21:00:00+08:00",
            "endTime": "2026-08-02T19:00:00+08:00",
        }
    ]

    with pytest.raises(ValidationError):
        command_type.model_validate(reversed_trip)
    with pytest.raises(ValidationError):
        command_type.model_validate(reversed_schedule)


def test_demo_processor_emits_a_deterministic_completed_event() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    processor = import_module("trip_agent.worker.processor")
    command_type = getattr(contracts, "PlanningCreateCommand", None)
    provider_type = getattr(processor, "DemoPlanningProvider", None)
    process = getattr(processor, "process_planning_create", None)
    assert command_type is not None
    assert provider_type is not None
    assert process is not None
    command = command_type.model_validate(COMMAND)

    first = asyncio.run(process(command, provider_type()))
    repeated = asyncio.run(process(command, provider_type()))

    assert first.event_type == "PLANNING_COMPLETED"
    assert first.schema_version == 5
    assert first.event_id == repeated.event_id
    assert first.run_id == repeated.run_id
    assert first.trace_id == command.trace_id
    assert first.task_id == command.task_id
    assert first.trip_id == command.trip_id
    assert first.payload.provider == "DEMO"
    assert first.payload.knowledge.status == "DEMO"
    assert first.payload.knowledge.query == "广州 美食 历史 FRIENDS"
    assert first.payload.knowledge.citations == ()
    assert first.payload.knowledge.freshness.status == "UNAVAILABLE"


def test_v4_processor_serializes_real_knowledge_citations_and_freshness() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    processor = import_module("trip_agent.worker.processor")
    command = contracts.PlanningCreateCommand.model_validate(COMMAND)

    class EvidenceProvider:
        async def get_evidence(self, received_command: object):
            assert received_command is command
            return contracts.KnowledgeEvidence(
                status="REAL",
                query="广州 历史",
                citations=(
                    contracts.KnowledgeCitationSnapshot(
                        document_id="guangzhou-history-001",
                        document_version=2,
                        chunk_id="guangzhou-history-001-v2-c0",
                        chunk_index=0,
                        title="广州历史文化资料",
                        source_url="https://www.gz.gov.cn/history",
                        source_name="广州市人民政府",
                        collected_at="2026-07-22T02:00:00Z",
                        reliability_level="official",
                        similarity=0.87,
                    ),
                ),
                freshness=contracts.KnowledgeFreshness(
                    status="FRESH",
                    checked_at="2026-07-23T01:00:00Z",
                ),
            )

    completed = asyncio.run(
        processor.process_planning_create(
            command,
            processor.DemoPlanningProvider(),
            knowledge_provider=EvidenceProvider(),
            occurred_at=datetime(2026, 7, 23, 1, 5, tzinfo=UTC),
        )
    )
    wire = completed.model_dump(mode="json", by_alias=True, exclude_none=True)

    assert wire["schemaVersion"] == 5
    assert wire["payload"]["knowledge"] == {
        "status": "REAL",
        "query": "广州 历史",
        "citations": [
            {
                "documentId": "guangzhou-history-001",
                "documentVersion": 2,
                "chunkId": "guangzhou-history-001-v2-c0",
                "chunkIndex": 0,
                "title": "广州历史文化资料",
                "sourceUrl": "https://www.gz.gov.cn/history",
                "sourceName": "广州市人民政府",
                "collectedAt": "2026-07-22T02:00:00Z",
                "reliabilityLevel": "official",
                "similarity": 0.87,
            }
        ],
        "freshness": {
            "status": "FRESH",
            "checkedAt": "2026-07-23T01:00:00Z",
        },
    }
    schema = json.loads(
        (Path(__file__).resolve().parents[3]
         / "contracts/messaging/planning-completed-event-v5.schema.json").read_text(
             encoding="utf-8"
         )
    )
    validator = Draft202012Validator(schema)
    validator.validate(wire)
    invalid_url = deepcopy(wire)
    invalid_url["payload"]["knowledge"]["citations"][0]["sourceUrl"] = (
        "ftp://example.com/source"
    )
    assert list(validator.iter_errors(invalid_url))


def test_demo_provider_builds_one_explicitly_sourced_day_per_trip_date() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    processor = import_module("trip_agent.worker.processor")
    command_type = getattr(contracts, "PlanningCreateCommand", None)
    provider_type = getattr(processor, "DemoPlanningProvider", None)
    process = getattr(processor, "process_planning_create", None)
    assert command_type is not None
    assert provider_type is not None
    assert process is not None
    command = command_type.model_validate(COMMAND)

    completed = asyncio.run(process(command, provider_type()))

    assert [str(day.date) for day in completed.payload.itinerary.days] == [
        "2026-08-01",
        "2026-08-02",
        "2026-08-03",
        "2026-08-04",
    ]
    assert all(len(day.activities) == 1 for day in completed.payload.itinerary.days)
    assert all(day.transit_legs == () for day in completed.payload.itinerary.days)
    assert all(day.activities[0].source == "DEMO" for day in completed.payload.itinerary.days)
    assert completed.payload.itinerary.estimated_total_cost == 0


@pytest.mark.parametrize("invalid_cost", ["0.001", "10000000000.00"])
def test_completed_event_models_reject_unpersistable_money(invalid_cost: str) -> None:
    contracts = import_module("trip_agent.worker.contracts")

    with pytest.raises(ValidationError):
        contracts.Itinerary.model_validate(
            {
                "title": "Demo itinerary",
                "days": [
                    {
                        "date": "2026-08-01",
                        "activities": [
                            {
                                "title": "Demo activity",
                                "startTime": "2026-08-01T09:00:00+08:00",
                                "endTime": "2026-08-01T10:00:00+08:00",
                                "estimatedCost": invalid_cost,
                                "source": "DEMO",
                            }
                        ],
                    }
                ],
                "estimatedTotalCost": invalid_cost,
            }
        )


def test_completed_event_models_reject_titles_over_two_hundred_characters() -> None:
    contracts = import_module("trip_agent.worker.contracts")

    with pytest.raises(ValidationError):
        contracts.Itinerary.model_validate(
            {
                "title": "x" * 201,
                "days": [
                    {
                        "date": "2026-08-01",
                        "activities": [
                            {
                                "title": "Demo activity",
                                "startTime": "2026-08-01T09:00:00+08:00",
                                "endTime": "2026-08-01T10:00:00+08:00",
                                "estimatedCost": 0,
                                "source": "DEMO",
                            }
                        ],
                    }
                ],
                "estimatedTotalCost": 0,
            }
        )


def test_v3_activity_contract_requires_real_amap_metadata_and_numeric_coordinates() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    activity_type = getattr(contracts, "ItineraryActivity", None)
    coordinates_type = getattr(contracts, "ActivityCoordinates", None)
    assert activity_type is not None
    assert coordinates_type is not None

    activity = activity_type(
        title="广东省博物馆",
        start_time="2026-08-01T09:00:00+08:00",
        end_time="2026-08-01T11:00:00+08:00",
        estimated_cost=0,
        source="AMAP",
        provider_poi_id="B00140TWHT",
        coordinates=coordinates_type(
            longitude=Decimal("113.319263"), latitude=Decimal("23.109078")
        ),
        address="珠江东路2号",
    )
    wire = activity.model_dump(mode="json", by_alias=True)

    assert wire["providerPoiId"] == "B00140TWHT"
    assert wire["coordinates"] == {"longitude": 113.319263, "latitude": 23.109078}
    with pytest.raises(ValidationError, match="JSON numbers"):
        coordinates_type(longitude="113.319263", latitude="23.109078")
    with pytest.raises(ValidationError):
        activity_type.model_validate({**wire, "coordinates": None})
    with pytest.raises(ValidationError):
        activity_type.model_validate(
            {
                **wire,
                "source": "DEMO",
                "providerPoiId": "pretend-amap-id",
            }
        )


def test_v3_json_schema_enforces_provider_estimate_consistency() -> None:
    schema = json.loads(
        (Path(__file__).resolve().parents[3]
         / "contracts/messaging/planning-completed-event-v3.schema.json").read_text(
             encoding="utf-8"
         )
    )
    validator = Draft202012Validator(schema)
    valid = {
        "eventType": "PLANNING_COMPLETED",
        "schemaVersion": 3,
        "eventId": "08db18af-3dfe-4e3f-9e3e-2900d43385b4",
        "traceId": "8f5ef9c2-c194-4292-b847-5b9dcfda978b",
        "taskId": "b0642d34-e24f-4b24-9ea7-82a68a4be781",
        "tripId": "08be9aca-fb30-4309-aa4b-93c240f19d75",
        "runId": "a61f2109-ec3f-51f8-a536-25f0049d8326",
        "occurredAt": "2026-08-01T03:00:00Z",
        "payload": {
            "provider": "DEMO",
            "itinerary": {
                "title": "Demo",
                "days": [{
                    "date": "2026-08-01",
                    "activities": [{
                        "title": "First",
                        "startTime": "2026-08-01T09:00:00+08:00",
                        "endTime": "2026-08-01T11:00:00+08:00",
                        "estimatedCost": 0,
                        "source": "DEMO",
                    }, {
                        "title": "Second",
                        "startTime": "2026-08-01T13:00:00+08:00",
                        "endTime": "2026-08-01T15:00:00+08:00",
                        "estimatedCost": 0,
                        "source": "DEMO",
                    }],
                    "transitLegs": [{
                        "fromActivityIndex": 0,
                        "toActivityIndex": 1,
                        "mode": "WALKING",
                        "distanceMeters": 100,
                        "durationSeconds": 60,
                        "provider": "DEMO",
                        "estimated": True,
                        "polyline": [{"longitude": 113.3, "latitude": 23.1}],
                    }],
                }],
                "estimatedTotalCost": 0,
            },
        },
    }
    validator.validate(valid)
    invalid = deepcopy(valid)
    invalid["payload"]["itinerary"]["days"][0]["transitLegs"][0]["provider"] = "AMAP"
    assert list(validator.iter_errors(invalid))


def test_v3_transit_leg_model_rejects_inconsistent_provider_estimate() -> None:
    contracts = import_module("trip_agent.worker.contracts")

    with pytest.raises(ValidationError, match="provider and estimated"):
        contracts.TransitLeg(
            from_activity_index=0,
            to_activity_index=1,
            mode="WALKING",
            distance_meters=100,
            duration_seconds=60,
            provider="AMAP",
            estimated=True,
            polyline=[{"longitude": 113.3, "latitude": 23.1}],
        )


def test_v3_day_contract_requires_one_ordered_leg_between_each_adjacent_activity() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    activities = [
        {
            "title": f"Activity {index}",
            "startTime": f"2026-08-01T{9 + index * 3:02d}:00:00+08:00",
            "endTime": f"2026-08-01T{11 + index * 3:02d}:00:00+08:00",
            "estimatedCost": 0,
            "source": "DEMO",
        }
        for index in range(2)
    ]
    leg = {
        "fromActivityIndex": 0,
        "toActivityIndex": 1,
        "mode": "WALKING",
        "distanceMeters": 1200,
        "durationSeconds": 900,
        "provider": "DEMO",
        "estimated": True,
        "polyline": [
            {"longitude": 113.31, "latitude": 23.11},
            {"longitude": 113.32, "latitude": 23.12},
        ],
    }

    day = contracts.ItineraryDay.model_validate(
        {"date": "2026-08-01", "activities": activities, "transitLegs": [leg]}
    )

    assert day.transit_legs[0].distance_meters == 1200
    with pytest.raises(ValidationError, match="adjacent"):
        contracts.ItineraryDay.model_validate(
            {
                "date": "2026-08-01",
                "activities": activities,
                "transitLegs": [{**leg, "fromActivityIndex": 1}],
            }
        )
    with pytest.raises(ValidationError, match="travel time"):
        contracts.ItineraryDay.model_validate(
            {
                "date": "2026-08-01",
                "activities": activities,
                "transitLegs": [{**leg, "durationSeconds": 8000}],
            }
        )


def test_amap_planner_builds_v4_activities_and_routes_for_every_trip_day() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    map_contracts = import_module("trip_agent.providers.map")
    processor = import_module("trip_agent.worker.processor")
    command = contracts.PlanningCreateCommand.model_validate(COMMAND)
    pois = tuple(
        map_contracts.Poi(
            provider_id=f"poi-{index}",
            name=f"真实地点 {index}",
            coordinates=map_contracts.Coordinates(
                longitude=113.31 + index / 100,
                latitude=23.11 + index / 100,
            ),
            type_name="风景名胜",
            type_code="110000",
            province="广东省",
            city="广州市",
            district="天河区",
            address=f"广州地址 {index}",
        )
        for index in range(1, 9)
    )

    class SuccessfulMapProvider:
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def search_pois(self, request: object):
            self.requests.append(request)
            return map_contracts.ProviderSuccess(
                data=pois,
                provider="AMAP",
                latency_ms=8,
                cached=False,
                fetched_at=datetime(2026, 7, 16, tzinfo=UTC),
                estimated=False,
            )

    class SuccessfulRouteProvider:
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def get_route(self, request: object):
            route = import_module("trip_agent.providers.route")
            self.requests.append(request)
            return map_contracts.ProviderSuccess(
                data=route.RoutePlan(
                    mode="WALKING",
                    distance_meters=1200,
                    duration_seconds=900,
                    steps=(
                        route.RouteStep(
                            instruction="Walk to the next activity",
                            distance_meters=1200,
                            duration_seconds=900,
                            polyline=(request.origin, request.destination),
                        ),
                    ),
                    polyline=(request.origin, request.destination),
                ),
                provider="AMAP",
                latency_ms=8,
                cached=False,
                fetched_at=datetime(2026, 7, 17, tzinfo=UTC),
                estimated=False,
            )

    map_provider = SuccessfulMapProvider()
    route_provider = SuccessfulRouteProvider()
    planner_type = getattr(processor, "AmapPlanningProvider", None)
    assert planner_type is not None

    completed = asyncio.run(
        processor.process_planning_create(
            command,
            planner_type(map_provider, route_provider),
        )
    )

    assert completed.schema_version == 5
    assert completed.payload.provider == "AMAP"
    daily_titles = [
        [activity.title for activity in day.activities]
        for day in completed.payload.itinerary.days
    ]
    assert daily_titles == [
        ["真实地点 1", "真实地点 2"],
        ["真实地点 3", "真实地点 4"],
        ["真实地点 5", "真实地点 6"],
        ["真实地点 7", "真实地点 8"],
    ]
    first = completed.payload.itinerary.days[0].activities[0]
    assert first.source == "AMAP"
    assert first.provider_poi_id == "poi-1"
    assert first.coordinates.longitude == Decimal("113.32")
    assert first.address == "广州地址 1"
    assert len(map_provider.requests) == 2
    request = map_provider.requests[0]
    assert request.city == "广州"
    assert request.keyword == "美食"
    assert request.limit == 24
    assert completed.payload.itinerary.estimated_total_cost == Decimal("800.00")
    assert first.estimated_cost == Decimal("100.00")
    assert len(route_provider.requests) == 4
    first_leg = completed.payload.itinerary.days[0].transit_legs[0]
    assert first_leg.from_activity_index == 0
    assert first_leg.to_activity_index == 1
    assert first_leg.provider == "AMAP"
    assert first_leg.estimated is False
    assert first_leg.polyline[0].longitude == Decimal("113.3200000")


@pytest.mark.parametrize("unexpected_exception", [False, True])
def test_amap_planner_only_falls_back_for_classified_route_failures(
    unexpected_exception: bool,
) -> None:
    contracts = import_module("trip_agent.worker.contracts")
    map_contracts = import_module("trip_agent.providers.map")
    processor = import_module("trip_agent.worker.processor")
    payload = deepcopy(COMMAND)
    payload["payload"]["trip"]["endDate"] = "2026-08-01"
    command = contracts.PlanningCreateCommand.model_validate(payload)
    pois = tuple(
        map_contracts.Poi(
            provider_id=f"poi-{index}",
            name=f"POI {index}",
            coordinates=map_contracts.Coordinates(
                longitude=113.31 + index / 100,
                latitude=23.11 + index / 100,
            ),
            type_name="Scenic spot",
            type_code="110000",
            province="Guangdong",
            city=command.payload.trip.destination,
            district="Tianhe",
            address=f"Address {index}",
        )
        for index in range(1, 3)
    )

    class MapProvider:
        async def search_pois(self, request: object):
            del request
            return map_contracts.ProviderSuccess(
                data=pois,
                provider="AMAP",
                latency_ms=1,
                cached=False,
                fetched_at=datetime(2026, 7, 17, tzinfo=UTC),
                estimated=False,
            )

    class RouteProvider:
        async def get_route(self, request: object):
            del request
            if unexpected_exception:
                raise RuntimeError("unexpected route defect")
            return map_contracts.ProviderFailure(
                provider="AMAP",
                error_code="PROVIDER_TIMEOUT",
                error_message="AMap route request timed out",
                retryable=True,
                latency_ms=1,
                fetched_at=datetime(2026, 7, 17, tzinfo=UTC),
            )

    planner = processor.AmapPlanningProvider(MapProvider(), RouteProvider())

    if unexpected_exception:
        with pytest.raises(RuntimeError, match="unexpected route defect"):
            asyncio.run(planner.plan(command))
        return

    result = asyncio.run(planner.plan(command))

    leg = result.itinerary.days[0].transit_legs[0]
    assert result.provider == "AMAP"
    assert leg.provider == "DEMO"
    assert leg.estimated is True


def test_amap_planner_rejects_inconsistent_successful_route_metadata() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    map_contracts = import_module("trip_agent.providers.map")
    route_contracts = import_module("trip_agent.providers.route")
    processor = import_module("trip_agent.worker.processor")
    payload = deepcopy(COMMAND)
    payload["payload"]["trip"]["endDate"] = "2026-08-01"
    command = contracts.PlanningCreateCommand.model_validate(payload)
    pois = tuple(
        map_contracts.Poi(
            provider_id=f"poi-{index}",
            name=f"POI {index}",
            coordinates=map_contracts.Coordinates(
                longitude=113.31 + index / 100,
                latitude=23.11 + index / 100,
            ),
            type_name="Scenic spot",
            type_code="110000",
            province="Guangdong",
            city=command.payload.trip.destination,
            district="Tianhe",
            address=f"Address {index}",
        )
        for index in range(1, 3)
    )

    class MapProvider:
        async def search_pois(self, request: object):
            del request
            return map_contracts.ProviderSuccess(
                data=pois,
                provider="AMAP",
                latency_ms=1,
                cached=False,
                fetched_at=datetime(2026, 7, 17, tzinfo=UTC),
                estimated=False,
            )

    class RouteProvider:
        async def get_route(self, request: object):
            plan = route_contracts.RoutePlan(
                mode="WALKING",
                distance_meters=100,
                duration_seconds=60,
                steps=(
                    route_contracts.RouteStep(
                        instruction="Walk",
                        distance_meters=100,
                        duration_seconds=60,
                        polyline=(request.origin, request.destination),
                    ),
                ),
                polyline=(request.origin, request.destination),
            )
            return map_contracts.ProviderSuccess(
                data=plan,
                provider="AMAP",
                latency_ms=1,
                cached=False,
                fetched_at=datetime(2026, 7, 17, tzinfo=UTC),
                estimated=True,
            )

    planner = processor.AmapPlanningProvider(MapProvider(), RouteProvider())

    with pytest.raises(RuntimeError, match="inconsistent source metadata"):
        asyncio.run(planner.plan(command))


def test_classified_amap_failure_falls_back_to_an_explicit_demo_v4_result() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    map_contracts = import_module("trip_agent.providers.map")
    processor = import_module("trip_agent.worker.processor")
    command = contracts.PlanningCreateCommand.model_validate(COMMAND)

    class FailedMapProvider:
        async def search_pois(self, request: object):
            del request
            return map_contracts.ProviderFailure(
                provider="AMAP",
                error_code="PROVIDER_AUTH_FAILED",
                error_message="AMap authentication failed",
                retryable=False,
                latency_ms=3,
                fetched_at=datetime(2026, 7, 16, tzinfo=UTC),
            )

    fallback_type = getattr(processor, "FallbackPlanningProvider", None)
    assert fallback_type is not None
    route_provider = import_module("trip_agent.providers.route").DemoRouteProvider()
    planner = fallback_type(
        processor.AmapPlanningProvider(FailedMapProvider(), route_provider),
        processor.DemoPlanningProvider(),
    )

    completed = asyncio.run(processor.process_planning_create(command, planner))

    assert completed.schema_version == 5
    assert completed.payload.provider == "DEMO"
    assert all(
        activity.source == "DEMO"
        for day in completed.payload.itinerary.days
        for activity in day.activities
    )


def test_unexpected_amap_exception_is_not_hidden_by_demo_fallback() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    processor = import_module("trip_agent.worker.processor")
    command = contracts.PlanningCreateCommand.model_validate(COMMAND)

    class BrokenMapProvider:
        async def search_pois(self, request: object):
            del request
            raise RuntimeError("unexpected planner defect")

    fallback_type = getattr(processor, "FallbackPlanningProvider", None)
    assert fallback_type is not None
    route_provider = import_module("trip_agent.providers.route").DemoRouteProvider()
    planner = fallback_type(
        processor.AmapPlanningProvider(BrokenMapProvider(), route_provider),
        processor.DemoPlanningProvider(),
    )

    with pytest.raises(RuntimeError, match="unexpected planner defect"):
        asyncio.run(processor.process_planning_create(command, planner))


def test_amap_planner_collects_unique_pois_across_preference_queries() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    map_contracts = import_module("trip_agent.providers.map")
    processor = import_module("trip_agent.worker.processor")
    command = contracts.PlanningCreateCommand.model_validate(COMMAND)

    def poi(index: int):
        return map_contracts.Poi(
            provider_id=f"poi-{index}",
            name=f"真实地点 {index}",
            coordinates=map_contracts.Coordinates(
                longitude=113.30 + index / 100,
                latitude=23.10 + index / 100,
            ),
            type_name="风景名胜",
            type_code="110000",
            province="广东省",
            city="广州市",
            district="越秀区",
            address=f"广州地址 {index}",
        )

    responses = {
        "美食": (poi(1), poi(2), poi(3), poi(4)),
        "历史": (poi(4), poi(5), poi(6), poi(7), poi(8)),
    }

    class CollectingMapProvider:
        def __init__(self) -> None:
            self.keywords: list[str] = []

        async def search_pois(self, request: object):
            self.keywords.append(request.keyword)
            return map_contracts.ProviderSuccess(
                data=responses[request.keyword],
                provider="AMAP",
                latency_ms=4,
                cached=False,
                fetched_at=datetime(2026, 7, 16, tzinfo=UTC),
                estimated=False,
            )

    map_provider = CollectingMapProvider()
    route_provider = import_module("trip_agent.providers.route").DemoRouteProvider()

    result = asyncio.run(
        processor.AmapPlanningProvider(map_provider, route_provider).plan(command)
    )

    assert result.provider == "AMAP"
    assert map_provider.keywords == ["美食", "历史"]
    assert [
        activity.provider_poi_id
        for day in result.itinerary.days
        for activity in day.activities
    ] == [
        f"poi-{index}" for index in range(1, 9)
    ]


def test_amap_planner_caps_not_found_queries_before_demo_fallback() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    map_contracts = import_module("trip_agent.providers.map")
    processor = import_module("trip_agent.worker.processor")
    payload = deepcopy(COMMAND)
    payload["payload"]["trip"]["constraints"]["preferences"] = [
        f"preference-{index}" for index in range(10)
    ]
    command = contracts.PlanningCreateCommand.model_validate(payload)

    class MissingMapProvider:
        def __init__(self) -> None:
            self.keywords: list[str] = []

        async def search_pois(self, request: object):
            self.keywords.append(request.keyword)
            return map_contracts.ProviderFailure(
                provider="AMAP",
                error_code="POI_NOT_FOUND",
                error_message="No matching POIs were found",
                retryable=False,
                latency_ms=1,
                fetched_at=datetime(2026, 7, 16, tzinfo=UTC),
            )

    map_provider = MissingMapProvider()
    route_provider = import_module("trip_agent.providers.route").DemoRouteProvider()
    planner = processor.FallbackPlanningProvider(
        processor.AmapPlanningProvider(map_provider, route_provider),
        processor.DemoPlanningProvider(),
    )

    result = asyncio.run(planner.plan(command))

    assert result.provider == "DEMO"
    assert map_provider.keywords == [f"preference-{index}" for index in range(6)]


def test_amap_planner_falls_back_when_unique_candidates_are_insufficient() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    map_contracts = import_module("trip_agent.providers.map")
    processor = import_module("trip_agent.worker.processor")
    payload = deepcopy(COMMAND)
    payload["payload"]["trip"]["constraints"]["preferences"] = [
        f"preference-{index}" for index in range(6)
    ]
    command = contracts.PlanningCreateCommand.model_validate(payload)
    repeated_poi = map_contracts.Poi(
        provider_id="same-poi",
        name="Repeated POI",
        coordinates=map_contracts.Coordinates(longitude=113.3, latitude=23.1),
        type_name="Scenic spot",
        type_code="110000",
        province="Guangdong",
        city=command.payload.trip.destination,
        district="Yuexiu",
        address="Repeated address",
    )

    class RepeatingMapProvider:
        def __init__(self) -> None:
            self.query_count = 0

        async def search_pois(self, request: object):
            del request
            self.query_count += 1
            return map_contracts.ProviderSuccess(
                data=(repeated_poi,),
                provider="AMAP",
                latency_ms=1,
                cached=False,
                fetched_at=datetime(2026, 7, 16, tzinfo=UTC),
                estimated=False,
            )

    map_provider = RepeatingMapProvider()
    route_provider = import_module("trip_agent.providers.route").DemoRouteProvider()
    planner = processor.FallbackPlanningProvider(
        processor.AmapPlanningProvider(map_provider, route_provider),
        processor.DemoPlanningProvider(),
    )

    result = asyncio.run(planner.plan(command))

    assert result.provider == "DEMO"
    assert map_provider.query_count == processor.MAX_POI_QUERIES


def test_amap_planner_uses_ranked_candidates_and_avoids_fixed_schedules() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    map_contracts = import_module("trip_agent.providers.map")
    route_contracts = import_module("trip_agent.providers.route")
    processor = import_module("trip_agent.worker.processor")
    payload = deepcopy(COMMAND)
    payload["payload"]["trip"]["endDate"] = "2026-08-01"
    payload["payload"]["trip"]["constraints"]["preferences"] = ["博物馆"]
    payload["payload"]["trip"]["constraints"]["fixedSchedules"] = [{
        "placeName": "已预约午餐",
        "startTime": "2026-08-01T12:00:00+08:00",
        "endTime": "2026-08-01T13:00:00+08:00",
    }]
    command = contracts.PlanningCreateCommand.model_validate(payload)
    pois = (
        map_contracts.Poi(
            provider_id="tower",
            name="广州塔",
            coordinates=map_contracts.Coordinates(longitude=113.32, latitude=23.11),
            type_name="风景名胜",
            type_code="110000",
            province="广东省",
            city=command.payload.trip.destination,
            district="海珠区",
            address="广州塔地址",
        ),
        map_contracts.Poi(
            provider_id="museum",
            name="广州博物馆",
            coordinates=map_contracts.Coordinates(longitude=113.27, latitude=23.14),
            type_name="博物馆",
            type_code="140100",
            province="广东省",
            city=command.payload.trip.destination,
            district="越秀区",
            address="广州博物馆地址",
        ),
    )

    class MapProvider:
        async def search_pois(self, request: object):
            del request
            return map_contracts.ProviderSuccess(
                data=pois,
                provider="AMAP",
                latency_ms=1,
                cached=False,
                fetched_at=datetime(2026, 7, 17, tzinfo=UTC),
                estimated=False,
            )

    class RouteProvider:
        async def get_route(self, request: object):
            return map_contracts.ProviderSuccess(
                data=route_contracts.RoutePlan(
                    mode="WALKING",
                    distance_meters=1_000,
                    duration_seconds=1_800,
                    steps=(route_contracts.RouteStep(
                        instruction="步行前往下一地点",
                        distance_meters=1_000,
                        duration_seconds=1_800,
                        polyline=(request.origin, request.destination),
                    ),),
                    polyline=(request.origin, request.destination),
                ),
                provider="AMAP",
                latency_ms=1,
                cached=False,
                fetched_at=datetime(2026, 7, 17, tzinfo=UTC),
                estimated=False,
            )

    result = asyncio.run(
        processor.AmapPlanningProvider(MapProvider(), RouteProvider()).plan(command)
    )

    activities = result.itinerary.days[0].activities
    assert [item.provider_poi_id for item in activities] == ["museum", "tower"]
    assert activities[0].start_time.isoformat() == "2026-08-01T09:00:00+08:00"
    assert activities[1].start_time.isoformat() == "2026-08-01T13:00:00+08:00"


def test_infeasible_hard_constraints_are_not_hidden_by_demo_fallback() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    map_contracts = import_module("trip_agent.providers.map")
    processor = import_module("trip_agent.worker.processor")
    payload = deepcopy(COMMAND)
    payload["payload"]["trip"]["endDate"] = "2026-08-01"
    payload["payload"]["trip"]["constraints"]["fixedSchedules"] = [{
        "placeName": "不可移动安排",
        "startTime": "2026-08-01T09:00:00+08:00",
        "endTime": "2026-08-01T18:00:00+08:00",
    }]
    command = contracts.PlanningCreateCommand.model_validate(payload)
    pois = tuple(
        map_contracts.Poi(
            provider_id=f"poi-{index}",
            name=f"POI {index}",
            coordinates=map_contracts.Coordinates(longitude=113.3 + index / 100, latitude=23.1),
            type_name="风景名胜",
            type_code="110000",
            province="广东省",
            city=command.payload.trip.destination,
            district="越秀区",
            address=f"地址 {index}",
        )
        for index in range(2)
    )

    class MapProvider:
        async def search_pois(self, request: object):
            del request
            return map_contracts.ProviderSuccess(
                data=pois,
                provider="AMAP",
                latency_ms=1,
                cached=False,
                fetched_at=datetime(2026, 7, 17, tzinfo=UTC),
                estimated=False,
            )

    planner = processor.FallbackPlanningProvider(
        processor.AmapPlanningProvider(
            MapProvider(), import_module("trip_agent.providers.route").DemoRouteProvider()
        ),
        processor.DemoPlanningProvider(),
    )

    with pytest.raises(processor.PlanningInfeasibleError) as failure:
        asyncio.run(planner.plan(command))

    assert failure.value.conflicts[0].code == "INSUFFICIENT_DAY_CAPACITY"
