"""B3 — 旅行骨架（Trip Skeleton）与住宿三态契约。

锁定 ``trip_skeleton.py`` 的完整行为：AccommodationState 三态、
Confirmed / AreaEstimated / Unresolved 三种住宿分辨率、
OvernightBoundary 跨夜边界、TripSkeleton 聚合与 build_trip_skeleton
纯函数构建，以及模块的依赖安全边界（不触及 provider / feasibility /
evaluation，不使用时钟、UUID、网络或数据库）。
"""

import ast
import math
import pathlib
from datetime import UTC, date, datetime

import pytest
from plan_evaluation_support import make_command, make_result

import trip_agent.planning.trip_skeleton as trip_skeleton_module
from trip_agent.feasibility.catalog import IMPLEMENTED_RULE_IDS, MISSING_RULE_IDS
from trip_agent.feasibility.models import FeasibilityStatus
from trip_agent.feasibility.validator import validate_itinerary
from trip_agent.planning.daily_schedule import DayPlan
from trip_agent.planning.trip_skeleton import (
    AccommodationState,
    AreaEstimatedAccommodation,
    AreaEstimateSource,
    ConfirmedAccommodation,
    GeoPoint,
    OvernightBoundary,
    TripSkeleton,
    UnresolvedAccommodation,
    build_trip_skeleton,
)


def test_accommodation_state_has_exact_three_values_in_stable_order() -> None:
    assert tuple(AccommodationState) == (
        AccommodationState.CONFIRMED,
        AccommodationState.AREA_ESTIMATED,
        AccommodationState.UNRESOLVED,
    )
    assert AccommodationState.CONFIRMED.value == "CONFIRMED"
    assert AccommodationState.AREA_ESTIMATED.value == "AREA_ESTIMATED"
    assert AccommodationState.UNRESOLVED.value == "UNRESOLVED"


def test_area_estimate_source_has_exact_three_values_in_stable_order() -> None:
    assert tuple(AreaEstimateSource) == (
        AreaEstimateSource.USER_REGION,
        AreaEstimateSource.PROVIDER_DISTRICT,
        AreaEstimateSource.DAY_PRIMARY_REGION,
    )
    assert AreaEstimateSource.USER_REGION.value == "USER_REGION"
    assert AreaEstimateSource.PROVIDER_DISTRICT.value == "PROVIDER_DISTRICT"
    assert AreaEstimateSource.DAY_PRIMARY_REGION.value == "DAY_PRIMARY_REGION"


# ── GeoPoint ──────────────────────────────────────────────────────────────


def test_geopoint_accepts_valid_coordinates() -> None:
    point = GeoPoint(longitude=113.28, latitude=23.13)

    assert point.longitude == 113.28
    assert point.latitude == 23.13


def test_geopoint_rejects_out_of_range_longitude() -> None:
    with pytest.raises(ValueError):
        GeoPoint(longitude=180.5, latitude=23.0)
    with pytest.raises(ValueError):
        GeoPoint(longitude=-180.5, latitude=23.0)


def test_geopoint_rejects_out_of_range_latitude() -> None:
    with pytest.raises(ValueError):
        GeoPoint(longitude=113.0, latitude=90.5)
    with pytest.raises(ValueError):
        GeoPoint(longitude=113.0, latitude=-90.5)


def test_geopoint_rejects_nan_and_infinity() -> None:
    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError):
            GeoPoint(longitude=bad, latitude=23.0)
        with pytest.raises(ValueError):
            GeoPoint(longitude=113.0, latitude=bad)


def test_geopoint_is_frozen() -> None:
    point = GeoPoint(longitude=113.28, latitude=23.13)

    with pytest.raises(AttributeError):
        point.longitude = 0.0  # type: ignore[misc]


# ── Confirmed accommodation ───────────────────────────────────────────────


