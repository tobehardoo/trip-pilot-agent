import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator
from test_planning_context_v3 import _v3_command

from trip_agent.worker.contracts import (
    ActivityCoordinates,
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
    KnowledgeEvidence,
    KnowledgeFreshness,
    PlanningCompletedEvent,
    PlanningCompletedPayload,
    PlanningConflict,
    PlanningCreateCommand,
    PlanningFailedEventV1,
    PlanningFailedPayloadV1,
    PlanningProgressEvent,
    PlanningProgressPayload,
    PlanningRelaxation,
    TransitLeg,
)
from trip_agent.worker.processor import DemoPlanningProvider, process_planning_create

CONTRACT_DIRECTORY = Path(__file__).parents[3] / "contracts" / "messaging"
COMPLETION_V6_FIXTURE_DIRECTORY = (
    Path(__file__).parents[3]
    / "contracts"
    / "fixtures"
    / "planning-completed-event-v6"
)
ACTIVE_SCHEMA_FILES = (
    "city-intelligence-refresh-command-v1.schema.json",
    "planning-cancel-command-v1.schema.json",
    "planning-completed-event-v4.schema.json",
    "planning-completed-event-v5.schema.json",
    "planning-completed-event-v6.schema.json",
    "planning-create-command-v2.schema.json",
    "planning-create-command-v3.schema.json",
    "planning-failed-event-v1.schema.json",
    "planning-failed-event-v2.schema.json",
    "planning-progress-event-v1.schema.json",
    "planning-replan-command-v1.schema.json",
)


def test_city_intelligence_refresh_contract_accepts_the_java_command_shape() -> None:
    command = {
        "eventType": "CITY_INTELLIGENCE_REFRESH_REQUESTED",
        "schemaVersion": 1,
        "eventId": "ca73c2f2-5565-47bd-b660-cbb20225c158",
        "refreshId": "f8aab348-d72b-498a-8d74-af5a2e0c79ae",
        "tripId": "9ee5e831-90f7-4a60-bb8d-fb488aa799ca",
        "occurredAt": "2026-07-26T08:00:00Z",
        "payload": {
            "city": "Guangzhou",
            "cityCode": "CN-GD-GZ",
            "startDate": "2026-08-01",
            "endDate": "2026-08-04",
            "sourceIds": ["2d9bc69b-5308-40bd-81c2-e098f12c0d5a"],
            "requiredCategories": ["OPENING_HOURS"],
            "idempotencyKey": "21538aaf-fdd9-4b14-9683-dd0e261e063c",
        },
    }

    Draft202012Validator(_load_schema("city-intelligence-refresh-command-v1.schema.json")).validate(
        command
    )


def test_v3_planning_create_contract_accepts_the_frozen_context_shape() -> None:
    schema = _load_schema("planning-create-command-v3.schema.json")
    Draft202012Validator(schema).validate(_v3_command())


def test_v8_completed_event_contract_accepts_worker_output() -> None:
    payload = deepcopy(_v3_command())
    payload["payload"]["trip"]["constraints"]["mustVisitPlaces"] = []
    command = PlanningCreateCommand.model_validate(payload)
    event = asyncio.run(process_planning_create(command, DemoPlanningProvider()))
    schema = _load_schema("planning-completed-event-v8.schema.json")

    Draft202012Validator(schema).validate(
        event.model_dump(mode="json", by_alias=True, exclude_none=True)
    )


@pytest.mark.parametrize(
    "fixture_name",
    (
        "completion-v6-legacy-amap.json",
        "completion-v6-demo.json",
        "completion-v6-real-only-amap.json",
        "completion-v6-explicit-fallback-mixed.json",
        "completion-v6-multi-transit-mixed.json",
    ),
)
def test_completion_v6_shared_fixtures_match_the_active_schema(
    fixture_name: str,
) -> None:
    fixture = json.loads(
        (COMPLETION_V6_FIXTURE_DIRECTORY / fixture_name).read_text(encoding="utf-8")
    )

    Draft202012Validator(_load_schema("planning-completed-event-v6.schema.json")).validate(
        fixture
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("requestedProviderMode", "REAL_ONLY"),
        ("actualProviders", []),
        ("fallbackAttempted", False),
        ("fallbackOperations", []),
    ),
)
def test_completion_v6_schema_rejects_illegal_provenance_combinations(
    field: str, value: object
) -> None:
    fixture = json.loads(
        (
            COMPLETION_V6_FIXTURE_DIRECTORY
            / "completion-v6-explicit-fallback-mixed.json"
        ).read_text(encoding="utf-8")
    )
    fixture["payload"]["providerProvenance"][field] = value

    errors = list(
        Draft202012Validator(
            _load_schema("planning-completed-event-v6.schema.json")
        ).iter_errors(fixture)
    )

    assert errors


