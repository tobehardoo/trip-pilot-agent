"""B5 Phase 1 — VisitDurationProfile domain model and scheduler integration.

Locks the profile invariants, the poi_quality migration, and the scheduler
behaviour (recommended minutes when a profile is present, magnitude fallback
otherwise, one shared duration helper).
"""

import math
from datetime import date

import pytest

from trip_agent.planning.daily_schedule import CandidateActivity, plan_day
from trip_agent.planning.poi_quality import duration_profile_for
from trip_agent.planning.visit_duration import (
    DurationProfileSource,
    VisitDurationProfile,
)
from trip_agent.providers.map import Coordinates, Poi


def _poi(
    provider_id: str = "p1",
    name: str = "越秀公园",
    *,
    type_name: str = "风景名胜",
    type_code: str = "110000",
) -> Poi:
    return Poi(
        provider_id=provider_id,
        name=name,
        coordinates=Coordinates(longitude=113.31, latitude=23.13),
        type_name=type_name,
        type_code=type_code,
        province="广东省",
        city="广州市",
        district="越秀区",
        address="addr",
    )


def _profile(
    *,
    min_minutes: int = 90,
    recommended_minutes: int = 150,
    max_minutes: int = 180,
    source: DurationProfileSource = DurationProfileSource.CATEGORY_PROFILE,
    source_ref: str = "category:scenic",
    confidence: float = 0.5,
    profile_version: str = "category-profile-v1",
    hard_constraint_eligible: bool = False,
) -> VisitDurationProfile:
    return VisitDurationProfile(
        min_minutes=min_minutes,
        recommended_minutes=recommended_minutes,
        max_minutes=max_minutes,
        source=source,
        source_ref=source_ref,
        confidence=confidence,
        profile_version=profile_version,
        hard_constraint_eligible=hard_constraint_eligible,
    )


# ── enum ───────────────────────────────────────────────────────────────────


def test_duration_profile_source_has_exact_five_members_in_stable_order() -> None:
    assert tuple(DurationProfileSource) == (
        DurationProfileSource.PROVIDER,
        DurationProfileSource.OFFICIAL_FACT,
        DurationProfileSource.CATEGORY_PROFILE,
        DurationProfileSource.CATEGORY_FALLBACK,
        DurationProfileSource.SYSTEM_DEFAULT,
    )


# ── construction invariants ────────────────────────────────────────────────


def test_profile_rejects_min_greater_than_recommended() -> None:
    with pytest.raises(ValueError):
        _profile(min_minutes=200, recommended_minutes=150)


def test_profile_rejects_recommended_greater_than_max() -> None:
    with pytest.raises(ValueError):
        _profile(recommended_minutes=200, max_minutes=180)


def test_profile_rejects_zero_or_negative_minutes() -> None:
    with pytest.raises(ValueError):
        _profile(min_minutes=0)
    with pytest.raises(ValueError):
        _profile(max_minutes=0)


def test_profile_rejects_minutes_over_1440() -> None:
    with pytest.raises(ValueError):
        _profile(max_minutes=1441)


def test_profile_rejects_bool_minutes() -> None:
    with pytest.raises((TypeError, ValueError)):
        _profile(min_minutes=True)  # type: ignore[arg-type]
    with pytest.raises((TypeError, ValueError)):
        _profile(recommended_minutes=False)  # type: ignore[arg-type]


def test_profile_rejects_nan_and_infinite_confidence() -> None:
    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError):
            _profile(confidence=bad)


def test_profile_rejects_confidence_out_of_range() -> None:
    with pytest.raises(ValueError):
        _profile(confidence=-0.1)
    with pytest.raises(ValueError):
        _profile(confidence=1.1)


def test_profile_rejects_bool_confidence() -> None:
    with pytest.raises((TypeError, ValueError)):
        _profile(confidence=True)  # type: ignore[arg-type]


def test_profile_rejects_plain_string_source() -> None:
    with pytest.raises((TypeError, ValueError)):
        _profile(source="PROVIDER")  # type: ignore[arg-type]


def test_profile_rejects_blank_source_ref_and_version() -> None:
    with pytest.raises(ValueError):
        _profile(source_ref="   ")
    with pytest.raises(ValueError):
        _profile(profile_version="")


def test_profile_trims_source_ref_and_version() -> None:
    profile = _profile(source_ref="  amap:42  ", profile_version="  v1  ")
    assert profile.source_ref == "amap:42"
    assert profile.profile_version == "v1"


def test_category_profile_cannot_be_hard_eligible() -> None:
    with pytest.raises(ValueError):
        _profile(
            source=DurationProfileSource.CATEGORY_PROFILE,
            hard_constraint_eligible=True,
        )