def test_confirmed_constructs_with_default_state() -> None:
    accommodation = ConfirmedAccommodation(
        label="Garden Hotel",
        provider_poi_id="POI-42",
        coordinates=GeoPoint(longitude=113.28, latitude=23.13),
    )

    assert accommodation.state == "CONFIRMED"
    assert accommodation.state == AccommodationState.CONFIRMED


def test_confirmed_normalises_label_id_and_region() -> None:
    accommodation = ConfirmedAccommodation(
        label="  Garden Hotel  ",
        provider_poi_id="  POI-42  ",
        coordinates=GeoPoint(longitude=113.28, latitude=23.13),
        region="  Yuexiu  ",
    )

    assert accommodation.label == "Garden Hotel"
    assert accommodation.provider_poi_id == "POI-42"
    assert accommodation.region == "Yuexiu"


def test_confirmed_rejects_empty_label() -> None:
    with pytest.raises(ValueError):
        ConfirmedAccommodation(
            label="",
            provider_poi_id="POI-42",
            coordinates=GeoPoint(longitude=113.28, latitude=23.13),
        )
    with pytest.raises(ValueError):
        ConfirmedAccommodation(
            label="   ",
            provider_poi_id="POI-42",
            coordinates=GeoPoint(longitude=113.28, latitude=23.13),
        )


def test_confirmed_rejects_empty_provider_poi_id() -> None:
    with pytest.raises(ValueError):
        ConfirmedAccommodation(
            label="Garden Hotel",
            provider_poi_id="",
            coordinates=GeoPoint(longitude=113.28, latitude=23.13),
        )
    with pytest.raises(ValueError):
        ConfirmedAccommodation(
            label="Garden Hotel",
            provider_poi_id="   ",
            coordinates=GeoPoint(longitude=113.28, latitude=23.13),
        )


def test_confirmed_rejects_blank_region_when_given() -> None:
    with pytest.raises(ValueError):
        ConfirmedAccommodation(
            label="Garden Hotel",
            provider_poi_id="POI-42",
            coordinates=GeoPoint(longitude=113.28, latitude=23.13),
            region="   ",
        )


def test_confirmed_requires_real_poi_by_construction() -> None:
    # A name-only accommodation cannot become CONFIRMED: provider_poi_id
    # and coordinates are mandatory fields.
    with pytest.raises(TypeError):
        ConfirmedAccommodation(  # type: ignore[call-arg]
            label="Garden Hotel",
            coordinates=GeoPoint(longitude=113.28, latitude=23.13),
        )


def test_confirmed_is_frozen() -> None:
    accommodation = ConfirmedAccommodation(
        label="Garden Hotel",
        provider_poi_id="POI-42",
        coordinates=GeoPoint(longitude=113.28, latitude=23.13),
    )

    with pytest.raises(AttributeError):
        accommodation.label = "Other Hotel"  # type: ignore[misc]


# ── Area estimated accommodation ──────────────────────────────────────────


def test_area_estimated_constructs_with_exact_state_and_source() -> None:
    accommodation = AreaEstimatedAccommodation(
        region="Yuexiu",
        source=AreaEstimateSource.USER_REGION,
    )

    assert accommodation.state == "AREA_ESTIMATED"
    assert accommodation.state == AccommodationState.AREA_ESTIMATED
    assert accommodation.source == AreaEstimateSource.USER_REGION


def test_area_estimated_accepts_all_sources() -> None:
    for source in (
        AreaEstimateSource.USER_REGION,
        AreaEstimateSource.PROVIDER_DISTRICT,
        AreaEstimateSource.DAY_PRIMARY_REGION,
    ):
        accommodation = AreaEstimatedAccommodation(region="Yuexiu", source=source)
        assert accommodation.source is source


def test_area_estimated_centroid_is_optional() -> None:
    with_centroid = AreaEstimatedAccommodation(
        region="Yuexiu",
        source=AreaEstimateSource.PROVIDER_DISTRICT,
        centroid=GeoPoint(longitude=113.28, latitude=23.13),
    )
    without_centroid = AreaEstimatedAccommodation(
        region="Yuexiu",
        source=AreaEstimateSource.PROVIDER_DISTRICT,
    )

    assert with_centroid.centroid == GeoPoint(longitude=113.28, latitude=23.13)
    assert without_centroid.centroid is None


