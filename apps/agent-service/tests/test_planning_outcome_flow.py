"""B6 — worker runtime outcome wiring: VERIFIED -> v9, else -> review v1."""

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
from trip_agent.feasibility.models import FeasibilityStatus
from trip_agent.guide_intelligence.opening_evidence import OpeningHoursEvidence
from trip_agent.guide_intelligence.opening_hours import parse_opening_text
from trip_agent.planning.visit_duration import (
    DurationProfileSource,
    VisitDurationProfile,
)
from trip_agent.worker.contracts import (
    ActivityCoordinates,
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
    PlanningCompletedEventV9,
    PlanningReviewRequiredEvent,
    TransitLeg,
)
from trip_agent.worker.processor import process_planning_create

_TS = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
_DAY = date(2026, 8, 1)


def _amap_activity(index: int, *, poi: str, title: str, start_hour: int = 10) -> ItineraryActivity:
    start = datetime(2026, 8, 1, start_hour, tzinfo=UTC)
    return ItineraryActivity(
        activity_id=UUID(int=index + 1),
        title=title,
        start_time=start,
        end_time=start + timedelta(minutes=60),
        estimated_cost=Decimal("0"),
        source="AMAP",
        provider_poi_id=poi,
        coordinates=ActivityCoordinates(longitude=Decimal("113.31"), latitude=Decimal("23.13")),
        address="addr",
        kind="ATTRACTION",
    )


