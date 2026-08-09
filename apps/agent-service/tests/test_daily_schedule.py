"""Unit tests for the pure daily-schedule module (B1)."""

from datetime import date, datetime
from decimal import Decimal

import pytest

import trip_agent.planning.daily_schedule as daily_schedule_module
from trip_agent.domain.shared import CHINA_TIME_ZONE
from trip_agent.planning.daily_schedule import (
    CandidateActivity,
    FixedSchedule,
    build_fixed_items,
    build_meal_demands,
    classify_day_type,
    compute_free_windows,
    day_window_minutes,
    plan_day,
)

START = date(2026, 8, 1)
MID = date(2026, 8, 2)
END = date(2026, 8, 3)


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=CHINA_TIME_ZONE)


def _candidate(
    poi_id: str,
    title: str,
    magnitude: str,
    *,
    region: str | None = "越秀区",
    must_include: bool = False,
    score: int = 0,
    kind: str = "ATTRACTION",
) -> CandidateActivity:
    return CandidateActivity(
        poi_id=poi_id,
        title=title,
        magnitude=magnitude,  # type: ignore[arg-type]
        region=region,
        must_include=must_include,
        score=score,
        kind=kind,  # type: ignore[arg-type]
    )


# ── day type ----------------------------------------------------------------

def test_classify_first_day_with_arrival_is_arrival_day() -> None:
    assert classify_day_type(MID, START, END, _at(1, 14), None) == "FULL_DAY"
    assert classify_day_type(START, START, END, _at(1, 14), None) == "ARRIVAL_DAY"


def test_classify_last_day_with_departure_is_departure_day() -> None:
    assert classify_day_type(END, START, END, None, _at(3, 10)) == "DEPARTURE_DAY"


def test_classify_full_day_without_anchors() -> None:
    assert classify_day_type(MID, START, END, None, None) == "FULL_DAY"


def test_classify_special_day_when_full_day_experience() -> None:
    assert classify_day_type(MID, START, END, None, None, has_full_day_experience=True) == (
        "SPECIAL_ACTIVITY_DAY"
    )


def test_classify_single_day_late_arrival_is_arrival_day() -> None:
    assert classify_day_type(START, START, START, _at(1, 16), None) == "ARRIVAL_DAY"


def test_classify_single_day_early_departure_is_departure_day() -> None:
    assert classify_day_type(START, START, START, None, _at(1, 9)) == "DEPARTURE_DAY"


def test_classify_single_day_mid_trip_is_full_day() -> None:
    assert classify_day_type(START, START, START, None, None) == "FULL_DAY"


# ── time window -------------------------------------------------------------

def test_day_window_defaults_to_9_to_18() -> None:
    assert day_window_minutes(MID, START, END, None, None) == (540, 1080)


def test_day_window_intensive_extends_to_20() -> None:
    assert day_window_minutes(MID, START, END, None, None, pace="INTENSIVE") == (540, 1200)


def test_day_window_arrival_tightens_start() -> None:
    assert day_window_minutes(START, START, END, _at(1, 14), None) == (840, 1080)


def test_day_window_departure_tightens_end() -> None:
    assert day_window_minutes(END, START, END, None, _at(3, 16)) == (540, 960)


def test_day_window_keeps_default_when_anchors_missing() -> None:
    assert day_window_minutes(START, START, END, None, None) == (540, 1080)


# ── free windows ------------------------------------------------------------

def test_free_windows_exclude_fixed_items() -> None:
    fixed = build_fixed_items(MID, None, None, (), ())
    assert compute_free_windows(fixed, 540, 1080) == ((540, 1080),)


def test_free_windows_split_around_fixed_block() -> None:
    fixed = build_fixed_items(
        MID, None, None,
        (FixedSchedule("预约", _at(2, 12), _at(2, 14)),),
        (),
    )
    windows = compute_free_windows(fixed, 540, 1080)
    assert windows == ((540, 720), (840, 1080))


def test_free_windows_drop_tiny_gaps() -> None:
    fixed = build_fixed_items(
        MID, None, None,
        (FixedSchedule("预约", _at(2, 11, 30), _at(2, 12)),),
        (),
    )
    windows = compute_free_windows(fixed, 540, 1080)
    # 540-690 and 720-1080; the tiny 690-720 gap (<60) is dropped.
    assert windows == ((540, 690), (720, 1080))