def test_area_estimated_rejects_empty_region() -> None:
    with pytest.raises(ValueError):
        AreaEstimatedAccommodation(region="", source=AreaEstimateSource.USER_REGION)
    with pytest.raises(ValueError):
        AreaEstimatedAccommodation(region="   ", source=AreaEstimateSource.USER_REGION)


def test_area_estimated_normalises_region_and_requested_label() -> None:
    accommodation = AreaEstimatedAccommodation(
        region="  Yuexiu  ",
        source=AreaEstimateSource.USER_REGION,
        requested_label="  near garden hotel  ",
    )

    assert accommodation.region == "Yuexiu"
    assert accommodation.requested_label == "near garden hotel"


def test_area_estimated_has_no_provider_poi_id() -> None:
    accommodation = AreaEstimatedAccommodation(
        region="Yuexiu",
        source=AreaEstimateSource.USER_REGION,
    )

    assert not hasattr(accommodation, "provider_poi_id")


def test_area_estimated_is_frozen() -> None:
    accommodation = AreaEstimatedAccommodation(
        region="Yuexiu",
        source=AreaEstimateSource.USER_REGION,
    )

    with pytest.raises(AttributeError):
        accommodation.region = "Tianhe"  # type: ignore[misc]


# ── Unresolved accommodation ──────────────────────────────────────────────


def test_unresolved_default_display_label() -> None:
    accommodation = UnresolvedAccommodation()

    assert accommodation.state == "UNRESOLVED"
    assert accommodation.state == AccommodationState.UNRESOLVED
    assert accommodation.display_label == "住宿地点待确认"


def test_unresolved_keeps_requested_label() -> None:
    accommodation = UnresolvedAccommodation(requested_label="Hilton Guangzhou")

    assert accommodation.requested_label == "Hilton Guangzhou"
    assert accommodation.display_label == "住宿地点待确认"


def test_unresolved_rejects_empty_requested_label() -> None:
    with pytest.raises(ValueError):
        UnresolvedAccommodation(requested_label="")
    with pytest.raises(ValueError):
        UnresolvedAccommodation(requested_label="   ")


def test_unresolved_normalises_display_label() -> None:
    accommodation = UnresolvedAccommodation(display_label="  住宿地点待确认  ")

    assert accommodation.display_label == "住宿地点待确认"


def test_unresolved_has_no_anchor_attributes() -> None:
    accommodation = UnresolvedAccommodation()

    assert not hasattr(accommodation, "provider_poi_id")
    assert not hasattr(accommodation, "coordinates")
    assert not hasattr(accommodation, "centroid")


def test_unresolved_is_frozen() -> None:
    accommodation = UnresolvedAccommodation()

    with pytest.raises(AttributeError):
        accommodation.display_label = "changed"  # type: ignore[misc]


# ── Trip Skeleton ─────────────────────────────────────────────────────────


def _day(day: date) -> DayPlan:
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
    )


def _confirmed(label: str = "Garden Hotel") -> ConfirmedAccommodation:
    return ConfirmedAccommodation(
        label=label,
        provider_poi_id="POI-42",
        coordinates=GeoPoint(longitude=113.28, latitude=23.13),
    )


def _estimated() -> AreaEstimatedAccommodation:
    return AreaEstimatedAccommodation(
        region="Yuexiu",
        source=AreaEstimateSource.USER_REGION,
    )


def _unresolved() -> UnresolvedAccommodation:
    return UnresolvedAccommodation()


def test_single_day_with_zero_nights_succeeds() -> None:
    skeleton = build_trip_skeleton((_day(date(2026, 8, 1)),), ())

    assert skeleton.day_count == 1
    assert skeleton.night_count == 0
    assert skeleton.overnights == ()
    assert skeleton.start_date == date(2026, 8, 1)
    assert skeleton.end_date == date(2026, 8, 1)


