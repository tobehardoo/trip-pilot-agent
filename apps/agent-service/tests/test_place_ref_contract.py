"""B13-D — PlaceRef contract (create command v4) fail-closed semantics."""

from copy import deepcopy
from datetime import date

import pytest
from pydantic import ValidationError
from test_planning_context_v3 import _v3_command

from trip_agent.worker.contracts import (
    PlaceRef,
    PlanningCreateCommand,
    TripConstraints,
)

AMAP_REF = {
    "provider": "AMAP",
    "providerPoiId": "B001234567",
    "name": "陈家祠",
    "address": "广州市荔湾区中山七路恩龙里34号",
    "province": "广东省",
    "city": "广州市",
    "district": "荔湾区",
    "longitude": 113.2405,
    "latitude": 23.1256,
}


def _v4_command() -> dict:
    payload = deepcopy(_v3_command())
    payload["schemaVersion"] = 4
    constraints = payload["payload"]["trip"]["constraints"]
    constraints["schemaVersion"] = 3
    constraints["mustVisitPlaces"] = ["陈家祠"]
    constraints["mustVisitPlaceRefs"] = [AMAP_REF]
    constraints["avoidPlaces"] = []
    constraints["avoidPlaceRefs"] = []
    # B13_FIX R1: v4 snapshots always carry the authoritative boundaries.
    payload["payload"]["trip"]["arrivalAt"] = "2026-08-01T11:00:00+08:00"
    payload["payload"]["trip"]["departureAt"] = "2026-08-02T17:00:00+08:00"
    return payload


# ── PlaceRef model ──────────────────────────────────────────────────────────


def test_place_ref_parses_with_camel_case_aliases() -> None:
    ref = PlaceRef.model_validate(AMAP_REF)
    assert ref.provider == "AMAP"
    assert ref.provider_poi_id == "B001234567"
    assert ref.longitude == 113.2405


def test_place_ref_rejects_unknown_provider() -> None:
    with pytest.raises(ValidationError):
        PlaceRef.model_validate({**AMAP_REF, "provider": "GOOGLE"})


def test_place_ref_rejects_out_of_range_coordinates() -> None:
    with pytest.raises(ValidationError):
        PlaceRef.model_validate({**AMAP_REF, "longitude": 181})
    with pytest.raises(ValidationError):
        PlaceRef.model_validate({**AMAP_REF, "latitude": -91})


def test_place_ref_rejects_string_coordinates() -> None:
    with pytest.raises(ValidationError):
        PlaceRef.model_validate({**AMAP_REF, "longitude": "113.24"})


# ── constraints schema v3 ────────────────────────────────────────────────────


def test_constraints_v3_accepts_parallel_place_refs() -> None:
    constraints = TripConstraints.model_validate(
        {
            "budgetAmount": 1000,
            "travelers": 1,
            "travelerType": "SOLO",
            "pace": "BALANCED",
            "preferences": [],
            "fixedSchedules": [],
            "mustVisitPlaces": ["陈家祠"],
            "mustVisitPlaceRefs": [AMAP_REF],
            "avoidPlaces": [],
            "avoidPlaceRefs": [],
            "schemaVersion": 3,
        }
    )
    assert constraints.must_visit_place_refs[0].provider_poi_id == "B001234567"


def test_constraints_v3_rejects_refs_without_matching_names() -> None:
    with pytest.raises(ValidationError):
        TripConstraints.model_validate(
            {
                "budgetAmount": 1000,
                "travelers": 1,
                "travelerType": "SOLO",
                "pace": "BALANCED",
                "preferences": [],
                "fixedSchedules": [],
                "mustVisitPlaces": ["陈家祠"],
                "mustVisitPlaceRefs": [{**AMAP_REF, "name": "光孝寺"}],
                "avoidPlaces": [],
                "avoidPlaceRefs": [],
                "schemaVersion": 3,
            }
        )


def test_constraints_v3_rejects_refs_length_mismatch() -> None:
    with pytest.raises(ValidationError):
        TripConstraints.model_validate(
            {
                "budgetAmount": 1000,
                "travelers": 1,
                "travelerType": "SOLO",
                "pace": "BALANCED",
                "preferences": [],
                "fixedSchedules": [],
                "mustVisitPlaces": ["陈家祠", "光孝寺"],
                "mustVisitPlaceRefs": [AMAP_REF],
                "avoidPlaces": [],
                "avoidPlaceRefs": [],
                "schemaVersion": 3,
            }
        )


def test_constraints_v2_rejects_place_refs() -> None:
    with pytest.raises(ValidationError):
        TripConstraints.model_validate(
            {
                "budgetAmount": 1000,
                "travelers": 1,
                "travelerType": "SOLO",
                "pace": "BALANCED",
                "preferences": [],
                "fixedSchedules": [],
                "mustVisitPlaces": ["陈家祠"],
                "mustVisitPlaceRefs": [AMAP_REF],
                "avoidPlaces": [],
                "avoidPlaceRefs": [],
                "schemaVersion": 2,
            }
        )


def test_anchor_place_ref_is_accepted_in_v3() -> None:
    constraints = TripConstraints.model_validate(
        {
            "budgetAmount": 1000,
            "travelers": 1,
            "travelerType": "SOLO",
            "pace": "BALANCED",
            "preferences": [],
            "fixedSchedules": [],
            "arrival": {
                "placeName": "陈家祠",
                "time": "2026-08-01T11:00:00+08:00",
                "placeRef": AMAP_REF,
            },
            "schemaVersion": 3,
        }
    )
    assert constraints.arrival is not None
    assert constraints.arrival.place_ref is not None
    assert constraints.arrival.place_ref.provider_poi_id == "B001234567"


# ── create command v4 ────────────────────────────────────────────────────────


def test_v4_command_accepts_constraints_v3_with_place_refs() -> None:
    command = PlanningCreateCommand.model_validate(_v4_command())
    assert command.schema_version == 4
    assert command.payload.trip.constraints.schema_version == 3
    assert command.payload.trip.constraints.must_visit_place_refs[0].name == "陈家祠"


def test_v4_command_accepts_constraints_v2_without_place_refs() -> None:
    # B13_FIX R1: v4 carries the authoritative boundaries regardless of
    # whether constraints use place refs (schema 2 = no refs is fine).
    payload = _v4_command()
    payload["payload"]["trip"]["constraints"]["schemaVersion"] = 2
    payload["payload"]["trip"]["constraints"].pop("mustVisitPlaceRefs")
    payload["payload"]["trip"]["constraints"].pop("avoidPlaceRefs")
    command = PlanningCreateCommand.model_validate(payload)
    assert command.payload.trip.constraints.schema_version == 2


def test_v4_command_rejects_constraints_schema_1() -> None:
    payload = _v4_command()
    payload["payload"]["trip"]["constraints"]["schemaVersion"] = 1
    with pytest.raises(ValidationError):
        PlanningCreateCommand.model_validate(payload)


def test_v3_command_rejects_constraints_v3_with_place_refs() -> None:
    payload = _v4_command()
    payload["schemaVersion"] = 3
    with pytest.raises(ValidationError):
        PlanningCreateCommand.model_validate(payload)


def test_v4_command_requires_planning_context() -> None:
    payload = _v4_command()
    payload["payload"].pop("planningContext")
    with pytest.raises(ValidationError):
        PlanningCreateCommand.model_validate(payload)


def test_v4_command_dates_project_unchanged() -> None:
    command = PlanningCreateCommand.model_validate(_v4_command())
    assert command.payload.trip.start_date == date(2026, 8, 1)
    assert command.payload.trip.end_date == date(2026, 8, 2)
