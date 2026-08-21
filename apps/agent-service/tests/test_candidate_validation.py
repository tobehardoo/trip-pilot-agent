"""B8 — candidate validation command and worker outcome flow."""

import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_local_replanning import REPLAN_COMMAND

CONTRACT_DIRECTORY = Path(__file__).parents[3] / "contracts" / "messaging"
CANDIDATE_FIXTURE_DIRECTORY = (
    Path(__file__).parents[3]
    / "contracts"
    / "fixtures"
    / "planning-candidate-validation-command-v1"
)


def _candidate_command(*, candidate_type: str = "EDIT") -> dict[str, object]:
    command = deepcopy(REPLAN_COMMAND)
    command["eventType"] = "PLANNING_CANDIDATE_VALIDATION_REQUESTED"
    payload = command["payload"]
    assert isinstance(payload, dict)
    payload["taskType"] = f"{candidate_type}_VALIDATE"
    payload["candidateType"] = candidate_type
    payload["changedDates"] = ["2026-08-01"]
    payload["impactedDates"] = ["2026-08-01", "2026-08-02"]
    payload["planningContext"] = None
    payload["rollbackFromVersionId"] = (
        "1b748af8-58fc-4515-8c39-29c68c5ae9f3" if candidate_type == "ROLLBACK" else None
    )
    for day in payload["itinerary"]["days"]:
        day["dayType"] = "FULL_DAY"
        for activity in day["activities"]:
            activity["locked"] = False
        for leg in day["transitLegs"]:
            leg["locked"] = False
    return command


def test_candidate_command_preserves_edit_lock_state() -> None:
    from trip_agent.worker.contracts import PlanningCandidateValidationCommand

    raw = _candidate_command()
    payload = raw["payload"]
    assert isinstance(payload, dict)
    payload["itinerary"]["days"][0]["activities"][0]["locked"] = True

    command = PlanningCandidateValidationCommand.model_validate(raw)

    assert command.payload.candidate_type == "EDIT"
    assert command.payload.task_type == "EDIT_VALIDATE"
    assert command.payload.itinerary.days[0].activities[0].locked is True


def test_candidate_v2_rejects_persisted_taxi_at_the_provider_boundary() -> None:
    from trip_agent.worker.contracts import PlanningCandidateValidationCommand

    raw = _candidate_command()
    raw["schemaVersion"] = 2
    raw["payload"]["trip"]["arrivalAt"] = None
    raw["payload"]["trip"]["departureAt"] = None
    leg = raw["payload"]["itinerary"]["days"][1]["transitLegs"][0]
    leg["mode"] = "TAXI"

    with pytest.raises(ValidationError, match="forbid TAXI"):
        PlanningCandidateValidationCommand.model_validate(raw)


def test_candidate_command_preserves_rollback_and_transit_lock_state() -> None:
    from trip_agent.worker.contracts import PlanningCandidateValidationCommand

    raw = _candidate_command(candidate_type="ROLLBACK")
    payload = raw["payload"]
    assert isinstance(payload, dict)
    payload["itinerary"]["days"][1]["transitLegs"][0]["locked"] = True

    command = PlanningCandidateValidationCommand.model_validate(raw)

    assert command.payload.candidate_type == "ROLLBACK"
    assert command.payload.rollback_from_version_id is not None
    assert command.payload.itinerary.days[1].transit_legs[0].locked is True


def test_candidate_command_accepts_mixed_provider_snapshot() -> None:
    from trip_agent.worker.contracts import PlanningCandidateValidationCommand

    raw = _candidate_command()
    payload = raw["payload"]
    assert isinstance(payload, dict)
    payload["itinerary"]["provider"] = "MIXED"
    demo_activity = payload["itinerary"]["days"][1]["activities"][0]
    demo_activity["source"] = "DEMO"
    for field in ("providerPoiId", "coordinates", "address"):
        demo_activity[field] = None

    command = PlanningCandidateValidationCommand.model_validate(raw)

    assert command.payload.itinerary.provider == "MIXED"
    assert {
        activity.source for day in command.payload.itinerary.days for activity in day.activities
    } == {"AMAP", "DEMO"}


def test_candidate_command_accepts_persisted_demo_transit_without_internal_cost() -> None:
    """Java's persisted candidate envelope excludes Python-only route-cost metadata."""
    from trip_agent.worker.contracts import PlanningCandidateValidationCommand

    raw = _candidate_command()
    payload = raw["payload"]
    assert isinstance(payload, dict)
    payload["itinerary"]["provider"] = "DEMO"
    for day in payload["itinerary"]["days"]:
        for activity in day["activities"]:
            activity["source"] = "DEMO"
            for field in ("providerPoiId", "coordinates", "address"):
                activity[field] = None
        for leg in day["transitLegs"]:
            leg["provider"] = "DEMO"
            leg["estimated"] = True

    command = PlanningCandidateValidationCommand.model_validate(raw)

    assert all(
        leg.provider == "DEMO" and leg.estimated_cost is None
        for day in command.payload.itinerary.days
        for leg in day.transit_legs
    )


