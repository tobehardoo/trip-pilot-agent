"""B6 — worker runtime outcome wiring: no blocker -> v10 completed, else -> review v1."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from plan_evaluation_support import make_command

from trip_agent.domain.planning.protocols import PlanningProviderError, PlanningResult
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
    PlanningCompletedEventV11,
    PlanningReviewRequiredEventV2,
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


def test_verified_create_emits_v10_completion() -> None:
    command = make_command(
        must_visit_places=("陈家祠", "光孝寺"),
        start_date="2026-08-01",
        end_date="2026-08-01",
    )

    event = asyncio.run(process_planning_create(command, _VerifiedProvider(), occurred_at=_TS))

    assert isinstance(event, PlanningCompletedEventV11)
    assert event.schema_version == 11
    assert event.occurred_at == _TS
    assert event.payload.feasibility_report.status is FeasibilityStatus.VERIFIED
    assert event.payload.has_blocker is False
    assert event.payload.feasibility_report.validated_at == _TS
    assert event.payload.feasibility_report.repair_attempts == ()


def test_unverified_create_emits_savable_v10_completion() -> None:
    command = make_command()

    event = asyncio.run(process_planning_create(command, _DemoProvider(), occurred_at=_TS))

    # B16: UNVERIFIED without blocker is a savable completion, not a review.
    assert isinstance(event, PlanningCompletedEventV11)
    assert event.schema_version == 11
    assert event.payload.has_blocker is False
    assert event.payload.feasibility_report.status is FeasibilityStatus.UNVERIFIED
    assert event.occurred_at == _TS
    assert event.payload.feasibility_report.validated_at == _TS


def test_report_id_is_stable_across_retries() -> None:
    command = make_command(
        must_visit_places=("陈家祠", "光孝寺"),
        start_date="2026-08-01",
        end_date="2026-08-01",
    )

    first = asyncio.run(process_planning_create(command, _VerifiedProvider(), occurred_at=_TS))
    second = asyncio.run(process_planning_create(command, _VerifiedProvider(), occurred_at=_TS))

    assert isinstance(first, PlanningCompletedEventV11)
    assert isinstance(second, PlanningCompletedEventV11)
    assert first.payload.feasibility_report.report_id == (
        second.payload.feasibility_report.report_id
    )


def test_demo_create_is_completed_not_failure() -> None:
    command = make_command()

    event = asyncio.run(process_planning_create(command, _DemoProvider(), occurred_at=_TS))

    # B16: demo (UNVERIFIED, no blocker) -> savable v10 completed, never a failure.
    assert isinstance(event, PlanningCompletedEventV11)
    assert event.payload.has_blocker is False
    assert event.payload.feasibility_report.status is not FeasibilityStatus.VERIFIED


# ── B6.1: real FAIL outcome + evaluator invocation + fingerprint binding ────


class _FailingProvider:
    """Provider whose itinerary trips a hard rule (route leg missing)."""

    def __init__(self) -> None:
        self.repair_calls = 0

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

    async def repair(self, request):
        self.repair_calls += 1
        return request.candidate


class _RepairingDurationProvider:
    def __init__(self, *, make_progress: bool = True) -> None:
        self.repair_calls = 0
        self.make_progress = make_progress

    async def plan(self, command):
        result = _verified_result()
        first = result.itinerary.days[0].activities[0]
        short = first.model_copy(
            update={"end_time": first.start_time + timedelta(minutes=20)}
        )
        day = result.itinerary.days[0].model_copy(
            update={"activities": (short, result.itinerary.days[0].activities[1])}
        )
        itinerary = result.itinerary.model_copy(update={"days": (day,)})
        return PlanningResult(
            provider="AMAP",
            itinerary=itinerary,
            validation_inputs=result.validation_inputs,
        )

    async def repair(self, request):
        self.repair_calls += 1
        if not self.make_progress:
            return request.candidate
        return PlanningResult(
            provider=request.candidate.provider,
            itinerary=request.candidate.itinerary,
            validation_inputs=request.candidate.validation_inputs,
        )


class _ThreeRoundProvider(_FailingProvider):
    async def repair(self, request):
        self.repair_calls += 1
        day = request.candidate.itinerary.days[0]
        first = day.activities[0].model_copy(
            update={"activity_id": UUID(int=1000 + self.repair_calls)}
        )
        itinerary = request.candidate.itinerary.model_copy(
            update={
                "days": (
                    day.model_copy(update={"activities": (first, day.activities[1])}),
                )
            }
        )
        return PlanningResult(provider="AMAP", itinerary=itinerary)


class _ProviderFailureDuringRepair(_FailingProvider):
    async def repair(self, request):
        self.repair_calls += 1
        raise PlanningProviderError("PROVIDER_UNAVAILABLE")


def test_one_local_repair_revalidates_to_verified_completion() -> None:
    provider = _RepairingDurationProvider()

    event = asyncio.run(
        process_planning_create(
            make_command(
                must_visit_places=("陈家祠", "光孝寺"),
                start_date="2026-08-01",
                end_date="2026-08-01",
            ),
            provider,
            occurred_at=_TS,
        )
    )

    assert isinstance(event, PlanningCompletedEventV11)
    assert provider.repair_calls == 0
    assert len(event.payload.feasibility_report.repair_attempts) == 1
    assert event.payload.feasibility_report.repair_attempts[0].action_codes == (
        "CLAMP_VISIT_DURATION",
    )
    assert event.payload.itinerary.days[0].activities[0].end_time == (
        event.payload.itinerary.days[0].activities[0].start_time
        + timedelta(minutes=45)
    )


def test_no_progress_stops_after_one_attempt_and_reviews() -> None:
    provider = _FailingProvider()

    event = asyncio.run(
        process_planning_create(
            make_command(start_date="2026-08-01", end_date="2026-08-01"),
            provider,
            occurred_at=_TS,
        )
    )

    assert isinstance(event, PlanningReviewRequiredEventV2)
    assert provider.repair_calls == 1
    assert len(event.payload.feasibility_report.repair_attempts) == 1
    attempt = event.payload.feasibility_report.repair_attempts[0]
    assert attempt.action_codes == ("REFRESH_TRANSIT_LEGS",)
    assert attempt.before_fingerprint == attempt.after_fingerprint


def test_repair_runtime_stops_at_three_attempts_and_preserves_history() -> None:
    provider = _ThreeRoundProvider()

    event = asyncio.run(
        process_planning_create(
            make_command(start_date="2026-08-01", end_date="2026-08-01"),
            provider,
            occurred_at=_TS,
        )
    )

    assert isinstance(event, PlanningReviewRequiredEventV2)
    assert provider.repair_calls == 3
    attempts = event.payload.feasibility_report.repair_attempts
    assert tuple(attempt.attempt_index for attempt in attempts) == (1, 2, 3)
    assert all(attempt.action_codes == ("REFRESH_TRANSIT_LEGS",) for attempt in attempts)
    assert len({attempt.after_fingerprint for attempt in attempts}) == 3


def test_provider_failure_during_repair_is_not_hidden_as_review() -> None:
    provider = _ProviderFailureDuringRepair()

    with pytest.raises(PlanningProviderError) as captured:
        asyncio.run(
            process_planning_create(
                make_command(start_date="2026-08-01", end_date="2026-08-01"),
                provider,
                occurred_at=_TS,
            )
        )

    assert captured.value.details.error_code == "PROVIDER_UNAVAILABLE"
    assert provider.repair_calls == 1


def test_hard_fail_emits_needs_repair_review() -> None:
    command = make_command(start_date="2026-08-01", end_date="2026-08-01")

    event = asyncio.run(process_planning_create(command, _FailingProvider(), occurred_at=_TS))

    assert isinstance(event, PlanningReviewRequiredEventV2)
    assert event.payload.feasibility_report.status.value == "NEEDS_REPAIR"
    assert not hasattr(event.payload, "evaluation")


def test_evaluator_called_for_savable_outcomes_only(monkeypatch) -> None:
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
            make_command(
                must_visit_places=("陈家祠", "光孝寺"),
                start_date="2026-08-01",
                end_date="2026-08-01",
            ),
            _VerifiedProvider(),
            occurred_at=_TS,
        )
    )
    assert isinstance(verified, PlanningCompletedEventV11)
    assert len(calls) == 1

    calls.clear()
    # B16: UNVERIFIED without blocker is a savable completion -> evaluated.
    savable = asyncio.run(process_planning_create(make_command(), _DemoProvider(), occurred_at=_TS))
    assert isinstance(savable, PlanningCompletedEventV11)
    assert savable.payload.has_blocker is False
    assert len(calls) == 1

    calls.clear()
    # A blocker report (FAIL present) routes to review and is never evaluated.
    repair = asyncio.run(
        process_planning_create(
            make_command(start_date="2026-08-01", end_date="2026-08-01"),
            _FailingProvider(),
            occurred_at=_TS,
        )
    )
    assert isinstance(repair, PlanningReviewRequiredEventV2)
    assert repair.payload.feasibility_report.has_blocker is True
    assert len(calls) == 0


def test_worker_report_fingerprint_matches_payload_itinerary() -> None:
    from trip_agent.feasibility.fingerprint import compute_itinerary_fingerprint

    verified = asyncio.run(
        process_planning_create(
            make_command(
                must_visit_places=("陈家祠", "光孝寺"),
                start_date="2026-08-01",
                end_date="2026-08-01",
            ),
            _VerifiedProvider(),
            occurred_at=_TS,
        )
    )
    assert isinstance(verified, PlanningCompletedEventV11)
    assert (
        verified.payload.feasibility_report.itinerary_fingerprint
        == compute_itinerary_fingerprint(verified.payload.itinerary)
    )

    savable = asyncio.run(process_planning_create(make_command(), _DemoProvider(), occurred_at=_TS))
    assert isinstance(savable, PlanningCompletedEventV11)
    assert (
        savable.payload.feasibility_report.itinerary_fingerprint
        == compute_itinerary_fingerprint(savable.payload.itinerary)
    )
