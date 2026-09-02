"""V2 P1-A — pace must have a real, observable effect on the day's load.

Audit §5.3 measured the largest functional gap: RELAXED and BALANCED produced
identical days in every tested scenario ("想轻松一点" was an invalid input).
The fix reserves deliberate slack inside every sightseeing slot for RELAXED
(the same capacity-discount mechanism the mobility-reduced path uses), which
shrinks the day's load without touching reserved meal times.

Counterfactual discipline (audit §22): every assertion below pins a *change*
against BALANCED on the audited fixture classes — never mere presence.
"""

from datetime import date

from trip_agent.planning.daily_schedule import (
    CandidateActivity,
    plan_day,
)
from trip_agent.planning.visit_duration import (
    DurationProfileSource,
    VisitDurationProfile,
)

_CATEGORY_VERSION = "category-profile-v1"
_TRIP_DATE = date(2026, 8, 1)


def _profile(minutes: int) -> VisitDurationProfile:
    return VisitDurationProfile(
        max(30, minutes - 60),
        minutes,
        minutes + 30,
        DurationProfileSource.CATEGORY_PROFILE,
        source_ref="category:probe",
        confidence=0.5,
        profile_version=_CATEGORY_VERSION,
    )


def _candidates(magnitude: str, minutes: int) -> tuple[CandidateActivity, ...]:
    """Sufficient pool (8 candidates) of one magnitude, as in audit §5.3."""
    return tuple(
        CandidateActivity(
            poi_id=f"poi-{index}",
            title=f"景点{index}",
            magnitude=magnitude,
            coordinates=(110.0 + index / 100, 20.0),
            region="越秀区",
            must_include=False,
            kind="ATTRACTION",
            score=50,
            visit_duration_profile=_profile(minutes),
        )
        for index in range(1, 9)
    )


def _plan(pace: str, candidates: tuple[CandidateActivity, ...]):
    day = plan_day(
        trip_date=_TRIP_DATE,
        start_date=_TRIP_DATE,
        end_date=_TRIP_DATE,
        arrival=None,
        departure=None,
        accommodation_known=False,
        candidates=candidates,
        pace=pace,
    )
    attractions = sum(
        1 for item in day.items if item.kind in {"ATTRACTION", "EXPERIENCE"}
    )
    meals = sum(1 for item in day.items if item.kind == "MEAL")
    return attractions, meals


def test_relaxed_carries_fewer_normal_activities_than_balanced() -> None:
    pool = _candidates("NORMAL", 150)
    relaxed = _plan("RELAXED", pool)
    balanced = _plan("BALANCED", pool)

    assert balanced == (2, 2), "audit baseline: BALANCED fits two 150-min visits"
    assert relaxed[0] < balanced[0], "RELAXED must lighten the day (AC-5)"
    # Reserved meal time is planning-owned and must survive the discount.
    assert relaxed[1] == balanced[1] == 2


def test_relaxed_carries_fewer_light_activities_than_balanced() -> None:
    pool = _candidates("LIGHT", 90)
    relaxed = _plan("RELAXED", pool)
    balanced = _plan("BALANCED", pool)

    # 功能③（2026-09）默认日终 09:00–21:00 后，BALANCED 可多排两场 90 分钟游览。
    assert balanced == (5, 2), "baseline: BALANCED fits five 90-min visits in the 21:00 window"
    assert relaxed[0] < balanced[0], "RELAXED must lighten the day (AC-5)"
    assert relaxed[1] == balanced[1] == 2


def test_intensive_day_end_and_load_are_unchanged() -> None:
    """INTENSIVE already differentiated (20:00 end); its load must not move."""
    normal_pool = _candidates("NORMAL", 150)
    light_pool = _candidates("LIGHT", 90)

    assert _plan("INTENSIVE", normal_pool) == (2, 2)
    assert _plan("INTENSIVE", light_pool) == (4, 2)