@pytest.mark.parametrize(
    ("candidate_type", "task_type", "rollback_id"),
    [
        ("EDIT", "ROLLBACK_VALIDATE", None),
        ("ROLLBACK", "EDIT_VALIDATE", "1b748af8-58fc-4515-8c39-29c68c5ae9f3"),
        ("EDIT", "EDIT_VALIDATE", "1b748af8-58fc-4515-8c39-29c68c5ae9f3"),
        ("ROLLBACK", "ROLLBACK_VALIDATE", None),
    ],
)
def test_candidate_command_rejects_identity_mismatches(
    candidate_type: str,
    task_type: str,
    rollback_id: str | None,
) -> None:
    from trip_agent.worker.contracts import PlanningCandidateValidationCommand

    raw = _candidate_command(candidate_type=candidate_type)
    payload = raw["payload"]
    assert isinstance(payload, dict)
    payload["taskType"] = task_type
    payload["rollbackFromVersionId"] = rollback_id

    with pytest.raises(ValidationError):
        PlanningCandidateValidationCommand.model_validate(raw)


def test_candidate_command_rejects_unexpanded_impacted_scope() -> None:
    from trip_agent.worker.contracts import PlanningCandidateValidationCommand

    raw = _candidate_command()
    payload = raw["payload"]
    assert isinstance(payload, dict)
    payload["impactedDates"] = ["2026-08-02"]

    with pytest.raises(ValidationError, match=r"N-1/N/N\+1"):
        PlanningCandidateValidationCommand.model_validate(raw)


def test_candidate_validation_emits_existing_review_outcome() -> None:
    from trip_agent.application.candidate_validation import CandidateValidationProvider
    from trip_agent.worker.contracts import (
        PlanningCandidateValidationCommand,
        PlanningReviewRequiredEventV2,
    )
    from trip_agent.worker.processor import process_candidate_validation

    command = PlanningCandidateValidationCommand.model_validate(_candidate_command())
    event = asyncio.run(
        process_candidate_validation(
            command,
            CandidateValidationProvider(),
            occurred_at=datetime(2026, 8, 13, 4, 0, tzinfo=UTC),
        )
    )

    assert isinstance(event, PlanningReviewRequiredEventV2)
    assert event.payload.status == "WAITING_USER"
    assert event.payload.itinerary.days[0].activities[0].locked is False


@pytest.mark.parametrize("candidate_type", ["EDIT", "ROLLBACK"])
def test_candidate_validation_command_matches_shared_schema(candidate_type: str) -> None:
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    from trip_agent.worker.contracts import PlanningCandidateValidationCommand

    raw = _candidate_command(candidate_type=candidate_type)
    PlanningCandidateValidationCommand.model_validate(raw)
    schema = json.loads(
        (CONTRACT_DIRECTORY / "planning-candidate-validation-command-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )

    registry = Registry()
    for path in CONTRACT_DIRECTORY.glob("*.schema.json"):
        dependency = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(dependency["$id"], Resource.from_contents(dependency))
    Draft202012Validator(schema, registry=registry).validate(raw)


def test_shared_candidate_command_fixtures_match_python_and_schema() -> None:
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    from trip_agent.worker.contracts import PlanningCandidateValidationCommand

    schema = json.loads(
        (CONTRACT_DIRECTORY / "planning-candidate-validation-command-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    registry = Registry()
    for path in CONTRACT_DIRECTORY.glob("*.schema.json"):
        dependency = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(dependency["$id"], Resource.from_contents(dependency))
    validator = Draft202012Validator(schema, registry=registry)

    for fixture_path in sorted(CANDIDATE_FIXTURE_DIRECTORY.glob("valid-*.json")):
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        validator.validate(fixture)
        PlanningCandidateValidationCommand.model_validate(fixture)


def test_shared_invalid_candidate_command_fixture_is_rejected() -> None:
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    from trip_agent.worker.contracts import PlanningCandidateValidationCommand

    fixture = json.loads(
        (CANDIDATE_FIXTURE_DIRECTORY / "invalid" / "edit-with-rollback-source.json").read_text(
            encoding="utf-8"
        )
    )
    schema = json.loads(
        (CONTRACT_DIRECTORY / "planning-candidate-validation-command-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    registry = Registry()
    for path in CONTRACT_DIRECTORY.glob("*.schema.json"):
        dependency = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(dependency["$id"], Resource.from_contents(dependency))

    from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema, registry=registry).validate(fixture)
    with pytest.raises(ValidationError):
        PlanningCandidateValidationCommand.model_validate(fixture)


def test_candidate_validation_mixed_snapshot_emits_wire_legal_provider() -> None:
    """F5: a MIXED snapshot provider (Java persistence aggregate from DEMO
    fallback legs; activities stay AMAP per the v11 wire contract) must not
    flow through to the wire completion provider (AMAP/DEMO only) — it used
    to raise ValidationError -> INTERNAL_ERROR with no terminal outcome."""
    from trip_agent.application.candidate_validation import CandidateValidationProvider
    from trip_agent.worker.contracts import PlanningCandidateValidationCommand
    from trip_agent.worker.processor import process_candidate_validation

    raw = _candidate_command()
    payload = raw["payload"]
    assert isinstance(payload, dict)
    payload["itinerary"]["provider"] = "MIXED"
    # activities stay AMAP (v11 wire const); the DEMO fallback lives on the
    # transit legs — the actual shape Java persists for a MIXED version.

    command = PlanningCandidateValidationCommand.model_validate(raw)
    event = asyncio.run(
        process_candidate_validation(
            command,
            CandidateValidationProvider(),
            occurred_at=datetime(2026, 8, 13, 4, 0, tzinfo=UTC),
        )
    )

    assert event.payload.provider in {"AMAP", "DEMO"}
    assert event.payload.provider != "MIXED"
    assert event.payload.provider != "MIXED"

