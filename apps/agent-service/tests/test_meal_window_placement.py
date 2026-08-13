"""B9.4 — explicit meal windows drive real placement."""

from datetime import date

from trip_agent.planning.daily_schedule import (
    MealWindowConstraint,
    build_meal_demands,
    plan_day,
)


def _demands_for(
    *,
    day_type: str = "FULL_DAY",
    explicit: tuple[MealWindowConstraint, ...] = (),
    free: tuple[tuple[int, int], ...] = ((540, 1080),),
    window_end: int = 1080,
) -> tuple:
    return build_meal_demands(
        day_type,
        window_start_minute=540,
        window_end_minute=window_end,
        free_windows=free,
        primary_region=None,
        explicit_windows=explicit,
    )


def test_explicit_lunch_window_wins_over_default() -> None:
    demands = _demands_for(explicit=(MealWindowConstraint("LUNCH", 11 * 60, 13 * 60),))
    lunch = next(meal for meal in demands if meal.meal_type == "LUNCH")
    assert lunch.start_minute >= 11 * 60
    assert lunch.end_minute <= 13 * 60


def test_explicit_window_without_room_produces_conflict_not_silent_drop() -> None:
    plan = plan_day(
        trip_date=date(2026, 8, 1),
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 1),
        arrival=None,
        departure=None,
        accommodation_known=False,
        meal_windows=(MealWindowConstraint("LUNCH", 540, 580),),
    )
    # The 60-minute lunch demand does not fit into the 40-minute window, so
    # the conflict must be surfaced explicitly.
    assert any(warning.startswith("MEAL_WINDOW_CONFLICT:LUNCH") for warning in plan.warnings)


def test_no_explicit_window_keeps_default_suggestion() -> None:
    demands = _demands_for(free=((540, 1260),), window_end=1260)
    lunch = next(meal for meal in demands if meal.meal_type == "LUNCH")
    dinner = next(meal for meal in demands if meal.meal_type == "DINNER")
    assert lunch.start_minute == 12 * 60
    assert dinner.start_minute == 18 * 60


def test_cross_midnight_window_keeps_end_past_1440() -> None:
    constraint = MealWindowConstraint("DINNER", 23 * 60, 1 * 60 + 1440)
    assert constraint.end_minute == 1500
    demands = _demands_for(
        day_type="FULL_DAY",
        explicit=(constraint,),
        free=((540, 1560),),
        window_end=1560,
    )
    dinner = next(meal for meal in demands if meal.meal_type == "DINNER")
    assert dinner.start_minute >= 23 * 60
    assert dinner.end_minute <= 1500
