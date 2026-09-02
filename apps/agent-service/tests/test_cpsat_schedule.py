"""CP-SAT day scheduler — exact selection over the greedy feasible space.

Contract under test:

* same feasible space as `_fill_slots` (slot capacity incl. pace/mobility
  discounts, inter-item pace buffer, VERIFIED opening windows/closures);
* better *selection*: the solver finds combinations score-ordered first-fit
  strands (the stranded-capacity case below is the canonical example);
* must-include is forced; an infeasible must-include falls back to the greedy
  result so upstream capacity repair sees a familiar situation;
* dispatch: default GREEDY is byte-identical to the historical path; CPSAT
  and SHADOW select via `PLANNING_DAY_SCHEDULER`; SHADOW always returns the
  greedy result.
"""

import logging

import pytest

from trip_agent.planning.cpsat_schedule import (
    choose_activities_cpsat,
    resolve_day_scheduler,
)
from trip_agent.planning.daily_schedule import (
    CandidateActivity,
    OpeningAvailability,
    PlacedActivity,
    _fill_slots,
    choose_activities,
)
from trip_agent.planning.visit_duration import (
    DurationProfileSource,
    VisitDurationProfile,
)

_CATEGORY_VERSION = "category-profile-v1"


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


def _candidate(
    poi_id: str,
    *,
    minutes: int,
    score: int,
    must_include: bool = False,
    region: str | None = None,
    opening: OpeningAvailability | None = None,
) -> CandidateActivity:
    return CandidateActivity(
        poi_id=poi_id,
        title=f"景点-{poi_id}",
        magnitude="LIGHT",
        region=region,
        must_include=must_include,
        kind="ATTRACTION",
        score=score,
        visit_duration_profile=_profile(minutes),
        opening=opening,
    )


# One 150-minute slot (09:00–11:30).  Greedy places the 90-min high-score
# candidate first and then cannot fit either 60-min candidate (60 + 12 buffer
# > remaining 60).  The exact solver pairs the two 60-min candidates for a
# higher total score inside the same feasible space.

_STRANDED_SLOT = ((540, 690),)

_STRANDED_CANDIDATES = (
    _candidate("long", minutes=90, score=150),
    _candidate("short-a", minutes=60, score=100),
    _candidate("short-b", minutes=60, score=100),
)


def _score(placed: tuple[PlacedActivity, ...]) -> int:
    return sum(item.candidate.score for item in placed)


def test_cpsat_finds_better_combination_than_greedy() -> None:
    greedy = _fill_slots(
        _STRANDED_CANDIDATES,
        _STRANDED_SLOT,
        pace="BALANCED",
        mobility_reduced=False,
        primary_region=None,
    )
    cpsat = choose_activities_cpsat(
        _STRANDED_CANDIDATES,
        _STRANDED_SLOT,
        day_type="FULL_DAY",
        pace="BALANCED",
        mobility_reduced=False,
        primary_region=None,
    )

    assert _score(greedy) == 150  # the long candidate strands the rest
    assert _score(cpsat) == 200  # short-a + short-b
    assert all(item.end_minute <= 690 for item in cpsat)
    starts = sorted(item.start_minute for item in cpsat)
    gaps = [b - a for a, b in zip(starts, starts[1:], strict=False)]
    # 60-min visit + 12-min pace buffer between the paired candidates.
    assert gaps and gaps[0] >= 72


def test_cpsat_respects_capacity_and_buffer() -> None:
    cpsat = choose_activities_cpsat(
        _STRANDED_CANDIDATES,
        _STRANDED_SLOT,
        day_type="FULL_DAY",
        pace="BALANCED",
        mobility_reduced=False,
        primary_region=None,
    )
    packed = sum(item.end_minute - item.start_minute for item in cpsat)
    assert packed <= 150
    ordered = sorted(cpsat, key=lambda item: item.start_minute)
    for previous, current in zip(ordered, ordered[1:], strict=False):
        assert current.start_minute >= previous.end_minute + 12


def test_verified_closed_excluded_and_window_respected() -> None:
    candidates = (
        _candidate(
            "closed",
            minutes=60,
            score=500,
            opening=OpeningAvailability(kind="VERIFIED_CLOSED"),
        ),
        _candidate(
            "windowed",
            minutes=60,
            score=50,
            opening=OpeningAvailability(
                kind="VERIFIED_WINDOW",
                windows=((600, 720),),
                last_entry_minute=660,
            ),
        ),
        _candidate("free", minutes=60, score=10),
    )
    cpsat = choose_activities_cpsat(
        candidates,
        ((540, 780),),
        day_type="FULL_DAY",
        pace="BALANCED",
        mobility_reduced=False,
        primary_region=None,
    )

    ids = {item.candidate.poi_id for item in cpsat}
    assert "closed" not in ids  # never silently moved: excluded
    windowed = next(item for item in cpsat if item.candidate.poi_id == "windowed")
    assert 600 <= windowed.start_minute <= 660  # inside the verified window and last-entry
    assert windowed.end_minute <= 720