def _leg() -> TransitLeg:
    return TransitLeg(
        transit_id=UUID(int=100),
        from_activity_index=0,
        to_activity_index=1,
        mode="WALKING",
        distance_meters=300,
        duration_seconds=300,
        provider="AMAP",
        estimated=False,
        polyline=(
            ActivityCoordinates(longitude=Decimal("113.31"), latitude=Decimal("23.13")),
            ActivityCoordinates(longitude=Decimal("113.32"), latitude=Decimal("23.14")),
        ),
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


def _eligible_profile(poi: str) -> VisitDurationProfile:
    return VisitDurationProfile(
        min_minutes=45,
        recommended_minutes=90,
        max_minutes=120,
        source=DurationProfileSource.OFFICIAL_FACT,
        source_ref=f"official:{poi}",
        confidence=0.9,
        profile_version="official-v1",
        hard_constraint_eligible=True,
    )


def _verified_result() -> PlanningResult:
    activities = (
        _amap_activity(0, poi="POI-1", title="陈家祠", start_hour=2),
        _amap_activity(1, poi="POI-2", title="光孝寺", start_hour=5),
    )
    itinerary = Itinerary(
        title="verified",
        days=(ItineraryDay(date=_DAY, activities=activities, transit_legs=(_leg(),)),),
        estimated_total_cost=Decimal("100.00"),
    )
    inputs = ValidationInputs(
        opening_hours_bindings=(
            OpeningHoursBinding(
                activity=ActivityLocator(day_index=0, activity_index=0),
                poi_key="POI-1",
                evidences=(_eligible_evidence("POI-1"),),
            ),
            OpeningHoursBinding(
                activity=ActivityLocator(day_index=0, activity_index=1),
                poi_key="POI-2",
                evidences=(_eligible_evidence("POI-2"),),
            ),
        ),
        visit_duration_bindings=(
            VisitDurationBinding(
                activity=ActivityLocator(day_index=0, activity_index=0),
                profile=_eligible_profile("POI-1"),
            ),
            VisitDurationBinding(
                activity=ActivityLocator(day_index=0, activity_index=1),
                profile=_eligible_profile("POI-2"),
            ),
        ),
        meal_projection_state=MealProjectionState.UNAVAILABLE,
    )
    return PlanningResult(
        provider="AMAP",
        itinerary=itinerary,
        trip_skeleton=None,
        validation_inputs=inputs,
    )


class _VerifiedProvider:
    async def plan(self, command):
        return _verified_result()


class _DemoProvider:
    async def plan(self, command):
        from trip_agent.infrastructure.demo.planning_provider import DemoPlanningProvider

        return await DemoPlanningProvider().plan(command)


def test_verified_create_emits_v9_completion() -> None:
    command = make_command(must_visit_places=("陈家祠", "光孝寺"))

    event = asyncio.run(process_planning_create(command, _VerifiedProvider(), occurred_at=_TS))

    assert isinstance(event, PlanningCompletedEventV9)
    assert event.schema_version == 9
    assert event.occurred_at == _TS
    assert event.payload.feasibility_report.status is FeasibilityStatus.VERIFIED
    assert event.payload.feasibility_report.validated_at == _TS


def test_unverified_create_emits_review_required() -> None:
    command = make_command()

    event = asyncio.run(process_planning_create(command, _DemoProvider(), occurred_at=_TS))

    assert isinstance(event, PlanningReviewRequiredEvent)
    assert event.schema_version == 1
    assert event.payload.status == "WAITING_USER"
    assert event.payload.feasibility_report.status is FeasibilityStatus.UNVERIFIED
    assert event.occurred_at == _TS
    assert event.payload.feasibility_report.validated_at == _TS
    assert not hasattr(event.payload, "evaluation")


def test_report_id_is_stable_across_retries() -> None:
    command = make_command(must_visit_places=("陈家祠", "光孝寺"))

    first = asyncio.run(process_planning_create(command, _VerifiedProvider(), occurred_at=_TS))
    second = asyncio.run(process_planning_create(command, _VerifiedProvider(), occurred_at=_TS))

    assert isinstance(first, PlanningCompletedEventV9)
    assert isinstance(second, PlanningCompletedEventV9)
    assert first.payload.feasibility_report.report_id == (
        second.payload.feasibility_report.report_id
    )


def test_demo_create_is_review_not_failure() -> None:
    command = make_command()

    event = asyncio.run(process_planning_create(command, _DemoProvider(), occurred_at=_TS))

    assert isinstance(event, PlanningReviewRequiredEvent)
    assert event.payload.feasibility_report.status is not FeasibilityStatus.VERIFIED


# ── B6.1: real FAIL outcome + evaluator invocation + fingerprint binding ────


class _FailingProvider:
    """Provider whose itinerary trips a hard rule (route leg missing)."""

    async def plan(self, command):
        activities = (
            _amap_activity(0, poi="POI-1", title="陈家祠", start_hour=2),
            _amap_activity(1, poi="POI-2", title="光孝寺", start_hour=5),
        )
        itinerary = Itinerary(
            title="failing",
            days=(ItineraryDay(date=_DAY, activities=activities, transit_legs=()),),
            estimated_total_cost=Decimal("100.00"),
        )
        return PlanningResult(provider="AMAP", itinerary=itinerary)


def test_hard_fail_emits_needs_repair_review() -> None:
    command = make_command()

    event = asyncio.run(process_planning_create(command, _FailingProvider(), occurred_at=_TS))

    assert isinstance(event, PlanningReviewRequiredEvent)
    assert event.payload.feasibility_report.status.value == "NEEDS_REPAIR"
    assert not hasattr(event.payload, "evaluation")


def test_evaluator_called_only_when_verified(monkeypatch) -> None:
    import trip_agent.worker.processor as processor_module

    calls = []
    real_evaluator = processor_module.get_plan_evaluator()

    class _SpyEvaluator:
        def evaluate(self, command, result):
            calls.append(1)
            return real_evaluator.evaluate(command, result)

    monkeypatch.setattr(processor_module, "get_plan_evaluator", lambda: _SpyEvaluator())

    verified = asyncio.run(
        process_planning_create(
            make_command(must_visit_places=("陈家祠", "光孝寺")),
            _VerifiedProvider(),
            occurred_at=_TS,
        )
    )
    assert isinstance(verified, PlanningCompletedEventV9)
    assert len(calls) == 1

    calls.clear()
    review = asyncio.run(process_planning_create(make_command(), _DemoProvider(), occurred_at=_TS))
    assert isinstance(review, PlanningReviewRequiredEvent)
    assert len(calls) == 0

    calls.clear()
    repair = asyncio.run(
        process_planning_create(make_command(), _FailingProvider(), occurred_at=_TS)
    )
    assert isinstance(repair, PlanningReviewRequiredEvent)
    assert len(calls) == 0


def test_worker_report_fingerprint_matches_payload_itinerary() -> None:
    from trip_agent.feasibility.fingerprint import compute_itinerary_fingerprint

    verified = asyncio.run(
        process_planning_create(
            make_command(must_visit_places=("陈家祠", "光孝寺")),
            _VerifiedProvider(),
            occurred_at=_TS,
        )
    )
    assert isinstance(verified, PlanningCompletedEventV9)
    assert (
        verified.payload.feasibility_report.itinerary_fingerprint
        == compute_itinerary_fingerprint(verified.payload.itinerary)
    )

    review = asyncio.run(process_planning_create(make_command(), _DemoProvider(), occurred_at=_TS))
    assert isinstance(review, PlanningReviewRequiredEvent)
    assert review.payload.feasibility_report.itinerary_fingerprint == compute_itinerary_fingerprint(
        review.payload.itinerary
    )
