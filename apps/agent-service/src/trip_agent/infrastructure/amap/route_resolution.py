"""Route query, caching, mode recommendation, and leg projection.

``RouteResolver`` owns every route-provider interaction for the AMap planning
provider: the real TRANSIT / DRIVING / WALKING queries, the per-plan call
budget, the route cache, the B19-C staged mode recommendation, provider
fallback handling, and the projection of a chosen route into a worker-contract
``TransitLeg``.  It is a stateless collaborator of
:class:`~trip_agent.infrastructure.amap.planning_provider.AmapPlanningProvider`
and of :class:`~trip_agent.infrastructure.amap.day_emitter.DayEmitter`.
"""

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid5

from trip_agent.domain.planning.protocols import PlanningProviderError
from trip_agent.domain.shared import MAX_ROUTE_CALLS_PER_PLAN, coordinate_decimal
from trip_agent.planning.cost_model import resolve_transit_cost
from trip_agent.planning.decision_trace import DecisionEvidence, DecisionTrace
from trip_agent.planning.mode_recommendation import (
    MAX_TRANSFERS,
    MAX_TRANSIT_WALKING_METERS,
    ConsideredMode,
    ModeRecommendation,
    ModeRecommendationReason,
    accessible_burdens,
    can_probe_transit,
    decide_transit_or_road,
)
from trip_agent.planning.transit_mode import (
    RECOVERABLE_ROUTE_CATEGORIES,
    is_walkable,
    should_try_walking,
    straight_line_distance_meters,
)
from trip_agent.planning.transport_strategy import (
    DEFAULT_TRANSPORT_STRATEGY,
    TransportStrategy,
)
from trip_agent.planning.weather_policy import WeatherLevel
from trip_agent.providers.errors import (
    FallbackDecision,
    ProviderExecutionMode,
    ProviderFallbackPolicy,
    ProviderOperation,
)
from trip_agent.providers.map import Poi, ProviderFailure, ProviderSuccess
from trip_agent.providers.route import RoutePlan, RouteProvider, RouteRequest
from trip_agent.worker.contracts import (
    ActivityCoordinates,
    FallbackOperation,
    TransitLeg,
)

logger = logging.getLogger(__name__)


def considered_modes(
    transit_route: ProviderSuccess[RoutePlan] | None,
    road_route: ProviderSuccess[RoutePlan] | None,
) -> tuple[ConsideredMode, ...]:
    """Per-mode facts for the recommendation trace (logging/tests only)."""
    considered: list[ConsideredMode] = []
    for route in (transit_route, road_route):
        if route is None:
            continue
        considered.append(
            ConsideredMode(
                mode=route.data.mode,
                available=True,
                duration_seconds=route.data.duration_seconds,
                distance_meters=route.data.distance_meters,
                walking_distance_meters=route.data.walking_distance_meters,
                transfer_count=route.data.transfer_count,
                cost=route.data.estimated_cost,
            )
        )
    return tuple(considered)


