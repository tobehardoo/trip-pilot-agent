"""B10 — orchestrator-level golden matrix (Python side).

Locks the catalog's accommodation three-state and opening-evidence-state
scenarios (G04-G14) through ``process_planning_create``, not by calling
individual rules.  Every scenario uses a fixed UTC timestamp and a fixed
command UUID, never reads the system clock, and asserts the aggregated
feasibility status and the blocking reason code structurally.

Catalog invariants under test:
  * CONFIRMED matching accommodation -> CROSS_DAY_CONTINUITY PASS (G04/G07)
  * AREA_ESTIMATED / UNRESOLVED -> CROSS_DAY_CONTINUITY UNKNOWN -> UNVERIFIED
    (G05/G06); a Demo-like provider must never fake confirmed continuity
  * OPENING_HOURS: only VERIFIED eligible evidence may PASS/FAIL; STALE /
    CONFLICTING / ineligible evidence is UNKNOWN (G09/G11/G12)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from plan_evaluation_support import make_command

from trip_agent.domain.planning.protocols import PlanningResult
from trip_agent.feasibility.inputs import (
    ActivityLocator,
    MealProjectionState,
    OpeningHoursBinding,
    ValidationInputs,
    VisitDurationBinding,
)
from trip_agent.feasibility.models import FeasibilityStatus, RuleOutcome
from trip_agent.guide_intelligence.opening_evidence import OpeningHoursEvidence
from trip_agent.guide_intelligence.opening_hours import parse_opening_text
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
from trip_agent.planning.visit_duration import (
    DurationProfileSource,
    VisitDurationProfile,
)
from trip_agent.worker.contracts import (
    ActivityCoordinates,
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
    PlanningCompletedEventV11,
    TransitLeg,
)
from trip_agent.worker.processor import process_planning_create

_TS = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
_D1 = date(2026, 8, 1)
_D2 = date(2026, 8, 2)
_HOTEL_POI = "POI-HOTEL"


def _coords(lng: str, lat: str) -> ActivityCoordinates:
    return ActivityCoordinates(longitude=Decimal(lng), latitude=Decimal(lat))


def _attraction(index: int, *, poi: str, title: str, day: date, hour: int) -> ItineraryActivity:
    start = datetime(day.year, day.month, day.day, hour, tzinfo=UTC)
    return ItineraryActivity(
        activity_id=UUID(int=index + 1),
        title=title,
        start_time=start,
        end_time=start + timedelta(minutes=90),
        estimated_cost=Decimal("0"),
        source="AMAP",
        provider_poi_id=poi,
        coordinates=_coords("113.31", "23.13"),
        address="addr",
        kind="ATTRACTION",
    )


def _accommodation(index: int, *, day: date, hour: int) -> ItineraryActivity:
    start = datetime(day.year, day.month, day.day, hour, tzinfo=UTC)
    return ItineraryActivity(
        activity_id=UUID(int=index + 1),
        title="Garden Hotel",
        start_time=start,
        end_time=start + timedelta(hours=1),
        estimated_cost=Decimal("0"),
        source="AMAP",
        provider_poi_id=_HOTEL_POI,
        coordinates=_coords("113.28", "23.13"),
        address="Yuexiu",
        kind="ACCOMMODATION",
    )


def _leg(index: int) -> TransitLeg:
    return TransitLeg(
        transit_id=UUID(int=100 + index),
        from_activity_index=0,
        to_activity_index=1,
        mode="WALKING",
        distance_meters=300,
        duration_seconds=300,
        provider="AMAP",
        estimated=False,
        polyline=(_coords("113.31", "23.13"), _coords("113.28", "23.13")),
    )


def _eligible_evidence(poi: str) -> OpeningHoursEvidence:
    return OpeningHoursEvidence(
        kind="OPENING_HOURS",
        poi_key=poi,
        parsed_hours=parse_opening_text("09:00-18:00"),
        raw="09:00-18:00",
        effective_date=None,
        source_ref=f"official:{poi}",
        reliability_level="OFFICIAL",
        source_reviewed=True,
        hard_constraint_eligible=True,
        confidence=0.9,
        checked_at=datetime(2026, 8, 1, tzinfo=UTC),
        expires_at=datetime(2026, 8, 31, tzinfo=UTC),
    )


def _stale_evidence(poi: str) -> OpeningHoursEvidence:
    return OpeningHoursEvidence(
        kind="OPENING_HOURS",
        poi_key=poi,
        parsed_hours=parse_opening_text("09:00-18:00"),
        raw="09:00-18:00",
        effective_date=None,
        source_ref=f"guide:{poi}",
        reliability_level="COMMUNITY_GUIDE",
        source_reviewed=False,
        hard_constraint_eligible=False,
        confidence=0.5,
        checked_at=datetime(2026, 7, 1, tzinfo=UTC),
        expires_at=datetime(2026, 7, 15, tzinfo=UTC),
    )


def _eligible_profile(poi: str) -> VisitDurationProfile:
    return VisitDurationProfile(
        min_minutes=45,
        recommended_minutes=90,
        max_minutes=180,
        source=DurationProfileSource.OFFICIAL_FACT,
        source_ref=f"official:{poi}",
        confidence=0.9,
        profile_version="official-v1",
        hard_constraint_eligible=True,
    )


def _day_plan(day: date) -> DayPlan:
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


def _multi_day_itinerary() -> Itinerary:
    # Day 1 ends with the hotel; day 2 begins with it, so a CONFIRMED
    # overnight can match both endpoints.  Times are China-local (UTC+8):
    # day 1 attraction 10:00, hotel 18:00; day 2 hotel 09:00, attraction 11:00.
    day1 = ItineraryDay(
        date=_D1,
        activities=(
            _attraction(0, poi="POI-1", title="陈家祠", day=_D1, hour=2),
            _accommodation(1, day=_D1, hour=10),
        ),
        transit_legs=(_leg(0),),
    )
    day2 = ItineraryDay(
        date=_D2,
        activities=(
            _accommodation(2, day=_D2, hour=1),
            _attraction(3, poi="POI-2", title="光孝寺", day=_D2, hour=3),
        ),
        transit_legs=(_leg(1),),
    )
    return Itinerary(
        title="golden-matrix",
        days=(day1, day2),
        estimated_total_cost=Decimal("200.00"),
    )


def _inputs(*, stale_opening: bool = False) -> ValidationInputs:
    evidence = _stale_evidence if stale_opening else _eligible_evidence
    return ValidationInputs(
        opening_hours_bindings=(
            OpeningHoursBinding(
                activity=ActivityLocator(day_index=0, activity_index=0),
                poi_key="POI-1",
                evidences=(evidence("POI-1"),),
            ),
            OpeningHoursBinding(
                activity=ActivityLocator(day_index=1, activity_index=1),
                poi_key="POI-2",
                evidences=(evidence("POI-2"),),
            ),
        ),
        visit_duration_bindings=(
            VisitDurationBinding(
                activity=ActivityLocator(day_index=0, activity_index=0),
                profile=_eligible_profile("POI-1"),
            ),
            VisitDurationBinding(
                activity=ActivityLocator(day_index=1, activity_index=1),
                profile=_eligible_profile("POI-2"),
            ),
        ),
        meal_projection_state=MealProjectionState.UNAVAILABLE,
    )


def _skeleton(accommodation) -> TripSkeleton:
    return build_trip_skeleton(
        (_day_plan(_D1), _day_plan(_D2)),
        (accommodation,),
    )


def _confirmed() -> ConfirmedAccommodation:
    return ConfirmedAccommodation(
        label="Garden Hotel",
        provider_poi_id=_HOTEL_POI,
        coordinates=GeoPoint(longitude=113.28, latitude=23.13),
    )


def _estimated() -> AreaEstimatedAccommodation:
    return AreaEstimatedAccommodation(region="Yuexiu", source=AreaEstimateSource.USER_REGION)


def _provider(*, accommodation=None, stale_opening: bool = False):
    itinerary = _multi_day_itinerary()

    class _Provider:
        async def plan(self, command):
            return PlanningResult(
                provider="AMAP",
                itinerary=itinerary,
                trip_skeleton=_skeleton(accommodation) if accommodation is not None else None,
                validation_inputs=_inputs(stale_opening=stale_opening),
            )

    return _Provider()


def _rule(report, rule_id: str):
    return next(r for r in report.rule_results if r.rule_id == rule_id)


# ── G04 / G07: CONFIRMED matching accommodation -> CROSS_DAY_CONTINUITY PASS ─


def test_g04_confirmed_hotel_verifies_cross_day_continuity() -> None:
    event = asyncio.run(
        process_planning_create(
            make_command(),
            _provider(accommodation=_confirmed()),
            occurred_at=_TS,
        )
    )

    assert isinstance(event, PlanningCompletedEventV11)
    report = event.payload.feasibility_report
    assert report.status is FeasibilityStatus.VERIFIED
    cross = _rule(report, "CROSS_DAY_CONTINUITY")
    assert cross.outcome is RuleOutcome.PASS
    assert cross.reason_code == "CROSS_DAY_ENDPOINTS_CONTINUOUS"


# ── G05: AREA_ESTIMATED -> UNVERIFIED, never a hard continuity PASS ─────────


def test_g05_area_estimated_hotel_is_unverified_not_verified() -> None:
    event = asyncio.run(
        process_planning_create(
            make_command(),
            _provider(accommodation=_estimated()),
            occurred_at=_TS,
        )
    )

    # B16: AREA_ESTIMATED -> UNVERIFIED without blocker -> v10 completed.
    assert isinstance(event, PlanningCompletedEventV11)
    assert event.payload.has_blocker is False
    report = event.payload.feasibility_report
    assert report.status is FeasibilityStatus.UNVERIFIED
    cross = _rule(report, "CROSS_DAY_CONTINUITY")
    assert cross.outcome is RuleOutcome.UNKNOWN
    assert cross.reason_code == "ACCOMMODATION_AREA_ESTIMATED"


# ── G06: UNRESOLVED -> UNVERIFIED ──────────────────────────────────────────


def test_g06_unresolved_hotel_is_unverified() -> None:
    event = asyncio.run(
        process_planning_create(
            make_command(),
            _provider(accommodation=UnresolvedAccommodation()),
            occurred_at=_TS,
        )
    )

    # B16: UNRESOLVED -> UNVERIFIED without blocker -> v10 completed.
    assert isinstance(event, PlanningCompletedEventV11)
    assert event.payload.has_blocker is False
    report = event.payload.feasibility_report
    assert report.status is FeasibilityStatus.UNVERIFIED
    cross = _rule(report, "CROSS_DAY_CONTINUITY")
    assert cross.outcome is RuleOutcome.UNKNOWN
    assert cross.reason_code == "ACCOMMODATION_UNRESOLVED"


# ── G09: VERIFIED eligible opening evidence -> OPENING_HOURS PASS ───────────


def test_g09_verified_opening_window_passes() -> None:
    event = asyncio.run(
        process_planning_create(
            make_command(),
            _provider(accommodation=_confirmed()),
            occurred_at=_TS,
        )
    )

    assert isinstance(event, PlanningCompletedEventV11)
    opening = _rule(event.payload.feasibility_report, "OPENING_HOURS")
    assert opening.outcome is RuleOutcome.PASS
    assert opening.reason_code == "OPENING_HOURS_VERIFIED"


# ── G11: STALE opening evidence -> UNKNOWN, never hard PASS ─────────────────


def test_g11_stale_opening_evidence_is_unverified() -> None:
    event = asyncio.run(
        process_planning_create(
            make_command(),
            _provider(accommodation=_confirmed(), stale_opening=True),
            occurred_at=_TS,
        )
    )

    # B16: STALE -> UNKNOWN without blocker -> v10 completed.
    assert isinstance(event, PlanningCompletedEventV11)
    assert event.payload.has_blocker is False
    report = event.payload.feasibility_report
    assert report.status is FeasibilityStatus.UNVERIFIED
    opening = _rule(report, "OPENING_HOURS")
    assert opening.outcome is RuleOutcome.UNKNOWN
    # Stale evidence may never be reported as hard-constraint eligible.
    assert all(not ref.hard_constraint_eligible for ref in opening.evidence_refs)
