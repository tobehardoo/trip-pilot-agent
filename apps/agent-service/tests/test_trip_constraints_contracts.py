"""B1: unified constraint contract is compatible with old and new JSONB shapes.

The Java travel-server now persists structured POI data and meal-window
sources inside the existing JSONB columns. The planning worker must accept
both the legacy shape (plain placeName, no mealWindow source) and the new
shape (optional poi + optional source) without changing validation rules.
"""

from copy import deepcopy
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_planning_worker import COMMAND

from trip_agent.worker.contracts import PlanningCreateCommand


def _base() -> dict:
    payload = deepcopy(COMMAND)
    payload["schemaVersion"] = 2
    payload["payload"]["trip"]["constraints"].update(
        {
            "schemaVersion": 2,
            "arrival": {
                "placeName": "广州南站",
                "time": "2026-08-01T11:00:00+08:00",
            },
            "departure": {
                "placeName": "广州白云机场",
                "time": "2026-08-02T17:00:00+08:00",
            },
            "accommodation": {"placeName": "北京路附近酒店"},
            "mustVisitPlaces": ["陈家祠"],
            "avoidPlaces": ["广州塔"],
            "mealWindows": [
                {"mealType": "LUNCH", "startTime": "12:00", "endTime": "13:00"}
            ],
            "mobilityLevel": "REDUCED",
        }
    )
    return payload


def test_legacy_constraints_without_new_fields_still_validate() -> None:
    payload = _base()
    command = PlanningCreateCommand.model_validate(payload)

    constraints = command.payload.trip.constraints
    assert constraints.arrival is not None
    assert constraints.arrival.place_name == "广州南站"
    assert constraints.arrival.poi is None
    assert constraints.accommodation is not None
    assert constraints.accommodation.place_name == "北京路附近酒店"
    assert constraints.accommodation.poi is None
    assert constraints.meal_windows[0].source is None
    # Java normalizes the legacy windows to USER_SET; the worker just reads
    # whatever source (or absence) the snapshot carries.
    assert constraints.meal_windows[0].meal_type == "LUNCH"


def test_new_constraints_with_structured_poi_and_sources_validate() -> None:
    payload = _base()
    payload["payload"]["trip"]["constraints"]["arrival"]["poi"] = {
        "name": "广州南站",
        "providerPoiId": "B000A7BD2F",
        "fullAddress": "广州市番禺区石壁街道南站北路",
        "longitude": 113.2673,
        "latitude": 22.9923,
        "city": "广州市",
        "district": "番禺区",
    }
    payload["payload"]["trip"]["constraints"]["accommodation"] = {
        "placeName": "天河希尔顿",
        "poi": {
            "name": "广州天河希尔顿酒店",
            "providerPoiId": "B0FFFABC12",
            "fullAddress": "广州市天河区林和西横路215号",
            "longitude": 113.3237,
            "latitude": 23.1376,
            "city": "广州市",
            "district": "天河区",
        },
    }
    payload["payload"]["trip"]["constraints"]["mealWindows"] = [
        {
            "mealType": "BREAKFAST",
            "startTime": "08:00",
            "endTime": "09:00",
            "source": "SYSTEM_DEFAULT",
        },
        {
            "mealType": "LUNCH",
            "startTime": "12:00",
            "endTime": "13:00",
            "source": "USER_SET",
        },
    ]

    command = PlanningCreateCommand.model_validate(payload)
    constraints = command.payload.trip.constraints

    poi = constraints.arrival.poi
    assert poi is not None
    assert poi.provider_poi_id == "B000A7BD2F"
    assert poi.longitude == Decimal("113.2673")
    assert poi.city == "广州市"
    assert constraints.accommodation.poi.full_address == "广州市天河区林和西横路215号"
    assert constraints.meal_windows[0].source == "SYSTEM_DEFAULT"
    assert constraints.meal_windows[1].source == "USER_SET"


def test_structured_poi_rejects_unpaired_coordinates() -> None:
    payload = _base()
    payload["payload"]["trip"]["constraints"]["arrival"]["poi"] = {
        "name": "不完整车站",
        "providerPoiId": "B000A7BD2F",
        "longitude": 113.2673,
    }

    with pytest.raises(ValidationError):
        PlanningCreateCommand.model_validate(payload)


def test_meal_window_rejects_unknown_source_and_bad_times() -> None:
    payload = _base()
    payload["payload"]["trip"]["constraints"]["mealWindows"] = [
        {"mealType": "LUNCH", "startTime": "12:00", "endTime": "13:00", "source": "OTHER"}
    ]
    with pytest.raises(ValidationError):
        PlanningCreateCommand.model_validate(payload)

    payload = _base()
    payload["payload"]["trip"]["constraints"]["mealWindows"] = [
        {"mealType": "LUNCH", "startTime": "13:00", "endTime": "12:00", "source": "USER_SET"}
    ]
    with pytest.raises(ValidationError):
        PlanningCreateCommand.model_validate(payload)
