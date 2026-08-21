"""B9.1 — unified validation projection across planning entry points."""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime

from test_local_replanning import REPLAN_COMMAND

from trip_agent.feasibility.inputs import MealProjectionState
from trip_agent.planning.trip_skeleton import (
    ConfirmedAccommodation,
    UnresolvedAccommodation,
)
from trip_agent.planning.validation_projection import project_validation_state
from trip_agent.worker.contracts import (
    Itinerary,
    MealWindow,
    PlanningReplanCommand,
)

CHINA = "Asia/Shanghai"


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
    meal_type: str | None = None,
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
        "address": "sample address" if source == "AMAP" else None,
        "kind": kind,
        "timeFixed": False,
        "locked": False,
        "typeCode": "060000" if source == "AMAP" else None,
        "typeName": "风景名胜" if source == "AMAP" else None,
        "mealType": meal_type,
    }


def _itinerary(days: list[dict[str, object]]) -> Itinerary:
    return Itinerary.model_validate(
        {
            "title": "route",
            "days": days,
            "estimatedTotalCost": 0,
        }
    )


def test_single_day_projection_has_zero_overnights() -> None:
    itinerary = _itinerary(
        [
            {
                "date": "2026-08-01",
                "dayType": "FULL_DAY",
                "activities": [
                    _activity(
                        title="museum",
                        start="2026-08-01T01:00:00Z",
                        end="2026-08-01T03:00:00Z",
                        kind="ATTRACTION",
                        poi_id="poi-museum",
                        lon=113.26,
                        lat=23.13,
                    ),
                ],
                "transitLegs": [],
            }
        ]
    )
    skeleton, inputs = project_validation_state(
        itinerary,
        requested_accommodation_label=None,
    )
    assert skeleton.overnights == ()
    assert inputs.opening_hours_bindings == ()
    assert inputs.meal_placement_bindings == ()


def test_multi_day_without_confirmed_hotel_stays_unresolved() -> None:
    itinerary = _itinerary(
        [
            {
                "date": "2026-08-01",
                "dayType": "FULL_DAY",
                "activities": [
                    _activity(
                        title="a",
                        start="2026-08-01T01:00:00Z",
                        end="2026-08-01T03:00:00Z",
                        kind="ATTRACTION",
                        poi_id="poi-a",
                        lon=113.26,
                        lat=23.13,
                    ),
                ],
                "transitLegs": [],
            },
            {
                "date": "2026-08-02",
                "dayType": "FULL_DAY",
                "activities": [
                    _activity(
                        title="b",
                        start="2026-08-02T01:00:00Z",
                        end="2026-08-02T03:00:00Z",
                        kind="ATTRACTION",
                        poi_id="poi-b",
                        lon=113.27,
                        lat=23.14,
                    ),
                ],
                "transitLegs": [],
            },
        ]
    )
    skeleton, _inputs = project_validation_state(
        itinerary, requested_accommodation_label="requested-hotel"
    )
    assert len(skeleton.overnights) == 1
    boundary = skeleton.overnights[0]
    assert isinstance(boundary.accommodation, UnresolvedAccommodation)
    assert boundary.accommodation.requested_label == "requested-hotel"


def test_multi_day_confirmed_hotel_requires_poi_and_coordinates() -> None:
    itinerary = _itinerary(
        [
            {
                "date": "2026-08-01",
                "dayType": "FULL_DAY",
                "activities": [
                    _activity(
                        title="hotel",
                        start="2026-08-01T14:00:00Z",
                        end="2026-08-02T02:00:00Z",
                        kind="ACCOMMODATION",
                        poi_id="poi-hotel",
                        lon=113.26,
                        lat=23.13,
                    ),
                ],
                "transitLegs": [],
            },
            {
                "date": "2026-08-02",
                "dayType": "FULL_DAY",
                "activities": [
                    _activity(
                        title="hotel",
                        start="2026-08-02T14:00:00Z",
                        end="2026-08-03T02:00:00Z",
                        kind="ACCOMMODATION",
                        poi_id="poi-hotel",
                        lon=113.26,
                        lat=23.13,
                    ),
                ],
                "transitLegs": [],
            },
        ]
    )
    skeleton, _inputs = project_validation_state(itinerary, requested_accommodation_label=None)
    assert len(skeleton.overnights) == 1
    assert isinstance(skeleton.overnights[0].accommodation, ConfirmedAccommodation)


