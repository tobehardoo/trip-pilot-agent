"""B4A — AMap accommodation projection unit tests.

Locks the transient Provider → TripSkeleton data flow: resolved POI becomes
CONFIRMED, explicit unresolved requests stay UNRESOLVED (never downgraded to
a region estimate), no-request nights use the day's primary region as
DAY_PRIMARY_REGION Area Estimated, and no-region nights become UNRESOLVED.
"""

import ast
import pathlib
from datetime import date

import trip_agent.infrastructure.amap.accommodation_projection as projection_module
from trip_agent.infrastructure.amap.accommodation_projection import (
    project_amap_trip_skeleton,
)
from trip_agent.planning.daily_schedule import DayPlan
from trip_agent.planning.trip_skeleton import (
    AccommodationState,
    AreaEstimatedAccommodation,
    AreaEstimateSource,
    ConfirmedAccommodation,
    GeoPoint,
    UnresolvedAccommodation,
)
from trip_agent.providers.map import Coordinates, Poi


def _day(day: date, *, region: str | None) -> DayPlan:
    return DayPlan(
        date=day,
        day_type="FULL_DAY",
        window_start_minute=540,
        window_end_minute=1080,
        items=(),
        meal_demands=(),
        origin=None,
        accommodation_unknown=False,
        warnings=(),
        primary_region=region,
    )


def _days(*regions: str | None) -> tuple[DayPlan, ...]:
    return tuple(
        _day(date(2026, 8, 1 + index), region=region) for index, region in enumerate(regions)
    )


def _hotel(
    provider_id: str = "HOTEL-1",
    name: str = "花园酒店",
    district: str = "越秀区",
) -> Poi:
    return Poi(
        provider_id=provider_id,
        name=name,
        coordinates=Coordinates(longitude=113.31, latitude=23.13),
        type_name="宾馆酒店",
        type_code="070000",
        province="广东省",
        city="广州市",
        district=district,
        address=f"{name}地址",
    )


# ── Confirmed ──────────────────────────────────────────────────────────────


def test_confirmed_projection_for_every_night() -> None:
    hotel = _hotel()
    skeleton = project_amap_trip_skeleton(
        day_plans=_days("越秀区", "天河区", "海珠区"),
        requested_accommodation_label=None,
        resolved_accommodation=hotel,
    )

    assert skeleton.night_count == 2
    for overnight in skeleton.overnights:
        accommodation = overnight.accommodation
        assert isinstance(accommodation, ConfirmedAccommodation)
        assert accommodation.label == "花园酒店"
        assert accommodation.provider_poi_id == "HOTEL-1"
        assert accommodation.coordinates == GeoPoint(longitude=113.31, latitude=23.13)
        assert accommodation.region == "越秀区"


def test_confirmed_accommodation_reused_across_nights() -> None:
    hotel = _hotel()
    skeleton = project_amap_trip_skeleton(
        day_plans=_days("越秀区", "天河区", "海珠区"),
        requested_accommodation_label=None,
        resolved_accommodation=hotel,
    )

    assert skeleton.overnights[0].accommodation is skeleton.overnights[1].accommodation


def test_confirmed_region_none_when_district_blank() -> None:
    hotel = _hotel(district="")
    skeleton = project_amap_trip_skeleton(
        day_plans=_days("越秀区", "天河区"),
        requested_accommodation_label=None,
        resolved_accommodation=hotel,
    )

    accommodation = skeleton.overnights[0].accommodation
    assert isinstance(accommodation, ConfirmedAccommodation)
    assert accommodation.region is None


# ── Explicit unresolved request ────────────────────────────────────────────


def test_explicit_unresolved_request_keeps_requested_label() -> None:
    skeleton = project_amap_trip_skeleton(
        day_plans=_days("越秀区", "天河区"),
        requested_accommodation_label="  没搜到的酒店  ",
        resolved_accommodation=None,
    )

    assert skeleton.night_count == 1
    accommodation = skeleton.overnights[0].accommodation
    assert isinstance(accommodation, UnresolvedAccommodation)
    assert accommodation.requested_label == "没搜到的酒店"
    assert accommodation.state == AccommodationState.UNRESOLVED
    assert not hasattr(accommodation, "provider_poi_id")
    assert not hasattr(accommodation, "coordinates")
    assert not hasattr(accommodation, "centroid")