def test_single_day_with_one_night_rejected() -> None:
    with pytest.raises(ValueError):
        build_trip_skeleton((_day(date(2026, 8, 1)),), (_confirmed(),))


def test_two_days_with_one_night_succeeds() -> None:
    skeleton = build_trip_skeleton(
        (_day(date(2026, 8, 1)), _day(date(2026, 8, 2))),
        (_confirmed(),),
    )

    assert skeleton.day_count == 2
    assert skeleton.night_count == 1
    assert len(skeleton.overnights) == 1


def test_three_days_with_two_nights_succeeds() -> None:
    skeleton = build_trip_skeleton(
        (
            _day(date(2026, 8, 1)),
            _day(date(2026, 8, 2)),
            _day(date(2026, 8, 3)),
        ),
        (_confirmed(), _unresolved()),
    )

    assert skeleton.day_count == 3
    assert skeleton.night_count == 2


def test_multi_day_with_zero_nights_rejected() -> None:
    with pytest.raises(ValueError):
        build_trip_skeleton(
            (_day(date(2026, 8, 1)), _day(date(2026, 8, 2))),
            (),
        )


def test_nights_one_short_rejected() -> None:
    with pytest.raises(ValueError):
        build_trip_skeleton(
            (
                _day(date(2026, 8, 1)),
                _day(date(2026, 8, 2)),
                _day(date(2026, 8, 3)),
            ),
            (_confirmed(),),
        )


def test_nights_one_extra_rejected() -> None:
    with pytest.raises(ValueError):
        build_trip_skeleton(
            (_day(date(2026, 8, 1)), _day(date(2026, 8, 2))),
            (_confirmed(), _unresolved()),
        )


def test_empty_days_rejected() -> None:
    with pytest.raises(ValueError):
        build_trip_skeleton((), ())


def test_days_reversed_rejected() -> None:
    with pytest.raises(ValueError):
        build_trip_skeleton(
            (_day(date(2026, 8, 2)), _day(date(2026, 8, 1))),
            (_confirmed(),),
        )


def test_days_duplicated_rejected() -> None:
    with pytest.raises(ValueError):
        build_trip_skeleton(
            (_day(date(2026, 8, 1)), _day(date(2026, 8, 1))),
            (_confirmed(),),
        )


def test_days_with_gap_rejected() -> None:
    with pytest.raises(ValueError):
        build_trip_skeleton(
            (_day(date(2026, 8, 1)), _day(date(2026, 8, 3))),
            (_confirmed(),),
        )


def test_boundary_dates_follow_adjacent_day_plans() -> None:
    days = (
        _day(date(2026, 8, 1)),
        _day(date(2026, 8, 2)),
        _day(date(2026, 8, 3)),
    )
    skeleton = build_trip_skeleton(days, (_confirmed(), _estimated()))

    assert skeleton.overnights[0].from_date == date(2026, 8, 1)
    assert skeleton.overnights[0].to_date == date(2026, 8, 2)
    assert skeleton.overnights[1].from_date == date(2026, 8, 2)
    assert skeleton.overnights[1].to_date == date(2026, 8, 3)


def test_all_three_states_appear_in_overnights() -> None:
    skeleton = build_trip_skeleton(
        (
            _day(date(2026, 8, 1)),
            _day(date(2026, 8, 2)),
            _day(date(2026, 8, 3)),
            _day(date(2026, 8, 4)),
        ),
        (_confirmed(), _estimated(), _unresolved()),
    )

    assert skeleton.accommodation_states == (
        AccommodationState.CONFIRMED,
        AccommodationState.AREA_ESTIMATED,
        AccommodationState.UNRESOLVED,
    )