def test_accommodation_activity_without_coordinates_never_confirms() -> None:
    itinerary = _itinerary(
        [
            {
                "date": "2026-08-01",
                "dayType": "FULL_DAY",
                "activities": [
                    _activity(
                        title="hotel",
                        start="2026-08-01T14:00:00Z",
                        end="2026-08-02T02:00:00Z",
                        kind="ACCOMMODATION",
                        source="DEMO",
                    ),
                ],
                "transitLegs": [],
            },
            {
                "date": "2026-08-02",
                "dayType": "FULL_DAY",
                "activities": [
                    _activity(
                        title="hotel",
                        start="2026-08-02T14:00:00Z",
                        end="2026-08-03T02:00:00Z",
                        kind="ACCOMMODATION",
                        source="DEMO",
                    ),
                ],
                "transitLegs": [],
            },
        ]
    )
    skeleton, _inputs = project_validation_state(itinerary, requested_accommodation_label=None)
    assert isinstance(skeleton.overnights[0].accommodation, UnresolvedAccommodation)


def test_local_replan_rebuilds_projection_from_final_itinerary() -> None:
    from trip_agent.application.replan_service import LocalReplanningProvider

    command = PlanningReplanCommand.model_validate(REPLAN_COMMAND)

    class _FakeRoute:
        async def get_route(self, request):
            from trip_agent.providers.map import Coordinates, ProviderSuccess
            from trip_agent.providers.route import RoutePlan, RouteStep

            return ProviderSuccess(
                data=RoutePlan(
                    mode="WALKING",
                    distance_meters=300,
                    duration_seconds=300,
                    polyline=(
                        Coordinates(longitude=113.26, latitude=23.13),
                        Coordinates(longitude=113.27, latitude=23.14),
                    ),
                    steps=(
                        RouteStep(
                            instruction="walk",
                            distance_meters=300,
                            duration_seconds=300,
                            polyline=(
                                Coordinates(longitude=113.26, latitude=23.13),
                                Coordinates(longitude=113.27, latitude=23.14),
                            ),
                        ),
                    ),
                    estimated_cost=None,
                ),
                provider="DEMO",
                estimated=True,
                fallback_error=None,
                fetched_at=datetime(2026, 8, 1, 1, 0, tzinfo=UTC),
                latency_ms=10,
                cached=False,
            )

    provider = LocalReplanningProvider(_FakeRoute())
    result = asyncio.run(provider.replan(command))
    assert result.trip_skeleton is not None
    assert result.validation_inputs is not None
    # Replan commands carry no facts, so no opening evidence is fabricated.
    assert result.validation_inputs.opening_hours_bindings == ()


def test_demo_provider_projects_unresolved_skeleton_and_unavailable_meal() -> None:
    from trip_agent.application.replan_service import LocalReplanningProvider  # noqa: F401
    from trip_agent.infrastructure.demo.planning_provider import DemoPlanningProvider
    from trip_agent.worker.contracts import PlanningCreateCommand

    raw = deepcopy(REPLAN_COMMAND)
    raw["eventType"] = "PLANNING_CREATE_REQUESTED"
    raw["schemaVersion"] = 2
    payload = raw["payload"]
    payload["taskType"] = "CREATE"
    payload.pop("baselineItineraryVersionId", None)
    payload.pop("impactedDates", None)
    payload.pop("itinerary", None)
    payload.pop("knowledge", None)
    payload["guideEvidence"] = {"facts": []}
    command = PlanningCreateCommand.model_validate(raw)

    result = asyncio.run(DemoPlanningProvider().plan(command))
    assert result.trip_skeleton is not None
    assert result.validation_inputs is not None
    # Demo never fabricates evidence and cannot resolve restaurants.
    assert result.validation_inputs.opening_hours_bindings == ()
    assert result.validation_inputs.meal_projection_state is MealProjectionState.UNAVAILABLE
    # Multi-day Demo itinerary keeps its overnight UNRESOLVED.
    assert len(result.trip_skeleton.overnights) == 1
    assert isinstance(
        result.trip_skeleton.overnights[0].accommodation,
        UnresolvedAccommodation,
    )