def test_explicit_unresolved_not_overridden_by_day_region() -> None:
    skeleton = project_amap_trip_skeleton(
        day_plans=_days("越秀区", "天河区"),
        requested_accommodation_label="某酒店",
        resolved_accommodation=None,
    )

    accommodation = skeleton.overnights[0].accommodation
    assert isinstance(accommodation, UnresolvedAccommodation)
    assert not isinstance(accommodation, AreaEstimatedAccommodation)


# ── No request + day primary region ────────────────────────────────────────


def test_no_request_with_primary_region_projects_area_estimated() -> None:
    skeleton = project_amap_trip_skeleton(
        day_plans=_days("越秀区", "天河区"),
        requested_accommodation_label=None,
        resolved_accommodation=None,
    )

    accommodation = skeleton.overnights[0].accommodation
    assert isinstance(accommodation, AreaEstimatedAccommodation)
    assert accommodation.region == "越秀区"
    assert accommodation.source == AreaEstimateSource.DAY_PRIMARY_REGION
    assert accommodation.centroid is None
    assert not hasattr(accommodation, "provider_poi_id")


# ── No request + no region ─────────────────────────────────────────────────


def test_no_request_without_region_projects_unresolved() -> None:
    skeleton = project_amap_trip_skeleton(
        day_plans=_days(None, None),
        requested_accommodation_label=None,
        resolved_accommodation=None,
    )

    accommodation = skeleton.overnights[0].accommodation
    assert isinstance(accommodation, UnresolvedAccommodation)
    assert accommodation.requested_label is None


# ── Per-night independence ─────────────────────────────────────────────────


def test_each_night_projects_its_own_region() -> None:
    skeleton = project_amap_trip_skeleton(
        day_plans=_days("越秀区", "天河区", "海珠区"),
        requested_accommodation_label=None,
        resolved_accommodation=None,
    )

    assert skeleton.night_count == 2
    first = skeleton.overnights[0].accommodation
    second = skeleton.overnights[1].accommodation
    assert isinstance(first, AreaEstimatedAccommodation)
    assert isinstance(second, AreaEstimatedAccommodation)
    assert first.region == "越秀区"
    assert second.region == "天河区"


# ── Single-day trip ────────────────────────────────────────────────────────


def test_single_day_trip_yields_empty_overnights() -> None:
    skeleton = project_amap_trip_skeleton(
        day_plans=_days("越秀区"),
        requested_accommodation_label=None,
        resolved_accommodation=None,
    )

    assert skeleton.day_count == 1
    assert skeleton.night_count == 0
    assert skeleton.overnights == ()


# ── Purity & dependency boundary ───────────────────────────────────────────


def test_projection_imports_no_feasibility_evaluation_or_worker() -> None:
    tree = ast.parse(pathlib.Path(projection_module.__file__).read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
    for module in imports:
        assert not module.startswith("trip_agent.feasibility"), module
        assert not module.startswith("trip_agent.evaluation"), module
        assert "worker" not in module, module


def test_projection_uses_no_clocks_uuids_or_io() -> None:
    source = pathlib.Path(projection_module.__file__).read_text(encoding="utf-8")
    assert "datetime.now" not in source
    assert "uuid" not in source
    assert "socket" not in source
    assert "requests" not in source
    assert "sqlite" not in source
    assert "psycopg" not in source


def test_projection_does_not_mutate_inputs() -> None:
    days = _days("越秀区", "天河区")
    original_days = list(days)
    hotel = _hotel()
    project_amap_trip_skeleton(
        day_plans=days,
        requested_accommodation_label=None,
        resolved_accommodation=hotel,
    )
    assert list(days) == original_days
    assert hotel.provider_id == "HOTEL-1"
    assert hotel.district == "越秀区"