def test_v6_completed_event_contract_accepts_worker_output_with_a_transit_leg() -> None:
    event = PlanningCompletedEvent(
        event_type="PLANNING_COMPLETED",
        schema_version=6,
        event_id=UUID("5aa31052-2c21-53af-bddb-6a86614d801b"),
        trace_id=UUID("ea930620-41a7-4fdc-b6d1-d298a850112a"),
        task_id=UUID("dfb858fc-b910-4056-a375-2366dcaab690"),
        trip_id=UUID("d209daf2-f004-42cc-8385-510825f40fe1"),
        run_id=UUID("3b85b6b6-9e42-433b-90ef-d94a3eb26e18"),
        occurred_at=datetime(2026, 7, 26, 8, 0, tzinfo=UTC),
        payload=PlanningCompletedPayload(
            provider="DEMO",
            itinerary=Itinerary(
                title="Demo itinerary",
                estimated_total_cost=Decimal("0"),
                days=(
                    ItineraryDay(
                        date=datetime(2026, 8, 1, tzinfo=UTC).date(),
                        activities=(
                            ItineraryActivity(
                                title="Museum",
                                start_time=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
                                end_time=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
                                estimated_cost=Decimal("0"),
                                source="DEMO",
                            ),
                            ItineraryActivity(
                                title="Park",
                                start_time=datetime(2026, 8, 1, 11, 0, tzinfo=UTC),
                                end_time=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
                                estimated_cost=Decimal("0"),
                                source="DEMO",
                            ),
                        ),
                        transit_legs=(
                            TransitLeg(
                                from_activity_index=0,
                                to_activity_index=1,
                                mode="WALKING",
                                distance_meters=100,
                                duration_seconds=300,
                                provider="DEMO",
                                estimated=True,
                                polyline=(ActivityCoordinates(longitude=0, latitude=0),),
                                estimated_cost=Decimal("0"),
                                cost_source="DEMO",
                            ),
                        ),
                    ),
                ),
            ),
            knowledge=KnowledgeEvidence(
                status="UNAVAILABLE",
                query="demo",
                citations=(),
                freshness=KnowledgeFreshness(status="UNAVAILABLE"),
                message="No production knowledge was used",
            ),
            fact_impacts=(),
        ),
    )

    Draft202012Validator(_load_schema("planning-completed-event-v6.schema.json")).validate(
        event.model_dump(mode="json", by_alias=True, exclude_none=True)
    )


def test_progress_event_model_matches_its_json_schema() -> None:
    event = PlanningProgressEvent(
        event_type="PLANNING_PROGRESS",
        schema_version=1,
        event_id=UUID("5aa31052-2c21-53af-bddb-6a86614d801b"),
        trace_id=UUID("ea930620-41a7-4fdc-b6d1-d298a850112a"),
        task_id=UUID("dfb858fc-b910-4056-a375-2366dcaab690"),
        trip_id=UUID("d209daf2-f004-42cc-8385-510825f40fe1"),
        occurred_at=datetime(2026, 7, 27, 8, 0, tzinfo=UTC),
        payload=PlanningProgressPayload(
            stage="TASK_ACCEPTED",
            sequence=1,
            progress=5,
            message="Planning task accepted",
            statistics={"tripDays": 3},
        ),
    )

    schema = _load_schema("planning-progress-event-v1.schema.json")
    Draft202012Validator(schema).validate(event.model_dump(mode="json", by_alias=True))


def _load_schema(file_name: str) -> dict[str, object]:
    with (CONTRACT_DIRECTORY / file_name).open(encoding="utf-8") as schema_file:
        return json.load(schema_file)


def test_every_active_messaging_schema_is_a_valid_draft_2020_12_schema() -> None:
    for file_name in ACTIVE_SCHEMA_FILES:
        Draft202012Validator.check_schema(_load_schema(file_name))