def test_repair_reprojects_locators_from_repaired_itinerary() -> None:
    repaired_itinerary = Itinerary.model_validate(
        {
            "title": "route",
            "days": [
                {
                    "date": "2026-08-01",
                    "dayType": "FULL_DAY",
                    "activities": [
                        _activity(
                            title="kept",
                            start="2026-08-01T01:00:00Z",
                            end="2026-08-01T02:00:00Z",
                            kind="ATTRACTION",
                            poi_id="poi-kept",
                            lon=113.26,
                            lat=23.13,
                        ),
                        _activity(
                            title="moved",
                            start="2026-08-01T02:30:00Z",
                            end="2026-08-01T03:30:00Z",
                            kind="ATTRACTION",
                            poi_id="poi-moved",
                            lon=113.27,
                            lat=23.14,
                        ),
                    ],
                    "transitLegs": [],
                },
                {
                    "date": "2026-08-02",
                    "dayType": "FULL_DAY",
                    "activities": [
                        _activity(
                            title="next",
                            start="2026-08-02T01:00:00Z",
                            end="2026-08-02T02:00:00Z",
                            kind="ATTRACTION",
                            poi_id="poi-next",
                            lon=113.28,
                            lat=23.15,
                        ),
                    ],
                    "transitLegs": [],
                },
            ],
            "estimatedTotalCost": 0,
        }
    )
    skeleton, inputs = project_validation_state(
        repaired_itinerary, requested_accommodation_label=None
    )
    # Locators must follow the repaired day order, not the pre-repair layout.
    locators = {
        (binding.activity.day_index, binding.activity.activity_index)
        for binding in inputs.visit_duration_bindings
    }
    assert locators == {(0, 0), (0, 1), (1, 0)}


def _meal_day(activities: list[dict[str, object]]) -> dict[str, object]:
    return {
        "date": "2026-08-01",
        "dayType": "FULL_DAY",
        "activities": activities,
        "transitLegs": [],
    }


def test_disabled_meal_windows_are_not_zipped_into_bindings() -> None:
    itinerary = _itinerary(
        [
            _meal_day(
                [
                    _activity(
                        title="lunch",
                        start="2026-08-01T04:00:00Z",
                        end="2026-08-01T05:00:00Z",
                        kind="MEAL",
                        source="DEMO",
                        meal_type="LUNCH",
                    ),
                ]
            )
        ]
    )
    _, inputs = project_validation_state(
        itinerary,
        requested_accommodation_label=None,
        meal_windows=(
            MealWindow.model_validate(
                {
                    "mealType": "DINNER",
                    "startTime": "18:00",
                    "endTime": "19:00",
                    "source": "DISABLED",
                }
            ),
            MealWindow.model_validate(
                {"mealType": "LUNCH", "startTime": "12:00", "endTime": "13:00"}
            ),
        ),
    )
    # The disabled dinner must never steal the only meal activity; the
    # source-less lunch keeps its USER semantics.
    assert [binding.meal_type.value for binding in inputs.meal_placement_bindings] == ["LUNCH"]


def test_meal_windows_bind_by_meal_type_not_command_order() -> None:
    itinerary = _itinerary(
        [
            _meal_day(
                [
                    _activity(
                        title="lunch",
                        start="2026-08-01T04:00:00Z",
                        end="2026-08-01T05:00:00Z",
                        kind="MEAL",
                        source="DEMO",
                        meal_type="LUNCH",
                    ),
                    _activity(
                        title="dinner",
                        start="2026-08-01T10:00:00Z",
                        end="2026-08-01T11:00:00Z",
                        kind="MEAL",
                        source="DEMO",
                        meal_type="DINNER",
                    ),
                ]
            )
        ]
    )
    _, inputs = project_validation_state(
        itinerary,
        requested_accommodation_label=None,
        meal_windows=(
            MealWindow.model_validate(
                {"mealType": "DINNER", "startTime": "18:00", "endTime": "19:00"}
            ),
            MealWindow.model_validate(
                {"mealType": "LUNCH", "startTime": "12:00", "endTime": "13:00"}
            ),
        ),
    )
    # Bindings pair each window with the same meal-type activity regardless
    # of the order the windows were declared in.
    by_type = {
        binding.meal_type.value: binding.activity.activity_index
        for binding in inputs.meal_placement_bindings
    }
    assert by_type == {"LUNCH": 0, "DINNER": 1}


