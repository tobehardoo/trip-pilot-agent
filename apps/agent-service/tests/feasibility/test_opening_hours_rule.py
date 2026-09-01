"""B5 Phase 4 — OPENING_HOURS canonical rule (reuses the resolver)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from plan_evaluation_support import make_command

from trip_agent.domain.shared import CHINA_TIME_ZONE
from trip_agent.feasibility.context import ValidationContext, build_budget_context
from trip_agent.feasibility.inputs import ActivityLocator, OpeningHoursBinding, ValidationInputs
from trip_agent.feasibility.models import EvidenceState, RuleOutcome
from trip_agent.feasibility.rules.opening import assess_opening_hours
from trip_agent.guide_intelligence.opening_evidence import OpeningHoursEvidence
from trip_agent.guide_intelligence.opening_hours import parse_opening_text
from trip_agent.worker.contracts import (
    ActivityCoordinates,
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
)

_TS = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
_DAY = date(2026, 8, 1)  # Saturday


def _evidence(
    poi_key: str,
    raw: str,
    *,
    eligible: bool = False,
    kind: str = "OPENING_HOURS",
    effective_date: date | None = None,
    source_ref: str = "official:1",
    expires: datetime = datetime(2026, 8, 15, tzinfo=UTC),
    scope: str | None = None,
    confidence: float | None = None,
) -> OpeningHoursEvidence:
    return OpeningHoursEvidence(
        kind=kind,  # type: ignore[arg-type]
        poi_key=poi_key,
        parsed_hours=parse_opening_text(raw, scope=scope),
        raw=raw,
        effective_date=effective_date,
        source_ref=source_ref,
        reliability_level="OFFICIAL" if eligible else "PROVIDER",
        source_reviewed=eligible,
        hard_constraint_eligible=eligible,
        confidence=confidence if confidence is not None else (0.9 if eligible else 0.7),
        checked_at=datetime(2026, 8, 1, tzinfo=UTC),
        expires_at=expires,
    )


def _activity(
    index: int,
    *,
    start_hour: int,
    start_minute: int = 0,
    start_second: int = 0,
    start_microsecond: int = 0,
    duration_minutes: int = 60,
    duration_seconds: int = 0,
    duration_microseconds: int = 0,
    kind: str = "ATTRACTION",
    poi: str = "POI-1",
    title: str = "A",
    day: int = 1,
    month: int = 8,
    year: int = 2026,
) -> ItineraryActivity:
    start = datetime(
        year,
        month,
        day,
        start_hour,
        start_minute,
        start_second,
        start_microsecond,
        tzinfo=CHINA_TIME_ZONE,
    )
    return ItineraryActivity(
        activity_id=UUID(int=index + 1),
        title=title,
        start_time=start,
        end_time=start
        + timedelta(
            minutes=duration_minutes,
            seconds=duration_seconds,
            microseconds=duration_microseconds,
        ),
        estimated_cost=Decimal("0"),
        source="AMAP",
        provider_poi_id=poi,
        coordinates=ActivityCoordinates(longitude=Decimal("113.31"), latitude=Decimal("23.13")),
        address="addr",
        kind=kind,  # type: ignore[arg-type]
    )


def _ctx(
    *activities: ItineraryActivity,
    bindings: tuple[OpeningHoursBinding, ...] = (),
    validation_time: datetime | None = _TS,
    day_date: date = _DAY,
) -> ValidationContext:
    command = make_command()
    itinerary = Itinerary(
        title="opening",
        days=(ItineraryDay(date=day_date, activities=activities, transit_legs=()),),
        estimated_total_cost=Decimal("0"),
    )
    return ValidationContext(
        command=command,
        itinerary=itinerary,
        budget=build_budget_context(command, itinerary),
        validation_inputs=ValidationInputs(
            opening_hours_bindings=bindings,
            meal_projection_state=__import__(
                "trip_agent.feasibility.inputs", fromlist=["MealProjectionState"]
            ).MealProjectionState.UNAVAILABLE,
        ),
        validation_time=validation_time,
    )


def _binding(
    day: int,
    activity: int,
    poi_key: str,
    *evidences: OpeningHoursEvidence,
) -> OpeningHoursBinding:
    return OpeningHoursBinding(
        activity=ActivityLocator(day_index=day, activity_index=activity),
        poi_key=poi_key,
        evidences=evidences,
    )


def test_no_applicable_activities_is_not_applicable() -> None:
    ctx = _ctx(
        _activity(0, start_hour=9, kind="ACCOMMODATION"),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.NOT_APPLICABLE
    assert assessment.result.reason_code == "NO_OPENING_HOURS_APPLICABLE_ACTIVITIES"


def test_missing_binding_is_unknown() -> None:
    ctx = _ctx(_activity(0, start_hour=10))

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.reason_code == "OPENING_BINDING_MISSING"


def test_daily_window_activity_inside_passes() -> None:
    ctx = _ctx(
        _activity(0, start_hour=10, duration_minutes=60),
        bindings=(_binding(0, 0, "POI-1", _evidence("POI-1", "09:00-18:00", eligible=True)),),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.PASS
    assert assessment.result.reason_code == "OPENING_HOURS_VERIFIED"


def test_daily_window_activity_outside_fails() -> None:
    ctx = _ctx(
        _activity(0, start_hour=19, duration_minutes=60),
        bindings=(_binding(0, 0, "POI-1", _evidence("POI-1", "09:00-18:00", eligible=True)),),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "ACTIVITY_OUTSIDE_OPENING_WINDOW"


def test_ineligible_verified_window_is_unknown() -> None:
    ctx = _ctx(
        _activity(0, start_hour=10),
        bindings=(_binding(0, 0, "POI-1", _evidence("POI-1", "09:00-18:00", eligible=False)),),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.reason_code == "OPENING_HOURS_UNVERIFIED"


def test_eligible_closure_fails() -> None:
    ctx = _ctx(
        _activity(0, start_hour=10),
        bindings=(_binding(0, 0, "POI-1", _evidence("POI-1", "闭馆", eligible=True)),),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "VENUE_CLOSED"


def test_ineligible_closure_is_unknown() -> None:
    ctx = _ctx(
        _activity(0, start_hour=10),
        bindings=(_binding(0, 0, "POI-1", _evidence("POI-1", "闭馆", eligible=False)),),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.reason_code == "OPENING_HOURS_UNVERIFIED"


def test_stale_evidence_is_unknown() -> None:
    ctx = _ctx(
        _activity(0, start_hour=10),
        bindings=(
            _binding(
                0,
                0,
                "POI-1",
                _evidence(
                    "POI-1", "09:00-18:00", eligible=True, expires=datetime(2026, 8, 1, tzinfo=UTC)
                ),
            ),
        ),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.reason_code == "OPENING_HOURS_UNVERIFIED"
    assert assessment.result.evidence_refs
    assert assessment.result.evidence_refs[0].state is EvidenceState.STALE


def test_weekly_positive_day_passes() -> None:
    ctx = _ctx(
        _activity(0, start_hour=10),
        bindings=(_binding(0, 0, "POI-1", _evidence("POI-1", "周六 09:00-18:00", eligible=True)),),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.PASS


def test_weekly_closed_weekday_is_unknown() -> None:
    ctx = _ctx(
        _activity(0, start_hour=10),
        bindings=(
            _binding(0, 0, "POI-1", _evidence("POI-1", "周一至周五 09:00-18:00", eligible=True)),
        ),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN


def test_today_evidence_matching_date_passes() -> None:
    ctx = _ctx(
        _activity(0, start_hour=10),
        bindings=(
            _binding(
                0,
                0,
                "POI-1",
                _evidence("POI-1", "09:00-18:00", eligible=True, effective_date=_DAY),
            ),
        ),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.PASS


def test_all_day_covers_activity() -> None:
    ctx = _ctx(
        _activity(0, start_hour=10, duration_minutes=300),
        bindings=(_binding(0, 0, "POI-1", _evidence("POI-1", "全天开放", eligible=True)),),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.PASS


def test_cross_midnight_window_passes() -> None:
    ctx = _ctx(
        _activity(0, start_hour=21, duration_minutes=60),
        bindings=(_binding(0, 0, "POI-1", _evidence("POI-1", "20:00-02:00", eligible=True)),),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.PASS


def test_multiple_windows_cannot_be_spliced() -> None:
    # 10:00-11:00 inside window 1, 13:00-14:00 inside window 2; a single
    # activity spanning 10:00-14:00 is NOT fully inside either window.
    ctx = _ctx(
        _activity(0, start_hour=10, duration_minutes=240),
        bindings=(
            _binding(0, 0, "POI-1", _evidence("POI-1", "09:00-12:00,13:00-18:00", eligible=True)),
        ),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "ACTIVITY_OUTSIDE_OPENING_WINDOW"


def test_last_entry_enforced() -> None:
    ctx = _ctx(
        _activity(0, start_hour=17, start_minute=30, duration_minutes=30),
        bindings=(
            _binding(
                0, 0, "POI-1", _evidence("POI-1", "09:00-18:00 (17:00停止入场)", eligible=True)
            ),
        ),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "ACTIVITY_AFTER_LAST_ENTRY"


def test_last_entry_boundary_allowed() -> None:
    # 17:00 start equals last entry -> allowed by the spec; start at 16:00
    # (before last entry) passes.
    ctx2 = _ctx(
        _activity(0, start_hour=16, duration_minutes=60),
        bindings=(
            _binding(
                0,
                0,
                "POI-1",
                _evidence("POI-1", "09:00-18:00 (17:00停止入场)", eligible=True),
            ),
        ),
    )

    assessment = assess_opening_hours(ctx2)

    assert assessment.result.outcome is RuleOutcome.PASS


def test_mixed_fail_and_unknown_fails() -> None:
    ctx = _ctx(
        _activity(0, start_hour=19, kind="ATTRACTION", poi="POI-1"),
        _activity(1, start_hour=10, kind="ATTRACTION", poi="POI-2"),
        bindings=(
            _binding(0, 0, "POI-1", _evidence("POI-1", "09:00-18:00", eligible=True)),
            _binding(0, 1, "POI-2", _evidence("POI-2", "09:00-18:00", eligible=False)),
        ),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "ACTIVITY_OUTSIDE_OPENING_WINDOW"


def test_unparseable_evidence_is_unknown() -> None:
    ctx = _ctx(
        _activity(0, start_hour=10),
        bindings=(_binding(0, 0, "POI-1", _evidence("POI-1", "随时欢迎", eligible=True)),),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.reason_code == "OPENING_HOURS_UNVERIFIED"


def test_evidence_refs_bounded_and_eligible_first() -> None:
    # 70 eligible + 70 ineligible evidences across 70 activities would need
    # 70 activities; simulate with many activities via one day.
    activities = tuple(
        _activity(index, start_hour=10, kind="ATTRACTION", poi=f"POI-{index}")
        for index in range(66)
    )
    bindings = tuple(
        _binding(
            0,
            index,
            f"POI-{index}",
            _evidence(f"POI-{index}", "09:00-18:00", eligible=index < 2),
        )
        for index in range(66)
    )
    ctx = _ctx(*activities, bindings=bindings)

    assessment = assess_opening_hours(ctx)

    assert len(assessment.result.evidence_refs) <= 64
    # eligible refs survive truncation
    assert assessment.result.evidence_refs[0].hard_constraint_eligible is True


def test_does_not_mutate_evidence() -> None:
    evidence = _evidence("POI-1", "09:00-18:00", eligible=True)
    before = (
        evidence.checked_at,
        evidence.expires_at,
        evidence.raw,
        evidence.confidence,
    )
    ctx = _ctx(
        _activity(0, start_hour=10),
        bindings=(_binding(0, 0, "POI-1", evidence),),
    )

    assess_opening_hours(ctx)

    assert (evidence.checked_at, evidence.expires_at, evidence.raw, evidence.confidence) == before


# ── B5.1 RED 1: month-end cross-midnight windows ───────────────────────────


@pytest.mark.parametrize(
    "year,month,day",
    [
        (2026, 1, 31),
        (2026, 4, 30),
        (2026, 12, 31),
        (2028, 2, 29),  # leap day -> March 1
    ],
)
def test_month_end_cross_midnight_window_passes(year: int, month: int, day: int) -> None:
    day_date = date(year, month, day)
    start = datetime(year, month, day, 23, 30, tzinfo=CHINA_TIME_ZONE)
    activity = ItineraryActivity(
        activity_id=UUID(int=1),
        title="Night",
        start_time=start,
        end_time=start + timedelta(hours=1),
        estimated_cost=Decimal("0"),
        source="AMAP",
        provider_poi_id="POI-1",
        coordinates=ActivityCoordinates(longitude=Decimal("113.31"), latitude=Decimal("23.13")),
        address="addr",
        kind="ATTRACTION",
    )
    ctx = _ctx(
        activity,
        day_date=day_date,
        bindings=(
            _binding(
                0,
                0,
                "POI-1",
                _evidence("POI-1", "20:00-02:00", eligible=True),
            ),
        ),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.PASS
    assert assessment.result.reason_code == "OPENING_HOURS_VERIFIED"


# ── B5.1 RED 2: exact time boundaries ──────────────────────────────────────


def test_opening_end_one_second_after_close_fails() -> None:
    ctx = _ctx(
        _activity(
            0,
            start_hour=17,
            start_minute=59,
            start_second=59,
            duration_minutes=0,
            duration_seconds=2,
        ),
        bindings=(_binding(0, 0, "POI-1", _evidence("POI-1", "09:00-18:00", eligible=True)),),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "ACTIVITY_OUTSIDE_OPENING_WINDOW"


def test_opening_end_exactly_at_close_passes() -> None:
    ctx = _ctx(
        _activity(0, start_hour=17, duration_minutes=60),
        bindings=(_binding(0, 0, "POI-1", _evidence("POI-1", "09:00-18:00", eligible=True)),),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.PASS


def test_opening_start_one_second_after_last_entry_fails() -> None:
    ctx = _ctx(
        _activity(0, start_hour=17, start_minute=0, start_second=1, duration_minutes=30),
        bindings=(
            _binding(
                0,
                0,
                "POI-1",
                _evidence("POI-1", "09:00-18:00 (17:00停止入场)", eligible=True),
            ),
        ),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "ACTIVITY_AFTER_LAST_ENTRY"


def test_opening_start_exactly_at_last_entry_passes() -> None:
    ctx = _ctx(
        _activity(0, start_hour=17, duration_minutes=60),
        bindings=(
            _binding(
                0,
                0,
                "POI-1",
                _evidence("POI-1", "09:00-18:00 (17:00停止入场)", eligible=True),
            ),
        ),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.PASS


def test_opening_microsecond_after_close_fails() -> None:
    ctx = _ctx(
        _activity(
            0,
            start_hour=17,
            start_minute=59,
            start_second=59,
            start_microsecond=999_000,
            duration_minutes=0,
            duration_seconds=1,
            duration_microseconds=2,
        ),
        bindings=(_binding(0, 0, "POI-1", _evidence("POI-1", "09:00-18:00", eligible=True)),),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL


def test_opening_cross_midnight_exact_end_at_close_passes() -> None:
    ctx = _ctx(
        _activity(
            0,
            start_hour=23,
            start_minute=59,
            start_second=59,
            duration_minutes=0,
            duration_seconds=2,
        ),
        bindings=(_binding(0, 0, "POI-1", _evidence("POI-1", "20:00-02:00", eligible=True)),),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.PASS


# ── B5.1 RED 3: evidence provenance from resolved verdicts ─────────────────


def test_conflicting_eligible_evidence_is_unknown_and_conflicting() -> None:
    evidence_a = _evidence("POI-1", "09:00-12:00", eligible=True, source_ref="official:a")
    evidence_b = _evidence("POI-1", "13:00-18:00", eligible=True, source_ref="official:b")
    ctx = _ctx(
        _activity(0, start_hour=10),
        bindings=(_binding(0, 0, "POI-1", evidence_a, evidence_b),),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    conflicting = [
        ref for ref in assessment.result.evidence_refs if ref.state is EvidenceState.CONFLICTING
    ]
    assert conflicting
    assert all(ref.hard_constraint_eligible is False for ref in conflicting)
    assert not any(ref.hard_constraint_eligible for ref in assessment.result.evidence_refs)


def test_unparseable_eligible_evidence_is_unknown_state() -> None:
    ctx = _ctx(
        _activity(0, start_hour=10),
        bindings=(
            _binding(
                0,
                0,
                "POI-1",
                _evidence("POI-1", "随时欢迎", eligible=True),
            ),
        ),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert all(ref.state is EvidenceState.UNKNOWN for ref in assessment.result.evidence_refs)
    assert all(ref.hard_constraint_eligible is False for ref in assessment.result.evidence_refs)


def test_effective_date_mismatch_never_shows_verified_eligible() -> None:
    # TODAY evidence bound to a different effective date -> resolver UNKNOWN.
    ctx = _ctx(
        _activity(0, start_hour=10),
        bindings=(
            _binding(
                0,
                0,
                "POI-1",
                _evidence(
                    "POI-1",
                    "09:00-18:00",
                    eligible=True,
                    effective_date=date(2026, 8, 2),
                    scope="TODAY",
                ),
            ),
        ),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert not any(
        ref.state is EvidenceState.VERIFIED and ref.hard_constraint_eligible
        for ref in assessment.result.evidence_refs
    )


def test_verified_window_keeps_verified_eligible_ref() -> None:
    ctx = _ctx(
        _activity(0, start_hour=10),
        bindings=(_binding(0, 0, "POI-1", _evidence("POI-1", "09:00-18:00", eligible=True)),),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.PASS
    assert any(
        ref.state is EvidenceState.VERIFIED and ref.hard_constraint_eligible
        for ref in assessment.result.evidence_refs
    )


def test_verified_closure_keeps_verified_eligible_ref() -> None:
    ctx = _ctx(
        _activity(0, start_hour=10),
        bindings=(_binding(0, 0, "POI-1", _evidence("POI-1", "闭馆", eligible=True)),),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert any(
        ref.state is EvidenceState.VERIFIED and ref.hard_constraint_eligible
        for ref in assessment.result.evidence_refs
    )


def test_mixed_verified_and_conflicting_refs_preserved() -> None:
    conflicting_evidence_a = _evidence(
        "POI-1", "09:00-12:00", eligible=True, source_ref="official:x"
    )
    conflicting_evidence_b = _evidence(
        "POI-1", "13:00-18:00", eligible=True, source_ref="official:y"
    )
    verified = _evidence("POI-2", "09:00-18:00", eligible=True, source_ref="official:z")
    ctx = _ctx(
        _activity(0, start_hour=10, poi="POI-1"),
        _activity(1, start_hour=10, poi="POI-2"),
        bindings=(
            _binding(0, 0, "POI-1", conflicting_evidence_a, conflicting_evidence_b),
            _binding(0, 1, "POI-2", verified),
        ),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert any(
        ref.state is EvidenceState.VERIFIED and ref.hard_constraint_eligible
        for ref in assessment.result.evidence_refs
    )
    assert any(
        ref.state is EvidenceState.CONFLICTING and not ref.hard_constraint_eligible
        for ref in assessment.result.evidence_refs
    )


def test_evidence_refs_deduped_and_bounded() -> None:
    evidence = _evidence("POI-1", "09:00-18:00", eligible=True)
    ctx = _ctx(
        _activity(0, start_hour=10),
        bindings=(_binding(0, 0, "POI-1", evidence, evidence),),
    )

    assessment = assess_opening_hours(ctx)

    ids = [ref.evidence_id for ref in assessment.result.evidence_refs]
    assert len(ids) == len(set(ids))
    assert len(ids) <= 64
    assert len(ids) == 1


# ── B5.2: temporary-closure eligibility basis in rule refs ────────────────


def test_temporary_closure_verified_ref_comes_from_eligible_basis() -> None:
    high_ineligible = _evidence(
        "POI-1",
        "临时闭馆",
        eligible=False,
        kind="TEMPORARY_CLOSURE",
        source_ref="official:high",
        confidence=0.99,
    )
    low_eligible = _evidence(
        "POI-1",
        "临时闭馆",
        eligible=True,
        kind="TEMPORARY_CLOSURE",
        source_ref="official:low",
        confidence=0.80,
    )
    ctx = _ctx(
        _activity(0, start_hour=10),
        bindings=(
            _binding(
                0,
                0,
                "POI-1",
                high_ineligible,
                low_eligible,
            ),
        ),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "VENUE_CLOSED"
    verified = [
        ref
        for ref in assessment.result.evidence_refs
        if ref.state is EvidenceState.VERIFIED and ref.hard_constraint_eligible
    ]
    assert verified, "must keep at least one VERIFIED/True basis"
    assert verified[0].evidence_id.endswith("official:low")
    high_ref = next(
        ref for ref in assessment.result.evidence_refs if ref.evidence_id.endswith("official:high")
    )
    assert high_ref.state is EvidenceState.UNKNOWN
    assert high_ref.hard_constraint_eligible is False


def test_all_ineligible_temporary_closures_yield_unknown() -> None:
    first = _evidence(
        "POI-1",
        "临时闭馆",
        eligible=False,
        kind="TEMPORARY_CLOSURE",
        source_ref="official:a",
        confidence=0.99,
    )
    second = _evidence(
        "POI-1",
        "临时闭馆",
        eligible=False,
        kind="TEMPORARY_CLOSURE",
        source_ref="official:b",
        confidence=0.80,
    )
    ctx = _ctx(
        _activity(0, start_hour=10),
        bindings=(_binding(0, 0, "POI-1", first, second),),
    )

    assessment = assess_opening_hours(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert all(
        ref.state is not EvidenceState.VERIFIED or not ref.hard_constraint_eligible
        for ref in assessment.result.evidence_refs
    )
    assert all(not ref.hard_constraint_eligible for ref in assessment.result.evidence_refs)


# ── B5.3: stable report across evidence order ──────────────────────────────


def test_same_confidence_closures_forward_backward_identical_report() -> None:
    def _assess(order: str):
        first = _evidence(
            "POI-1",
            "临时闭馆",
            eligible=True,
            kind="TEMPORARY_CLOSURE",
            source_ref="official:a",
            confidence=0.90,
        )
        second = _evidence(
            "POI-1",
            "临时闭馆",
            eligible=True,
            kind="TEMPORARY_CLOSURE",
            source_ref="official:b",
            confidence=0.90,
        )
        evidences = (first, second) if order == "forward" else (second, first)
        ctx = _ctx(
            _activity(0, start_hour=10),
            bindings=(_binding(0, 0, "POI-1", *evidences),),
        )
        return assess_opening_hours(ctx)

    forward = _assess("forward")
    backward = _assess("backward")

    assert forward.result.outcome is RuleOutcome.FAIL
    assert forward.result.reason_code == "VENUE_CLOSED"
    assert forward.result == backward.result
    assert [ref.evidence_id for ref in forward.result.evidence_refs] == [
        ref.evidence_id for ref in backward.result.evidence_refs
    ]