def test_different_nights_allow_different_states() -> None:
    skeleton = build_trip_skeleton(
        (
            _day(date(2026, 8, 1)),
            _day(date(2026, 8, 2)),
            _day(date(2026, 8, 3)),
        ),
        (_estimated(), _confirmed()),
    )

    assert skeleton.overnights[0].accommodation.state == "AREA_ESTIMATED"
    assert skeleton.overnights[1].accommodation.state == "CONFIRMED"


def test_skeleton_properties() -> None:
    skeleton = build_trip_skeleton(
        (
            _day(date(2026, 8, 1)),
            _day(date(2026, 8, 2)),
            _day(date(2026, 8, 3)),
        ),
        (_confirmed(), _unresolved()),
    )

    assert skeleton.start_date == date(2026, 8, 1)
    assert skeleton.end_date == date(2026, 8, 3)
    assert skeleton.day_count == 3
    assert skeleton.night_count == 2
    assert skeleton.accommodation_states == (
        AccommodationState.CONFIRMED,
        AccommodationState.UNRESOLVED,
    )


def test_overnight_boundary_rejects_non_consecutive_dates() -> None:
    with pytest.raises(ValueError):
        OvernightBoundary(
            from_date=date(2026, 8, 1),
            to_date=date(2026, 8, 3),
            accommodation=_confirmed(),
        )


def test_overnight_boundary_requires_accommodation() -> None:
    with pytest.raises(TypeError):
        OvernightBoundary(  # type: ignore[call-arg]
            from_date=date(2026, 8, 1),
            to_date=date(2026, 8, 2),
        )


def test_trip_skeleton_is_frozen() -> None:
    skeleton = build_trip_skeleton(
        (_day(date(2026, 8, 1)), _day(date(2026, 8, 2))),
        (_confirmed(),),
    )

    with pytest.raises(AttributeError):
        skeleton.days = ()  # type: ignore[misc]


def test_overnight_boundary_is_frozen() -> None:
    boundary = OvernightBoundary(
        from_date=date(2026, 8, 1),
        to_date=date(2026, 8, 2),
        accommodation=_confirmed(),
    )

    with pytest.raises(AttributeError):
        boundary.accommodation = _unresolved()  # type: ignore[misc]


def test_build_does_not_mutate_input_day_plans() -> None:
    days = (_day(date(2026, 8, 1)), _day(date(2026, 8, 2)))
    skeleton = build_trip_skeleton(days, (_confirmed(),))

    assert skeleton.days == days
    assert skeleton.days[0] is days[0]
    assert skeleton.days[1] is days[1]


# ── Safety & dependency boundary ──────────────────────────────────────────


def _trip_skeleton_imports() -> list[str]:
    module_path = pathlib.Path(trip_skeleton_module.__file__)
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
    return imports


def test_trip_skeleton_imports_no_provider_feasibility_or_evaluation() -> None:
    for module in _trip_skeleton_imports():
        assert "provider" not in module.lower(), module
        assert not module.startswith("trip_agent.feasibility"), module
        assert not module.startswith("trip_agent.evaluation"), module


def test_trip_skeleton_uses_no_clocks_uuids_or_io() -> None:
    source = pathlib.Path(trip_skeleton_module.__file__).read_text(encoding="utf-8")
    assert "datetime.now" not in source
    assert "uuid" not in source
    assert "socket" not in source
    assert "sqlite" not in source
    assert "psycopg" not in source
    assert "requests" not in source
    assert "urllib" not in source


def test_b4b_catalog_implemented_set_is_exactly_seven() -> None:
    assert IMPLEMENTED_RULE_IDS == (
        "TRIP_DATE_RANGE",
        "FIXED_SCHEDULE_COVERAGE",
        "BUDGET_LIMIT",
        "DUPLICATE_POI",
        "ACTIVITY_OVERLAP",
        "ROUTE_ENDPOINT_CONTINUITY",
        "CROSS_DAY_CONTINUITY",
    )


