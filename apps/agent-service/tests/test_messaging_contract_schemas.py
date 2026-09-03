import asyncio
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as JsonSchemaValidationError
from plan_evaluation_support import make_command, make_result
from test_planning_context_v3 import _v3_command

from trip_agent.infrastructure.demo.planning_provider import DemoPlanningProvider
from trip_agent.worker.contracts import (
    PlanningConflict,
    PlanningCreateCommand,
    PlanningFailedEvent,
    PlanningFailedPayload,
    PlanningProgressEvent,
    PlanningProgressPayload,
    PlanningRelaxation,
)
from trip_agent.worker.processor import process_planning_create

CONTRACT_DIRECTORY = Path(__file__).parents[3] / "contracts" / "messaging"
COMPLETION_V9_FIXTURE_DIRECTORY = (
    Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "planning-completed-event-v9"
)
COMPLETION_V11_FIXTURE_DIRECTORY = (
    Path(__file__).resolve().parents[3]
    / "contracts"
    / "fixtures"
    / "planning-completed-event-v11"
)
REVIEW_V1_FIXTURE_DIRECTORY = (
    Path(__file__).resolve().parents[3]
    / "contracts"
    / "fixtures"
    / "planning-review-required-event-v1"
)
ACTIVE_SCHEMA_FILES = (
    "agent-ask-user-event-v1.schema.json",
    "agent-completed-event-v1.schema.json",
    "agent-resume-command-v1.schema.json",
    "agent-run-finished-event-v1.schema.json",
    "agent-start-command-v1.schema.json",
    "agent-step-event-v1.schema.json",
    "city-intelligence-refresh-command-v1.schema.json",
    "planning-cancel-command-v1.schema.json",
    "planning-create-command-v2.schema.json",
    "planning-create-command-v3.schema.json",
    "planning-create-command-v4.schema.json",
    "planning-failed-event-v1.schema.json",
    "planning-failed-event-v2.schema.json",
    "planning-progress-event-v1.schema.json",
    "planning-progress-event-v2.schema.json",
    "planning-replan-command-v1.schema.json",
    "planning-replan-command-v2.schema.json",
    "planning-candidate-validation-command-v1.schema.json",
    "planning-candidate-validation-command-v2.schema.json",
    "planning-completed-event-v9.schema.json",
    "planning-completed-event-v10.schema.json",
    "planning-completed-event-v11.schema.json",
    "planning-review-required-event-v1.schema.json",
    "planning-review-required-event-v2.schema.json",
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


def test_completed_v11_contract_accepts_worker_output() -> None:
    payload = deepcopy(_v3_command())
    payload["payload"]["trip"]["constraints"]["mustVisitPlaces"] = []
    command = PlanningCreateCommand.model_validate(payload)
    event = asyncio.run(process_planning_create(command, DemoPlanningProvider()))
    # B19-B: the producer writes completion v11 (B16 UNVERIFIED/no-blocker is
    # still savable); v11 keeps the v10 structure plus TRANSIT route modes.
    assert event.schema_version == 11
    assert event.event_type == "PLANNING_COMPLETED"
    assert event.payload.has_blocker is False
    schema = _load_schema("planning-completed-event-v11.schema.json")

    Draft202012Validator(schema).validate(
        event.model_dump(mode="json", by_alias=True, exclude_none=True)
    )


def test_v11_worker_wire_fingerprint_covers_injected_transit_costs() -> None:
    class ProviderWithTransitCosts:
        async def plan(self, _command: object):
            return make_result()

    event = asyncio.run(
        process_planning_create(
            make_command(start_date="2026-08-01", end_date="2026-08-01"),
            ProviderWithTransitCosts(),
        )
    )

    wire = event.model_dump(mode="json", by_alias=True, exclude_none=False)
    wire_itinerary = wire["payload"]["itinerary"]
    wire_leg = wire_itinerary["days"][0]["transitLegs"][0]
    assert "estimatedCost" in wire_leg
    assert "costSource" in wire_leg
    canonical = json.dumps(
        wire_itinerary,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    assert wire["payload"]["feasibilityReport"]["itineraryFingerprint"] == expected


def test_v11_worker_wire_carries_each_activity_cost_source() -> None:
    """B1: every wired activity must surface a valid costSource.

    ItineraryActivity.cost_source is excluded from serialization but is
    injected back onto each serialized activity (mirroring the v11 transit
    leg cost injection), so consumers can tell a provider price from an
    estimator output.
    """
    class Provider:
        async def plan(self, _command: object):
            return make_result()

    event = asyncio.run(
        process_planning_create(
            make_command(start_date="2026-08-01", end_date="2026-08-01"),
            Provider(),
        )
    )

    wire = event.model_dump(mode="json", by_alias=True, exclude_none=False)
    valid_sources = {
        "PROVIDER", "RULE_ESTIMATE", "CATEGORY_ESTIMATE", "CITY_ESTIMATE",
        "DEMO", "UNKNOWN",
    }
    activities = [
        activity
        for day in wire["payload"]["itinerary"]["days"]
        for activity in day["activities"]
    ]
    assert activities, "worker wire must expose at least one activity"
    for activity in activities:
        assert "costSource" in activity, "activity is missing costSource"
        assert activity["costSource"] in valid_sources


def test_fact_impact_omits_none_optional_fields_on_the_wire() -> None:
    """A fact impact must omit every optional-not-nullable field, never emit null.

    The v10 schema declares date/targetPoiId/targetName/sourceUrl optional
    (absent means no value, e.g. a city-wide weather impact); a
    present-but-null value is rejected by both the JSON Schema and the Java
    parsers (PlanningCompletedEventParser / PlanningReviewRequiredEventParser).
    """
    from trip_agent.worker.contracts import PlanningFactImpact

    impact = PlanningFactImpact(
        fact_id="fact_weather_citywide",
        category="WEATHER",
        date=None,
        effect="OUTDOOR_POI_DOWNRANKED",
        target_poi_id=None,
        target_name=None,
        reason="对应日期预计降雨，露天候选降低优先级",
        source_name="和风天气城市情报",
        source_type="CITY_INTELLIGENCE",
        source_url=None,
        reliability_level="WEATHER_PROVIDER",
        checked_at=datetime(2026, 8, 17, 11, 32, 18, tzinfo=UTC),
        evidence="2026-08-10 越秀历史天气：晴",
        stale=False,
        conflicted=True,
        refresh_failed=False,
    )

    wire = impact.model_dump(mode="json", by_alias=True, exclude_none=False)

    # All four optional-not-nullable fields must be absent, never null.
    for key in ("date", "targetPoiId", "targetName", "sourceUrl"):
        assert key not in wire, f"{key} must be omitted when unset"

    with_values = impact.model_copy(
        update={
            "date": datetime(2026, 8, 10, tzinfo=UTC).date(),
            "target_poi_id": "B00140T14D",
            "target_name": "陈家祠",
            "source_url": "https://www.qweather.com/weather/yuexiu-101280107.html",
        }
    )
    wire_with_values = with_values.model_dump(mode="json", by_alias=True, exclude_none=False)
    assert wire_with_values["targetPoiId"] == "B00140T14D"
    assert wire_with_values["targetName"] == "陈家祠"
    assert wire_with_values["sourceUrl"] == "https://www.qweather.com/weather/yuexiu-101280107.html"
    assert "date" in wire_with_values and "date" not in wire


def test_fact_impact_stale_fact_scenario_conforms_to_v10_schema() -> None:
    """A stale-fact impact (None target/source/date) must serialize schema-valid.

    trusted_context.py produces STALE_FACT_WARNING impacts with
    target_name=None; the v10 schema must accept the resulting wire JSON
    with no null value inside factImpacts items.
    """
    from trip_agent.worker.contracts import PlanningFactImpact

    impact = PlanningFactImpact(
        fact_id="fact_opening_stale",
        category="OPENING_HOURS",
        date=None,
        effect="STALE_FACT_WARNING",
        target_poi_id=None,
        target_name=None,
        reason="营业时间事实已超过新鲜度阈值",
        source_name="高德地图",
        source_type="MAP_PROVIDER",
        source_url=None,
        reliability_level="AMAP_POI",
        checked_at=datetime(2026, 8, 17, 11, 32, 18, tzinfo=UTC),
        evidence="POI 营业时间更新于 90 天前",
        stale=True,
        conflicted=False,
        refresh_failed=False,
    )

    wire = impact.model_dump(mode="json", by_alias=True, exclude_none=False)
    for key in ("date", "targetPoiId", "targetName", "sourceUrl"):
        assert key not in wire, f"{key} must be omitted when unset"

    event = json.loads(
        (Path(__file__).resolve().parents[3]
         / "contracts/fixtures/planning-completed-event-v10"
         / "completion-v10-unverified-savable.json").read_text(encoding="utf-8")
    )
    event["payload"]["factImpacts"] = [wire]
    schema = _load_schema("planning-completed-event-v10.schema.json")
    Draft202012Validator(schema).validate(event)


def test_completed_v10_shared_fixture_conforms_to_schema() -> None:
    fixture = json.loads(
        (Path(__file__).resolve().parents[3]
         / "contracts/fixtures/planning-completed-event-v10"
         / "completion-v10-unverified-savable.json").read_text(encoding="utf-8")
    )
    schema = _load_schema("planning-completed-event-v10.schema.json")
    Draft202012Validator(schema).validate(fixture)
    assert fixture["schemaVersion"] == 10
    assert fixture["payload"]["hasBlocker"] is False
    assert fixture["payload"]["feasibilityReport"]["status"] == "UNVERIFIED"


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


def test_publishing_progress_stage_matches_its_json_schema() -> None:
    event = PlanningProgressEvent(
        event_type="PLANNING_PROGRESS",
        schema_version=1,
        event_id=UUID("5aa31052-2c21-53af-bddb-6a86614d801b"),
        trace_id=UUID("ea930620-41a7-4fdc-b6d1-d298a850112a"),
        task_id=UUID("dfb858fc-b910-4056-a375-2366dcaab690"),
        trip_id=UUID("d209daf2-f004-42cc-8385-510825f40fe1"),
        occurred_at=datetime(2026, 7, 27, 8, 0, tzinfo=UTC),
        payload=PlanningProgressPayload(
            stage="RESULT_PUBLISHING",
            sequence=7,
            progress=95,
            message="Publishing planning result",
            statistics={},
        ),
    )

    schema = _load_schema("planning-progress-event-v1.schema.json")
    Draft202012Validator(schema).validate(event.model_dump(mode="json", by_alias=True))


def test_repair_progress_v2_matches_schema_and_requires_attempt_index() -> None:
    event = PlanningProgressEvent(
        event_type="PLANNING_PROGRESS",
        schema_version=2,
        event_id=UUID("5aa31052-2c21-53af-bddb-6a86614d801b"),
        trace_id=UUID("ea930620-41a7-4fdc-b6d1-d298a850112a"),
        task_id=UUID("dfb858fc-b910-4056-a375-2366dcaab690"),
        trip_id=UUID("d209daf2-f004-42cc-8385-510825f40fe1"),
        occurred_at=datetime(2026, 7, 27, 8, 0, tzinfo=UTC),
        payload=PlanningProgressPayload(
            stage="REPAIRING",
            sequence=8,
            progress=75,
            message="Applying bounded repair attempt",
            statistics={"attemptIndex": 2, "actionCount": 1},
        ),
    )
    body = event.model_dump(mode="json", by_alias=True)
    schema = _load_schema("planning-progress-event-v2.schema.json")

    Draft202012Validator(schema).validate(body)
    invalid = deepcopy(body)
    del invalid["payload"]["statistics"]["attemptIndex"]
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema).validate(invalid)


def _load_schema(file_name: str) -> dict[str, object]:
    with (CONTRACT_DIRECTORY / file_name).open(encoding="utf-8") as schema_file:
        return json.load(schema_file)


def _local_schema_registry():
    from referencing import Registry, Resource

    registry = Registry()
    for path in CONTRACT_DIRECTORY.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return registry


def test_every_active_messaging_schema_is_a_valid_draft_2020_12_schema() -> None:
    for file_name in ACTIVE_SCHEMA_FILES:
        Draft202012Validator.check_schema(_load_schema(file_name))


def test_planning_failed_event_model_matches_its_json_schema() -> None:
    event = PlanningFailedEvent(
        event_type="PLANNING_FAILED",
        schema_version=2,
        event_id=UUID("38e10d2b-fd84-55ae-97dc-a1e00cac682b"),
        trace_id=UUID("ea930620-41a7-4fdc-b6d1-d298a850112a"),
        task_id=UUID("dfb858fc-b910-4056-a375-2366dcaab690"),
        trip_id=UUID("d209daf2-f004-42cc-8385-510825f40fe1"),
        run_id=UUID("3b85b6b6-9e42-433b-90ef-d94a3eb26e18"),
        occurred_at=datetime(2026, 7, 26, 8, 0, tzinfo=UTC),
        payload=PlanningFailedPayload(
            status="FAILED",
            error_code="NO_FEASIBLE_ITINERARY",
            error_category="PLANNING_INFEASIBLE",
            provider="PLANNER",
            operation="PLANNING",
            retryable=False,
            retry_count=0,
            fallback_attempted=False,
            fallback_succeeded=False,
            safe_message="时间、交通与固定安排无法同时满足",
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

    schema = _load_schema("planning-failed-event-v2.schema.json")
    Draft202012Validator(schema).validate(event.model_dump(mode="json", by_alias=True))


# ── B6.1: v9/review schema hard constraints ────────────────────────────────


def test_v9_schema_requires_evaluation_in_both_payloads() -> None:
    schema = _load_schema("planning-completed-event-v9.schema.json")
    for payload_name in ("amapPayload", "demoPayload"):
        payload = schema["$defs"][payload_name]
        assert "evaluation" in payload["required"], payload_name
        assert "feasibilityReport" in payload["required"], payload_name


def test_v9_schema_report_status_is_const_verified() -> None:
    schema = _load_schema("planning-completed-event-v9.schema.json")
    for payload_name in ("amapPayload", "demoPayload"):
        payload = schema["$defs"][payload_name]
        ref = payload["properties"]["feasibilityReport"]["$ref"]
        report = schema["$defs"][ref.split("/")[-1]]
        assert report["properties"]["status"] == {"const": "VERIFIED"}


def test_v9_schema_rejects_fixture_without_evaluation() -> None:
    import copy
    import json

    schema = _load_schema("planning-completed-event-v9.schema.json")
    registry = _local_schema_registry()
    fixture = json.loads(
        (COMPLETION_V9_FIXTURE_DIRECTORY / "completion-v9-verified-amap.json").read_text(
            encoding="utf-8"
        )
    )
    broken = copy.deepcopy(fixture)
    del broken["payload"]["evaluation"]
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema, registry=registry).validate(broken)


def test_v9_schema_rejects_unverified_and_needs_repair_status() -> None:
    import copy
    import json

    schema = _load_schema("planning-completed-event-v9.schema.json")
    registry = _local_schema_registry()
    fixture = json.loads(
        (COMPLETION_V9_FIXTURE_DIRECTORY / "completion-v9-verified-amap.json").read_text(
            encoding="utf-8"
        )
    )
    for status in ("UNVERIFIED", "NEEDS_REPAIR"):
        broken = copy.deepcopy(fixture)
        broken["payload"]["feasibilityReport"]["status"] = status
        with pytest.raises(JsonSchemaValidationError):
            Draft202012Validator(schema, registry=registry).validate(broken)


def test_v9_schema_accepts_verified_fixture() -> None:
    import json

    schema = _load_schema("planning-completed-event-v9.schema.json")
    registry = _local_schema_registry()
    fixture = json.loads(
        (COMPLETION_V9_FIXTURE_DIRECTORY / "completion-v9-verified-amap.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema, registry=registry).validate(fixture)


# ── B6.1: active schema coverage for v9/review ──────────────────────────────


def test_active_schema_check_includes_v9_and_review() -> None:
    names = set(ACTIVE_SCHEMA_FILES)
    assert "planning-completed-event-v9.schema.json" in names
    assert "planning-review-required-event-v1.schema.json" in names


def test_all_active_schemas_have_matching_fixture_sets() -> None:
    import json

    registry = _local_schema_registry()
    for schema_name in ACTIVE_SCHEMA_FILES:
        schema = _load_schema(schema_name)
        base = schema_name.removesuffix(".schema.json")
        fixture_dir = CONTRACT_DIRECTORY.parent / "fixtures" / base
        if not fixture_dir.exists():
            continue
        for fixture in fixture_dir.glob("*.json"):
            Draft202012Validator(schema, registry=registry).validate(
                json.loads(fixture.read_text(encoding="utf-8"))
            )
    # v9/review fixtures are covered explicitly below.
    v9 = _load_schema("planning-completed-event-v9.schema.json")
    review = _load_schema("planning-review-required-event-v1.schema.json")
    for fixture in COMPLETION_V9_FIXTURE_DIRECTORY.glob("*.json"):
        Draft202012Validator(v9, registry=registry).validate(
            json.loads(fixture.read_text(encoding="utf-8"))
        )
    for fixture in REVIEW_V1_FIXTURE_DIRECTORY.glob("*.json"):
        Draft202012Validator(review, registry=registry).validate(
            json.loads(fixture.read_text(encoding="utf-8"))
        )


def test_schema_and_model_agree_on_required_fields() -> None:
    """Both the v9 schema and the v11 model reject payloads missing the
    authoritative outcome fields.

    F-3c removed the v9 model; the schema half keeps the v9 fixture against
    the v9 schema (still active), while the model half re-derives the same
    hard-constraint check from the current v11 model + v11 fixture.
    """
    import copy
    import json

    schema = _load_schema("planning-completed-event-v9.schema.json")
    registry = _local_schema_registry()
    fixture = json.loads(
        (COMPLETION_V9_FIXTURE_DIRECTORY / "completion-v9-verified-amap.json").read_text(
            encoding="utf-8"
        )
    )
    # model requires evaluation and feasibilityReport; drop each and check
    # that BOTH the schema and the Pydantic model reject the payload.
    for field in ("evaluation", "feasibilityReport"):
        broken = copy.deepcopy(fixture)
        del broken["payload"][field]
        with pytest.raises(JsonSchemaValidationError):
            Draft202012Validator(schema, registry=registry).validate(broken)

    from trip_agent.worker.contracts import PlanningCompletedEventV11

    v11_fixture = json.loads(
        (
            COMPLETION_V11_FIXTURE_DIRECTORY / "completion-v11-transit-savable.json"
        ).read_text(encoding="utf-8")
    )
    for field in ("evaluation", "feasibilityReport"):
        broken = copy.deepcopy(v11_fixture)
        del broken["payload"][field]
        with pytest.raises(Exception) as exc:
            PlanningCompletedEventV11.model_validate(broken)
        assert exc.value


# ── B13-D: planning-create-command v4 with PlaceRef ─────────────────────────

CREATE_V4_FIXTURE_DIRECTORY = (
    Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "planning-create-command-v4"
)


def test_v4_schema_accepts_the_place_ref_fixture() -> None:
    import json

    schema = _load_schema("planning-create-command-v4.schema.json")
    registry = _local_schema_registry()
    fixture = json.loads((CREATE_V4_FIXTURE_DIRECTORY / "valid.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, registry=registry).validate(fixture)


def test_v4_schema_rejects_unknown_place_provider() -> None:
    import copy
    import json

    schema = _load_schema("planning-create-command-v4.schema.json")
    registry = _local_schema_registry()
    fixture = json.loads((CREATE_V4_FIXTURE_DIRECTORY / "valid.json").read_text(encoding="utf-8"))
    broken = copy.deepcopy(fixture)
    broken["payload"]["trip"]["constraints"]["mustVisitPlaceRefs"][0]["provider"] = "GOOGLE"
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema, registry=registry).validate(broken)


def test_v4_schema_accepts_constraints_schema_version_2() -> None:
    # B13_FIX R1: v4 carries the authoritative boundaries regardless of
    # whether constraints carry place refs (schema 2 = no refs is fine).
    import copy
    import json

    schema = _load_schema("planning-create-command-v4.schema.json")
    registry = _local_schema_registry()
    fixture = json.loads((CREATE_V4_FIXTURE_DIRECTORY / "valid.json").read_text(encoding="utf-8"))
    broken = copy.deepcopy(fixture)
    constraints = broken["payload"]["trip"]["constraints"]
    constraints["schemaVersion"] = 2
    constraints.pop("mustVisitPlaceRefs", None)
    constraints.pop("avoidPlaceRefs", None)
    for anchor in ("arrival", "departure", "accommodation"):
        if constraints.get(anchor):
            constraints[anchor].pop("placeRef", None)
    Draft202012Validator(schema, registry=registry).validate(broken)


def test_v4_schema_rejects_constraints_schema_version_2_with_refs() -> None:
    # B13_FIX R2 (P0-2): schema 2 is legacy-only — any refs (list or anchor)
    # must be rejected by the JSON Schema, matching Java and Python.
    import copy
    import json

    schema = _load_schema("planning-create-command-v4.schema.json")
    registry = _local_schema_registry()
    fixture = json.loads((CREATE_V4_FIXTURE_DIRECTORY / "valid.json").read_text(encoding="utf-8"))
    for refs_field in ("mustVisitPlaceRefs", "avoidPlaceRefs"):
        broken = copy.deepcopy(fixture)
        broken["payload"]["trip"]["constraints"]["schemaVersion"] = 2
        broken["payload"]["trip"]["constraints"][refs_field] = [copy.deepcopy(
            fixture["payload"]["trip"]["constraints"]["mustVisitPlaceRefs"][0]
        )]
        with pytest.raises(JsonSchemaValidationError):
            Draft202012Validator(schema, registry=registry).validate(broken)
    broken = copy.deepcopy(fixture)
    broken["payload"]["trip"]["constraints"]["schemaVersion"] = 2
    broken["payload"]["trip"]["constraints"]["arrival"]["placeRef"] = copy.deepcopy(
        fixture["payload"]["trip"]["constraints"]["mustVisitPlaceRefs"][0]
    )
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema, registry=registry).validate(broken)


def test_v4_schema_rejects_refs_count_mismatch() -> None:
    # B13_FIX R2 (P0-2): once any ref is present, the ref count must equal
    # the name count — the mixed legacy/structured rule in the JSON Schema.
    import copy
    import json

    schema = _load_schema("planning-create-command-v4.schema.json")
    registry = _local_schema_registry()
    fixture = json.loads((CREATE_V4_FIXTURE_DIRECTORY / "valid.json").read_text(encoding="utf-8"))
    broken = copy.deepcopy(fixture)
    constraints = broken["payload"]["trip"]["constraints"]
    constraints["mustVisitPlaces"] = ["陈家祠", "光孝寺"]
    constraints["mustVisitPlaceRefs"] = [copy.deepcopy(
        fixture["payload"]["trip"]["constraints"]["mustVisitPlaceRefs"][0]
    )]
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema, registry=registry).validate(broken)


def test_v4_schema_accepts_legacy_names_with_empty_refs() -> None:
    # B13_FIX R2 (P0-2): legacy free-text names with NO structured refs stay
    # legal under schema 3 (historical text was never structured).
    import copy
    import json

    schema = _load_schema("planning-create-command-v4.schema.json")
    registry = _local_schema_registry()
    fixture = json.loads((CREATE_V4_FIXTURE_DIRECTORY / "valid.json").read_text(encoding="utf-8"))
    broken = copy.deepcopy(fixture)
    constraints = broken["payload"]["trip"]["constraints"]
    constraints["mustVisitPlaces"] = ["陈家祠", "光孝寺"]
    constraints["mustVisitPlaceRefs"] = []
    constraints["avoidPlaces"] = []
    constraints["avoidPlaceRefs"] = []
    Draft202012Validator(schema, registry=registry).validate(broken)


def test_v4_schema_requires_snapshot_boundary_fields() -> None:
    import copy
    import json

    schema = _load_schema("planning-create-command-v4.schema.json")
    registry = _local_schema_registry()
    fixture = json.loads((CREATE_V4_FIXTURE_DIRECTORY / "valid.json").read_text(encoding="utf-8"))
    broken = copy.deepcopy(fixture)
    del broken["payload"]["trip"]["arrivalAt"]
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema, registry=registry).validate(broken)


def test_v4_schema_rejects_command_schema_version_3() -> None:
    import copy
    import json

    schema = _load_schema("planning-create-command-v4.schema.json")
    registry = _local_schema_registry()
    fixture = json.loads((CREATE_V4_FIXTURE_DIRECTORY / "valid.json").read_text(encoding="utf-8"))
    broken = copy.deepcopy(fixture)
    broken["schemaVersion"] = 3
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema, registry=registry).validate(broken)


# ── B13_FIX R1: replan v2 / candidate-validation v2 fixtures ────────────────

REPLAN_V2_FIXTURE_DIRECTORY = (
    Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "planning-replan-command-v2"
)
CANDIDATE_V2_FIXTURE_DIRECTORY = (
    Path(__file__).resolve().parents[3]
    / "contracts"
    / "fixtures"
    / "planning-candidate-validation-command-v2"
)


def test_replan_v2_schema_accepts_its_fixture() -> None:
    import json

    schema = _load_schema("planning-replan-command-v2.schema.json")
    registry = _local_schema_registry()
    fixture = json.loads(
        (REPLAN_V2_FIXTURE_DIRECTORY / "valid.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema, registry=registry).validate(fixture)


def test_replan_v2_schema_accepts_the_existing_transit_runtime_mode() -> None:
    import copy
    import json

    schema = _load_schema("planning-replan-command-v2.schema.json")
    registry = _local_schema_registry()
    fixture = json.loads(
        (REPLAN_V2_FIXTURE_DIRECTORY / "valid.json").read_text(encoding="utf-8")
    )
    day = fixture["payload"]["itinerary"]["days"][0]
    second = copy.deepcopy(day["activities"][0])
    second["title"] = "Tower"
    second["providerPoiId"] = "tower"
    second["coordinates"] = {"longitude": 113.32, "latitude": 23.12}
    day["activities"].append(second)
    day["transitLegs"].append(
        {
            "fromActivityIndex": 0,
            "toActivityIndex": 1,
            "mode": "TRANSIT",
            "distanceMeters": 1800,
            "durationSeconds": 720,
            "provider": "AMAP",
            "estimated": False,
            "locked": False,
            "estimatedCost": 3,
            "costSource": "PROVIDER",
            "polyline": [
                {"longitude": 113.31, "latitude": 23.11},
                {"longitude": 113.32, "latitude": 23.12},
            ],
        }
    )

    Draft202012Validator(schema, registry=registry).validate(fixture)


def test_replan_v2_schema_accepts_the_java_day_and_activity_snapshot_fields() -> None:
    import json

    schema = _load_schema("planning-replan-command-v2.schema.json")
    registry = _local_schema_registry()
    fixture = json.loads(
        (REPLAN_V2_FIXTURE_DIRECTORY / "valid.json").read_text(encoding="utf-8")
    )
    day = fixture["payload"]["itinerary"]["days"][0]
    day["dayType"] = "FULL_DAY"
    activity = day["activities"][0]
    activity.update(
        {
            "kind": "ATTRACTION",
            "timeFixed": False,
            "locked": True,
            "typeCode": "110000",
            "typeName": "景点",
        }
    )

    Draft202012Validator(schema, registry=registry).validate(fixture)


def test_replan_v2_fixture_parses_with_the_python_model() -> None:
    import json

    from trip_agent.worker.contracts import PlanningReplanCommand

    fixture = json.loads(
        (REPLAN_V2_FIXTURE_DIRECTORY / "valid.json").read_text(encoding="utf-8")
    )
    command = PlanningReplanCommand.model_validate(fixture)
    assert command.schema_version == 2
    assert command.payload.trip.arrival_at is not None
    assert command.payload.trip.departure_at is not None
    assert command.payload.trip.constraints.schema_version == 3


def test_replan_v2_schema_rejects_v1_body() -> None:
    import json

    schema = _load_schema("planning-replan-command-v2.schema.json")
    registry = _local_schema_registry()
    fixture = json.loads(
        (REPLAN_V2_FIXTURE_DIRECTORY / "valid.json").read_text(encoding="utf-8")
    )
    fixture["schemaVersion"] = 1
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema, registry=registry).validate(fixture)


def test_candidate_v2_schema_accepts_edit_and_rollback_fixtures() -> None:
    import json

    schema = _load_schema("planning-candidate-validation-command-v2.schema.json")
    registry = _local_schema_registry()
    for name in ("valid-edit.json", "valid-rollback.json"):
        fixture = json.loads(
            (CANDIDATE_V2_FIXTURE_DIRECTORY / name).read_text(encoding="utf-8")
        )
        Draft202012Validator(schema, registry=registry).validate(fixture)


def test_candidate_v2_schema_accepts_the_existing_transit_runtime_mode() -> None:
    import copy
    import json

    schema = _load_schema("planning-candidate-validation-command-v2.schema.json")
    registry = _local_schema_registry()
    fixture = json.loads(
        (CANDIDATE_V2_FIXTURE_DIRECTORY / "valid-edit.json").read_text(encoding="utf-8")
    )
    day = fixture["payload"]["itinerary"]["days"][0]
    second = copy.deepcopy(day["activities"][0])
    second["title"] = "Tower"
    second["providerPoiId"] = "tower"
    second["coordinates"] = {"longitude": 113.32, "latitude": 23.12}
    day["activities"].append(second)
    day["transitLegs"].append(
        {
            "fromActivityIndex": 0,
            "toActivityIndex": 1,
            "mode": "TRANSIT",
            "distanceMeters": 1800,
            "durationSeconds": 720,
            "provider": "AMAP",
            "estimated": False,
            "estimatedCost": 3,
            "costSource": "PROVIDER",
            "polyline": [
                {"longitude": 113.31, "latitude": 23.11},
                {"longitude": 113.32, "latitude": 23.12},
            ],
            "locked": False,
        }
    )

    Draft202012Validator(schema, registry=registry).validate(fixture)


def test_candidate_v2_fixtures_parse_with_the_python_model() -> None:
    import json

    from trip_agent.worker.contracts import PlanningCandidateValidationCommand

    for name in ("valid-edit.json", "valid-rollback.json"):
        fixture = json.loads(
            (CANDIDATE_V2_FIXTURE_DIRECTORY / name).read_text(encoding="utf-8")
        )
        command = PlanningCandidateValidationCommand.model_validate(fixture)
        assert command.schema_version == 2
        assert command.payload.trip.arrival_at is not None
        assert command.payload.trip.departure_at is not None


def test_v1_legacy_fixtures_keep_their_published_meaning() -> None:
    import json

    schema = _load_schema("planning-candidate-validation-command-v1.schema.json")
    registry = _local_schema_registry()
    for name in ("valid-edit.json", "valid-rollback.json"):
        fixture = json.loads(
            (
                Path(__file__).resolve().parents[3]
                / "contracts"
                / "fixtures"
                / "planning-candidate-validation-command-v1"
                / name
            ).read_text(encoding="utf-8")
        )
        Draft202012Validator(schema, registry=registry).validate(fixture)


COMPLETION_V10_FIXTURE_DIRECTORY = (
    Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "planning-completed-event-v10"
)


def _v10_completion_fixture() -> dict[str, object]:
    return json.loads(
        (
            COMPLETION_V10_FIXTURE_DIRECTORY / "completion-v10-unverified-savable.json"
        ).read_text(encoding="utf-8")
    )


def _v11_completion_with_transit_leg(mode: str) -> dict[str, object]:
    fixture = _v10_completion_fixture()
    fixture["schemaVersion"] = 11
    fixture["payload"]["itinerary"]["days"][0]["transitLegs"][0]["mode"] = mode
    return fixture


def test_active_schema_check_includes_v11_and_review_v2() -> None:
    assert "planning-completed-event-v11.schema.json" in ACTIVE_SCHEMA_FILES
    assert "planning-review-required-event-v2.schema.json" in ACTIVE_SCHEMA_FILES


def test_v11_completed_schema_accepts_a_transit_leg() -> None:
    schema = _load_schema("planning-completed-event-v11.schema.json")
    registry = _local_schema_registry()
    Draft202012Validator(schema, registry=registry).validate(
        _v11_completion_with_transit_leg(mode="TRANSIT")
    )


def test_v11_completed_schema_rejects_taxi_mode() -> None:
    schema = _load_schema("planning-completed-event-v11.schema.json")
    registry = _local_schema_registry()
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema, registry=registry).validate(
            _v11_completion_with_transit_leg(mode="TAXI")
        )


def test_v11_completed_python_model_rejects_taxi_mode() -> None:
    from pydantic import ValidationError

    from trip_agent.worker.contracts import PlanningCompletedEventV11

    with pytest.raises(ValidationError, match="forbid TAXI"):
        PlanningCompletedEventV11.model_validate(
            _v11_completion_with_transit_leg(mode="TAXI")
        )


def test_v10_completed_schema_rejects_a_transit_leg() -> None:
    schema = _load_schema("planning-completed-event-v10.schema.json")
    registry = _local_schema_registry()
    fixture = _v10_completion_fixture()
    fixture["payload"]["itinerary"]["days"][0]["transitLegs"][0]["mode"] = "TRANSIT"
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema, registry=registry).validate(fixture)


