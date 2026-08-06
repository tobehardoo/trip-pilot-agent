"""Local replanning provider — refreshes transit legs for impacted days only.

Extracted from ``worker/processor.py``.
"""

import logging
from decimal import Decimal
from uuid import UUID, uuid5

from trip_agent.domain.planning.protocols import (
    OptimizationConflict,
    PlanningInfeasibleError,
    PlanningProviderError,
    PlanningResult,
    RelaxationSuggestion,
)
from trip_agent.domain.shared import coordinate_decimal
from trip_agent.providers.errors import (
    FallbackDecision,
    ProviderExecutionMode,
    ProviderFallbackPolicy,
    ProviderOperation,
)
from trip_agent.providers.map import Coordinates, ProviderFailure, ProviderSuccess
from trip_agent.providers.route import RoutePlan, RouteProvider, RouteRequest
from trip_agent.worker.contracts import (
    ActivityCoordinates,
    FallbackOperation,
    Itinerary,
    ItineraryDay,
    PlanningReplanCommand,
    ReplanItineraryDay,
    TransitLeg,
)
from trip_agent.worker.progress import report_planning_progress

logger = logging.getLogger(__name__)


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
        *,
        provider_mode: ProviderExecutionMode = ProviderExecutionMode.REAL_ONLY,
        fallback_policy: ProviderFallbackPolicy | None = None,
    ) -> None:
        self._route_provider = route_provider
        self._route_fallback = route_fallback
        self._provider_mode = provider_mode
        self._fallback_policy = fallback_policy or ProviderFallbackPolicy()

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
                await self._replan_day(day, command.task_id)
                if day.date in impacted_dates
                else day.to_itinerary_day()
            )
            days.append(replanned)
        actual_providers = tuple(sorted({
            activity.source
            for day in days
            for activity in day.activities
        } | {
            leg.provider
            for day in days
            for leg in day.transit_legs
        }))
        fallback_operations = tuple(
            leg.fallback_operation
            for day in days
            for leg in day.transit_legs
            if leg.fallback_operation is not None
        )
        used_route_fallback = bool(fallback_operations)
        primary_provider = (
            "DEMO"
            if self._provider_mode == ProviderExecutionMode.DEMO_ONLY
            else "AMAP"
        )
        itinerary = Itinerary(
            title=snapshot.title,
            days=tuple(days),
            estimated_total_cost=snapshot.estimated_total_cost,
        )
        if not self._can_record_provenance(actual_providers, used_route_fallback):
            logger.warning(
                "replan_provider_provenance_unrecorded mode=%s actual_providers=%s task_id=%s",
                self._provider_mode.value,
                actual_providers,
                command.task_id,
            )
            return PlanningResult(provider=snapshot.provider, itinerary=itinerary)
        return PlanningResult(
            provider=snapshot.provider,
            itinerary=itinerary,
            requested_provider_mode=self._provider_mode.value,
            primary_provider=primary_provider,
            actual_providers=actual_providers,
            fallback_attempted=used_route_fallback,
            fallback_succeeded=used_route_fallback,
            fallback_reason=("ROUTE_PROVIDER_FAILURE" if used_route_fallback else None),
            fallback_operations=fallback_operations,
        )

    def _can_record_provenance(
        self,
        actual_providers: tuple[str, ...],
        used_route_fallback: bool,
    ) -> bool:
        if self._provider_mode == ProviderExecutionMode.DEMO_ONLY:
            return actual_providers == ("DEMO",) and not used_route_fallback
        if self._provider_mode == ProviderExecutionMode.REAL_ONLY:
            return actual_providers == ("AMAP",) and not used_route_fallback
        if used_route_fallback:
            return "DEMO" in actual_providers
        return actual_providers == ("AMAP",)

    async def _replan_day(self, day: ReplanItineraryDay, task_id: UUID) -> ItineraryDay:
        activities = tuple(
            activity
            if activity.activity_id is not None
            else activity.model_copy(
                update={
                    "activity_id": uuid5(
                        task_id,
                        "replan-activity:"
                        f"{day.date}:{index}:{activity.title}:{activity.start_time.isoformat()}",
                    )
                }
            )
            for index, activity in enumerate(day.activities)
        )
        legs: list[TransitLeg] = []
        for index, (origin, destination) in enumerate(
            zip(activities, activities[1:], strict=False)
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
            existing_leg = self._transit_leg_for_endpoints(day, index, index + 1)
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
            transit_id = (
                existing_leg.transit_id
                if existing_leg is not None and existing_leg.transit_id is not None
                else uuid5(
                    task_id,
                    f"replan-transit:{day.date}:{origin.activity_id}:"
                    f"{destination.activity_id}:{route.data.mode}",
                )
            )
            fallback_operation = (
                FallbackOperation(
                    operation="ROUTE",
                    transit_id=transit_id,
                    from_activity_id=origin.activity_id,
                    to_activity_id=destination.activity_id,
                    requested_mode="REAL_WITH_EXPLICIT_FALLBACK",
                    actual_provider="DEMO",
                    error_category=route.fallback_error.category.value,
                    error_code=route.fallback_error.error_code,
                    retry_count=route.fallback_error.retry_count,
                )
                if route.fallback_error is not None
                else None
            )
            legs.append(
                TransitLeg(
                    transit_id=transit_id,
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
                    fallback_operation=fallback_operation,
                )
            )
        return ItineraryDay(
            date=day.date,
            activities=activities,
            transit_legs=tuple(legs),
        )

    @staticmethod
    def _transit_leg_for_endpoints(
        day: ReplanItineraryDay,
        from_activity_index: int,
        to_activity_index: int,
    ) -> TransitLeg | None:
        matches = tuple(
            leg
            for leg in day.transit_legs
            if leg.from_activity_index == from_activity_index
            and leg.to_activity_index == to_activity_index
        )
        if len(matches) > 1:
            raise ValueError("replan day contains duplicate transit endpoints")
        return matches[0] if matches else None

    async def _route(
        self, request: RouteRequest
    ) -> ProviderSuccess[RoutePlan]:
        result = await self._route_provider.get_route(request)
        fallback_error = None
        if isinstance(result, ProviderFailure):
            primary_error = PlanningProviderError.from_failure(
                result,
                operation=ProviderOperation.ROUTE,
            )
            decision = self._fallback_policy.decide(
                self._provider_mode,
                primary_error.details,
            )
            if (
                decision != FallbackDecision.ALLOW_FALLBACK
                or self._route_fallback is None
            ):
                raise primary_error.with_fallback(
                    allowed=False,
                    attempted=False,
                    succeeded=False,
                )
            logger.warning(
                "provider_route_fallback operation=replan category=%s reason=%s retry_count=%s",
                primary_error.details.category,
                primary_error.details.error_code,
                primary_error.details.retry_count,
            )
            fallback_error = primary_error.details
            result = await self._route_fallback.get_route(request)
        if isinstance(result, ProviderFailure):
            raise PlanningProviderError.from_failure(
                result,
                operation=ProviderOperation.ROUTE,
            ).with_fallback(allowed=True, attempted=True, succeeded=False)
        if result.provider not in {"AMAP", "DEMO"}:
            raise PlanningProviderError("UNEXPECTED_ROUTE_PROVIDER")
        if (result.provider == "AMAP" and result.estimated) or (
            result.provider == "DEMO" and not result.estimated
        ):
            raise RuntimeError(
                "route provider returned inconsistent source metadata"
            )
        if fallback_error is not None:
            return result.model_copy(update={"fallback_error": fallback_error})
        return result
