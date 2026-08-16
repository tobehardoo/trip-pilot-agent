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


# ── B13-F: meal window source drives placement semantics ────────────────────


def test_default_window_places_inside_suggestion_when_room() -> None:
    demands = _demands_for(
        explicit=(MealWindowConstraint("LUNCH", 11 * 60, 13 * 60, "DEFAULT"),),
    )
    lunch = next(meal for meal in demands if meal.meal_type == "LUNCH")
    assert lunch.start_minute >= 11 * 60
    assert lunch.end_minute <= 13 * 60


def test_default_window_without_room_falls_back_to_default_minute() -> None:
    plan = plan_day(
        trip_date=date(2026, 8, 1),
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 1),
        arrival=None,
        departure=None,
        accommodation_known=False,
        meal_windows=(MealWindowConstraint("LUNCH", 9 * 60, 9 * 60 + 40, "DEFAULT"),),
    )
    # The 40-minute suggestion cannot fit a 60-minute meal, so the meal still
    # happens at the default minute — a soft suggestion must never starve
    # the traveller, and it never surfaces a hard conflict.
    lunch = next(meal for meal in plan.meal_demands if meal.meal_type == "LUNCH")
    assert lunch.start_minute == 12 * 60
    assert not any(warning.startswith("MEAL_WINDOW_CONFLICT") for warning in plan.warnings)


def test_user_window_without_room_still_conflicts() -> None:
    plan = plan_day(
        trip_date=date(2026, 8, 1),
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 1),
        arrival=None,
        departure=None,
        accommodation_known=False,
        meal_windows=(MealWindowConstraint("LUNCH", 9 * 60, 9 * 60 + 40, "USER"),),
    )
    assert not any(meal.meal_type == "LUNCH" for meal in plan.meal_demands)
    assert any(warning.startswith("MEAL_WINDOW_CONFLICT:LUNCH") for warning in plan.warnings)


def test_disabled_window_produces_no_meal_demand_and_no_warning() -> None:
    plan = plan_day(
        trip_date=date(2026, 8, 1),
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 1),
        arrival=None,
        departure=None,
        accommodation_known=False,
        meal_windows=(MealWindowConstraint("LUNCH", 12 * 60, 13 * 60, "DISABLED"),),
    )
    assert not any(meal.meal_type == "LUNCH" for meal in plan.meal_demands)
    assert not any(warning.startswith("MEAL_WINDOW_CONFLICT") for warning in plan.warnings)


def test_disabled_dinner_keeps_user_lunch_without_conflict() -> None:
    plan = plan_day(
        trip_date=date(2026, 8, 1),
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 1),
        arrival=None,
        departure=None,
        accommodation_known=False,
        meal_windows=(
            MealWindowConstraint("LUNCH", 11 * 60, 13 * 60, "USER"),
            MealWindowConstraint("DINNER", 18 * 60, 19 * 60, "DISABLED"),
        ),
    )
    types = {meal.meal_type for meal in plan.meal_demands}
    assert types == {"LUNCH"}
    assert not any(warning.startswith("MEAL_WINDOW_CONFLICT") for warning in plan.warnings)