def test_review_v1_schema_rejects_a_transit_leg() -> None:
    schema = _load_schema("planning-review-required-event-v1.schema.json")
    registry = _local_schema_registry()
    fixture = json.loads(
        (REVIEW_V1_FIXTURE_DIRECTORY / "review-v1-unverified-demo.json").read_text(
            encoding="utf-8"
        )
    )
    fixture["payload"]["itinerary"]["days"][0]["transitLegs"][0]["mode"] = "TRANSIT"
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema, registry=registry).validate(fixture)


def test_review_v2_schema_accepts_a_transit_leg() -> None:
    schema = _load_schema("planning-review-required-event-v2.schema.json")
    registry = _local_schema_registry()
    fixture = json.loads(
        (REVIEW_V1_FIXTURE_DIRECTORY / "review-v1-unverified-demo.json").read_text(
            encoding="utf-8"
        )
    )
    fixture["schemaVersion"] = 2
    fixture["payload"]["itinerary"]["days"][0]["transitLegs"][0]["mode"] = "TRANSIT"
    Draft202012Validator(schema, registry=registry).validate(fixture)


def test_review_v2_python_model_rejects_taxi_mode() -> None:
    from pydantic import ValidationError

    from trip_agent.worker.contracts import PlanningReviewRequiredEventV2

    fixture = json.loads(
        (REVIEW_V1_FIXTURE_DIRECTORY / "review-v1-unverified-demo.json").read_text(
            encoding="utf-8"
        )
    )
    fixture["schemaVersion"] = 2
    fixture["payload"]["itinerary"]["days"][0]["transitLegs"][0]["mode"] = "TAXI"
    with pytest.raises(ValidationError, match="forbid TAXI"):
        PlanningReviewRequiredEventV2.model_validate(fixture)


def test_v11_completed_and_review_v2_models_are_defined() -> None:
    from trip_agent.worker.contracts import (
        PlanningCompletedEventV11,
        PlanningReviewRequiredEventV2,
    )

    assert PlanningCompletedEventV11.__name__ == "PlanningCompletedEventV11"
    assert PlanningReviewRequiredEventV2.__name__ == "PlanningReviewRequiredEventV2"


def test_worker_emits_the_v11_completion_contract() -> None:
    payload = deepcopy(_v3_command())
    payload["payload"]["trip"]["constraints"]["mustVisitPlaces"] = []
    command = PlanningCreateCommand.model_validate(payload)
    event = asyncio.run(process_planning_create(command, DemoPlanningProvider()))

    assert event.schema_version == 11
