"""B13_FIX R1 — authoritative arrivalAt/departureAt in planning snapshots.

P0-1: boundary times were persisted but never travelled in the planning
command, so late-arrival / early-departure constraints were silently lost.
These tests pin the corrected contract semantics (create v4, replan v2,
candidate-validation v2).
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from test_planning_context_v3 import _v3_command

from trip_agent.worker.contracts import (
    PlanningCandidateValidationCommand,
    PlanningCreateCommand,
    PlanningReplanCommand,
)

ARRIVAL = "2026-08-01T18:00:00+08:00"
DEPARTURE = "2026-08-03T08:00:00+08:00"
CN = timezone(timedelta(hours=8))

_MISSING = object()


def _v4_command(
    *,
    arrival_at: str | None | object = ARRIVAL,
    departure_at: str | None | object = DEPARTURE,
    constraint_anchors: bool = False,
) -> dict:
    payload = deepcopy(_v3_command())
    payload["schemaVersion"] = 4
    constraints = payload["payload"]["trip"]["constraints"]
    constraints["schemaVersion"] = 3
    if not constraint_anchors:
        constraints.pop("arrival", None)
        constraints.pop("departure", None)
    # Keep must/avoid lists consistently empty so the ONLY error source in
    # R1 boundary tests is the snapshot boundary fields (R2 covers mixed
    # legacy/structured states separately).
    constraints["mustVisitPlaces"] = []
    constraints["mustVisitPlaceRefs"] = []
    constraints["avoidPlaces"] = []
    constraints["avoidPlaceRefs"] = []
    snapshot = payload["payload"]["trip"]
    if arrival_at is not _MISSING:
        snapshot["arrivalAt"] = arrival_at
    if departure_at is not _MISSING:
        snapshot["departureAt"] = departure_at
    return payload


def _replan_command(schema_version: int, *, with_boundaries: bool) -> dict:
    from test_local_replanning import REPLAN_COMMAND

    payload = deepcopy(REPLAN_COMMAND)
    payload["schemaVersion"] = schema_version
    if with_boundaries:
        snapshot = payload["payload"]["trip"]
        snapshot["arrivalAt"] = "2026-08-01T09:00:00+08:00"
        snapshot["departureAt"] = "2026-08-02T18:00:00+08:00"
    return payload


def _candidate_command(schema_version: int, *, with_boundaries: bool) -> dict:
    from datetime import date, timedelta

    from test_local_replanning import REPLAN_COMMAND

    payload = deepcopy(REPLAN_COMMAND)
    payload["eventType"] = "PLANNING_CANDIDATE_VALIDATION_REQUESTED"
    payload["schemaVersion"] = schema_version
    trip = payload["payload"]["trip"]
    changed = ["2026-08-01"]
    start = date.fromisoformat(trip["startDate"])
    end = date.fromisoformat(trip["endDate"])
    expected = {
        (start + timedelta(days=offset)).isoformat()
        for offset in range((end - start).days + 1)
    }
    impacted = sorted(
        {
            (date.fromisoformat(day) + timedelta(days=delta)).isoformat()
            for day in changed
            for delta in (-1, 0, 1)
        }
        & expected
    )
    payload["payload"] = {
        "taskType": "EDIT_VALIDATE",
        "candidateType": "EDIT",
        "baselineTripVersion": payload["payload"]["baselineTripVersion"],
        "baselineItineraryVersionId": payload["payload"]["baselineItineraryVersionId"],
        "rollbackFromVersionId": None,
        "idempotencyKey": payload["payload"]["idempotencyKey"],
        "changedDates": changed,
        "impactedDates": impacted,
        "trip": trip,
        "itinerary": payload["payload"]["itinerary"],
        "knowledge": payload["payload"]["knowledge"],
        "planningContext": None,
    }
    if with_boundaries:
        snapshot = payload["payload"]["trip"]
        snapshot["arrivalAt"] = "2026-08-01T09:00:00+08:00"
        snapshot["departureAt"] = "2026-08-02T18:00:00+08:00"
    return payload


# ── create v4 snapshot boundaries ────────────────────────────────────────────


def test_v4_requires_snapshot_boundary_fields() -> None:
    # Fields must be PRESENT in v4, even when null (legacy trip).
    payload = _v4_command(arrival_at=_MISSING, departure_at=_MISSING)
    with pytest.raises(ValidationError):
        PlanningCreateCommand.model_validate(payload)

    payload = _v4_command(arrival_at=_MISSING)
    with pytest.raises(ValidationError):
        PlanningCreateCommand.model_validate(payload)


def test_v4_accepts_authoritative_boundaries() -> None:
    command = PlanningCreateCommand.model_validate(_v4_command())
    snapshot = command.payload.trip
    assert snapshot.arrival_at == datetime(2026, 8, 1, 18, 0, tzinfo=CN)
    assert snapshot.departure_at == datetime(2026, 8, 3, 8, 0, tzinfo=CN)


def test_v4_rejects_naive_snapshot_boundary() -> None:
    with pytest.raises(ValidationError):
        PlanningCreateCommand.model_validate(_v4_command(arrival_at="2026-08-01T18:00:00"))


def test_v4_rejects_reversed_boundaries() -> None:
    with pytest.raises(ValidationError):
        PlanningCreateCommand.model_validate(
            _v4_command(arrival_at=DEPARTURE, departure_at=ARRIVAL)
        )


def test_v4_rejects_equal_boundaries() -> None:
    with pytest.raises(ValidationError):
        PlanningCreateCommand.model_validate(
            _v4_command(arrival_at=ARRIVAL, departure_at=ARRIVAL)
        )


def test_v4_accepts_null_boundaries_for_legacy_trips() -> None:
    # Legacy date-only trips keep null boundaries; the fields are present.
    command = PlanningCreateCommand.model_validate(
        _v4_command(arrival_at=None, departure_at=None)
    )
    assert command.payload.trip.arrival_at is None
    assert command.payload.trip.departure_at is None


def test_v4_allows_constraints_schema_2_without_place_refs() -> None:
    payload = _v4_command()
    payload["payload"]["trip"]["constraints"]["schemaVersion"] = 2
    payload["payload"]["trip"]["constraints"].pop("mustVisitPlaceRefs", None)
    payload["payload"]["trip"]["constraints"].pop("avoidPlaceRefs", None)
    command = PlanningCreateCommand.model_validate(payload)
    assert command.payload.trip.constraints.schema_version == 2


def test_v4_still_rejects_constraints_schema_1() -> None:
    payload = _v4_command()
    payload["payload"]["trip"]["constraints"]["schemaVersion"] = 1
    with pytest.raises(ValidationError):
        PlanningCreateCommand.model_validate(payload)


# ── legacy v2/v3 keep working without snapshot boundaries ────────────────────


def test_v3_command_without_snapshot_boundaries_still_parses() -> None:
    command = PlanningCreateCommand.model_validate(_v3_command())
    assert command.schema_version == 3
    assert command.payload.trip.arrival_at is None
    assert command.payload.trip.departure_at is None


# ── replan version matrix ────────────────────────────────────────────────────


def test_replan_v1_accepts_legacy_snapshot_without_boundaries() -> None:
    command = PlanningReplanCommand.model_validate(_replan_command(1, with_boundaries=False))
    assert command.schema_version == 1


def test_replan_v2_requires_boundary_fields() -> None:
    with pytest.raises(ValidationError):
        PlanningReplanCommand.model_validate(_replan_command(2, with_boundaries=False))


def test_replan_v2_accepts_boundary_fields() -> None:
    command = PlanningReplanCommand.model_validate(_replan_command(2, with_boundaries=True))
    assert command.schema_version == 2
    assert command.payload.trip.arrival_at is not None
    assert command.payload.trip.departure_at is not None


def test_replan_v2_rejects_naive_boundary() -> None:
    payload = _replan_command(2, with_boundaries=True)
    payload["payload"]["trip"]["arrivalAt"] = "2026-08-01T09:00:00"
    with pytest.raises(ValidationError):
        PlanningReplanCommand.model_validate(payload)


# ── candidate-validation version matrix ──────────────────────────────────────


def test_candidate_v1_accepts_legacy_snapshot_without_boundaries() -> None:
    command = PlanningCandidateValidationCommand.model_validate(
        _candidate_command(1, with_boundaries=False)
    )
    assert command.schema_version == 1


def test_candidate_v2_requires_boundary_fields() -> None:
    with pytest.raises(ValidationError):
        PlanningCandidateValidationCommand.model_validate(
            _candidate_command(2, with_boundaries=False)
        )


def test_candidate_v2_accepts_boundary_fields() -> None:
    command = PlanningCandidateValidationCommand.model_validate(
        _candidate_command(2, with_boundaries=True)
    )
    assert command.schema_version == 2
    assert command.payload.trip.arrival_at is not None
    assert command.payload.trip.departure_at is not None
