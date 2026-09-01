"""V3 P2-0 — the one-shot planning context view (audit §6, V2 audit §15.3).

``PlanningContextView`` is the resolved planning input snapshot: weather,
budget and mobility context parsed ONCE per plan instead of being re-derived
at every decision point.  It is a frozen, inert value object — no setters, no
side effects, no decision logic, never serialized, never persisted.

The module also hosts the context resolver functions that used to live in
``infrastructure/amap/planning_provider.py`` (moved verbatim so behaviour is
byte-identical); the provider re-exports them for backwards compatibility.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from trip_agent.planning.budget_policy import (
    BudgetPressure,
    activity_cost_ceiling,
    budget_per_person_per_day,
    budget_pressure,
)
from trip_agent.planning.cost_model import ResolvedCost, resolve_attraction_cost
from trip_agent.planning.transport_strategy import (
    TransportStrategy,
    resolve_transport_strategy,
)
from trip_agent.planning.weather_policy import (
    WeatherLevel,
    classify_weather_level,
    walking_threshold_for,
)

if TYPE_CHECKING:
    from trip_agent.providers.map import Poi
    from trip_agent.worker.contracts import (
        GuideFactEvidence,
        PlanningContextFact,
        PlanningContextSnapshot,
        PlanningCreateCommand,
        PlanningReplanCommand,
    )


def weather_statements_for_date(
    facts: tuple[GuideFactEvidence, ...],
    trip_date: date,
) -> tuple[str, ...]:
    """Return only structured weather evidence that applies to one trip day."""
    return tuple(
        f"{fact.statement} {fact.evidence}"
        for fact in facts
        if fact.category == "WEATHER" and fact.effective_date == trip_date
    )


def planning_context_weather_statements(
    context: PlanningContextSnapshot | None,
    trip_date: date,
) -> tuple[str, ...]:
    """Weather statements from the frozen planning-context snapshot.

    Facts without an effective date apply to every trip day (the same
    applicability rule ``planning_fact_impacts`` uses).
    """
    if context is None:
        return ()
    return tuple(
        f"{fact.statement} {fact.evidence}"
        for fact in context.facts
        if fact.category == "WEATHER"
        and (fact.effective_date is None or fact.effective_date == trip_date)
    )


def weather_level_for_date(
    command: PlanningCreateCommand | PlanningReplanCommand,
    trip_date: date,
) -> WeatherLevel | None:
    """Most severe weather level for one trip day; None when unknown."""
    statements = (
        *weather_statements_for_date(command.payload.guide_evidence.facts, trip_date),
        *planning_context_weather_statements(command.payload.planning_context, trip_date),
    )
    return classify_weather_level(statements)


def walking_threshold_seconds_for_date(
    command: PlanningCreateCommand | PlanningReplanCommand,
    trip_date: date,
) -> int:
    """V1 weather-aware walking policy for one trip day.

    Combines guide-evidence and planning-context weather facts, classifies
    the most severe level, and maps it to a walking threshold.  No weather
    signal keeps the 20-minute product default.
    """
    return walking_threshold_for(weather_level_for_date(command, trip_date))


def trip_day_count(command: PlanningCreateCommand | PlanningReplanCommand) -> int:
    trip = command.payload.trip
    return (trip.end_date - trip.start_date).days + 1


def attraction_cost_hints(
    command: PlanningCreateCommand | PlanningReplanCommand,
    pois: tuple[Poi, ...],
) -> dict[str, ResolvedCost]:
    """Per-candidate attraction cost, resolved once before ranking (no I/O).

    Recall may surface the same provider id through several keywords; the
    hint map is keyed by id, so duplicates resolve once (first occurrence
    wins) — the resulting dict is identical, the redundant work is not done.
    """
    context = command.payload.planning_context
    facts = context.facts if context is not None else ()
    travelers = command.payload.trip.constraints.travelers
    seen: dict[str, Poi] = {}
    for poi in pois:
        seen.setdefault(poi.provider_id, poi)
    return {
        poi.provider_id: resolve_attraction_cost(facts, poi.name, travelers=travelers)
        for poi in seen.values()
    }


def budget_pressure_for(
    command: PlanningCreateCommand | PlanningReplanCommand,
) -> BudgetPressure | None:
    """Trip-level budget pressure; None when no budget was stated."""
    constraints = command.payload.trip.constraints
    return budget_pressure(
        budget_per_person_per_day(
            constraints.budget_amount,
            constraints.travelers,
            trip_day_count(command),
        )
    )


def resolve_transport_strategy_for_date(
    command: PlanningCreateCommand | PlanningReplanCommand,
    trip_date: date,
) -> TransportStrategy:
    """P1-3: resolve weather × budget × mobility into transport parameters."""
    return resolve_transport_strategy(
        weather_level=weather_level_for_date(command, trip_date),
        budget_pressure=budget_pressure_for(command),
        mobility_reduced=command.payload.trip.constraints.mobility_level == "REDUCED",
    )


@dataclass(frozen=True, slots=True)
class DayContext:
    """Resolved context for ONE trip day (built once, consumed read-only)."""

    trip_date: date
    weather_level: WeatherLevel | None
    transport_strategy: TransportStrategy

    @property
    def walking_threshold_seconds(self) -> int:
        return self.transport_strategy.walking_threshold_seconds


@dataclass(frozen=True, slots=True)
class PlanningContextView:
    """The planning input snapshot: context parsed once, consumed everywhere.

    Inert by design — plain resolved values plus per-day contexts.  Decisions
    stay in the policies; nothing here mutates business state.
    """

    budget_per_person_per_day: Decimal | None
    budget_pressure: BudgetPressure | None
    activity_cost_ceiling: Decimal | None
    facts: tuple[PlanningContextFact, ...]
    cost_hints: Mapping[str, ResolvedCost]
    days: tuple[DayContext, ...]


def build_context_view(
    command: PlanningCreateCommand | PlanningReplanCommand,
    *,
    candidate_pois: tuple[Poi, ...],
) -> PlanningContextView:
    """Parse the whole planning context exactly once (audit P2-0)."""
    constraints = command.payload.trip.constraints
    context = command.payload.planning_context
    per_person_per_day = budget_per_person_per_day(
        constraints.budget_amount,
        constraints.travelers,
        trip_day_count(command),
    )
    pressure = budget_pressure(per_person_per_day)
    mobility_reduced = constraints.mobility_level == "REDUCED"
    days: list[DayContext] = []
    for offset in range(trip_day_count(command)):
        trip_date = command.payload.trip.start_date + timedelta(days=offset)
        # One weather resolution per day — never twice (P2-0 discipline).
        level = weather_level_for_date(command, trip_date)
        days.append(
            DayContext(
                trip_date=trip_date,
                weather_level=level,
                transport_strategy=resolve_transport_strategy(
                    weather_level=level,
                    budget_pressure=pressure,
                    mobility_reduced=mobility_reduced,
                ),
            )
        )
    return PlanningContextView(
        budget_per_person_per_day=per_person_per_day,
        budget_pressure=pressure,
        activity_cost_ceiling=activity_cost_ceiling(per_person_per_day),
        facts=context.facts if context is not None else (),
        cost_hints=attraction_cost_hints(command, candidate_pois),
        days=days,
    )
