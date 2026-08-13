"""B9.5 — cross-entry consistency and safety regression matrix."""

from datetime import UTC, datetime

import pytest

from trip_agent.feasibility.inputs import MealProjectionState
from trip_agent.feasibility.models import FeasibilityStatus, RuleOutcome
from trip_agent.feasibility.validator import validate_itinerary
from trip_agent.planning.validation_projection import project_validation_state
from trip_agent.worker.contracts import Itinerary


def _activity(
    *,
    title: str,
    start: str,
    end: str,
    kind: str | None = None,
    source: str = "AMAP",
    poi_id: str | None = None,
    lon: float | None = None,
    lat: float | None = None,
) -> dict[str, object]:
    coordinates = (
        {"longitude": lon, "latitude": lat} if lon is not None and lat is not None else None
    )
    return {
        "activityId": None,
        "title": title,
        "startTime": start,
        "endTime": end,
        "estimatedCost": 0,
        "source": source,
        "providerPoiId": poi_id,
        "coordinates": coordinates,
        "address": "address" if source == "AMAP" else None,
        "kind": kind,
        "timeFixed": False,
        "locked": False,
        "typeCode": "060000" if source == "AMAP" else None,
        "typeName": "风景名胜" if source == "AMAP" else None,
    }


def _hotel_day(day: str, *, hotel_last: bool) -> dict[str, object]:
    hotel = _activity(
        title="hotel",
        start=f"{day}T14:00:00Z",
        end=f"{day}T15:00:00Z",
        kind="ACCOMMODATION",
        poi_id="poi-hotel",
        lon=113.26,
        lat=23.13,
    )
    museum = _activity(
        title="museum",
        start=f"{day}T01:00:00Z",
        end=f"{day}T03:00:00Z",
        kind="ATTRACTION",
        poi_id="poi-museum",
        lon=113.27,
        lat=23.14,
    )
    return {
        "date": day,
        "dayType": "FULL_DAY",
        "activities": [museum, hotel] if hotel_last else [hotel, museum],
        "transitLegs": [],
    }


def _plain_day(day: str) -> dict[str, object]:
    return {
        "date": day,
        "dayType": "FULL_DAY",
        "activities": [
            _activity(
                title="museum",
                start=f"{day}T01:00:00Z",
                end=f"{day}T03:00:00Z",
                kind="ATTRACTION",
                poi_id="poi-museum",
                lon=113.27,
                lat=23.14,
            ),
        ],
        "transitLegs": [],
    }


def _itinerary(days: list[dict[str, object]]) -> Itinerary:
    return Itinerary.model_validate({"title": "route", "days": days, "estimatedTotalCost": 0})


def _validate(
    itinerary: Itinerary,
    *,
    skeleton: object,
    inputs: object,
) -> FeasibilityStatus:
    from trip_agent.worker.contracts import PlanningCreateCommand

    class _Command:
        pass

    # A minimal stand-in exposing just the fields the rules read.
    command = PlanningCreateCommand.model_validate(
        {
            "eventType": "PLANNING_CREATE_REQUESTED",
            "schemaVersion": 2,
            "eventId": "c75013d4-b83a-4d11-a52c-66138751d75b",
            "traceId": "6f24951e-94bb-4d9a-9446-043698479f24",
            "taskId": "fb204eed-1484-4ccb-855e-af72d914b987",
            "tripId": "fb21f112-d17f-4e4f-8598-b1cd1c64ca04",
            "occurredAt": "2026-07-24T04:00:00Z",
            "payload": {
                "taskType": "CREATE",
                "baselineTripVersion": 0,
                "idempotencyKey": "00000000-0000-4000-8000-000000000001",
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
                "guideEvidence": {"facts": []},
            },
        }
    )
    report = validate_itinerary(
        command=command,
        itinerary=itinerary,
        report_id="3d76fb9e-362e-4b28-8a9e-18e8ac7050ad",
        validated_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        trip_skeleton=skeleton,
        validation_inputs=inputs,
    )
    return report


@pytest.mark.parametrize(
    ("days", "expected_continuity"),
    [
        ([_plain_day("2026-08-01")], "zero_overnight"),
        ([_plain_day("2026-08-01"), _plain_day("2026-08-02")], "unresolved_unknown"),
        (
            [_hotel_day("2026-08-01", hotel_last=True), _hotel_day("2026-08-02", hotel_last=False)],
            "confirmed_pass",
        ),
    ],
)
def test_accommodation_matrix_never_fabricates_continuity(
    days: list[dict[str, object]], expected_continuity: str
) -> None:
    itinerary = _itinerary(days)
    skeleton, inputs = project_validation_state(itinerary, requested_accommodation_label=None)
    report = _validate(itinerary, skeleton=skeleton, inputs=inputs)
    cross = next(
        result for result in report.rule_results if result.rule_id == "CROSS_DAY_CONTINUITY"
    )
    if expected_continuity == "zero_overnight":
        assert cross.outcome in (RuleOutcome.NOT_APPLICABLE, RuleOutcome.UNKNOWN)
        assert cross.outcome is not RuleOutcome.PASS
    elif expected_continuity == "unresolved_unknown":
        assert cross.outcome is RuleOutcome.UNKNOWN
        assert cross.outcome is not RuleOutcome.PASS
    else:
        assert cross.outcome is RuleOutcome.PASS
    assert report.status is not FeasibilityStatus.VERIFIED or (
        expected_continuity == "confirmed_pass"
    )


def test_opening_without_evidence_never_passes() -> None:
    itinerary = _itinerary([_plain_day("2026-08-01")])
    skeleton, inputs = project_validation_state(
        itinerary, requested_accommodation_label=None, facts=()
    )
    report = _validate(itinerary, skeleton=skeleton, inputs=inputs)
    opening = next(result for result in report.rule_results if result.rule_id == "OPENING_HOURS")
    assert opening.outcome is not RuleOutcome.PASS


def test_meal_without_explicit_window_is_not_applicable() -> None:
    itinerary = _itinerary([_plain_day("2026-08-01")])
    skeleton, inputs = project_validation_state(itinerary, requested_accommodation_label=None)
    report = _validate(itinerary, skeleton=skeleton, inputs=inputs)
    meal = next(result for result in report.rule_results if result.rule_id == "MEAL_WINDOW")
    assert meal.outcome is RuleOutcome.NOT_APPLICABLE


def test_demo_style_projection_keeps_meal_unavailable() -> None:
    itinerary = _itinerary([_plain_day("2026-08-01")])
    skeleton, inputs = project_validation_state(
        itinerary,
        requested_accommodation_label=None,
        meal_projection_state=MealProjectionState.UNAVAILABLE,
    )
    assert inputs.meal_projection_state is MealProjectionState.UNAVAILABLE
    assert inputs.opening_hours_bindings == ()
