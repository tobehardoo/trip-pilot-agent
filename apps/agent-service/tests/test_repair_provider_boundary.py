from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal

from test_local_replanning import REPLAN_COMMAND

from trip_agent.application.replan_service import LocalReplanningProvider
from trip_agent.domain.planning.protocols import PlanningRepairRequest, PlanningResult
from trip_agent.feasibility.inputs import ValidationInputs
from trip_agent.providers.errors import ProviderErrorCategory, ProviderExecutionMode
from trip_agent.providers.map import ProviderFailure, ProviderSuccess
from trip_agent.providers.route import RoutePlan, RouteStep
from trip_agent.worker.contracts import Itinerary, PlanningReplanCommand


class _Routes:
    def __init__(self, *, mode: str | None = None, estimated_cost: float | None = None) -> None:
        self.requests: list[object] = []
        self.mode = mode
        self.estimated_cost = estimated_cost

    async def get_route(self, request):
        self.requests.append(request)
        return ProviderSuccess(
            data=RoutePlan(
                mode=self.mode or request.mode,
                distance_meters=500,
                duration_seconds=300,
                steps=(
                    RouteStep(
                        instruction="walk",
                        distance_meters=500,
                        duration_seconds=300,
                        polyline=(request.origin, request.destination),
                    ),
                ),
                polyline=(request.origin, request.destination),
                estimated_cost=self.estimated_cost,
            ),
            provider="AMAP",
            latency_ms=1,
            cached=False,
            fetched_at=datetime(2026, 8, 1, tzinfo=UTC),
            estimated=False,
        )


def _candidate() -> tuple[PlanningReplanCommand, PlanningResult]:
    raw = deepcopy(REPLAN_COMMAND)
    raw["payload"]["impactedDates"] = ["2026-08-01"]
    command = PlanningReplanCommand.model_validate(raw)
    itinerary = Itinerary(
        title=command.payload.itinerary.title,
        days=tuple(day.to_itinerary_day() for day in command.payload.itinerary.days),
        estimated_total_cost=command.payload.itinerary.estimated_total_cost,
    )
    result = PlanningResult(
        provider="AMAP",
        itinerary=itinerary,
        validation_inputs=ValidationInputs(),
    )
    return command, result


def test_repair_provider_refreshes_only_requested_days_and_preserves_inputs() -> None:
    command, candidate = _candidate()
    routes = _Routes()
    provider = LocalReplanningProvider(routes)

    repaired = asyncio.run(
        provider.repair(
            PlanningRepairRequest(
                command=command,
                candidate=candidate,
                impacted_dates=(date(2026, 8, 1),),
                attempt_index=1,
            )
        )
    )

    assert len(routes.requests) == 1
    assert repaired.itinerary.days[0].transit_legs
    assert repaired.itinerary.days[1] is candidate.itinerary.days[1]
    # B9.1: repair re-projects inputs from the repaired itinerary instead of
    # reusing the stale pre-repair bindings/locators.
    assert repaired.validation_inputs is not None
    assert repaired.validation_inputs is not candidate.validation_inputs


def test_repair_provider_preserves_day_type_but_hides_driving_toll() -> None:
    command, candidate = _candidate()
    first_day = candidate.itinerary.days[0].model_copy(update={"day_type": "ARRIVAL_DAY"})
    candidate = PlanningResult(
        provider="AMAP",
        itinerary=candidate.itinerary.model_copy(
            update={"days": (first_day, *candidate.itinerary.days[1:])}
        ),
        validation_inputs=candidate.validation_inputs,
        requested_provider_mode="REAL_ONLY",
        primary_provider="AMAP",
        actual_providers=("AMAP",),
    )
    provider = LocalReplanningProvider(_Routes(mode="DRIVING", estimated_cost=12.345))

    repaired = asyncio.run(
        provider.repair(
            PlanningRepairRequest(
                command=command,
                candidate=candidate,
                impacted_dates=(date(2026, 8, 1),),
                attempt_index=1,
            )
        )
    )

    leg = repaired.itinerary.days[0].transit_legs[0]
    assert repaired.itinerary.days[0].day_type == "ARRIVAL_DAY"
    assert leg.estimated_cost is None
    assert leg.cost_source == "UNKNOWN"


class _FailedRoutes:
    async def get_route(self, _request):
        return ProviderFailure(
            provider="AMAP",
            error_code="PROVIDER_TIMEOUT",
            error_message="route timed out",
            category=ProviderErrorCategory.TIMEOUT,
            operation="ROUTE",
            retryable=True,
            retry_count=1,
            retry_exhausted=True,
            latency_ms=1,
            fetched_at=datetime(2026, 8, 1, tzinfo=UTC),
        )


class _DemoRoutes:
    async def get_route(self, request):
        return ProviderSuccess(
            data=RoutePlan(
                mode=request.mode,
                distance_meters=500,
                duration_seconds=300,
                steps=(
                    RouteStep(
                        instruction="estimated route",
                        distance_meters=500,
                        duration_seconds=300,
                        polyline=(request.origin, request.destination),
                    ),
                ),
                polyline=(request.origin, request.destination),
                estimated_cost=Decimal("8.50"),
            ),
            provider="DEMO",
            latency_ms=1,
            cached=False,
            fetched_at=datetime(2026, 8, 1, tzinfo=UTC),
            estimated=True,
        )


def test_repair_provider_rebuilds_provenance_after_route_fallback() -> None:
    command, candidate = _candidate()
    candidate = PlanningResult(
        provider="AMAP",
        itinerary=candidate.itinerary,
        validation_inputs=candidate.validation_inputs,
        requested_provider_mode="REAL_WITH_EXPLICIT_FALLBACK",
        primary_provider="AMAP",
        actual_providers=("AMAP",),
    )
    provider = LocalReplanningProvider(
        _FailedRoutes(),
        _DemoRoutes(),
        provider_mode=ProviderExecutionMode.REAL_WITH_EXPLICIT_FALLBACK,
    )

    repaired = asyncio.run(
        provider.repair(
            PlanningRepairRequest(
                command=command,
                candidate=candidate,
                impacted_dates=(date(2026, 8, 1),),
                attempt_index=1,
            )
        )
    )

    assert repaired.actual_providers == ("AMAP", "DEMO")
    assert repaired.fallback_attempted is True
    assert repaired.fallback_succeeded is True
    assert repaired.fallback_reason == "ROUTE_PROVIDER_FAILURE"
    assert len(repaired.fallback_operations) == 1
    assert repaired.itinerary.days[0].transit_legs[0].provider == "DEMO"
    assert repaired.provider_provenance() is not None


def test_repair_provider_rejects_more_than_three_dates() -> None:
    command, candidate = _candidate()

    try:
        PlanningRepairRequest(
            command=command,
            candidate=candidate,
            impacted_dates=tuple(date(2026, 8, day) for day in (1, 2, 3, 4)),
            attempt_index=1,
        )
    except ValueError as error:
        assert "three" in str(error)
    else:
        raise AssertionError("expected a bounded repair-date failure")