# ── meals -------------------------------------------------------------------

def test_full_day_reserves_lunch_and_dinner() -> None:
    demands = build_meal_demands(
        "FULL_DAY", 540, 1080, ((540, 1080),), primary_region="越秀区"
    )
    assert {d.meal_type for d in demands} == {"LUNCH", "DINNER"}


def test_arrival_day_reserves_only_dinner() -> None:
    demands = build_meal_demands(
        "ARRIVAL_DAY", 840, 1080, ((840, 1080),), primary_region="越秀区"
    )
    assert {d.meal_type for d in demands} == {"DINNER"}


def test_departure_day_reserves_only_lunch() -> None:
    demands = build_meal_demands(
        "DEPARTURE_DAY", 540, 960, ((540, 960),), primary_region="越秀区"
    )
    assert {d.meal_type for d in demands} == {"LUNCH"}


def test_meal_demand_kept_when_region_unknown() -> None:
    demands = build_meal_demands(
        "FULL_DAY", 540, 1080, ((540, 1080),), primary_region=None
    )
    assert len(demands) == 2
    assert all(d.region is None for d in demands)


def test_no_meal_when_free_window_too_small() -> None:
    demands = build_meal_demands(
        "FULL_DAY", 540, 1080, ((540, 590),), primary_region="越秀区"
    )
    assert demands == ()


# ── plan_day end-to-end -----------------------------------------------------

def test_full_day_selects_by_capacity_not_fixed_two() -> None:
    candidates = tuple(
        _candidate(f"poi-{index}", f"景点{index}", "NORMAL", region="越秀区")
        for index in range(6)
    )
    plan = plan_day(
        trip_date=MID, start_date=START, end_date=END,
        arrival=None, departure=None, accommodation_known=True,
        candidates=candidates,
    )
    activities = [item for item in plan.items if item.kind in {"ATTRACTION", "EXPERIENCE"}]
    # Capacity at 9-18 (540 min): 150min normals with buffers => at most 3 fit.
    assert 2 <= len(activities) <= 3
    assert plan.day_type == "FULL_DAY"
    assert plan.accommodation_unknown is False


def test_must_include_retained_when_capacity_tight() -> None:
    candidates = (
        _candidate("must-1", "必去A", "NORMAL", must_include=True, score=0),
        _candidate("opt-1", "可选B", "NORMAL", score=90),
    )
    plan = plan_day(
        trip_date=MID, start_date=START, end_date=END,
        arrival=None, departure=None, accommodation_known=True,
        candidates=candidates,
    )
    titles = [item.title for item in plan.items if item.kind == "ATTRACTION"]
    assert "必去A" in titles
    assert not any(w.startswith("MUST_VISIT_UNSCHEDULED") for w in plan.warnings)


def test_must_include_can_be_scheduled_not_time_locked() -> None:
    # A must-visit is not time_fixed: it must appear, but its window is movable.
    candidate = _candidate("must-1", "必去A", "NORMAL", must_include=True)
    plan = plan_day(
        trip_date=MID, start_date=START, end_date=END,
        arrival=None, departure=None, accommodation_known=True,
        candidates=(candidate,),
    )
    item = next(item for item in plan.items if item.poi_id == "must-1")
    assert item.time_fixed is False


def test_arrival_day_afternoon_places_dinner_and_only_light() -> None:
    candidates = (
        _candidate("n-1", "普通景点", "NORMAL", region="越秀区"),
        _candidate("l-1", "轻量景点", "LIGHT", region="越秀区"),
    )
    plan = plan_day(
        trip_date=START, start_date=START, end_date=END,
        arrival=_at(1, 15), departure=None, accommodation_known=True,
        candidates=candidates,
    )
    assert plan.day_type == "ARRIVAL_DAY"
    kinds = {item.kind for item in plan.items}
    assert "ARRIVAL" in kinds
    # 15:00 arrival leaves only 15:30–18:00 after the anchor; a NORMAL
    # (150min) does not fit next to the 17:00 dinner reservation, only LIGHT.
    attractions = [item for item in plan.items if item.kind == "ATTRACTION"]
    assert attractions and all(item.magnitude == "LIGHT" for item in attractions)
    assert {d.meal_type for d in plan.meal_demands} == {"DINNER"}


