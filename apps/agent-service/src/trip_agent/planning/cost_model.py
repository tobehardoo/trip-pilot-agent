"""Deterministic cost resolution with explicit provenance (P0 Data-Truth).

Cost priority chain per activity / meal:

    1. PROVIDER       — a trusted knowledge fact with a structured amount
                        (TICKET_PRICE for attractions, REFERENCE_SPEND for
                        meals, ``normalizedValue.amount`` in CNY)
    2. RULE_ESTIMATE  — deterministic fallback constants (documented below)

Invariants:

* A cost of 0 is only ever produced by an explicit provider fact (free
  admission, amount == 0).  "Unknown" never collapses to 0.
* P1-4: per-person prices are scaled by the party size for every
  per-person cost category (tickets, meals and public-transit fares).
  Per-vehicle costs (DRIVING tolls) and per-room costs (accommodation)
  are NOT scaled — scaling one category alone distorts the budget ratio.
* Every resolved cost carries its ``cost_source`` so downstream consumers
  (explanations, evaluation, budget checks) can reason about trust.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from trip_agent.domain.shared import AMAP_ACTIVITY_ESTIMATED_COST, text_matches

if TYPE_CHECKING:
    from trip_agent.worker.contracts import PlanningContextFact

type CostSource = Literal[
    "PROVIDER",
    "RULE_ESTIMATE",
    "CATEGORY_ESTIMATE",
    "CITY_ESTIMATE",
    "DEMO",
    "UNKNOWN",
]

# Fallback attraction estimate: the historical calibrated flat constant
# (domain/shared.py).  Kept flat in P0 on purpose — see module docstring.
FALLBACK_ATTRACTION_COST = AMAP_ACTIVITY_ESTIMATED_COST

# Fallback per-meal per-person estimate when no REFERENCE_SPEND fact exists.
# A meal always happens, so "unknown" must not silently read as free; the
# constant is a deliberate, documented product default and easy to adjust.
DEFAULT_MEAL_COST = Decimal("50.00")

# P1-5: fallback accommodation estimate, per ROOM per NIGHT (not per person —
# a room is shared, so this cost must not scale with the party size).
# Product decision to confirm: accommodation IS counted against the trip
# budget, because a multi-day budget that ignores lodging is fiction.
DEFAULT_ACCOMMODATION_PER_NIGHT = Decimal("300.00")

# Transit modes whose cost is charged per traveller.  A DRIVING toll is
# charged per vehicle, so it must never scale with the party size.
PARTY_SCALED_MODES = frozenset({"TRANSIT"})

_TICKET_CATEGORIES = frozenset({"TICKET_PRICE"})
_SPEND_CATEGORIES = frozenset({"REFERENCE_SPEND"})


@dataclass(frozen=True, slots=True)
class ResolvedCost:
    amount: Decimal
    source: CostSource


def _fact_amount(fact: PlanningContextFact) -> Decimal | None:
    value = (fact.normalized_value or {}).get("amount")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if value < 0:
        return None
    return Decimal(str(value))


def collect_prices(
    facts: tuple[PlanningContextFact, ...],
    target_name: str,
    categories: frozenset[str],
) -> tuple[Decimal, ...]:
    """Structured amounts of fresh, target-matching facts (deterministic order)."""
    prices: list[Decimal] = []
    for fact in facts:
        if fact.category not in categories or fact.stale:
            continue
        amount = _fact_amount(fact)
        if amount is None:
            continue
        if text_matches(target_name, f"{fact.statement} {fact.evidence}"):
            prices.append(amount)
    return tuple(prices)


def _preferred_price(prices: tuple[Decimal, ...]) -> Decimal:
    """Deterministic pick: the first price (fact order) wins."""
    return prices[0]


def resolve_attraction_cost(
    facts: tuple[PlanningContextFact, ...],
    poi_name: str,
    *,
    travelers: int = 1,
) -> ResolvedCost:
    """Attraction cost: official ticket price when known, fallback otherwise.

    A matched amount of 0 is honoured as "free admission" (PROVIDER, 0).
    Ticket prices are per person, so both the provider price and the
    fallback allowance scale with the party size.
    """
    scaled = max(travelers, 1)
    prices = collect_prices(facts, poi_name, _TICKET_CATEGORIES)
    if prices:
        return ResolvedCost(
            amount=_preferred_price(prices) * scaled, source="PROVIDER"
        )
    return ResolvedCost(
        amount=FALLBACK_ATTRACTION_COST * scaled, source="RULE_ESTIMATE"
    )


def resolve_meal_cost(
    facts: tuple[PlanningContextFact, ...],
    restaurant_name: str,
    *,
    travelers: int = 1,
) -> ResolvedCost:
    """Meal cost: per-person spend fact when known, documented default otherwise."""
    scaled = max(travelers, 1)
    spends = collect_prices(facts, restaurant_name, _SPEND_CATEGORIES)
    if spends:
        return ResolvedCost(amount=_preferred_price(spends) * scaled, source="PROVIDER")
    return ResolvedCost(amount=DEFAULT_MEAL_COST * scaled, source="RULE_ESTIMATE")


def resolve_transit_cost(
    amount: Decimal | None,
    *,
    mode: str,
    travelers: int = 1,
) -> Decimal | None:
    """Scale a transit fare by the party size when the mode is per person."""
    if amount is None:
        return None
    if mode not in PARTY_SCALED_MODES:
        return amount
    return amount * max(travelers, 1)


def provider_priced_titles(
    activities: Iterable[object],
) -> frozenset[str]:
    """Titles of activities whose cost actually came from a provider fact."""
    return frozenset(
        activity.title  # type: ignore[attr-defined]
        for activity in activities
        if getattr(activity, "cost_source", None) == "PROVIDER"
    )