def test_continuity_rules_no_longer_missing() -> None:
    assert "ROUTE_ENDPOINT_CONTINUITY" not in MISSING_RULE_IDS
    assert "CROSS_DAY_CONTINUITY" not in MISSING_RULE_IDS
    assert MISSING_RULE_IDS == (
        "MUST_VISIT_COVERAGE",
        "OPENING_HOURS",
        "VISIT_DURATION",
        "MEAL_WINDOW",
    )


def test_b3_does_not_make_validator_report_verified() -> None:
    report = validate_itinerary(
        command=make_command(),
        itinerary=make_result().itinerary,
        report_id="3d76fb9e-362e-4b28-8a9e-18e8ac7050ad",
        validated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    assert report.status is not FeasibilityStatus.VERIFIED


# ── B3.1 runtime invariants ───────────────────────────────────────────────


def test_state_not_overridable_via_constructor_confirmed() -> None:
    with pytest.raises(TypeError):
        ConfirmedAccommodation(
            label="Garden Hotel",
            provider_poi_id="POI-42",
            coordinates=GeoPoint(longitude=113.28, latitude=23.13),
            state=AccommodationState.UNRESOLVED,
        )


def test_state_not_overridable_via_constructor_area_estimated() -> None:
    with pytest.raises(TypeError):
        AreaEstimatedAccommodation(
            region="Yuexiu",
            source=AreaEstimateSource.USER_REGION,
            state=AccommodationState.CONFIRMED,
        )


def test_state_not_overridable_via_constructor_unresolved() -> None:
    with pytest.raises(TypeError):
        UnresolvedAccommodation(state=AccommodationState.CONFIRMED)


def test_confirmed_rejects_none_coordinates() -> None:
    with pytest.raises(ValueError):
        ConfirmedAccommodation(
            label="Garden Hotel",
            provider_poi_id="POI-42",
            coordinates=None,  # type: ignore[arg-type]
        )


def test_confirmed_rejects_non_geopoint_coordinates() -> None:
    with pytest.raises(ValueError):
        ConfirmedAccommodation(
            label="Garden Hotel",
            provider_poi_id="POI-42",
            coordinates=(113.28, 23.13),  # type: ignore[arg-type]
        )


def test_area_estimated_rejects_plain_string_source() -> None:
    with pytest.raises(ValueError):
        AreaEstimatedAccommodation(
            region="Yuexiu",
            source="USER_REGION",  # type: ignore[arg-type]
        )


def test_area_estimated_rejects_none_source() -> None:
    with pytest.raises(ValueError):
        AreaEstimatedAccommodation(
            region="Yuexiu",
            source=None,  # type: ignore[arg-type]
        )


def test_area_estimated_rejects_unknown_source_value() -> None:
    with pytest.raises(ValueError):
        AreaEstimatedAccommodation(
            region="Yuexiu",
            source="MADE_UP_SOURCE",  # type: ignore[arg-type]
        )


def test_area_estimated_rejects_non_geopoint_centroid() -> None:
    with pytest.raises(ValueError):
        AreaEstimatedAccommodation(
            region="Yuexiu",
            source=AreaEstimateSource.USER_REGION,
            centroid=(113.28, 23.13),  # type: ignore[arg-type]
        )


def test_overnight_boundary_rejects_none_accommodation() -> None:
    with pytest.raises(ValueError):
        OvernightBoundary(
            from_date=date(2026, 8, 1),
            to_date=date(2026, 8, 2),
            accommodation=None,  # type: ignore[arg-type]
        )


def test_overnight_boundary_rejects_non_accommodation_object() -> None:
    with pytest.raises(ValueError):
        OvernightBoundary(
            from_date=date(2026, 8, 1),
            to_date=date(2026, 8, 2),
            accommodation="Garden Hotel",  # type: ignore[arg-type]
        )


def test_accommodation_states_are_real_enum_instances() -> None:
    skeleton = build_trip_skeleton(
        (
            _day(date(2026, 8, 1)),
            _day(date(2026, 8, 2)),
            _day(date(2026, 8, 3)),
        ),
        (_confirmed(), _estimated()),
    )

    assert all(isinstance(state, AccommodationState) for state in skeleton.accommodation_states)
    assert skeleton.accommodation_states[0] is AccommodationState.CONFIRMED
    assert skeleton.accommodation_states[1] is AccommodationState.AREA_ESTIMATED


def test_geopoint_rejects_bool_longitude() -> None:
    with pytest.raises(ValueError):
        GeoPoint(longitude=True, latitude=23.13)  # type: ignore[arg-type]


def test_geopoint_rejects_bool_latitude() -> None:
    with pytest.raises(ValueError):
        GeoPoint(longitude=113.28, latitude=False)  # type: ignore[arg-type]


# ── B3.2 container immutability ────────────────────────────────────────────


class _FakeDayPlan:
    def __init__(self, day: date) -> None:
        self.date = day


class _FakeOvernightBoundary:
    def __init__(self, from_date: date, to_date: date, accommodation: object) -> None:
        self.from_date = from_date
        self.to_date = to_date
        self.accommodation = accommodation


def test_builder_snapshots_mutable_days_input() -> None:
    days = [_day(date(2026, 8, 1)), _day(date(2026, 8, 2))]
    skeleton = build_trip_skeleton(days, (_confirmed(),))

    assert isinstance(skeleton.days, tuple)
    days.clear()
    assert skeleton.day_count == 2
    assert skeleton.start_date == date(2026, 8, 1)
    assert skeleton.end_date == date(2026, 8, 2)
    assert skeleton.days == (_day(date(2026, 8, 1)), _day(date(2026, 8, 2)))


def test_direct_construction_snapshots_mutable_inputs() -> None:
    days = [_day(date(2026, 8, 1)), _day(date(2026, 8, 2))]
    boundaries = [
        OvernightBoundary(
            from_date=date(2026, 8, 1),
            to_date=date(2026, 8, 2),
            accommodation=_confirmed(),
        )
    ]
    skeleton = TripSkeleton(days=days, overnights=boundaries)

    assert isinstance(skeleton.days, tuple)
    assert isinstance(skeleton.overnights, tuple)
    days.clear()
    boundaries.clear()
    assert skeleton.day_count == 2
    assert skeleton.night_count == 1
    assert skeleton.days[0].date == date(2026, 8, 1)
    assert skeleton.overnights[0].from_date == date(2026, 8, 1)


def test_trip_skeleton_rejects_duck_typed_day() -> None:
    fake = _FakeDayPlan(date(2026, 8, 1))
    with pytest.raises((TypeError, ValueError)):
        TripSkeleton(
            days=(fake, _day(date(2026, 8, 2))),
            overnights=(
                OvernightBoundary(
                    from_date=date(2026, 8, 1),
                    to_date=date(2026, 8, 2),
                    accommodation=_confirmed(),
                ),
            ),
        )


def test_trip_skeleton_rejects_duck_typed_overnight() -> None:
    fake = _FakeOvernightBoundary(date(2026, 8, 1), date(2026, 8, 2), _confirmed())
    with pytest.raises((TypeError, ValueError)):
        TripSkeleton(
            days=(_day(date(2026, 8, 1)), _day(date(2026, 8, 2))),
            overnights=(fake,),
        )


def test_tuple_inputs_keep_element_identity() -> None:
    days = (_day(date(2026, 8, 1)), _day(date(2026, 8, 2)))
    accommodation = _confirmed()
    skeleton = build_trip_skeleton(days, (accommodation,))

    assert skeleton.days[0] is days[0]
    assert skeleton.days[1] is days[1]
    assert skeleton.overnights[0].accommodation is accommodation


def test_builder_does_not_mutate_list_input() -> None:
    days = [_day(date(2026, 8, 1)), _day(date(2026, 8, 2))]
    original = list(days)
    build_trip_skeleton(days, (_confirmed(),))
    assert days == original
