"""B5 Phase 6 — MEAL_WINDOW canonical rule."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from plan_evaluation_support import make_command

from trip_agent.domain.shared import CHINA_TIME_ZONE
from trip_agent.feasibility.context import ValidationContext, build_budget_context
from trip_agent.feasibility.inputs import (
    ActivityLocator,
    MealPlacementBinding,
    MealProjectionState,
    MealWindowType,
    ValidationInputs,
)
from trip_agent.feasibility.models import RuleOutcome
from trip_agent.feasibility.rules.meal import assess_meal_window
from trip_agent.worker.contracts import (
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
)


def _meal_activity(
    index: int,
    *,
    day: int = 1,
    start_hour: int,
    start_minute: int = 0,
    start_second: int = 0,
    start_microsecond: int = 0,
    duration_minutes: int = 60,
    duration_seconds: int = 0,
    duration_microseconds: int = 0,
) -> ItineraryActivity:
    start = datetime(
        2026,
        8,
        day,
        start_hour,
        start_minute,
        start_second,
        start_microsecond,
        tzinfo=CHINA_TIME_ZONE,
    )
    return ItineraryActivity(
        activity_id=UUID(int=index + 1),
        title="meal",
        start_time=start,
        end_time=start
        + timedelta(
            minutes=duration_minutes,
            seconds=duration_seconds,
            microseconds=duration_microseconds,
        ),
        estimated_cost=Decimal("0"),
        source="DEMO",
        kind="MEAL",
    )


def _binding(day: int, activity: int, meal_type: MealWindowType) -> MealPlacementBinding:
    return MealPlacementBinding(
        activity=ActivityLocator(day_index=day, activity_index=activity),
        meal_type=meal_type,
    )


def _ctx(
    *days: tuple[tuple[ItineraryActivity, ...], tuple[MealPlacementBinding, ...]],
    meal_windows: tuple[tuple[str, int, int, str | None], ...] = (),
    projection_state: MealProjectionState = MealProjectionState.UNAVAILABLE,
) -> ValidationContext:
    if not days:
        days = (((_meal_activity(0, start_hour=12),), ()),)
    command = make_command(
        meal_windows=tuple(
            {
                "mealType": meal_type,
                "startTime": f"{start:02d}:00",
                "endTime": f"{end:02d}:00",
                **({"source": source} if source is not None else {}),
            }
            for meal_type, start, end, *rest in meal_windows
            for source in (rest[0] if rest else None,)
        )
    )
    itinerary = Itinerary(
        title="meal",
        days=tuple(
            ItineraryDay(
                date=date(2026, 8, day_index + 1),
                activities=activities,
                transit_legs=(),
            )
            for day_index, (activities, _) in enumerate(days)
        ),
        estimated_total_cost=Decimal("0"),
    )
    bindings = tuple(binding for _, day_bindings in days for binding in day_bindings)
    return ValidationContext(
        command=command,
        itinerary=itinerary,
        budget=build_budget_context(command, itinerary),
        validation_inputs=ValidationInputs(
            meal_placement_bindings=bindings,
            meal_projection_state=projection_state,
        ),
    )


def test_no_meal_windows_is_not_applicable() -> None:
    ctx = _ctx()

    assessment = assess_meal_window(ctx)

    assert assessment.result.outcome is RuleOutcome.NOT_APPLICABLE
    assert assessment.result.reason_code == "NO_MEAL_WINDOWS"


def test_unavailable_projection_is_unknown() -> None:
    ctx = _ctx(
        meal_windows=(("LUNCH", 12, 13),),
        projection_state=MealProjectionState.UNAVAILABLE,
    )

    assessment = assess_meal_window(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.reason_code == "MEAL_WINDOW_UNVERIFIED"


def test_complete_projection_missing_placement_fails() -> None:
    ctx = _ctx(
        meal_windows=(("LUNCH", 12, 13),),
        projection_state=MealProjectionState.COMPLETE,
    )

    assessment = assess_meal_window(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "MEAL_PLACEMENT_MISSING"
    assert assessment.result.affected_dates == (date(2026, 8, 1),)


def test_breakfast_missing_fails() -> None:
    ctx = _ctx(
        ((_meal_activity(0, start_hour=12),), (_binding(0, 0, MealWindowType.LUNCH),)),
        meal_windows=(("BREAKFAST", 8, 9), ("LUNCH", 12, 13)),
        projection_state=MealProjectionState.COMPLETE,
    )

    assessment = assess_meal_window(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "MEAL_PLACEMENT_MISSING"


def test_lunch_and_dinner_inside_pass() -> None:
    ctx = _ctx(
        (
            (
                _meal_activity(0, start_hour=12),
                _meal_activity(1, start_hour=18),
            ),
            (
                _binding(0, 0, MealWindowType.LUNCH),
                _binding(0, 1, MealWindowType.DINNER),
            ),
        ),
        meal_windows=(("LUNCH", 12, 13), ("DINNER", 18, 19)),
        projection_state=MealProjectionState.COMPLETE,
    )

    assessment = assess_meal_window(ctx)

    assert assessment.result.outcome is RuleOutcome.PASS
    assert assessment.result.reason_code == "MEAL_WINDOWS_VERIFIED"


def test_placement_outside_window_fails() -> None:
    ctx = _ctx(
        (
            (_meal_activity(0, start_hour=13, start_minute=30),),
            (_binding(0, 0, MealWindowType.LUNCH),),
        ),
        meal_windows=(("LUNCH", 12, 13),),
        projection_state=MealProjectionState.COMPLETE,
    )

    assessment = assess_meal_window(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "MEAL_OUTSIDE_WINDOW"


def test_exact_boundary_passes() -> None:
    ctx = _ctx(
        (
            (_meal_activity(0, start_hour=12, duration_minutes=60),),
            (_binding(0, 0, MealWindowType.LUNCH),),
        ),
        meal_windows=(("LUNCH", 12, 13),),
        projection_state=MealProjectionState.COMPLETE,
    )

    assessment = assess_meal_window(ctx)

    assert assessment.result.outcome is RuleOutcome.PASS


def test_multi_day_one_missing_is_fail() -> None:
    ctx = _ctx(
        ((_meal_activity(0, start_hour=12),), ()),
        ((_meal_activity(1, start_hour=12, day=2),), ()),
        meal_windows=(("LUNCH", 12, 13),),
        projection_state=MealProjectionState.COMPLETE,
    )

    assessment = assess_meal_window(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.affected_dates == (date(2026, 8, 1), date(2026, 8, 2))


def test_wrong_meal_type_does_not_count() -> None:
    ctx = _ctx(
        (
            (_meal_activity(0, start_hour=12),),
            (_binding(0, 0, MealWindowType.DINNER),),
        ),
        meal_windows=(("LUNCH", 12, 13),),
        projection_state=MealProjectionState.COMPLETE,
    )

    assessment = assess_meal_window(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "MEAL_PLACEMENT_MISSING"


def test_naive_activity_time_is_unknown_not_crash() -> None:
    start = datetime(2026, 8, 1, 12)  # naive
    activity = ItineraryActivity(
        activity_id=UUID(int=1),
        title="meal",
        start_time=start,
        end_time=start + timedelta(minutes=60),
        estimated_cost=Decimal("0"),
        source="DEMO",
        kind="MEAL",
    )
    ctx = _ctx(
        ((activity,), (_binding(0, 0, MealWindowType.LUNCH),)),
        meal_windows=(("LUNCH", 12, 13),),
        projection_state=MealProjectionState.COMPLETE,
    )

    assessment = assess_meal_window(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.reason_code == "MEAL_WINDOW_UNVERIFIED"


def test_does_not_mutate_inputs() -> None:
    ctx = _ctx(
        ((_meal_activity(0, start_hour=12),), (_binding(0, 0, MealWindowType.LUNCH),)),
        meal_windows=(("LUNCH", 12, 13),),
        projection_state=MealProjectionState.COMPLETE,
    )
    before = ctx.itinerary.model_dump_json(by_alias=True)

    assess_meal_window(ctx)

    assert ctx.itinerary.model_dump_json(by_alias=True) == before


# ── B5.1 RED 2: exact meal window boundaries ───────────────────────────────


def test_meal_end_one_second_after_window_fails() -> None:
    ctx = _ctx(
        (
            (_meal_activity(0, start_hour=12, duration_minutes=60, duration_seconds=1),),
            (_binding(0, 0, MealWindowType.LUNCH),),
        ),
        meal_windows=(("LUNCH", 12, 13),),
        projection_state=MealProjectionState.COMPLETE,
    )

    assessment = assess_meal_window(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "MEAL_OUTSIDE_WINDOW"


def test_meal_start_one_second_before_window_fails() -> None:
    ctx = _ctx(
        (
            (
                _meal_activity(
                    0,
                    start_hour=11,
                    start_minute=59,
                    start_second=59,
                    duration_minutes=1,
                    duration_seconds=1,
                ),
            ),
            (_binding(0, 0, MealWindowType.LUNCH),),
        ),
        meal_windows=(("LUNCH", 12, 13),),
        projection_state=MealProjectionState.COMPLETE,
    )

    assessment = assess_meal_window(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "MEAL_OUTSIDE_WINDOW"


def test_meal_exact_boundaries_pass() -> None:
    ctx = _ctx(
        (
            (_meal_activity(0, start_hour=12, duration_minutes=60),),
            (_binding(0, 0, MealWindowType.LUNCH),),
        ),
        meal_windows=(("LUNCH", 12, 13),),
        projection_state=MealProjectionState.COMPLETE,
    )

    assessment = assess_meal_window(ctx)

    assert assessment.result.outcome is RuleOutcome.PASS


def test_meal_microsecond_after_window_fails() -> None:
    ctx = _ctx(
        (
            (
                _meal_activity(
                    0,
                    start_hour=12,
                    duration_minutes=60,
                    duration_microseconds=1,
                ),
            ),
            (_binding(0, 0, MealWindowType.LUNCH),),
        ),
        meal_windows=(("LUNCH", 12, 13),),
        projection_state=MealProjectionState.COMPLETE,
    )

    assessment = assess_meal_window(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "MEAL_OUTSIDE_WINDOW"


# ── B13-F: meal window source truth table ───────────────────────────────────


def test_default_only_windows_are_not_hard_constraints() -> None:
    ctx = _ctx(
        meal_windows=(("LUNCH", 12, 13, "DEFAULT"),),
        projection_state=MealProjectionState.COMPLETE,
    )

    assessment = assess_meal_window(ctx)

    assert assessment.result.outcome is RuleOutcome.NOT_APPLICABLE


def test_default_placement_outside_suggestion_is_not_a_fail() -> None:
    ctx = _ctx(
        (
            (_meal_activity(0, start_hour=14),),
            (_binding(0, 0, MealWindowType.LUNCH),),
        ),
        meal_windows=(("LUNCH", 12, 13, "DEFAULT"),),
        projection_state=MealProjectionState.COMPLETE,
    )

    assessment = assess_meal_window(ctx)

    assert assessment.result.outcome is RuleOutcome.NOT_APPLICABLE


def test_disabled_windows_are_never_constrained() -> None:
    ctx = _ctx(
        meal_windows=(("DINNER", 18, 19, "DISABLED"),),
        projection_state=MealProjectionState.COMPLETE,
    )

    assessment = assess_meal_window(ctx)

    assert assessment.result.outcome is RuleOutcome.NOT_APPLICABLE


def test_mixed_windows_only_user_missing_fails() -> None:
    ctx = _ctx(
        meal_windows=(("LUNCH", 12, 13, "USER"), ("DINNER", 18, 19, "DEFAULT")),
        projection_state=MealProjectionState.COMPLETE,
    )

    assessment = assess_meal_window(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "MEAL_PLACEMENT_MISSING"
    assert assessment.result.affected_dates == (date(2026, 8, 1),)


def test_mixed_windows_default_outside_does_not_fail_user_inside() -> None:
    ctx = _ctx(
        (
            (
                _meal_activity(0, start_hour=12),
                _meal_activity(1, start_hour=15),
            ),
            (
                _binding(0, 0, MealWindowType.LUNCH),
                _binding(0, 1, MealWindowType.DINNER),
            ),
        ),
        meal_windows=(("LUNCH", 12, 13, "USER"), ("DINNER", 18, 19, "DEFAULT")),
        projection_state=MealProjectionState.COMPLETE,
    )

    assessment = assess_meal_window(ctx)

    assert assessment.result.outcome is RuleOutcome.PASS
    assert assessment.result.reason_code == "MEAL_WINDOWS_VERIFIED"


def test_source_less_window_is_treated_as_user() -> None:
    # Historical trips carry meal windows without a source; they must keep
    # their hard-constraint semantics (never downgraded to a suggestion).
    ctx = _ctx(
        (
            (_meal_activity(0, start_hour=14),),
            (_binding(0, 0, MealWindowType.LUNCH),),
        ),
        meal_windows=(("LUNCH", 12, 13),),
        projection_state=MealProjectionState.COMPLETE,
    )

    assessment = assess_meal_window(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "MEAL_OUTSIDE_WINDOW"