def test_departure_day_only_places_light_and_lunch() -> None:
    candidates = (
        _candidate("n-1", "普通景点", "NORMAL", region="越秀区"),
        _candidate("l-1", "轻量景点", "LIGHT", region="越秀区"),
    )
    plan = plan_day(
        trip_date=END, start_date=START, end_date=END,
        arrival=None, departure=_at(3, 11), accommodation_known=True,
        candidates=candidates,
    )
    assert plan.day_type == "DEPARTURE_DAY"
    assert "DEPARTURE" in {item.kind for item in plan.items}
    assert {d.meal_type for d in plan.meal_demands} == {"LUNCH"}


def test_missing_hotel_uses_virtual_origin_and_marks_unknown() -> None:
    plan = plan_day(
        trip_date=MID, start_date=START, end_date=END,
        arrival=None, departure=None, accommodation_known=False,
        candidates=(_candidate("a-1", "A", "NORMAL"),),
    )
    assert plan.accommodation_unknown is True
    assert plan.origin is not None
    assert plan.origin.accommodation_known is False
    assert plan.origin.label == "城市中心"


def test_known_hotel_origin() -> None:
    plan = plan_day(
        trip_date=MID, start_date=START, end_date=END,
        arrival=None, departure=None, accommodation_known=True,
        candidates=(_candidate("a-1", "A", "NORMAL"),),
    )
    assert plan.accommodation_unknown is False
    assert plan.origin is not None
    assert plan.origin.accommodation_known is True
    assert plan.origin.label == "酒店"


def test_special_activity_day_chooses_full_day_experience() -> None:
    candidates = (
        _candidate("exp-1", "泰山", "FULL_DAY", region="泰山区", score=80, kind="EXPERIENCE"),
        _candidate("n-1", "博物馆", "NORMAL", region="泰山区", score=90),
    )
    plan = plan_day(
        trip_date=MID, start_date=START, end_date=END,
        arrival=None, departure=None, accommodation_known=True,
        candidates=candidates, has_full_day_experience=True,
    )
    assert plan.day_type == "SPECIAL_ACTIVITY_DAY"
    experience = [item for item in plan.items if item.kind == "EXPERIENCE"]
    assert len(experience) == 1
    assert experience[0].title == "泰山"
    assert experience[0].magnitude == "FULL_DAY"


def test_single_day_late_arrival_plan_not_empty_but_minimal() -> None:
    plan = plan_day(
        trip_date=START, start_date=START, end_date=START,
        arrival=_at(1, 17), departure=None, accommodation_known=True,
        candidates=(_candidate("n-1", "A", "NORMAL"), _candidate("l-1", "B", "LIGHT")),
    )
    assert plan.day_type == "ARRIVAL_DAY"
    assert plan.window_start_minute == 1020  # 17:00
    assert plan.window_end_minute == 1080    # 18:00 default


def test_early_departure_keeps_departure_anchor() -> None:
    """An 08:00 departure must keep the DEPARTURE anchor, not a null window."""
    plan = plan_day(
        trip_date=END, start_date=START, end_date=END,
        arrival=None, departure=_at(3, 8), accommodation_known=True,
        candidates=(_candidate("n-1", "A", "NORMAL"),),
    )
    assert plan.day_type == "DEPARTURE_DAY"
    assert "NO_USABLE_DAY_WINDOW" not in plan.warnings
    kinds = [item.kind for item in plan.items]
    assert "DEPARTURE" in kinds


def test_late_arrival_keeps_arrival_anchor() -> None:
    """A 20:00 arrival must keep the ARRIVAL anchor with room for its buffer."""
    plan = plan_day(
        trip_date=START, start_date=START, end_date=END,
        arrival=_at(1, 20), departure=None, accommodation_known=True,
        candidates=(_candidate("n-1", "A", "NORMAL"),),
    )
    assert plan.day_type == "ARRIVAL_DAY"
    assert "NO_USABLE_DAY_WINDOW" not in plan.warnings
    kinds = [item.kind for item in plan.items]
    assert "ARRIVAL" in kinds
    # arrival at 20:00 (1200) plus its 30-minute buffer must be inside the window.
    assert plan.window_start_minute == 1200
    assert plan.window_end_minute == 1230


