"""AMap-based planning provider — real POI search, route queries, and scheduling.

This provider depends on AMap web-service APIs for POI search and route
planning, on the candidate ranker for scoring, and on the pure daily-schedule
module (:mod:`trip_agent.planning.daily_schedule`) for deterministic daily
plans (day types, anchors, meal demand, capacity).

The class is the facade / orchestrator of the AMap planning pipeline; the
implementation clusters live in the sibling collaborators:

- :mod:`~trip_agent.infrastructure.amap.poi_recall` — POI recall + candidates
- :mod:`~trip_agent.infrastructure.amap.opening_hours` — opening evidence
- :mod:`~trip_agent.infrastructure.amap.anchor_resolution` — anchors / meals
- :mod:`~trip_agent.infrastructure.amap.route_resolution` — routes / modes
- :mod:`~trip_agent.infrastructure.amap.day_emitter` — daily emission
- :mod:`~trip_agent.infrastructure.amap.repair_policy` — repair decisions
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal

from trip_agent.domain.planning.protocols import (
    OptimizationConflict,
    PlanningInfeasibleError,
    PlanningProviderError,
    PlanningRepairRequest,
    PlanningResult,
    RelaxationSuggestion,
)
from trip_agent.domain.shared import snapshot_boundary_times
from trip_agent.infrastructure.amap.accommodation_projection import (
    project_amap_trip_skeleton,
)
from trip_agent.infrastructure.amap.anchor_resolution import AnchorResolver
from trip_agent.infrastructure.amap.day_emitter import DayEmitter
from trip_agent.infrastructure.amap.feasibility_projection import (
    project_amap_validation_inputs,
)
from trip_agent.infrastructure.amap.opening_hours import (
    entity_facts_for_pois,
    with_opening_availability,
)
from trip_agent.infrastructure.amap.poi_recall import PoiRecaller
from trip_agent.infrastructure.amap.repair_policy import (
    MAX_MOBILITY_REPAIR_ATTEMPTS,
    WINDOW_RELAX_STEP_MINUTES,
    can_relax_window_start,
    capacity_repair_candidate,
    mobility_repair_candidate,
)
from trip_agent.infrastructure.amap.route_resolution import RouteResolver
from trip_agent.planning.candidates import CandidateRanker
from trip_agent.planning.context_view import (
    PlanningContextView,
    build_context_view,
)
from trip_agent.planning.daily_schedule import (
    BUFFER_BETWEEN_MINUTES,
    RELAXED_SLOT_CAPACITY_DISCOUNT_MINUTES,
    DayPlan,
    MealDemand,
    plan_day,
)
from trip_agent.planning.decision_trace import DecisionEvidence, DecisionTrace
from trip_agent.planning.poi_quality import canonical_poi_key, classify_place
from trip_agent.planning.transport_strategy import TransportStrategy
from trip_agent.planning.trusted_context import hard_closed_fact
from trip_agent.planning.weather_policy import WeatherLevel
from trip_agent.providers.errors import (
    ProviderExecutionMode,
    ProviderFallbackPolicy,
)
from trip_agent.providers.map import MapProvider, Poi, ProviderSuccess
from trip_agent.providers.route import RoutePlan, RouteProvider
from trip_agent.worker.contracts import (
    GuideFactEvidence,
    Itinerary,
    ItineraryDay,
    PlanningCreateCommand,
    PlanningReplanCommand,
    TripConstraints,
)
from trip_agent.worker.progress import report_planning_progress

logger = logging.getLogger(__name__)


def _non_weather_guide_statements(
    facts: tuple[GuideFactEvidence, ...],
) -> tuple[str, ...]:
    return tuple(
        f"{fact.statement} {fact.evidence}" for fact in facts if fact.category != "WEATHER"
    )


def _avoid_provider_ids(constraints: TripConstraints) -> frozenset[str]:
    """B13_FIX.1 R6: structured avoid refs exclude by exact provider id.

    When refs are present (schemaVersion 3), only the exact provider ids are
    excluded; legacy text matching is suppressed by the ranker.
    """
    return frozenset(
        ref.provider_poi_id for ref in constraints.avoid_place_refs if ref.provider_poi_id
    )


def _titles_with_reason(
    ranked: object,
    prefix: str,
) -> tuple[str, ...]:
    """Titles of ranked candidates carrying a reason with the given prefix
    (the ranker already computed these — this only reads them)."""
    titles = tuple(
        item.poi.name
        for item in ranked  # type: ignore[attr-defined]
        if any(reason.startswith(prefix) for reason in item.reasons)  # type: ignore[attr-defined]
    )
    return titles[:8]


class AmapPlanningProvider:
    """Generates a real itinerary using AMap web-service APIs.

    Facade / orchestrator: owns the planning pipeline state and delegates the
    implementation clusters to :class:`PoiRecaller`, :class:`AnchorResolver`,
    :class:`RouteResolver` and :class:`DayEmitter` (plus the pure-function
    modules :mod:`opening_hours` and :mod:`repair_policy`).

    Uses AMap POI search for candidate discovery, AMap route planning for
    inter‑activity transit, a deterministic :class:`CandidateRanker` for
    scoring, and the pure daily-schedule module for deterministic daily plans.
    """

    def __init__(
        self,
        map_provider: MapProvider,
        route_provider: RouteProvider,
        transit_route: RouteProvider | None = None,
        route_fallback: RouteProvider | None = None,
        candidate_ranker: CandidateRanker | None = None,
        provider_mode: ProviderExecutionMode = ProviderExecutionMode.REAL_ONLY,
        fallback_policy: ProviderFallbackPolicy | None = None,
    ) -> None:
        self._map_provider = map_provider
        self._route_provider = route_provider
        self._transit_route = transit_route
        self._route_fallback = route_fallback
        self._candidate_ranker = candidate_ranker or CandidateRanker()
        self._provider_mode = provider_mode
        self._fallback_policy = fallback_policy or ProviderFallbackPolicy()
        self._recaller = PoiRecaller(map_provider)
        self._anchor_resolver = AnchorResolver(map_provider)
        self._route_resolver = RouteResolver(
            route_provider,
            transit_route=transit_route,
            route_fallback=route_fallback,
            provider_mode=provider_mode,
            fallback_policy=self._fallback_policy,
        )
        self._day_emitter = DayEmitter(self._anchor_resolver, self._route_resolver)

    # -- public API -----------------------------------------------------------

    async def plan(self, command: PlanningCreateCommand) -> PlanningResult:
        return await self._plan_with_skeleton(command)

    async def replan(self, command: PlanningReplanCommand) -> PlanningResult:
        from trip_agent.application.replan_service import (  # noqa: PLC0415
            LocalReplanningProvider,
        )

        return await LocalReplanningProvider(
            self._route_provider,
            self._route_fallback,
            transit_route=self._transit_route,
            provider_mode=self._provider_mode,
            fallback_policy=self._fallback_policy,
        ).replan(command)

    async def repair(self, request: PlanningRepairRequest) -> PlanningResult:
        from trip_agent.application.replan_service import (  # noqa: PLC0415
            LocalReplanningProvider,
        )

        return await LocalReplanningProvider(
            self._route_provider,
            self._route_fallback,
            transit_route=self._transit_route,
            provider_mode=self._provider_mode,
            fallback_policy=self._fallback_policy,
        ).repair(request)

    @staticmethod
    def _magnitude_for_poi(poi: Poi) -> str:
        return PoiRecaller.magnitude_for_poi(poi)

    # -- test-facing compatibility shims ---------------------------------------
    # F-4.1 extracted these private methods into the collaborator modules;
    # the shims below keep the historical class surface intact for the
    # characterization tests that probe the provider internals.  Production
    # code must call the collaborators directly (``self._recaller`` /
    # ``self._anchor_resolver`` / ``self._route_resolver`` / ``self._day_emitter``).

    async def _collect_pois(
        self, command: PlanningCreateCommand, required_count: int
    ) -> tuple:
        return await self._recaller.collect(command, required_count)

    @staticmethod
    def _is_must_visit_poi(
        poi: Poi,
        must_visit_text: set[str],
        must_visit_ids: set[str] | None = None,
    ) -> bool:
        return PoiRecaller.is_must_visit_poi(poi, must_visit_text, must_visit_ids)

    async def _resolve_travel_anchors(
        self,
        command: PlanningCreateCommand,
    ) -> object:
        return await self._anchor_resolver.resolve_travel_anchors(command)

    async def _resolve_meal_poi(
        self,
        meal: MealDemand,
        command: PlanningCreateCommand,
        *,
        excluded_provider_ids: frozenset[str] = frozenset(),
        decision_traces: list[DecisionTrace] | None = None,
        context_view: PlanningContextView | None = None,
    ) -> Poi | None:
        return await self._anchor_resolver.resolve_meal_poi(
            meal,
            command,
            excluded_provider_ids=excluded_provider_ids,
            decision_traces=decision_traces,
            context_view=context_view,
        )

    async def _route(self, request: object) -> object:
        return await self._route_resolver.route(request)  # type: ignore[arg-type]

    async def _route_cached(
        self,
        request: object,
        cache: dict[tuple[str, ...], ProviderSuccess[RoutePlan]],
        calls: list[int],
    ) -> ProviderSuccess[RoutePlan]:
        return await self._route_resolver.route_cached(request, cache, calls)  # type: ignore[arg-type]

    async def _route_for_pair(
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
        transport_strategy: TransportStrategy | None = None,
        weather_level: WeatherLevel | None = None,
        decision_traces: list[DecisionTrace] | None = None,
    ) -> ProviderSuccess[RoutePlan]:
        return await self._route_resolver.route_for_pair(
            origin_poi,
            destination_poi,
            departure_at,
            route_cache,
            route_calls,
            city=city,
            remaining_legs=remaining_legs,
            mobility_reduced=mobility_reduced,
            transport_strategy=transport_strategy,
            weather_level=weather_level,
            decision_traces=decision_traces,
        )

    def _leg_from_route(
        self,
        task_id: object,
        trip_date: object,
        from_index: int,
        to_index: int,
        route: ProviderSuccess[RoutePlan],
        *,
        travelers: int = 1,
    ) -> object:
        return self._route_resolver.leg_from_route(
            task_id,  # type: ignore[arg-type]
            trip_date,  # type: ignore[arg-type]
            from_index,
            to_index,
            route,
            travelers=travelers,
        )

    # -- daily-skeleton scheduling path ----------------------------------------

    async def _plan_with_skeleton(self, command: PlanningCreateCommand) -> PlanningResult:
        trip = command.payload.trip
        constraints = trip.constraints
        day_count = (trip.end_date - trip.start_date).days + 1
        await report_planning_progress(
            "POI_RECALLING",
            "Loading destination points of interest",
            {"requiredPoiCount": day_count * 3},
        )
        raw_pois = await self._recaller.collect(command, max(day_count * 3, 2))
        # B13_FIX.2 R9: structured must-visit refs are fixed planning
        # inputs.  A ref whose exact id the search pages never repeated is
        # still pinned from the server-signed, canonicalized PlaceRef data —
        # the user's chosen place is never dropped just because page one of
        # an ordinary keyword search did not repeat the id.
        structured_refs = tuple(getattr(constraints, "must_visit_place_refs", ()))
        must_visit_ids = {ref.provider_poi_id for ref in structured_refs if ref.provider_poi_id}
        recalled_ids = {fetched.poi.provider_id for fetched in raw_pois}
        pinned_pois = tuple(
            self._recaller.poi_from_ref(ref, trip.destination)
            for ref in structured_refs
            if ref.provider_poi_id and ref.provider_poi_id not in recalled_ids
        )
        # Candidate quality (V2, SI-1/2/3/6): the sightseeing pool admits
        # ATTRACTION-class places only — dining, accommodation, shopping and
        # anything unclassified are fail-closed out before ranking.  Transport
        # hubs serving arrival/departure are resolved separately and kept.
        activity_pois = tuple(
            fetched.poi
            for fetched in raw_pois
            if classify_place(fetched.poi) == "ATTRACTION"
        )
        candidate_pois = (*activity_pois, *pinned_pois)
        if not candidate_pois:
            raise PlanningProviderError("INSUFFICIENT_AMAP_POIS")
        # V3 P2-0: the whole planning context is parsed exactly once, here —
        # weather/budget/mobility resolution and per-candidate cost hints are
        # consumed from this view everywhere below (no per-decision recompute).
        context_view = build_context_view(command, candidate_pois=candidate_pois)
        # V2 P0-C: real decisions with their evidence, accumulated across the
        # pipeline and converted into DecisionExplanation records by the
        # evaluator.  Planning-process-only — never serialized.
        decision_traces: list[DecisionTrace] = []
        # V3 P2-2b: pool admission is a real decision (fail-closed semantic
        # governance) — summarize what the recall batch contained and why the
        # non-attraction classes stayed out.  Output only: the pool itself is
        # untouched (SI-1..6 behaviour is unchanged).
        excluded_map: dict[str, Poi] = {}
        for fetched in raw_pois:
            poi = fetched.poi
            if classify_place(poi) != "ATTRACTION":
                # recall may surface one POI through several keywords —
                # the summary counts places, not recall hits
                excluded_map.setdefault(poi.provider_id, poi)
        excluded = tuple(excluded_map.values())
        if excluded:
            kinds: dict[str, int] = {}
            for poi in excluded:
                kind = classify_place(poi)
                kinds[kind] = kinds.get(kind, 0) + 1
            kind_summary = "、".join(f"{kind}×{count}" for kind, count in sorted(kinds.items()))
            names = "、".join(poi.name for poi in excluded[:6])
            decision_traces.append(
                DecisionTrace(
                    subject_type="PLAN",
                    subject_id=None,
                    summary=(
                        f"{len(excluded)} 个召回候选不是可游览地点，"
                        f"未进入景点池（{kind_summary}）"
                    ),
                    reason_codes=("PROVIDER_CONSTRAINT",),
                    reasons=(
                        "按地图分类语义 fail-closed：餐饮/住宿/购物/交通设施"
                        "与未知类别不作为景点安排",
                    ),
                    evidence=(
                        DecisionEvidence(
                            key="excluded_count",
                            label="剔除数量",
                            value=str(len(excluded)),
                        ),
                        DecisionEvidence(
                            key="excluded_kinds",
                            label="剔除类别",
                            value=kind_summary,
                        ),
                        DecisionEvidence(
                            key="excluded_names",
                            label="剔除候选",
                            value=names,
                        ),
                    ),
                )
            )
        # B14_FIX R5 (D05): the ranker is a real execution boundary — the
        # stage must be reported, otherwise the UI shows it as never run.
        await report_planning_progress(
            "CANDIDATES_RANKING",
            "Ranking candidate attractions for the trip",
            {"candidateCount": len(candidate_pois)},
        )
        ranking = self._candidate_ranker.rank(
            candidate_pois,
            destination=trip.destination,
            preferences=constraints.preferences,
            traveler_type=constraints.traveler_type,
            limit=len(candidate_pois),
            must_visit_places=constraints.must_visit_places,
            avoid_places=constraints.avoid_places,
            # B13_FIX.1 R6: structured avoid refs exclude by exact provider id.
            avoid_provider_ids=_avoid_provider_ids(constraints),
            # B13_FIX.2 R9: exact must-visit ids are pinned — they bypass the
            # ordinary selection cutoff, so a low-scoring exact id is never
            # cut from the selected candidates.
            pinned_provider_ids=must_visit_ids,
            # B18-A: the must-visit ranking boost uses the same exact-id
            # identity as must_include — sibling POIs whose name merely
            # contains the must-visit text get no +100.
            must_visit_provider_ids=frozenset(must_visit_ids),
            guide_statements=_non_weather_guide_statements(command.payload.guide_evidence.facts),
            entity_facts=entity_facts_for_pois(raw_pois, command),
            # P1-2: budget-aware ranking.  Costs are pre-resolved from the
            # knowledge layer (pure, no I/O) so a tight budget can demote
            # candidates whose *known* price breaks the ceiling.  Only applied
            # when the budget is actually tight — no budget, no penalty.
            cost_hints=context_view.cost_hints,
            budget_ceiling=(
                context_view.activity_cost_ceiling
                if context_view.budget_pressure == "TIGHT"
                else None
            ),
        )
        ranked_pois = tuple(item.poi for item in ranking.selected)
        poi_by_id = {poi.provider_id: poi for poi in ranked_pois}
        score_by_id = {item.poi.provider_id: item.score for item in ranking.selected}
        # V2 P0-C: record the budget demotion decision.  BUDGET_CONSTRAINT was
        # defined in the reason-code vocabulary but never emitted (audit
        # §16.2); the ranking call above applied the ceiling demotion when the
        # budget pressure is TIGHT.
        if context_view.budget_pressure == "TIGHT":
            decision_traces.append(
                DecisionTrace(
                    subject_type="PLAN",
                    subject_id=None,
                    summary="预算紧张：已知票价超出当日人均门票上限的候选已在排序中降权",
                    reason_codes=("BUDGET_CONSTRAINT",),
                    reasons=(
                        "预算压力为 TIGHT；降权仅作用于知识层 PROVIDER 成本来源的候选",
                    ),
                    evidence=(
                        DecisionEvidence(
                            key="budget_pressure", label="预算压力", value="TIGHT"
                        ),
                        DecisionEvidence(
                            key="budget_amount",
                            label="预算金额",
                            value=str(constraints.budget_amount),
                        ),
                        DecisionEvidence(
                            key="travelers", label="出行人数", value=str(constraints.travelers)
                        ),
                        DecisionEvidence(
                            key="cost_ceiling",
                            label="当日人均门票上限",
                            value=str(context_view.activity_cost_ceiling),
                        ),
                        DecisionEvidence(
                            key="penalized_candidates",
                            label="被降权候选",
                            value="、".join(
                                _titles_with_reason(ranking.selected, "BUDGET_TIGHT_COST_PENALTY")
                            )
                            or "无",
                        ),
                    ),
                )
            )
        # V3 P2-2a: ranking reasons are already computed by the ranker —
        # surface them as plan-level decision traces.  Output only: the
        # ranking itself is untouched (no rescoring here).
        interest_titles = _titles_with_reason(ranking.selected, "PREFERENCE_MATCH:")
        guide_titles = _titles_with_reason(ranking.selected, "GUIDE_FACT_MATCH")
        if interest_titles or guide_titles:
            # reasons 必须与 reason_codes 一一对应（DecisionExplanation 校验）；
            # 偏好命中与导览推荐命中合并为同一条 INTEREST_MATCH 理由。
            decision_traces.append(
                DecisionTrace(
                    subject_type="PLAN",
                    subject_id=None,
                    summary="候选排序匹配了你的兴趣偏好与导览推荐",
                    reason_codes=("INTEREST_MATCH",),
                    reasons=(
                        f"偏好命中：{'、'.join(interest_titles) if interest_titles else '无'}；"
                        f"导览推荐命中：{'、'.join(guide_titles) if guide_titles else '无'}",
                    ),
                    evidence=(
                        DecisionEvidence(
                            key="preference_matched",
                            label="偏好命中候选",
                            value="、".join(interest_titles) or "无",
                        ),
                        DecisionEvidence(
                            key="guide_matched",
                            label="导览推荐命中候选",
                            value="、".join(guide_titles) or "无",
                        ),
                    ),
                )
            )
        must_visit_titles = _titles_with_reason(ranking.selected, "MUST_VISIT_MATCH:")
        if must_visit_titles:
            decision_traces.append(
                DecisionTrace(
                    subject_type="PLAN",
                    subject_id=None,
                    summary="必去地点已在排序中锁定并优先安排",
                    reason_codes=("MUST_VISIT",),
                    reasons=(f"必去命中：{'、'.join(must_visit_titles)}",),
                    evidence=(
                        DecisionEvidence(
                            key="must_visit_matched",
                            label="必去命中候选",
                            value="、".join(must_visit_titles),
                        ),
                    ),
                )
            )
        # V2 P1-A: a RELAXED pace is a real schedule policy (per-slot rest
        # slack in planning/daily_schedule._fill_slots) — record it so the
        # lighter day is explainable (audit G: "如果 Pace 改变了行程，但没有
        # 任何可观察证据，这也是一个值得记录的问题").
        if constraints.pace == "RELAXED":
            decision_traces.append(
                DecisionTrace(
                    subject_type="PLAN",
                    subject_id=None,
                    summary="节奏为 RELAXED：每个观光时段预留休整余量，每日负载相应降低",
                    reason_codes=("PACE_POLICY",),
                    reasons=(
                        "RELAXED 节奏在调度容量中预留 "
                        f"{RELAXED_SLOT_CAPACITY_DISCOUNT_MINUTES} 分钟/时段 的休整余量",
                    ),
                    evidence=(
                        DecisionEvidence(
                            key="pace", label="旅行节奏", value=str(constraints.pace)
                        ),
                        DecisionEvidence(
                            key="slot_capacity_discount_minutes",
                            label="时段容量折扣",
                            value=str(RELAXED_SLOT_CAPACITY_DISCOUNT_MINUTES),
                        ),
                        DecisionEvidence(
                            key="buffer_between_minutes",
                            label="活动间隔缓冲",
                            value=str(BUFFER_BETWEEN_MINUTES["RELAXED"]),
                        ),
                    ),
                )
            )
        must_visit_text = set(constraints.must_visit_places)
        candidates = tuple(
            self._recaller.to_candidate(poi, must_visit_text, score_by_id, must_visit_ids)
            for poi in ranked_pois
        )
        # Contradictory structured constraints (a must-visit id that is also
        # avoided, or that never survived ranking) still fail closed — the
        # requirement is real and cannot be satisfied by pinning alone.
        unpinned_structured = must_visit_ids - {
            candidate.poi_id for candidate in candidates if candidate.must_include
        }
        if unpinned_structured:
            raise PlanningInfeasibleError(
                conflicts=(
                    OptimizationConflict(
                        "MUST_VISIT_UNAVAILABLE",
                        "所选必去地点不是可安排的景点，或当前地图资料无法确认",
                        tuple(sorted(unpinned_structured)),
                    ),
                ),
                relaxations=(
                    RelaxationSuggestion(
                        "CHECK_TRAVEL_CONTEXT",
                        "请重新搜索并选择景点本身，不要选择地铁站、出入口或停车场",
                    ),
                ),
            )
        # Canonical identity per candidate: used for cross-day dedup so that
        # sub-facilities of the same place (光孝寺 vs 光孝寺-六祖殿) collapse
        # into one, while genuinely distinct attractions stay apart.
        canonical_key_by_id = {poi.provider_id: canonical_poi_key(poi) for poi in ranked_pois}
        anchors = await self._anchor_resolver.resolve_travel_anchors(command)
        special_date = self._day_emitter.special_day_date(command, candidates)

        route_cache: dict[tuple[str, ...], ProviderSuccess[RoutePlan]] = {}
        route_calls = [0]
        itinerary_days: list[ItineraryDay] = []
        day_plans: list[DayPlan] = []
        warnings: list[str] = []
        total_cost = Decimal("0")
        context = command.payload.planning_context
        closure_filtered_must: set[str] = set()
        used_meal_poi_ids: set[str] = set()
        remaining_candidates = candidates
        # B14_FIX R5 (D05): the day loop really calculates routes (route
        # provider calls) and solves per-day constraints — report both stage
        # boundaries so the UI never shows executed work as "未执行".
        await report_planning_progress(
            "ROUTES_CALCULATING",
            "Calculating travel routes between planned places",
            {"dayCount": day_count},
        )
        await report_planning_progress(
            "CONSTRAINTS_SOLVING",
            "Solving daily time, budget and preference constraints",
            {"dayCount": day_count},
        )
        for offset in range(day_count):
            trip_date = trip.start_date + timedelta(days=offset)
            has_full = trip_date == special_date
            day_candidates = (
                remaining_candidates
                if has_full or special_date is None
                else tuple(
                    candidate
                    for candidate in remaining_candidates
                    if candidate.magnitude != "FULL_DAY"
                )
            )
            if context is not None:
                day_candidates = tuple(
                    candidate
                    for candidate in day_candidates
                    if hard_closed_fact(context, trip_date, candidate.title) is None
                )
                # B9.2: verified eligible opening evidence now constrains
                # placement (earliest legal window, last-entry, closure
                # exclusion).  Only resolver VERIFIED states map to a
                # constraint; UNKNOWN/STALE/CONFLICTING stay unconstrained.
                day_candidates = with_opening_availability(day_candidates, context, trip_date)
                for candidate in candidates:
                    if (
                        candidate.must_include
                        and hard_closed_fact(context, trip_date, candidate.title) is not None
                    ):
                        closure_filtered_must.add(candidate.poi_id)
            mobility_reduced = constraints.mobility_level == "REDUCED"
            arrival_boundary, departure_boundary = snapshot_boundary_times(trip)
            window_relax_steps = 0
            window_override: tuple[int, int] | None = None
            while True:
                try:
                    for repair_attempt in range(MAX_MOBILITY_REPAIR_ATTEMPTS + 1):
                        day_plan = plan_day(
                            trip_date=trip_date,
                            start_date=trip.start_date,
                            end_date=trip.end_date,
                            arrival=arrival_boundary,
                            departure=departure_boundary,
                            accommodation_known=anchors.accommodation is not None,
                            fixed_schedules=self._day_emitter.fixed_schedules_on(
                                constraints.fixed_schedules, trip_date
                            ),
                            candidates=day_candidates,
                            has_full_day_experience=has_full,
                            pace=constraints.pace,
                            mobility_reduced=mobility_reduced,
                            meal_preferences=constraints.preferences,
                            # V3 P2-1: the per-person daily budget feeds the
                            # meal envelope (soft) attached to each demand.
                            budget_per_person=context_view.budget_per_person_per_day,
                            meal_windows=self._day_emitter.meal_window_constraints(constraints),
                            window_override=window_override,
                        )
                        day, day_cost, day_warnings = await self._day_emitter.emit_day(
                            command,
                            offset,
                            day_plan,
                            anchors,
                            poi_by_id,
                            route_cache,
                            route_calls,
                            frozenset(used_meal_poi_ids),
                            decision_traces=decision_traces,
                            context_view=context_view,
                        )
                        rejected_poi_id = (
                            mobility_repair_candidate(day, day_candidates)
                            if mobility_reduced
                            else None
                        )
                        if (
                            rejected_poi_id is None
                            or repair_attempt == MAX_MOBILITY_REPAIR_ATTEMPTS
                        ):
                            break
                        day_candidates = tuple(
                            candidate
                            for candidate in day_candidates
                            if candidate.poi_id != rejected_poi_id
                        )
                except PlanningInfeasibleError as error:
                    removable_poi_id = capacity_repair_candidate(
                        error, day_plan, day_candidates
                    )
                    if removable_poi_id is not None:
                        day_candidates = tuple(
                            candidate
                            for candidate in day_candidates
                            if candidate.poi_id != removable_poi_id
                        )
                        continue
                    # B17: deterministic capacity repair is exhausted (no
                    # removable optional left).  Boundedly relax the day's
                    # start instead of failing immediately — but only when the
                    # boundary is system-default, never a user anchor.
                    if can_relax_window_start(
                        day_plan, error, steps_taken=window_relax_steps
                    ):
                        window_relax_steps += 1
                        window_override = (
                            day_plan.window_start_minute - WINDOW_RELAX_STEP_MINUTES,
                            day_plan.window_end_minute,
                        )
                        continue
                    raise
                break
            itinerary_days.append(day)
            used_meal_poi_ids.update(
                activity.provider_poi_id
                for activity in day.activities
                if activity.kind == "MEAL" and activity.provider_poi_id is not None
            )
            # B4A: keep only the mobility-repair-final day plan; intermediate
            # repair attempts are discarded so the skeleton matches the
            # itinerary that was actually emitted.
            day_plans.append(day_plan)
            total_cost += day_cost
            warnings.extend(day_warnings)
            placed_on_day = {
                key
                for activity in day.activities
                if activity.kind in {"ATTRACTION", "EXPERIENCE"}
                and activity.provider_poi_id is not None
                for key in (canonical_key_by_id.get(activity.provider_poi_id),)
                if key is not None
            }
            remaining_candidates = tuple(
                candidate
                for candidate in remaining_candidates
                if canonical_key_by_id.get(candidate.poi_id) not in placed_on_day
            )

        placed_ids = {
            activity.provider_poi_id
            for day in itinerary_days
            for activity in day.activities
            if activity.provider_poi_id is not None
        }
        must_visit_unplaced = tuple(
            candidate.title
            for candidate in candidates
            if candidate.must_include and candidate.poi_id not in placed_ids
        )
        closure_unplaced = tuple(
            candidate.title
            for candidate in candidates
            if candidate.must_include
            and candidate.poi_id in closure_filtered_must
            and candidate.poi_id not in placed_ids
        )
        if closure_unplaced:
            raise PlanningInfeasibleError(
                conflicts=(
                    OptimizationConflict(
                        "MUST_VISIT_UNAVAILABLE",
                        "必去地点在对应行程日期被官方临时关闭，无法安排",
                        closure_unplaced,
                    ),
                ),
                relaxations=(
                    RelaxationSuggestion(
                        "ADJUST_TRAVEL_CONTEXT",
                        "调整行程日期或更换必去地点后重试",
                    ),
                ),
            )
        if must_visit_unplaced:
            raise PlanningInfeasibleError(
                conflicts=(
                    OptimizationConflict(
                        "MUST_VISIT_UNAVAILABLE",
                        "必去地点无法与当前时间、路线或行动能力约束同时满足",
                        must_visit_unplaced,
                    ),
                ),
                relaxations=(
                    RelaxationSuggestion(
                        "ADJUST_TRAVEL_CONTEXT",
                        "调整到返时间、行动能力或其他必去地点后重试",
                    ),
                ),
            )
        actual_providers = tuple(
            sorted(
                {
                    "AMAP",
                    *(leg.provider for day in itinerary_days for leg in day.transit_legs),
                }
            )
        )
        fallback_operations = tuple(
            leg.fallback_operation
            for day in itinerary_days
            for leg in day.transit_legs
            if leg.fallback_operation is not None
        )
        itinerary = Itinerary(
            title=f"{trip.destination} 真实地点行程",
            days=tuple(itinerary_days),
            estimated_total_cost=total_cost,
        )
        # B4A: transient accommodation projection — provider → TripSkeleton.
        # Not persisted, not emitted on any message contract; the worker
        # currently ignores this field.
        trip_skeleton = project_amap_trip_skeleton(
            day_plans=tuple(day_plans),
            requested_accommodation_label=(
                constraints.accommodation.place_name
                if constraints.accommodation is not None
                else None
            ),
            resolved_accommodation=anchors.accommodation,
        )
        # B5: transient validation inputs.  Each selected POI keeps the fetch
        # time of its own search batch (object identity, never a shared
        # timestamp); the worker and message contracts ignore this field.
        fetched_by_identity = {id(fetched.poi): fetched for fetched in raw_pois}
        selected_snapshots = tuple(
            fetched_by_identity[id(poi)] for poi in ranked_pois if id(poi) in fetched_by_identity
        )
        validation_inputs = project_amap_validation_inputs(
            itinerary=itinerary,
            day_plans=tuple(day_plans),
            fetched_snapshots=selected_snapshots,
        )
        return PlanningResult(
            provider="AMAP",
            itinerary=itinerary,
            guide_fact_ids=(),
            requested_provider_mode=self._provider_mode.value,
            primary_provider="AMAP",
            actual_providers=actual_providers,
            fallback_attempted=bool(fallback_operations),
            fallback_succeeded=bool(fallback_operations),
            fallback_reason=("ROUTE_PROVIDER_FAILURE" if fallback_operations else None),
            fallback_operations=fallback_operations,
            trip_skeleton=trip_skeleton,
            validation_inputs=validation_inputs,
            decision_traces=tuple(decision_traces),
        )
