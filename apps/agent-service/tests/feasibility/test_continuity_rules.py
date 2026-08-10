"""B4B — continuity hard rules: ROUTE_ENDPOINT_CONTINUITY and
CROSS_DAY_CONTINUITY.

Truth tables locked here:
- route: N/A (no adjacent pairs), PASS (coords + leg), FAIL (coords, no
  leg), UNKNOWN (missing endpoint coordinates), FAIL > UNKNOWN.
- cross-day: N/A (single day), UNKNOWN (no skeleton / date mismatch /
  AREA_ESTIMATED / UNRESOLVED), PASS (matching CONFIRMED endpoints),
  FAIL (CONFIRMED endpoint mismatch), FAIL > UNKNOWN.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from plan_evaluation_support import make_command

from trip_agent.feasibility.context import ValidationContext, build_budget_context
from trip_agent.feasibility.models import RuleOutcome
from trip_agent.feasibility.rules.continuity import (
    assess_cross_day_continuity,
    assess_route_endpoint_continuity,
)
from trip_agent.planning.daily_schedule import DayPlan
from trip_agent.planning.trip_skeleton import (
    AreaEstimatedAccommodation,
    AreaEstimateSource,
    ConfirmedAccommodation,
    GeoPoint,
    TripSkeleton,
    UnresolvedAccommodation,
    build_trip_skeleton,
)
from trip_agent.worker.contracts import (
    ActivityCoordinates,
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
    TransitLeg,
)

_TS = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


# ── builders ───────────────────────────────────────────────────────────────


def _day(day: date, *, region: str | None = None) -> DayPlan:
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


def _amap_activity(
    index: int,
    *,
    kind: str = "ATTRACTION",
    provider_poi_id: str | None = None,
    longitude: Decimal | float = Decimal("113.310000"),
    latitude: Decimal | float = Decimal("23.130000"),
    start_hour: int | None = None,
) -> ItineraryActivity:
    start = 9 + index * 2 if start_hour is None else start_hour
    return ItineraryActivity(
        activity_id=None,
        title=f"Activity {index}",
        start_time=datetime(2026, 8, 1, start, 0, tzinfo=UTC),
        end_time=datetime(2026, 8, 1, start + 1, 0, tzinfo=UTC),
        estimated_cost=Decimal("0"),
        source="AMAP",
        provider_poi_id=provider_poi_id or f"POI-{index}",
        coordinates=ActivityCoordinates(longitude=longitude, latitude=latitude),
        address=f"Address {index}",
        kind=kind,  # type: ignore[arg-type]
    )


def _demo_activity(index: int, *, start_hour: int | None = None) -> ItineraryActivity:
    start = 9 + index * 2 if start_hour is None else start_hour
    return ItineraryActivity(
        activity_id=None,
        title=f"Demo {index}",
        start_time=datetime(2026, 8, 1, start, 0, tzinfo=UTC),
        end_time=datetime(2026, 8, 1, start + 1, 0, tzinfo=UTC),
        estimated_cost=Decimal("0"),
        source="DEMO",
        coordinates=None,
        kind="ATTRACTION",
    )


def _leg(
    index: int,
    *,
    provider: str = "AMAP",
) -> TransitLeg:
    return TransitLeg(
        transit_id=None,
        from_activity_index=index,
        to_activity_index=index + 1,
        mode="WALKING",
        distance_meters=300,
        duration_seconds=300,
        provider=provider,  # type: ignore[arg-type]
        estimated=provider == "DEMO",
        estimated_cost=Decimal("0") if provider == "DEMO" else None,
        cost_source="DEMO" if provider == "DEMO" else "PROVIDER",
        polyline=(
            ActivityCoordinates(longitude=Decimal("113.31"), latitude=Decimal("23.13")),
            ActivityCoordinates(longitude=Decimal("113.32"), latitude=Decimal("23.14")),
        ),
    )


def _itinerary(
    *days: tuple[tuple[ItineraryActivity, ...], tuple[TransitLeg, ...]],
) -> Itinerary:
    return Itinerary(
        title="Continuity fixture",
        days=tuple(
            ItineraryDay(
                date=date(2026, 8, 1) + timedelta(days=index),
                activities=activities,
                transit_legs=legs,
            )
            for index, (activities, legs) in enumerate(days)
        ),
        estimated_total_cost=Decimal("0"),
    )


def _ctx(
    itinerary: Itinerary,
    *,
    trip_skeleton: TripSkeleton | None = None,
) -> ValidationContext:
    command = make_command()
    return ValidationContext(
        command=command,
        itinerary=itinerary,
        budget=build_budget_context(command, itinerary),
        trip_skeleton=trip_skeleton,
    )


def _skeleton(
    *overnights: tuple[date, object],
) -> TripSkeleton:
    from_dates = [day for day, _ in overnights]
    days = tuple(_day(day) for day in from_dates) + (_day(from_dates[-1] + timedelta(days=1)),)
    accommodations = tuple(accommodation for _, accommodation in overnights)
    return build_trip_skeleton(days, accommodations)


def _confirmed(
    provider_poi_id: str = "HOTEL-1",
    *,
    longitude: float = 113.31,
    latitude: float = 23.13,
) -> ConfirmedAccommodation:
    return ConfirmedAccommodation(
        label="Garden Hotel",
        provider_poi_id=provider_poi_id,
        coordinates=GeoPoint(longitude=longitude, latitude=latitude),
    )


# ── ROUTE_ENDPOINT_CONTINUITY ──────────────────────────────────────────────


def test_route_single_activity_is_not_applicable() -> None:
    ctx = _ctx(_itinerary(((_amap_activity(0),), ())))

    assessment = assess_route_endpoint_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.NOT_APPLICABLE
    assert assessment.result.reason_code == "NO_ADJACENT_ACTIVITY_PAIRS"
    assert assessment.findings == ()


def test_route_multi_day_single_activity_each_is_not_applicable() -> None:
    ctx = _ctx(
        _itinerary(
            ((_amap_activity(0),), ()),
            ((_amap_activity(1),), ()),
        )
    )

    assessment = assess_route_endpoint_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.NOT_APPLICABLE
    assert assessment.result.reason_code == "NO_ADJACENT_ACTIVITY_PAIRS"


def test_route_amap_coordinates_with_leg_passes() -> None:
    ctx = _ctx(
        _itinerary(
            ((_amap_activity(0), _amap_activity(1)), (_leg(0),)),
        )
    )

    assessment = assess_route_endpoint_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.PASS
    assert assessment.result.reason_code == "ROUTE_ENDPOINTS_CONTINUOUS"
    assert assessment.findings == ()


def test_route_coordinates_without_leg_fails() -> None:
    ctx = _ctx(
        _itinerary(
            ((_amap_activity(0), _amap_activity(1)), ()),
        )
    )

    assessment = assess_route_endpoint_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "ROUTE_LEG_MISSING"
    assert len(assessment.findings) == 1
    finding = assessment.findings[0]
    assert finding.reason_code == "ROUTE_LEG_MISSING"
    assert finding.affected_date == date(2026, 8, 1)


def test_route_missing_coordinate_is_unknown_even_with_leg() -> None:
    ctx = _ctx(
        _itinerary(
            (
                (_amap_activity(0), _demo_activity(1)),
                (_leg(0),),
            ),
        )
    )

    assessment = assess_route_endpoint_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.reason_code == "ROUTE_ENDPOINTS_UNVERIFIABLE"
    assert assessment.findings[0].reason_code == "ROUTE_ENDPOINT_COORDINATES_MISSING"


def test_route_demo_activities_with_leg_stay_unknown() -> None:
    ctx = _ctx(
        _itinerary(
            ((_demo_activity(0), _demo_activity(1)), (_leg(0, provider="DEMO"),)),
        )
    )

    assessment = assess_route_endpoint_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.reason_code == "ROUTE_ENDPOINTS_UNVERIFIABLE"
    assert assessment.findings[0].reason_code == "ROUTE_ENDPOINT_COORDINATES_MISSING"


def test_route_fail_precedes_unknown() -> None:
    ctx = _ctx(
        _itinerary(
            (
                (
                    _amap_activity(0),
                    _amap_activity(1),
                    _amap_activity(2),
                    _demo_activity(3),
                ),
                # pair (0,1) has a leg; pair (1,2) lacks one (FAIL);
                # pair (2,3) has a coordinate-less endpoint (UNKNOWN).
                (_leg(0),),
            ),
        )
    )

    assessment = assess_route_endpoint_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "ROUTE_LEG_MISSING"


def test_route_all_unknown_stays_unknown() -> None:
    ctx = _ctx(
        _itinerary(
            ((_demo_activity(0), _demo_activity(1), _demo_activity(2)), ()),
        )
    )

    assessment = assess_route_endpoint_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.reason_code == "ROUTE_ENDPOINTS_UNVERIFIABLE"


def test_route_multi_day_affected_dates_stable_and_unique() -> None:
    ctx = _ctx(
        _itinerary(
            ((_amap_activity(0), _amap_activity(1)), ()),
            ((_amap_activity(2), _amap_activity(3)), ()),
        )
    )

    assessment = assess_route_endpoint_continuity(ctx)

    assert assessment.result.affected_dates == (date(2026, 8, 1), date(2026, 8, 2))
    assert len(assessment.result.affected_dates) == 2


def test_route_aggregate_refs_capped_at_64() -> None:
    activities = tuple(_amap_activity(i, start_hour=7 + (i % 8)) for i in range(66))
    ctx = _ctx(_itinerary((activities, ())))

    assessment = assess_route_endpoint_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert len(assessment.result.affected_entity_refs) == 64


def test_route_does_not_mutate_itinerary() -> None:
    activities = (_amap_activity(0), _amap_activity(1))
    legs = (_leg(0),)
    itinerary = _itinerary((activities, legs))
    before = itinerary.model_dump_json(by_alias=True)

    assess_route_endpoint_continuity(_ctx(itinerary))

    assert itinerary.model_dump_json(by_alias=True) == before


def test_route_activity_ref_prefers_activity_id_then_poi_id() -> None:
    with_id = ItineraryActivity(
        activity_id=__import__("uuid").UUID("3d76fb9e-362e-4b28-8a9e-18e8ac7050ad"),
        title="With id",
        start_time=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        end_time=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
        estimated_cost=Decimal("0"),
        source="AMAP",
        provider_poi_id="POI-1",
        coordinates=ActivityCoordinates(longitude=Decimal("113.31"), latitude=Decimal("23.13")),
        address="Address with id",
        kind="ATTRACTION",
    )
    with_poi = _amap_activity(1, provider_poi_id="POI-2")
    ctx = _ctx(_itinerary(((with_id, with_poi), ())))

    assessment = assess_route_endpoint_continuity(ctx)

    refs = assessment.result.affected_entity_refs
    assert "3d76fb9e-362e-4b28-8a9e-18e8ac7050ad" in refs
    assert "POI-2" in refs


# ── CROSS_DAY_CONTINUITY ───────────────────────────────────────────────────


def _hotel_node(
    day: int,
    poi_id: str,
    *,
    hour: int,
    longitude: Decimal = Decimal("113.310000"),
    latitude: Decimal = Decimal("23.130000"),
    has_coordinates: bool = True,
) -> ItineraryActivity:
    return ItineraryActivity(
        activity_id=None,
        title="Hotel",
        start_time=datetime(2026, 8, day, hour, 0, tzinfo=UTC),
        end_time=datetime(2026, 8, day, hour + 1, 0, tzinfo=UTC),
        estimated_cost=Decimal("0"),
        source="AMAP",
        provider_poi_id=poi_id,
        coordinates=(
            ActivityCoordinates(longitude=longitude, latitude=latitude) if has_coordinates else None
        ),
        address="Hotel address",
        kind="ACCOMMODATION",
    )


def _overnight_itinerary(
    day_one: tuple[ItineraryActivity, ...],
    day_two: tuple[ItineraryActivity, ...],
) -> Itinerary:
    return _itinerary(
        (day_one, ()),
        (day_two, ()),
    )


def test_cross_single_day_without_skeleton_is_not_applicable() -> None:
    ctx = _ctx(_itinerary(((_amap_activity(0),), ())), trip_skeleton=None)

    assessment = assess_cross_day_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.NOT_APPLICABLE
    assert assessment.result.reason_code == "SINGLE_DAY_TRIP"


def test_cross_multi_day_without_skeleton_is_unknown() -> None:
    ctx = _ctx(
        _overnight_itinerary((_amap_activity(0),), (_amap_activity(1),)),
        trip_skeleton=None,
    )

    assessment = assess_cross_day_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.reason_code == "TRIP_SKELETON_UNAVAILABLE"


def test_cross_skeleton_date_mismatch_is_unknown() -> None:
    skeleton = _skeleton((date(2026, 8, 1), _confirmed()))
    # Itinerary dates (8-2, 8-3) differ from skeleton dates (8-1, 8-2).
    itinerary = Itinerary(
        title="Date mismatch",
        days=(
            ItineraryDay(
                date=date(2026, 8, 2),
                activities=(_amap_activity(0),),
                transit_legs=(),
            ),
            ItineraryDay(
                date=date(2026, 8, 3),
                activities=(_amap_activity(1),),
                transit_legs=(),
            ),
        ),
        estimated_total_cost=Decimal("0"),
    )
    ctx = _ctx(itinerary, trip_skeleton=skeleton)

    assessment = assess_cross_day_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.reason_code == "TRIP_SKELETON_DATE_MISMATCH"


def test_cross_confirmed_matching_endpoints_passes() -> None:
    skeleton = _skeleton((date(2026, 8, 1), _confirmed()))
    itinerary = _overnight_itinerary(
        (_amap_activity(0), _hotel_node(1, "HOTEL-1", hour=21)),
        (_hotel_node(2, "HOTEL-1", hour=8), _amap_activity(1)),
    )
    ctx = _ctx(itinerary, trip_skeleton=skeleton)

    assessment = assess_cross_day_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.PASS
    assert assessment.result.reason_code == "CROSS_DAY_ENDPOINTS_CONTINUOUS"
    assert assessment.findings == ()


def test_cross_confirmed_missing_previous_night_endpoint_fails() -> None:
    skeleton = _skeleton((date(2026, 8, 1), _confirmed()))
    itinerary = _overnight_itinerary(
        (_amap_activity(0),),  # last activity is NOT an accommodation node
        (_hotel_node(2, "HOTEL-1", hour=8), _amap_activity(1)),
    )
    ctx = _ctx(itinerary, trip_skeleton=skeleton)

    assessment = assess_cross_day_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "OVERNIGHT_ENDPOINT_MISMATCH"
    assert assessment.findings[0].reason_code == "OVERNIGHT_ENDPOINT_MISMATCH"


def test_cross_confirmed_missing_next_morning_endpoint_fails() -> None:
    skeleton = _skeleton((date(2026, 8, 1), _confirmed()))
    itinerary = _overnight_itinerary(
        (_amap_activity(0), _hotel_node(1, "HOTEL-1", hour=21)),
        (_amap_activity(1),),  # first activity is NOT an accommodation node
    )
    ctx = _ctx(itinerary, trip_skeleton=skeleton)

    assessment = assess_cross_day_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "OVERNIGHT_ENDPOINT_MISMATCH"


def test_cross_confirmed_poi_id_mismatch_fails() -> None:
    skeleton = _skeleton((date(2026, 8, 1), _confirmed(provider_poi_id="HOTEL-1")))
    itinerary = _overnight_itinerary(
        (_amap_activity(0), _hotel_node(1, "OTHER-HOTEL", hour=21)),
        (_hotel_node(2, "HOTEL-1", hour=8), _amap_activity(1)),
    )
    ctx = _ctx(itinerary, trip_skeleton=skeleton)

    assessment = assess_cross_day_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "OVERNIGHT_ENDPOINT_MISMATCH"
    assert "HOTEL-1" in assessment.result.affected_entity_refs


def test_cross_confirmed_coordinates_mismatch_fails() -> None:
    skeleton = _skeleton((date(2026, 8, 1), _confirmed(longitude=113.40, latitude=23.40)))
    itinerary = _overnight_itinerary(
        (_amap_activity(0), _hotel_node(1, "HOTEL-1", hour=21)),
        (_hotel_node(2, "HOTEL-1", hour=8), _amap_activity(1)),
    )
    ctx = _ctx(itinerary, trip_skeleton=skeleton)

    assessment = assess_cross_day_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "OVERNIGHT_ENDPOINT_MISMATCH"


def test_cross_confirmed_quantized_coordinates_pass() -> None:
    # GeoPoint carries more than 6 decimal places (8 here); quantising to
    # the project's COORDINATE_SCALE (7 places) must equal the itinerary's
    # standard quantised coordinates — no false conflict.
    skeleton = _skeleton(
        (
            date(2026, 8, 1),
            _confirmed(longitude=113.31000001, latitude=23.13000001),
        )
    )
    itinerary = _overnight_itinerary(
        (_amap_activity(0), _hotel_node(1, "HOTEL-1", hour=21)),
        (_hotel_node(2, "HOTEL-1", hour=8), _amap_activity(1)),
    )
    ctx = _ctx(itinerary, trip_skeleton=skeleton)

    assessment = assess_cross_day_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.PASS
    assert assessment.result.reason_code == "CROSS_DAY_ENDPOINTS_CONTINUOUS"


def test_cross_area_estimated_is_unknown() -> None:
    skeleton = _skeleton(
        (
            date(2026, 8, 1),
            AreaEstimatedAccommodation(
                region="Yuexiu",
                source=AreaEstimateSource.DAY_PRIMARY_REGION,
            ),
        )
    )
    ctx = _ctx(
        _overnight_itinerary((_amap_activity(0),), (_amap_activity(1),)),
        trip_skeleton=skeleton,
    )

    assessment = assess_cross_day_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.reason_code == "ACCOMMODATION_AREA_ESTIMATED"


def test_cross_unresolved_is_unknown() -> None:
    skeleton = _skeleton((date(2026, 8, 1), UnresolvedAccommodation()))
    ctx = _ctx(
        _overnight_itinerary((_amap_activity(0),), (_amap_activity(1),)),
        trip_skeleton=skeleton,
    )

    assessment = assess_cross_day_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.reason_code == "ACCOMMODATION_UNRESOLVED"


def test_cross_confirmed_pass_plus_area_estimated_is_unknown() -> None:
    skeleton = _skeleton(
        (date(2026, 8, 1), _confirmed()),
        (
            date(2026, 8, 2),
            AreaEstimatedAccommodation(
                region="Yuexiu",
                source=AreaEstimateSource.DAY_PRIMARY_REGION,
            ),
        ),
    )
    itinerary = _itinerary(
        ((_amap_activity(0), _hotel_node(1, "HOTEL-1", hour=21)), ()),
        ((_hotel_node(2, "HOTEL-1", hour=8), _amap_activity(1)), ()),
        ((_amap_activity(2),), ()),
    )
    ctx = _ctx(itinerary, trip_skeleton=skeleton)

    assessment = assess_cross_day_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.reason_code == "ACCOMMODATION_AREA_ESTIMATED"


def test_cross_confirmed_fail_plus_unresolved_is_fail() -> None:
    skeleton = _skeleton(
        (date(2026, 8, 1), _confirmed()),
        (date(2026, 8, 2), UnresolvedAccommodation()),
    )
    itinerary = _itinerary(
        ((_amap_activity(0),), ()),  # night 1: confirmed but no endpoint -> FAIL
        ((_hotel_node(2, "HOTEL-1", hour=8), _amap_activity(1)), ()),
        ((_amap_activity(2),), ()),
    )
    ctx = _ctx(itinerary, trip_skeleton=skeleton)

    assessment = assess_cross_day_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "OVERNIGHT_ENDPOINT_MISMATCH"


def test_cross_multi_night_findings_are_stable() -> None:
    skeleton = _skeleton(
        (date(2026, 8, 1), _confirmed()),
        (date(2026, 8, 2), _confirmed()),
    )
    itinerary = _itinerary(
        ((_amap_activity(0),), ()),  # night 1 mismatch
        ((_hotel_node(2, "HOTEL-1", hour=8), _amap_activity(1)), ()),
        ((_amap_activity(2),), ()),  # night 2 mismatch
    )
    ctx = _ctx(itinerary, trip_skeleton=skeleton)

    assessment = assess_cross_day_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.affected_dates == (
        date(2026, 8, 1),
        date(2026, 8, 2),
        date(2026, 8, 3),
    )
    assert len(assessment.findings) == 2
    assert assessment.findings[0].affected_date == date(2026, 8, 1)
    assert assessment.findings[1].affected_date == date(2026, 8, 2)


def test_cross_does_not_mutate_inputs() -> None:
    skeleton = _skeleton((date(2026, 8, 1), _confirmed()))
    itinerary = _overnight_itinerary(
        (_amap_activity(0), _hotel_node(1, "HOTEL-1", hour=21)),
        (_hotel_node(2, "HOTEL-1", hour=8), _amap_activity(1)),
    )
    before = itinerary.model_dump_json(by_alias=True)
    before_days = tuple(skeleton.days)

    assess_cross_day_continuity(_ctx(itinerary, trip_skeleton=skeleton))

    assert itinerary.model_dump_json(by_alias=True) == before
    assert skeleton.days == before_days


# ── purity & dependency boundary ───────────────────────────────────────────


def test_continuity_module_imports_no_provider_evaluation_or_worker() -> None:
    import ast
    import pathlib

    import trip_agent.feasibility.rules.continuity as continuity_module

    tree = ast.parse(pathlib.Path(continuity_module.__file__).read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
    for module in imports:
        assert "provider" not in module.lower(), module
        assert not module.startswith("trip_agent.evaluation"), module
        # Shared message contracts are fine (core.py imports them too);
        # the worker runtime/processor is not.
        assert "worker.processor" not in module, module
        assert not module.startswith("trip_agent.application"), module


def test_continuity_module_uses_no_clocks_uuids_or_io() -> None:
    import pathlib

    import trip_agent.feasibility.rules.continuity as continuity_module

    source = pathlib.Path(continuity_module.__file__).read_text(encoding="utf-8")
    assert "datetime.now" not in source
    assert "uuid" not in source
    assert "socket" not in source
    assert "sqlite" not in source
    assert "requests" not in source


def test_continuity_failures_are_never_repairable() -> None:
    route_ctx = _ctx(
        _itinerary(
            ((_amap_activity(0), _amap_activity(1)), ()),
        )
    )
    route = assess_route_endpoint_continuity(route_ctx)
    assert route.result.outcome is RuleOutcome.FAIL
    assert route.result.repairable is False

    skeleton = _skeleton((date(2026, 8, 1), _confirmed()))
    cross_ctx = _ctx(
        _overnight_itinerary((_amap_activity(0),), (_amap_activity(1),)),
        trip_skeleton=skeleton,
    )
    cross = assess_cross_day_continuity(cross_ctx)
    assert cross.result.outcome is RuleOutcome.FAIL
    assert cross.result.repairable is False


# ── B4B.1: dual-side coordinate quantisation ───────────────────────────────


def test_cross_dual_side_high_precision_coordinates_pass() -> None:
    # Both skeleton (float) and itinerary nodes (high-precision Decimal)
    # carry more than 6 decimals; both must quantise to the same standard.
    skeleton = _skeleton(
        (
            date(2026, 8, 1),
            _confirmed(longitude=113.31000001, latitude=23.13000001),
        )
    )
    itinerary = _overnight_itinerary(
        (
            _amap_activity(0),
            _hotel_node(
                1,
                "HOTEL-1",
                hour=21,
                longitude=Decimal("113.31000001"),
                latitude=Decimal("23.13000001"),
            ),
        ),
        (
            _hotel_node(
                2,
                "HOTEL-1",
                hour=8,
                longitude=Decimal("113.31000001"),
                latitude=Decimal("23.13000001"),
            ),
            _amap_activity(1),
        ),
    )
    ctx = _ctx(itinerary, trip_skeleton=skeleton)

    assessment = assess_cross_day_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.PASS
    assert assessment.result.reason_code == "CROSS_DAY_ENDPOINTS_CONTINUOUS"


def test_cross_high_precision_activity_side_quantises_to_standard_pass() -> None:
    # Skeleton at standard precision; one activity node carries a
    # high-precision tail that quantises to the same standard value.
    skeleton = _skeleton((date(2026, 8, 1), _confirmed()))
    itinerary = _overnight_itinerary(
        (
            _amap_activity(0),
            _hotel_node(
                1,
                "HOTEL-1",
                hour=21,
                longitude=Decimal("113.31000001"),
                latitude=Decimal("23.13000001"),
            ),
        ),
        (_hotel_node(2, "HOTEL-1", hour=8), _amap_activity(1)),
    )
    ctx = _ctx(itinerary, trip_skeleton=skeleton)

    assessment = assess_cross_day_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.PASS


def test_cross_real_coordinate_difference_still_fails() -> None:
    # A genuinely different coordinate (113.32 vs 113.31) must still FAIL.
    skeleton = _skeleton((date(2026, 8, 1), _confirmed()))
    itinerary = _overnight_itinerary(
        (
            _amap_activity(0),
            _hotel_node(
                1,
                "HOTEL-1",
                hour=21,
                longitude=Decimal("113.320000"),
                latitude=Decimal("23.130000"),
            ),
        ),
        (_hotel_node(2, "HOTEL-1", hour=8), _amap_activity(1)),
    )
    ctx = _ctx(itinerary, trip_skeleton=skeleton)

    assessment = assess_cross_day_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "OVERNIGHT_ENDPOINT_MISMATCH"


# ── B4B.1: affected_dates completeness ─────────────────────────────────────


def test_cross_area_estimated_affected_dates_include_both_ends() -> None:
    skeleton = _skeleton(
        (
            date(2026, 8, 1),
            AreaEstimatedAccommodation(
                region="Yuexiu",
                source=AreaEstimateSource.DAY_PRIMARY_REGION,
            ),
        )
    )
    ctx = _ctx(
        _overnight_itinerary((_amap_activity(0),), (_amap_activity(1),)),
        trip_skeleton=skeleton,
    )

    assessment = assess_cross_day_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.affected_dates == (date(2026, 8, 1), date(2026, 8, 2))


def test_cross_unresolved_affected_dates_include_both_ends() -> None:
    skeleton = _skeleton((date(2026, 8, 1), UnresolvedAccommodation()))
    ctx = _ctx(
        _overnight_itinerary((_amap_activity(0),), (_amap_activity(1),)),
        trip_skeleton=skeleton,
    )

    assessment = assess_cross_day_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.affected_dates == (date(2026, 8, 1), date(2026, 8, 2))


def test_cross_confirmed_mismatch_affected_dates_include_both_ends() -> None:
    skeleton = _skeleton((date(2026, 8, 1), _confirmed()))
    ctx = _ctx(
        _overnight_itinerary((_amap_activity(0),), (_amap_activity(1),)),
        trip_skeleton=skeleton,
    )

    assessment = assess_cross_day_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.affected_dates == (date(2026, 8, 1), date(2026, 8, 2))


def test_cross_two_consecutive_boundaries_cover_all_three_days() -> None:
    skeleton = _skeleton(
        (date(2026, 8, 1), _confirmed()),
        (date(2026, 8, 2), _confirmed()),
    )
    itinerary = _itinerary(
        ((_amap_activity(0),), ()),
        ((_amap_activity(1),), ()),
        ((_amap_activity(2),), ()),
    )
    ctx = _ctx(itinerary, trip_skeleton=skeleton)

    assessment = assess_cross_day_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.affected_dates == (
        date(2026, 8, 1),
        date(2026, 8, 2),
        date(2026, 8, 3),
    )


def test_cross_no_skeleton_affected_dates_cover_itinerary() -> None:
    itinerary = _itinerary(
        ((_amap_activity(0),), ()),
        ((_amap_activity(1),), ()),
        ((_amap_activity(2),), ()),
    )
    ctx = _ctx(itinerary, trip_skeleton=None)

    assessment = assess_cross_day_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.reason_code == "TRIP_SKELETON_UNAVAILABLE"
    assert assessment.result.affected_dates == (
        date(2026, 8, 1),
        date(2026, 8, 2),
        date(2026, 8, 3),
    )


def test_cross_date_mismatch_affected_dates_cover_itinerary() -> None:
    skeleton = _skeleton((date(2026, 8, 1), _confirmed()))
    itinerary = Itinerary(
        title="Mismatch",
        days=(
            ItineraryDay(
                date=date(2026, 8, 2),
                activities=(_amap_activity(0),),
                transit_legs=(),
            ),
            ItineraryDay(
                date=date(2026, 8, 3),
                activities=(_amap_activity(1),),
                transit_legs=(),
            ),
        ),
        estimated_total_cost=Decimal("0"),
    )
    ctx = _ctx(itinerary, trip_skeleton=skeleton)

    assessment = assess_cross_day_continuity(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.reason_code == "TRIP_SKELETON_DATE_MISMATCH"
    assert assessment.result.affected_dates == (date(2026, 8, 2), date(2026, 8, 3))