class RouteResolver:
    """Real route queries + mode recommendation + leg projection."""

    def __init__(
        self,
        route_provider: RouteProvider,
        transit_route: RouteProvider | None = None,
        route_fallback: RouteProvider | None = None,
        provider_mode: ProviderExecutionMode = ProviderExecutionMode.REAL_ONLY,
        fallback_policy: ProviderFallbackPolicy | None = None,
    ) -> None:
        self._route_provider = route_provider
        self._transit_route = transit_route
        self._route_fallback = route_fallback
        self._provider_mode = provider_mode
        self._fallback_policy = fallback_policy or ProviderFallbackPolicy()

    async def route(self, request: RouteRequest) -> ProviderSuccess[RoutePlan]:
        if request.mode == "TRANSIT":
            if self._transit_route is None:
                raise PlanningProviderError("PROVIDER_UNSUPPORTED_MODE")
            route_provider = self._transit_route
        else:
            route_provider = self._route_provider
        result = await route_provider.get_route(request)
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
            if decision != FallbackDecision.ALLOW_FALLBACK or self._route_fallback is None:
                raise primary_error.with_fallback(
                    allowed=False,
                    attempted=False,
                    succeeded=False,
                )
            logger.warning(
                "provider_route_fallback category=%s reason=%s retry_count=%s",
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
            raise RuntimeError("route provider returned inconsistent source metadata")
        if fallback_error is not None:
            return result.model_copy(update={"fallback_error": fallback_error})
        return result

    async def route_for_pair(
        self,
        origin_poi: Poi,
        destination_poi: Poi,
        departure_at: datetime,
        route_cache: dict[tuple[str, ...], ProviderSuccess[RoutePlan]],
        route_calls: list[int],
        *,
        city: str | None = None,
        remaining_legs: int = 1,
        mobility_reduced: bool = False,
        # P1-3: weather × budget × mobility resolved upstream into plain
        # optimization parameters.  None keeps the B19-C baseline.
        transport_strategy: TransportStrategy | None = None,
        # V2 P0-C: the resolved weather level for this day (trace evidence
        # only) and the in-process trace sink.  Both optional so existing
        # callers and tests stay unchanged.
        weather_level: WeatherLevel | None = None,
        decision_traces: list[DecisionTrace] | None = None,
    ) -> ProviderSuccess[RoutePlan]:
        """B19-C: staged per-leg mode recommendation over real route facts.

        Stage 1 — WALKING short-circuit (B18-B, unchanged semantics): a leg
        whose straight-line distance is within the walking prefilter gets a
        real WALKING route query; if the actual walking duration is within
        the strategy's walking threshold the walking route is used unchanged
        and no other mode is queried for comparison (walkability wins by
        product rule, even when a car would be faster — this is not
        min(duration)).  V1: the threshold is weather-aware and the transit
        tolerance is budget-aware (planning.transport_strategy).

        Stage 2 — TRANSIT vs DRIVING: otherwise the leg queries real TRANSIT
        (when a city is known and the dynamic budget reservation allows the
        extra probe) and DRIVING, then the ordered rules pick one.  The
        returned route is used verbatim for the TransitLeg, so every fact
        (mode/duration/distance/polyline/cost) comes from one response.
        """
        strategy = transport_strategy or DEFAULT_TRANSPORT_STRATEGY
        straight = straight_line_distance_meters(
            origin_poi.coordinates,
            destination_poi.coordinates,
        )
        # P2-2c: the deadline trace evidence references the walk probe —
        # initialise it so long legs (no walking probe at all) cannot hit an
        # UnboundLocalError in the stage-2 trace below.
        walk_route = None
        if should_try_walking(straight):
            walk_route = await self.try_walking_route(
                RouteRequest(
                    origin=origin_poi.coordinates,
                    destination=destination_poi.coordinates,
                    departure_at=departure_at,
                    origin_poi_id=origin_poi.provider_id,
                    destination_poi_id=destination_poi.provider_id,
                    mode="WALKING",
                ),
                route_cache,
                route_calls,
            )
            if walk_route is not None and is_walkable(
                walk_route.data.duration_seconds, strategy.walking_threshold_seconds
            ):
                # V2 P0-C: a context-stratified walk is a real decision — the
                # threshold (and therefore this choice) moved with the
                # weather.  Emit a TRANSIT_MODE trace with the evidence.
                if strategy.reason != "DEFAULT" and decision_traces is not None:
                    decision_traces.append(
                        DecisionTrace(
                            subject_type="TRANSIT",
                            subject_id=None,
                            summary=(
                                f"该段步行 {walk_route.data.duration_seconds}s 在当前策略"
                                f"阈值 {strategy.walking_threshold_seconds}s 内，选择步行"
                            ),
                            reason_codes=("TRANSIT_MODE",),
                            reasons=(
                                f"交通策略（{strategy.reason}）将步行阈值调整为 "
                                f"{strategy.walking_threshold_seconds}s，实际步行时长未超出",
                            ),
                            evidence=(
                                DecisionEvidence(
                                    key="strategy_reason",
                                    label="策略原因",
                                    value=strategy.reason,
                                ),
                                DecisionEvidence(
                                    key="weather_level",
                                    label="天气等级",
                                    value=str(weather_level) if weather_level else "UNKNOWN",
                                ),
                                DecisionEvidence(
                                    key="walking_threshold_seconds",
                                    label="步行阈值",
                                    value=str(strategy.walking_threshold_seconds),
                                ),
                                DecisionEvidence(
                                    key="walking_duration_seconds",
                                    label="步行时长",
                                    value=str(walk_route.data.duration_seconds),
                                ),
                                DecisionEvidence(
                                    key="selected_mode",
                                    label="选中交通方式",
                                    value=str(walk_route.data.mode),
                                ),
                            ),
                        )
                    )
                logger.info(
                    "mode_recommendation origin=%s destination=%s mode=WALKING "
                    "reason=%s provider_calls_used=%s budget_degraded=false",
                    origin_poi.provider_id,
                    destination_poi.provider_id,
                    ModeRecommendationReason.WALKABLE.value,
                    route_calls[0],
                )
                return walk_route
        recommendation = await self.recommend_transit_or_road(
            origin_poi,
            destination_poi,
            departure_at,
            city,
            route_cache,
            route_calls,
            remaining_legs,
            mobility_reduced,
            strategy,
        )
        # V2 P0-C: the walk did not survive the strategy threshold — the mode
        # came out of the ordered rules under the active context.  Emit a
        # TRANSIT_MODE trace with the rule outcome and its evidence.
        if strategy.reason != "DEFAULT" and decision_traces is not None:
            deadline_strategy = strategy.reason == "FIXED_SCHEDULE_DEADLINE"
            decision_traces.append(
                DecisionTrace(
                    subject_type="TRANSIT",
                    subject_id=None,
                    summary=(
                        f"该段步行超出策略阈值 {strategy.walking_threshold_seconds}s，"
                        f"按规则选择 {recommendation.selected_route.data.mode}"
                    ),
                    # reason_codes/reasons must stay 1:1 — DecisionExplanation
                    # rejects a code without its own reason (the audit's
                    # scenario-1 anchor legs hit this and took the whole plan
                    # down with an internal error).
                    reason_codes=(
                        ("TRANSIT_MODE", "FIXED_APPOINTMENT")
                        if deadline_strategy
                        else ("TRANSIT_MODE",)
                    ),
                    reasons=(
                        (
                            f"步行不可行（阈值 {strategy.walking_threshold_seconds}s），"
                            f"模式规则判定原因：{recommendation.reason.value}",
                            "交通策略处于固定时刻约束（FIXED_SCHEDULE_DEADLINE），"
                            "所选模式需满足该时刻约束",
                        )
                        if deadline_strategy
                        else (
                            f"步行不可行（阈值 {strategy.walking_threshold_seconds}s），"
                            f"模式规则判定原因：{recommendation.reason.value}",
                        )
                    ),
                    evidence=(
                        DecisionEvidence(
                            key="strategy_reason", label="策略原因", value=strategy.reason
                        ),
                        DecisionEvidence(
                            key="weather_level",
                            label="天气等级",
                            value=str(weather_level) if weather_level else "UNKNOWN",
                        ),
                        DecisionEvidence(
                            key="walking_threshold_seconds",
                            label="步行阈值",
                            value=str(strategy.walking_threshold_seconds),
                        ),
                        *(
                            (
                                DecisionEvidence(
                                    key="walking_duration_seconds",
                                    label="步行时长",
                                    value=str(walk_route.data.duration_seconds),
                                ),
                            )
                            if walk_route is not None
                            else ()
                        ),
                        DecisionEvidence(
                            key="selected_mode",
                            label="选中交通方式",
                            value=str(recommendation.selected_route.data.mode),
                        ),
                        DecisionEvidence(
                            key="mode_reason",
                            label="模式判定原因",
                            value=recommendation.reason.value,
                        ),
                    ),
                )
            )
        logger.info(
            "mode_recommendation origin=%s destination=%s mode=%s reason=%s "
            "provider_calls_used=%s budget_degraded=%s",
            origin_poi.provider_id,
            destination_poi.provider_id,
            recommendation.selected_route.data.mode,
            recommendation.reason.value,
            route_calls[0],
            recommendation.reason is ModeRecommendationReason.BUDGET_DEGRADED,
        )
        return recommendation.selected_route

    async def recommend_transit_or_road(
        self,
        origin_poi: Poi,
        destination_poi: Poi,
        departure_at: datetime,
        city: str | None,
        route_cache: dict[tuple[str, ...], ProviderSuccess[RoutePlan]],
        route_calls: list[int],
        remaining_legs: int,
        mobility_reduced: bool,
        transport_strategy: TransportStrategy | None = None,
    ) -> ModeRecommendation:
        """Stage 2: compare real TRANSIT and DRIVING facts, pick one.

        Recoverable provider failures (same white-list as B18-B walking)
        make a candidate mode unavailable; non-recoverable failures keep
        raising — they are not an unavailability signal and must not be
        swallowed.  If no candidate survives, the existing provider error
        policy applies (never fabricate a route).
        """
        transit_route: ProviderSuccess[RoutePlan] | None = None
        transit_error: PlanningProviderError | None = None
        probe_allowed = city is not None and can_probe_transit(
            MAX_ROUTE_CALLS_PER_PLAN - route_calls[0],
            remaining_legs,
        )
        if probe_allowed:
            try:
                transit_route = await self.route_cached(
                    RouteRequest(
                        origin=origin_poi.coordinates,
                        destination=destination_poi.coordinates,
                        departure_at=departure_at,
                        origin_poi_id=origin_poi.provider_id,
                        destination_poi_id=destination_poi.provider_id,
                        mode="TRANSIT",
                        city=city,
                    ),
                    route_cache,
                    route_calls,
                )
            except PlanningProviderError as error:
                if error.details.category not in RECOVERABLE_ROUTE_CATEGORIES:
                    raise
                transit_error = error

        road_route: ProviderSuccess[RoutePlan] | None = None
        road_error: PlanningProviderError | None = None
        try:
            road_route = await self.route_cached(
                RouteRequest(
                    origin=origin_poi.coordinates,
                    destination=destination_poi.coordinates,
                    departure_at=departure_at,
                    origin_poi_id=origin_poi.provider_id,
                    destination_poi_id=destination_poi.provider_id,
                    mode="DRIVING",
                ),
                route_cache,
                route_calls,
            )
        except PlanningProviderError as error:
            if error.details.category not in RECOVERABLE_ROUTE_CATEGORIES:
                raise
            road_error = error

        if road_route is None and transit_route is None:
            # Existing provider error policy: no fabricated route, no fake
            # duration.  Prefer surfacing the road error (the baseline).
            if road_error is not None:
                raise road_error
            assert transit_error is not None
            raise transit_error

        if transit_route is None:
            reason = (
                ModeRecommendationReason.BUDGET_DEGRADED
                if city is not None and not probe_allowed
                else ModeRecommendationReason.TRANSIT_UNAVAILABLE
            )
            assert road_route is not None
            return ModeRecommendation(
                selected_route=road_route,
                reason=reason,
                considered=considered_modes(transit_route, road_route),
            )
        if road_route is None:
            return ModeRecommendation(
                selected_route=transit_route,
                reason=ModeRecommendationReason.ROAD_UNAVAILABLE,
                considered=considered_modes(transit_route, road_route),
            )

        transfer_limit, walking_limit = accessible_burdens(
            mobility_reduced=mobility_reduced,
            max_transfers=MAX_TRANSFERS,
            max_transit_walking_meters=MAX_TRANSIT_WALKING_METERS,
        )
        strategy = transport_strategy or DEFAULT_TRANSPORT_STRATEGY
        choose_transit, reason = decide_transit_or_road(
            transit_route.data.duration_seconds,
            road_route.data.duration_seconds,
            transfer_count=transit_route.data.transfer_count,
            walking_distance_meters=transit_route.data.walking_distance_meters,
            max_transit_duration_ratio=strategy.max_transit_duration_ratio,
            max_transfers=transfer_limit,
            max_transit_walking_meters=walking_limit,
        )
        return ModeRecommendation(
            selected_route=transit_route if choose_transit else road_route,
            reason=reason,
            considered=considered_modes(transit_route, road_route),
        )

    async def try_walking_route(
        self,
        request: RouteRequest,
        route_cache: dict[tuple[str, ...], ProviderSuccess[RoutePlan]],
        route_calls: list[int],
    ) -> ProviderSuccess[RoutePlan] | None:
        """Query WALKING; recoverable provider failures degrade to ``None`` so
        the caller falls back to DRIVING instead of failing the whole plan.
        Non-recoverable failures (programming errors / invalid contract /
        corrupt input) keep raising — they are not a walking-unavailability
        signal and must not be swallowed."""
        try:
            return await self.route_cached(request, route_cache, route_calls)
        except PlanningProviderError as error:
            if error.details.category not in RECOVERABLE_ROUTE_CATEGORIES:
                raise
            logger.warning(
                "walking_route_unavailable category=%s code=%s — falling back to driving",
                error.details.category.value,
                error.details.error_code,
            )
            return None

    async def route_cached(
        self,
        request: RouteRequest,
        cache: dict[tuple[str, ...], ProviderSuccess[RoutePlan]],
        calls: list[int],
    ) -> ProviderSuccess[RoutePlan]:
        if request.mode == "TRANSIT":
            departure_utc = request.departure_at.astimezone(UTC)
            departure_bucket = departure_utc.replace(
                minute=(departure_utc.minute // 15) * 15,
                second=0,
                microsecond=0,
            )
            key = (
                "TRANSIT",
                str(request.city),
                str(request.strategy),
                str(request.nightflag),
                request.origin_poi_id or str(request.origin),
                request.destination_poi_id or str(request.destination),
                departure_bucket.isoformat(),
            )
        else:
            key = (
                request.origin_poi_id or str(request.origin),
                request.destination_poi_id or str(request.destination),
                request.mode,
                request.departure_at.isoformat(),
            )
        cached = cache.get(key)
        if cached is not None:
            return cached
        if calls[0] >= MAX_ROUTE_CALLS_PER_PLAN:
            raise PlanningProviderError("ROUTE_CALL_BUDGET_EXHAUSTED")
        calls[0] += 1
        result = await self.route(request)
        cache[key] = result
        return result

    def leg_from_route(
        self,
        task_id: UUID,
        trip_date: date,
        from_index: int,
        to_index: int,
        route: ProviderSuccess[RoutePlan],
        *,
        travelers: int = 1,
    ) -> TransitLeg:
        transit_id = uuid5(
            task_id,
            f"transit:{trip_date}:{from_index}:{to_index}:{route.data.mode}",
        )
        fallback_operation = (
            FallbackOperation(
                operation="ROUTE",
                transit_id=transit_id,
                from_activity_id=None,
                to_activity_id=None,
                requested_mode="REAL_WITH_EXPLICIT_FALLBACK",
                actual_provider="DEMO",
                error_category=route.fallback_error.category.value,
                error_code=route.fallback_error.error_code,
                retry_count=route.fallback_error.retry_count,
            )
            if route.fallback_error is not None
            else None
        )
        # P1-4: a TRANSIT fare is charged per traveller, a DRIVING toll per
        # vehicle — only the former scales with the party size.
        cost = resolve_transit_cost(
            self.transit_cost(route.data), mode=route.data.mode, travelers=travelers
        )
        if route.provider == "DEMO" and cost is None:
            cost = Decimal("0.00")
        return TransitLeg(
            transit_id=transit_id,
            from_activity_index=from_index,
            to_activity_index=to_index,
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
            estimated_cost=cost,
            cost_source=self.transit_cost_source(route),
            fallback_operation=fallback_operation,
        )

    @staticmethod
    def transit_cost(plan: RoutePlan) -> Decimal | None:
        """Extract monetary cost from a route plan.

        Walking is always free (0).  Driving cost comes from the provider
        (AMap toll estimate) when available; otherwise ``None`` signals
        that the cost could not be determined.
        """
        if plan.mode == "WALKING":
            return Decimal("0.00")
        if plan.estimated_cost is not None:
            return Decimal(str(round(plan.estimated_cost, 2)))
        return None

    @staticmethod
    def transit_cost_source(
        route: ProviderSuccess[RoutePlan],
    ) -> Literal["PROVIDER", "RULE_ESTIMATE", "DEMO", "UNKNOWN"]:
        if route.provider == "DEMO":
            return "DEMO"
        if route.data.mode == "WALKING":
            return "RULE_ESTIMATE"
        if route.data.estimated_cost is not None:
            return "PROVIDER"
        return "UNKNOWN"
