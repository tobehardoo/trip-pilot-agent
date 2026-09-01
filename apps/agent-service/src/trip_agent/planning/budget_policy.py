"""Deterministic budget pressure derivation (pure, no I/O).

Budget pressure is resolved ONCE per plan and then consumed by the ranking
layer (P1-2) and the transport strategy (P1-3).  Context is resolved before
optimization — the solver never sees a raw budget amount.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

type BudgetPressure = Literal["TIGHT", "NORMAL", "RELAXED"]

# Per-person, per-day thresholds (CNY).  A trip under 300/day/person cannot
# absorb discretionary spending; above 800/day/person the budget is not the
# binding constraint.  Both are documented product constants, easy to adjust.
TIGHT_BUDGET_PER_PERSON_PER_DAY = Decimal("300")
RELAXED_BUDGET_PER_PERSON_PER_DAY = Decimal("800")

# A single attraction should not consume more than ~35% of one person's
# daily budget before it starts losing ground in the ranking.
ACTIVITY_CEILING_RATIO = Decimal("0.35")

# V3 P2-1: a day's dining should not consume more than ~30% of one person's
# daily budget.  The ratio yields a per-meal SOFT envelope (split across the
# day's meals): overspending picks a pricier place anyway and only records a
# BUDGET_CONSTRAINT trace — a meal always happens, hunger is not an output.
MEAL_BUDGET_RATIO = Decimal("0.30")


def budget_per_person_per_day(
    budget_amount: Decimal | None,
    travelers: int,
    day_count: int,
) -> Decimal | None:
    """Per-person daily budget, or None when the budget is unknown.

    A missing or non-positive budget yields ``None`` (NOT_APPLICABLE): the
    absence of a constraint must never read as pressure.
    """
    if budget_amount is None or budget_amount <= 0:
        return None
    if travelers < 1 or day_count < 1:
        return None
    return Decimal(budget_amount) / Decimal(travelers * day_count)


def budget_pressure(
    per_person_per_day: Decimal | None,
) -> BudgetPressure | None:
    """Classify budget pressure; None when no budget was stated."""
    if per_person_per_day is None:
        return None
    if per_person_per_day < TIGHT_BUDGET_PER_PERSON_PER_DAY:
        return "TIGHT"
    if per_person_per_day <= RELAXED_BUDGET_PER_PERSON_PER_DAY:
        return "NORMAL"
    return "RELAXED"


def activity_cost_ceiling(per_person_per_day: Decimal | None) -> Decimal | None:
    """Per-activity affordability ceiling used by budget-aware ranking."""
    if per_person_per_day is None:
        return None
    return per_person_per_day * ACTIVITY_CEILING_RATIO


def meal_budget_envelope(
    per_person_per_day: Decimal | None,
    meal_count: int,
) -> Decimal | None:
    """Per-meal, per-person SOFT dining envelope (V3 P2-1).

    ``per_person_per_day × MEAL_BUDGET_RATIO`` split across the day's meals.
    None when no budget was stated or the day reserves no meals — the absence
    of a constraint must never read as pressure.  The envelope only steers
    restaurant selection and tracing; it never removes a meal.
    """
    if per_person_per_day is None or meal_count < 1:
        return None
    return (per_person_per_day * MEAL_BUDGET_RATIO / meal_count).quantize(
        Decimal("0.01")
    )