# ---------------------------------------------------------------------------
# B19-E: accommodation status output projection (P1 — end-to-end display)
# ---------------------------------------------------------------------------

def _accommodation_itinerary(*, with_poi: bool) -> Itinerary:
    """Two-day itinerary with an ACCOMMODATION node at the overnight boundary."""
    days = [
        {
            "date": "2026-09-10",
            "activities": [
                _activity(title="到达", start="2026-09-10T10:00:00+08:00",
                          end="2026-09-10T10:30:00+08:00", kind="ARRIVAL",
                          source="DEMO"),
                _activity(title="酒店", start="2026-09-10T21:00:00+08:00",
                          end="2026-09-10T22:00:00+08:00", kind="ACCOMMODATION",
                          source="AMAP" if with_poi else "DEMO",
                          poi_id="B0001" if with_poi else None,
                          lon=113.32 if with_poi else None,
                          lat=23.12 if with_poi else None),
            ],
            "transitLegs": [],
        },
        {
            "date": "2026-09-11",
            "activities": [
                _activity(title="越秀公园", start="2026-09-11T09:00:00+08:00",
                          end="2026-09-11T11:00:00+08:00", kind=None,
                          source="DEMO"),
            ],
            "transitLegs": [],
        },
    ]
    return _itinerary(days)


def test_accommodation_status_none_without_requested_label() -> None:
    from trip_agent.planning.validation_projection import project_accommodation_status

    it = _accommodation_itinerary(with_poi=True)
    assert project_accommodation_status(it, None) is None


def test_accommodation_status_confirmed_with_poi_and_coordinates() -> None:
    from trip_agent.planning.validation_projection import project_accommodation_status

    it = _accommodation_itinerary(with_poi=True)
    status = project_accommodation_status(it, "白天鹅宾馆")
    assert status is not None
    assert status.status == "CONFIRMED"
    assert status.place_name == "白天鹅宾馆"


def test_accommodation_status_unresolved_without_poi() -> None:
    from trip_agent.planning.validation_projection import project_accommodation_status

    it = _accommodation_itinerary(with_poi=False)
    status = project_accommodation_status(it, "白天鹅宾馆")
    assert status is not None
    assert status.status == "UNRESOLVED"
    assert status.place_name == "白天鹅宾馆"


def test_accommodation_status_unresolved_without_accommodation_activity() -> None:
    from trip_agent.planning.validation_projection import project_accommodation_status

    it = _itinerary([
        {"date": "2026-09-10",
         "activities": [_activity(title="到达", start="2026-09-10T10:00:00+08:00",
                                  end="2026-09-10T10:30:00+08:00", kind="ARRIVAL",
                                  source="DEMO")],
         "transitLegs": []},
        {"date": "2026-09-11",
         "activities": [_activity(title="越秀公园", start="2026-09-11T09:00:00+08:00",
                                  end="2026-09-11T11:00:00+08:00", kind=None,
                                  source="DEMO")],
         "transitLegs": []},
    ])
    status = project_accommodation_status(it, "白天鹅宾馆")
    assert status is not None
    assert status.status == "UNRESOLVED"


def test_accommodation_status_confirmed_via_requested_place_ref() -> None:
    """B19-E: a precise provider candidate selected by the user is CONFIRMED
    even when the planner projected no hotel activity (e.g. DEMO provider)."""
    from trip_agent.planning.validation_projection import project_accommodation_status

    it = _itinerary([
        {"date": "2026-09-10",
         "activities": [_activity(title="到达", start="2026-09-10T10:00:00+08:00",
                                  end="2026-09-10T10:30:00+08:00", kind="ARRIVAL",
                                  source="DEMO")],
         "transitLegs": []},
        {"date": "2026-09-11",
         "activities": [_activity(title="越秀公园", start="2026-09-11T09:00:00+08:00",
                                  end="2026-09-11T11:00:00+08:00", kind=None,
                                  source="DEMO")],
         "transitLegs": []},
    ])
    class _Ref:
        provider_poi_id = "B0001HOTEL"

    status = project_accommodation_status(it, "白天鹅宾馆", _Ref())
    assert status is not None
    assert status.status == "CONFIRMED"
    assert status.place_name == "白天鹅宾馆"