def test_must_include_forced_over_higher_score_optional() -> None:
    candidates = (
        _candidate("long", minutes=90, score=150),
        _candidate("must", minutes=60, score=10, must_include=True),
    )
    cpsat = choose_activities_cpsat(
        candidates,
        ((540, 690),),
        day_type="FULL_DAY",
        pace="BALANCED",
        mobility_reduced=False,
        primary_region=None,
    )
    ids = {item.candidate.poi_id for item in cpsat}
    assert "must" in ids


def test_infeasible_must_include_falls_back_to_greedy() -> None:
    candidates = (
        _candidate("half-day", minutes=240, score=10, must_include=True),
        _candidate("free", minutes=60, score=100),
    )
    slots = ((540, 690),)
    greedy = _fill_slots(
        candidates, slots, pace="BALANCED", mobility_reduced=False, primary_region=None
    )
    cpsat = choose_activities_cpsat(
        candidates,
        slots,
        day_type="FULL_DAY",
        pace="BALANCED",
        mobility_reduced=False,
        primary_region=None,
    )
    # The 240-min must-include cannot fit the 150-min slot; the model is
    # infeasible and the fallback returns exactly the greedy result (whose
    # MUST_VISIT_UNSCHEDULED warning the pipeline already handles).
    assert cpsat == greedy
    assert {item.candidate.poi_id for item in cpsat} == {"free"}


def test_relaxed_discount_mirrors_greedy() -> None:
    candidates = (
        _candidate("a", minutes=90, score=100),
        _candidate("b", minutes=90, score=90),
    )
    slots = ((540, 690),)  # 150 raw; RELAXED discounts 60 → packable 90
    greedy = _fill_slots(
        candidates, slots, pace="RELAXED", mobility_reduced=False, primary_region=None
    )
    cpsat = choose_activities_cpsat(
        candidates,
        slots,
        day_type="FULL_DAY",
        pace="RELAXED",
        mobility_reduced=False,
        primary_region=None,
    )
    assert len(greedy) == 1
    assert len(cpsat) == 1
    assert cpsat[0].end_minute <= 540 + 90


def test_dispatch_default_greedy_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLANNING_DAY_SCHEDULER", raising=False)
    result = choose_activities(
        _STRANDED_CANDIDATES,
        _STRANDED_SLOT,
        day_type="FULL_DAY",
        pace="BALANCED",
    )
    expected = _fill_slots(
        _STRANDED_CANDIDATES,
        _STRANDED_SLOT,
        pace="BALANCED",
        mobility_reduced=False,
        primary_region=None,
    )
    assert result == expected


def test_dispatch_cpsat_mode_selects_optimal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLANNING_DAY_SCHEDULER", "CPSAT")
    result = choose_activities(
        _STRANDED_CANDIDATES,
        _STRANDED_SLOT,
        day_type="FULL_DAY",
        pace="BALANCED",
    )
    assert _score(result) == 200


def test_dispatch_shadow_returns_greedy_and_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("PLANNING_DAY_SCHEDULER", "SHADOW")
    expected = _fill_slots(
        _STRANDED_CANDIDATES,
        _STRANDED_SLOT,
        pace="BALANCED",
        mobility_reduced=False,
        primary_region=None,
    )
    with caplog.at_level(logging.INFO, logger="trip_agent.planning.cpsat_schedule"):
        result = choose_activities(
            _STRANDED_CANDIDATES,
            _STRANDED_SLOT,
            day_type="FULL_DAY",
            pace="BALANCED",
        )
    assert result == expected  # shadow never changes behavior
    assert any("day scheduler shadow" in record.message for record in caplog.records)


def test_resolve_day_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLANNING_DAY_SCHEDULER", raising=False)
    assert resolve_day_scheduler() == "GREEDY"
    assert resolve_day_scheduler({"PLANNING_DAY_SCHEDULER": "cpsat"}) == "CPSAT"
    assert resolve_day_scheduler({"PLANNING_DAY_SCHEDULER": " SHADOW "}) == "SHADOW"
    with pytest.raises(ValueError):
        resolve_day_scheduler({"PLANNING_DAY_SCHEDULER": "EXACT"})