def test_fixed_schedule_overlap_is_warned() -> None:
    plan = plan_day(
        trip_date=MID, start_date=START, end_date=END,
        arrival=None, departure=None, accommodation_known=True,
        fixed_schedules=(
            FixedSchedule("预约1", _at(2, 10), _at(2, 12)),
            FixedSchedule("预约2", _at(2, 11), _at(2, 13)),
        ),
        candidates=(_candidate("a-1", "A", "NORMAL"),),
    )
    assert any(w.startswith("FIXED_OVERLAP") for w in plan.warnings)


def test_meal_demands_always_reserve_time_even_without_restaurant() -> None:
    # The plan carries meal time regardless of any restaurant lookup; the
    # provider decides later whether a real POI exists.
    plan = plan_day(
        trip_date=MID, start_date=START, end_date=END,
        arrival=None, departure=None, accommodation_known=True,
        candidates=(_candidate("a-1", "A", "NORMAL"),),
        meal_preferences=("粤菜",),
        budget_per_person=Decimal("50"),
    )
    assert len(plan.meal_demands) == 2
    meal_items = [item for item in plan.items if item.kind == "MEAL"]
    assert len(meal_items) == 2
    assert all(item.meal is not None for item in meal_items)
    # reserved span is exactly one hour
    assert all(item.end_minute - item.start_minute == 60 for item in meal_items)


# ── B4A: primary_region exposure -------------------------------------------


def test_plan_day_exposes_primary_region_from_single_region() -> None:
    candidates = tuple(
        _candidate(f"poi-{index}", f"景点{index}", "NORMAL", region="越秀区") for index in range(3)
    )
    plan = plan_day(
        trip_date=MID,
        start_date=START,
        end_date=END,
        arrival=None,
        departure=None,
        accommodation_known=True,
        candidates=candidates,
    )
    assert plan.primary_region == "越秀区"


def test_plan_day_primary_region_favours_majority_region() -> None:
    candidates = (
        _candidate("a-1", "A景点", "NORMAL", region="越秀区"),
        _candidate("a-2", "A2景点", "NORMAL", region="越秀区"),
        _candidate("a-3", "A3景点", "NORMAL", region="越秀区"),
        _candidate("b-1", "B景点", "NORMAL", region="天河区"),
    )
    plan = plan_day(
        trip_date=MID,
        start_date=START,
        end_date=END,
        arrival=None,
        departure=None,
        accommodation_known=True,
        candidates=candidates,
    )
    assert plan.primary_region == "越秀区"


def test_plan_day_primary_region_is_none_without_regions() -> None:
    candidates = (
        _candidate("n-1", "A景点", "NORMAL", region=None),
        _candidate("n-2", "B景点", "NORMAL", region=None),
    )
    plan = plan_day(
        trip_date=MID,
        start_date=START,
        end_date=END,
        arrival=None,
        departure=None,
        accommodation_known=True,
        candidates=candidates,
    )
    assert plan.primary_region is None


def test_no_usable_day_window_has_no_primary_region(monkeypatch) -> None:
    monkeypatch.setattr(
        daily_schedule_module, "day_window_minutes", lambda *args, **kwargs: (1200, 600)
    )
    plan = plan_day(
        trip_date=MID,
        start_date=START,
        end_date=END,
        arrival=None,
        departure=None,
        accommodation_known=True,
        candidates=(_candidate("a-1", "A", "NORMAL", region="越秀区"),),
    )
    assert plan.warnings == ("NO_USABLE_DAY_WINDOW",)
    assert plan.primary_region is None


def test_day_plan_remains_frozen() -> None:
    plan = plan_day(
        trip_date=MID,
        start_date=START,
        end_date=END,
        arrival=None,
        departure=None,
        accommodation_known=True,
        candidates=(_candidate("a-1", "A", "NORMAL", region="越秀区"),),
    )
    with pytest.raises(AttributeError):
        plan.primary_region = "天河区"  # type: ignore[misc]
