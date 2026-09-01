"""V3 P2-0 — the planning context is parsed exactly once per plan.

The audit's P2-0 acceptance requires proving that context resolution is no
longer repeated at every decision point: weather is resolved once per day,
budget pressure once per plan, and per-candidate attraction costs once for
the whole pipeline (the emit phase reuses the view's hints instead of
re-resolving).  Counters are attached around the real plan() run — no
mocked planner, only counted resolvers.
"""

import asyncio
from unittest import mock

from test_planning_intelligence_v1 import (
    _single_day_payload,
    _weather_map_provider,
    _weather_route_provider,
)

from trip_agent.infrastructure.amap import day_emitter as emitter_module
from trip_agent.infrastructure.amap import planning_provider as provider_module
from trip_agent.planning import context_view
from trip_agent.worker.contracts import PlanningCreateCommand


def _command(days: int) -> PlanningCreateCommand:
    payload = _single_day_payload("8 月 1 日晴天，26℃。")
    end = f"2026-08-{1 + days - 1:02d}"
    payload["payload"]["trip"]["endDate"] = end
    # The context identity must match the trip window (command validator).
    payload["payload"]["planningContext"]["travelEndDate"] = end
    return PlanningCreateCommand.model_validate(payload)


def _run_counted(command: PlanningCreateCommand) -> dict[str, int]:
    """Run the real pipeline with counters on every context resolver."""
    counts = {"weather_view": 0, "weather_emit_fallback": 0, "pressure": 0, "cost": 0}

    original_weather = context_view.weather_level_for_date
    original_pressure = context_view.budget_pressure
    original_cost = context_view.resolve_attraction_cost
    # F-4.1: the emit-phase resolvers moved to the day_emitter module, so the
    # fallback counters patch that namespace (patching the facade module would
    # silently no-op and stop guarding the "no re-resolve in emit" property).
    provider_cost = emitter_module.resolve_attraction_cost
    provider_weather = emitter_module.weather_level_for_date

    def counting_weather(command_, trip_date):
        counts["weather_view"] += 1
        return original_weather(command_, trip_date)

    def counting_pressure(per_person_per_day):
        counts["pressure"] += 1
        return original_pressure(per_person_per_day)

    def counting_cost(*args, **kwargs):
        counts["cost"] += 1
        return original_cost(*args, **kwargs)

    def counting_cost_provider(*args, **kwargs):
        counts["cost"] += 1
        return provider_cost(*args, **kwargs)

    def counting_weather_emit(*args, **kwargs):
        counts["weather_emit_fallback"] += 1
        return provider_weather(*args, **kwargs)

    route = _weather_route_provider(walking_duration=800, road_duration=600)
    planner = provider_module.AmapPlanningProvider(
        _weather_map_provider(), route, route
    )
    with (
        mock.patch.object(context_view, "weather_level_for_date", counting_weather),
        mock.patch.object(context_view, "budget_pressure", counting_pressure),
        mock.patch.object(context_view, "resolve_attraction_cost", counting_cost),
        mock.patch.object(
            emitter_module, "resolve_attraction_cost", counting_cost_provider
        ),
        mock.patch.object(
            emitter_module, "weather_level_for_date", counting_weather_emit
        ),
    ):
        asyncio.run(planner.plan(command))
    return counts


def test_context_resolved_once_per_day_and_once_per_budget() -> None:
    """3-day trip: weather exactly 3× (once per day), budget pressure exactly
    1× for the whole plan, and the emit phase never re-resolves weather."""
    counts = _run_counted(_command(days=3))

    assert counts["weather_view"] == 3, counts
    assert counts["weather_emit_fallback"] == 0, counts
    assert counts["pressure"] == 1, counts


def test_attraction_costs_resolved_once_per_unique_candidate() -> None:
    """Two unique candidates → exactly two cost resolutions for the whole
    pipeline.  Recall surfaces each candidate through several keywords, but
    the hint map resolves per UNIQUE candidate (duplicates used to re-resolve
    the same POI once per recall hit), and the emit phase consumes the hints
    instead of re-resolving."""
    counts = _run_counted(_command(days=1))

    assert counts["cost"] == 2, counts


def test_view_is_frozen_and_inert() -> None:
    """The view is a frozen value object: no setters, no business state."""
    import dataclasses

    from trip_agent.planning.context_view import PlanningContextView

    assert dataclasses.is_dataclass(PlanningContextView)
    assert PlanningContextView.__dataclass_params__.frozen is True
    assert PlanningContextView.__dataclass_params__.slots is True
    fields = {field.name for field in dataclasses.fields(PlanningContextView)}
    assert fields == {
        "budget_per_person_per_day",
        "budget_pressure",
        "activity_cost_ceiling",
        "facts",
        "cost_hints",
        "days",
    }