def test_category_fallback_and_system_default_cannot_be_hard_eligible() -> None:
    for source in (
        DurationProfileSource.CATEGORY_FALLBACK,
        DurationProfileSource.SYSTEM_DEFAULT,
    ):
        with pytest.raises(ValueError):
            _profile(source=source, hard_constraint_eligible=True)


def test_provider_eligible_requires_confidence_at_or_above_threshold() -> None:
    with pytest.raises(ValueError):
        _profile(
            source=DurationProfileSource.PROVIDER,
            confidence=0.7,
            hard_constraint_eligible=True,
        )
    profile = _profile(
        source=DurationProfileSource.PROVIDER,
        confidence=0.8,
        source_ref="amap:42",
        hard_constraint_eligible=True,
    )
    assert profile.hard_constraint_eligible is True


def test_official_fact_eligible_with_high_confidence() -> None:
    profile = _profile(
        source=DurationProfileSource.OFFICIAL_FACT,
        confidence=0.9,
        source_ref="official:42",
        hard_constraint_eligible=True,
    )
    assert profile.hard_constraint_eligible is True


def test_profile_is_frozen() -> None:
    profile = _profile()
    with pytest.raises(AttributeError):
        profile.min_minutes = 10  # type: ignore[misc]


def test_profile_is_pure_dataclass_slots() -> None:
    profile = _profile()
    assert not hasattr(profile, "__dict__")


# ── poi_quality migration ──────────────────────────────────────────────────


def test_duration_profile_for_returns_new_model_not_hard_eligible() -> None:
    profile = duration_profile_for(_poi())
    assert isinstance(profile, VisitDurationProfile)
    assert profile.hard_constraint_eligible is False
    assert profile.source in {
        DurationProfileSource.CATEGORY_PROFILE,
        DurationProfileSource.CATEGORY_FALLBACK,
        DurationProfileSource.SYSTEM_DEFAULT,
    }
    assert profile.profile_version
    assert profile.source_ref
    assert 0 <= profile.confidence <= 1


def test_duration_profile_does_not_fake_provider_duration() -> None:
    profile = duration_profile_for(_poi())
    assert profile.source is not DurationProfileSource.PROVIDER


def test_amap_profile_matches_magnitude_derivation() -> None:
    from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider

    poi = _poi()
    duration_profile_for(poi)
    magnitude = AmapPlanningProvider._magnitude_for_poi(poi)
    assert magnitude in {"LIGHT", "NORMAL", "HALF_DAY", "FULL_DAY"}


# ── CandidateActivity + scheduler integration ──────────────────────────────


def test_candidate_accepts_optional_profile_default_none() -> None:
    candidate = CandidateActivity(poi_id="p1", title="A", magnitude="NORMAL")
    assert candidate.visit_duration_profile is None


def test_scheduler_uses_recommended_minutes_when_profile_present() -> None:
    profile = _profile(
        min_minutes=60,
        recommended_minutes=200,
        max_minutes=240,
        source=DurationProfileSource.OFFICIAL_FACT,
        confidence=0.9,
        source_ref="official:1",
        hard_constraint_eligible=True,
    )
    candidate = CandidateActivity(
        poi_id="p1",
        title="A",
        magnitude="NORMAL",
        visit_duration_profile=profile,
    )
    plan = plan_day(
        trip_date=date(2026, 8, 1),
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 2),
        arrival=None,
        departure=None,
        accommodation_known=True,
        candidates=(candidate,),
    )
    placed = next(item for item in plan.items if item.poi_id == "p1")
    assert placed.end_minute - placed.start_minute == 200


def test_scheduler_falls_back_to_magnitude_without_profile() -> None:
    candidate = CandidateActivity(poi_id="p1", title="A", magnitude="NORMAL")
    plan = plan_day(
        trip_date=date(2026, 8, 1),
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 2),
        arrival=None,
        departure=None,
        accommodation_known=True,
        candidates=(candidate,),
    )
    placed = next(item for item in plan.items if item.poi_id == "p1")
    assert placed.end_minute - placed.start_minute == 150


def test_place_and_fill_slots_share_duration_helper() -> None:
    from trip_agent.planning.daily_schedule import (
        MAGNITUDE_DURATION_MINUTES,
        _activity_duration_minutes,
    )

    with_profile = CandidateActivity(
        poi_id="p1",
        title="A",
        magnitude="NORMAL",
        visit_duration_profile=_profile(
            recommended_minutes=200,
            max_minutes=240,
        ),
    )
    without_profile = CandidateActivity(poi_id="p2", title="B", magnitude="NORMAL")

    assert _activity_duration_minutes(with_profile) == 200
    assert _activity_duration_minutes(without_profile) == MAGNITUDE_DURATION_MINUTES["NORMAL"]
