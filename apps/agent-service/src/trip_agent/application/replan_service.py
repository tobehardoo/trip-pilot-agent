"""Local replanning provider — refreshes transit legs for impacted days only.

Extracted from ``worker/processor.py``.
"""

from decimal import Decimal

from trip_agent.domain.planning.protocols import (
    PlanningInfeasibleError,
    PlanningProviderError,
    PlanningResult,
)
from trip_agent.domain.shared import coordinate_decimal
from trip_agent.planning.optimization import OptimizationConflict, RelaxationSuggestion
from trip_agent.providers._demo_route import DemoRouteProvider
from trip_agent.providers.map import Coordinates, ProviderFailure, ProviderSuccess
from trip_agent.providers.route import RoutePlan, RouteProvider, RouteRequest
from trip_agent.worker.contracts import (
    ActivityCoordinates,
    Itinerary,
    ItineraryDay,
    PlanningReplanCommand,
    ReplanItineraryDay,
    TransitLeg,
)
from trip_agent.worker.progress import report_planning_progress


class LocalReplanningProvider:
    """Re‑route impacted days while keeping existing activities intact.

    Only dates listed in ``command.payload.impacted_dates`` are re‑routed;
    all other days are returned as‑is from the baseline itinerary snapshot.
    Locked activities are preserved by the caller (Java side) before the
    replan command is issued, so this provider only needs to handle transit
    refresh.
    """

    def __init__(
        self,
        route_provider: RouteProvider,
        route_fallback: RouteProvider | None = None,
    ) -> None:
        self._route_provider = route_provider
        self._route_fallback = route_fallback or DemoRouteProvider()

    async def replan(self, command: PlanningReplanCommand) -> PlanningResult:
        snapshot = command.payload.itinerary
        impacted_dates = set(command.payload.impacted_dates)
        await report_planning_progress(
            "ROUTES_CALCULATING",
            "Refreshing routes for the impacted itinerary days",
            {"impactedDays": len(impacted_dates)},
        )
        days: list[ItineraryDay] = []
        for day in snapshot.days:
            replanned = (
                await self._replan_day(day)
                if day.date in impacted_dates
                else day.to_itinerary_day()
            )
            days.append(replanned)
        return PlanningResult(
            provider=snapshot.provider,
            itinerary=Itinerary(
                title=snapshot.title,
                days=tuple(days),
                estimated_total_cost=snapshot.estimated_total_cost,
            ),
        )

    async def _replan_day(self, day: ReplanItineraryDay) -> ItineraryDay:
        legs: list[TransitLeg] = []
        for index, (origin, destination) in enumerate(
            zip(day.activities, day.activities[1:], strict=False)
        ):
            if origin.coordinates is None or destination.coordinates is None:
                raise PlanningInfeasibleError(
                    conflicts=(
                        OptimizationConflict(
                            "REPLAN_ACTIVITY_COORDINATES_MISSING",
                            "Local replanning requires coordinates for adjacent activities",
                            (origin.title, destination.title),
                        ),
                    ),
                    relaxations=(
                        RelaxationSuggestion(
                            "RUN_FULL_REPLAN",
                            "Run a full plan to resolve activities without map coordinates",
                        ),
                    ),
                )
            existing_leg = (
                day.transit_legs[index]
                if index < len(day.transit_legs)
                else None
            )
            route = await self._route(
                RouteRequest(
                    origin=Coordinates(
                        longitude=float(origin.coordinates.longitude),
                        latitude=float(origin.coordinates.latitude),
                    ),
                    destination=Coordinates(
                        longitude=float(destination.coordinates.longitude),
                        latitude=float(destination.coordinates.latitude),
                    ),
                    mode=(
                        existing_leg.mode
                        if existing_leg is not None
                        else "WALKING"
                    ),
                    departure_at=origin.end_time,
                    origin_poi_id=origin.provider_poi_id,
                    destination_poi_id=destination.provider_poi_id,
                )
            )
            leg_cost = Decimal("0.00") if route.data.mode == "WALKING" else None
            cost_source = "RULE_ESTIMATE" if route.data.mode == "WALKING" else (
                "DEMO" if route.provider == "DEMO" else "UNKNOWN"
            )
            legs.append(
                TransitLeg(
                    from_activity_index=index,
                    to_activity_index=index + 1,
                    mode=route.data.mode,
                    distance_meters=route.data.distance_meters,
                    duration_seconds=route.data.duration_seconds,
                    provider=route.provider,
                    estimated=route.estimated,
                    polyline=tuple(
                        ActivityCoordinates(
                            longitude=coordinate_decimal(point.longitude),
                            latitude=coordinate_decimal(point.latitude),
                        )
                        for point in route.data.polyline
                    ),
                    estimated_cost=leg_cost,
                    cost_source=cost_source,
                )
            )
        return ItineraryDay(
            date=day.date,
            activities=day.activities,
            transit_legs=tuple(legs),
        )

    async def _route(
        self, request: RouteRequest
    ) -> ProviderSuccess[RoutePlan]:
        result = await self._route_provider.get_route(request)
        if isinstance(result, ProviderFailure):
            result = await self._route_fallback.get_route(request)
        if isinstance(result, ProviderFailure):
            raise PlanningProviderError(result.error_code)
        if result.provider not in {"AMAP", "DEMO"}:
            raise PlanningProviderError("UNEXPECTED_ROUTE_PROVIDER")
        if (result.provider == "AMAP" and result.estimated) or (
            result.provider == "DEMO" and not result.estimated
        ):
            raise RuntimeError(
                "route provider returned inconsistent source metadata"
            )
        return result