def test_planning_failed_event_model_matches_its_json_schema() -> None:
    event = PlanningFailedEventV1(
        event_type="PLANNING_FAILED",
        schema_version=1,
        event_id=UUID("38e10d2b-fd84-55ae-97dc-a1e00cac682b"),
        trace_id=UUID("ea930620-41a7-4fdc-b6d1-d298a850112a"),
        task_id=UUID("dfb858fc-b910-4056-a375-2366dcaab690"),
        trip_id=UUID("d209daf2-f004-42cc-8385-510825f40fe1"),
        run_id=UUID("3b85b6b6-9e42-433b-90ef-d94a3eb26e18"),
        occurred_at=datetime(2026, 7, 26, 8, 0, tzinfo=UTC),
        payload=PlanningFailedPayloadV1(
            status="FAILED",
            error_code="NO_FEASIBLE_ITINERARY",
            message="时间、交通与固定安排无法同时满足",
            conflicts=(
                PlanningConflict(
                    code="INSUFFICIENT_DAY_CAPACITY",
                    message="当天可用时间不足",
                    affected=("2026-08-01",),
                ),
            ),
            relaxation_suggestions=(
                PlanningRelaxation(
                    code="REDUCE_OPTIONAL_ACTIVITIES",
                    message="减少一个可选活动",
                ),
            ),
        ),
    )

    schema = _load_schema("planning-failed-event-v1.schema.json")
    Draft202012Validator(schema).validate(event.model_dump(mode="json", by_alias=True))


def test_amap_activity_blank_optional_strings_normalized_to_none() -> None:
    """P4-F2 regression: blank optional strings (address, type_name) are
    normalized to None; a blank type label must never survive as an empty
    string, and a blank address must not trip the AddressText min-length
    constraint before structural-anchor rules apply."""
    activity = ItineraryActivity(
        title="Guangzhou South",
        start_time=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        end_time=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
        estimated_cost=Decimal("0"),
        source="AMAP",
        provider_poi_id="B00140VAP3",
        coordinates=ActivityCoordinates(
            longitude=Decimal("113.269097"),
            latitude=Decimal("22.988344"),
        ),
        address="X",
        type_code="150200",
        type_name="  ",
        kind="ATTRACTION",
        time_fixed=False,
    )
    assert activity.type_name is None
    assert activity.address == "X"

    with pytest.raises(ValueError, match="AMAP activity requires provider metadata"):
        # A non-structural activity with a blank address stays rejected:
        # candidates without an address are filtered upstream (EMPTY_ADDRESS),
        # so failing closed here is the correct contract.
        ItineraryActivity(
            title="No Address",
            start_time=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
            end_time=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
            estimated_cost=Decimal("0"),
            source="AMAP",
            provider_poi_id="B00140VAP3",
            coordinates=ActivityCoordinates(
                longitude=Decimal("113.269097"),
                latitude=Decimal("22.988344"),
            ),
            address="",
            type_code="150200",
            type_name="",
            kind="ATTRACTION",
            time_fixed=False,
        )


def test_amap_structural_anchor_allows_empty_address() -> None:
    """P4-F2 regression: an ARRIVAL anchor resolved to an AMap POI whose
    street address is empty must still validate; the address is display-only
    and the provider id + coordinate pair is the anchor contract."""
    activity = ItineraryActivity(
        title="Baiyun Airport",
        start_time=datetime(2026, 8, 10, 8, 0, tzinfo=UTC),
        end_time=datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
        estimated_cost=Decimal("0"),
        source="AMAP",
        provider_poi_id="B00140NZIQ",
        coordinates=ActivityCoordinates(
            longitude=Decimal("113.304651"),
            latitude=Decimal("23.377894"),
        ),
        address=None,
        type_code="150104",
        type_name="飞机场",
        kind="ARRIVAL",
        time_fixed=True,
    )
    assert activity.address is None
    assert activity.provider_poi_id == "B00140NZIQ"


def test_amap_structural_anchor_rejects_lone_coordinate_pair() -> None:
    """A structural anchor must carry both provider id and coordinates, not
    just one of them."""
    with pytest.raises(ValueError, match="requires both provider id and coordinates"):
        ItineraryActivity(
            title="Split Anchor",
            start_time=datetime(2026, 8, 10, 8, 0, tzinfo=UTC),
            end_time=datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
            estimated_cost=Decimal("0"),
            source="AMAP",
            provider_poi_id="B00140NZIQ",
            coordinates=None,
            address=None,
            type_code="150104",
            type_name="飞机场",
            kind="ARRIVAL",
            time_fixed=True,
        )
