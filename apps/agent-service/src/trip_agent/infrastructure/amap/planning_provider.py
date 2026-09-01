"""AMap-based planning provider — real POI search, route queries, and scheduling.

This provider depends on AMap web-service APIs for POI search and route
planning, on the candidate ranker for scoring, and on the pure daily-schedule
module (:mod:`trip_agent.planning.daily_schedule`) for deterministic daily
plans (day types, anchors, meal demand, capacity).
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid5

from trip_agent.domain.planning.protocols import (
    OptimizationConflict,
    PlanningInfeasibleError,
    PlanningProviderError,
    PlanningRepairRequest,
    PlanningResult,
    RelaxationSuggestion,
    ResolvedTravelAnchors,
)
from trip_agent.domain.shared import (
    CHINA_TIME_ZONE,
    MAX_ROUTE_CALLS_PER_PLAN,
    candidate_keywords,
    coordinate_decimal,
    minute_datetime,
    snapshot_boundary_times,
    text_matches,
)
from trip_agent.guide_intelligence.travel_entities import (
    FactProvenance,
    FactValue,
    TravelEntityLocation,
    build_attraction,
)
from trip_agent.infrastructure.amap.accommodation_projection import (
    project_amap_trip_skeleton,
)
from trip_agent.infrastructure.amap.feasibility_projection import (
    project_amap_validation_inputs,
)
from trip_agent.planning.candidates import CandidateRanker, is_must_visit_poi
from trip_agent.planning.context_view import (
    PlanningContextView,
    build_context_view,
    resolve_transport_strategy_for_date,
    weather_level_for_date,
)
from trip_agent.planning.cost_model import (
    DEFAULT_ACCOMMODATION_PER_NIGHT,
    DEFAULT_MEAL_COST,
    resolve_attraction_cost,
    resolve_meal_cost,
    resolve_transit_cost,
)
from trip_agent.planning.daily_schedule import (
    BUFFER_BETWEEN_MINUTES,
    DEFAULT_DAY_START_MINUTE,
    RELAXED_SLOT_CAPACITY_DISCOUNT_MINUTES,
    CandidateActivity,
    DayPlan,
    DayPlanItem,
    FixedSchedule,
    MealDemand,
    MealWindowConstraint,
    classify_day_type,
    plan_day,
)
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
from trip_agent.planning.poi_quality import (
    canonical_poi_key,
    classify_place,
    duration_profile_for,
    magnitude_for_duration,
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
    deadline_strategy,
)
from trip_agent.planning.trusted_context import hard_closed_fact
from trip_agent.planning.weather_policy import WeatherLevel
from trip_agent.providers.errors import (
    FallbackDecision,
    ProviderExecutionMode,
    ProviderFallbackPolicy,
    ProviderOperation,
)
from trip_agent.providers.map import (
    Coordinates,
    MapProvider,
    Poi,
    PoiSearchRequest,
    ProviderFailure,
    ProviderSuccess,
)
from trip_agent.providers.route import RoutePlan, RouteProvider, RouteRequest
from trip_agent.worker.contracts import (
    ActivityCoordinates,
    FallbackOperation,
    GuideFactEvidence,
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
    PlanningCreateCommand,
    PlanningReplanCommand,
    TransitLeg,
    TripConstraints,
)
from trip_agent.worker.progress import report_planning_progress

logger = logging.getLogger(__name__)

# B18-B: walking-route failures in these categories are "recoverable" — the leg
# falls back to the DRIVING road baseline instead of failing the plan.  They
# mirror the fallback policy's local/explicitly-allowed categories.  Anything
# else (INTERNAL_ERROR, AUTHENTICATION_ERROR, PERMISSION_DENIED, INVALID_REQUEST,
# MALFORMED_RESPONSE, QUOTA_EXCEEDED, ...) keeps raising: those are not a
# walking-unavailability signal and must not be swallowed.
def _considered_modes(
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

_REDUCED_MOBILITY_MAX_HOP_METERS = 3_000
_MAX_MOBILITY_REPAIR_ATTEMPTS = 2

# B17 bounded repair relaxation: after deterministic capacity repair is
# exhausted, pull a SYSTEM-DEFAULT day start earlier in fixed steps so real
# transit time can fit before a fixed departure.  The floor keeps the
# relaxation bounded; user-derived boundaries (arrival/departure anchors,
# fixed schedules, meal hard windows) are never moved.
_WINDOW_RELAX_STEP_MINUTES = 30
_WINDOW_RELAX_FLOOR_MINUTE = 7 * 60


@dataclass(frozen=True, slots=True)
class _FetchedPoi:
    """A recalled POI paired with the fetch time of the response that
    produced it.

    ``ProviderSuccess.fetched_at`` is the single source of fetch time;
    it travels through the recall/projection boundary here instead of being
    stored on :class:`Poi`.  Never replaced by a downstream clock.
    """

    poi: Poi
    fetched_at: datetime


def _resolver_clock(facts: tuple[object, ...]) -> datetime:
    """The single freshness clock for opening resolution.

    Uses the latest evidence observation as the resolver 'as-of' moment so
    the resolver never depends on wall-clock time during planning.
    """
    checked = tuple(
        getattr(fact, "checked_at", None)
        for fact in facts
        if getattr(fact, "checked_at", None) is not None
    )
    if checked:
        return max(checked)
    return datetime.now(UTC)


def _entity_facts_for_pois(
    pois: tuple[_FetchedPoi, ...],
    command: PlanningCreateCommand,
) -> tuple:
    """Project fresh planning-context opening-hour facts onto recalled POIs.

    The event contract predates ``cityAdcode``; keep that field explicitly unknown
    until the producer supplies the structured region, while still preserving the
    fact's source and expiry for candidate explanations.
    """
    context = command.payload.planning_context
    if context is None:
        return ()
    opening_facts = tuple(
        fact for fact in context.facts if fact.category == "OPENING_HOURS" and not fact.stale
    )
    entities = []
    for fetched in pois:
        poi = fetched.poi
        fact = next(
            (
                item
                for item in opening_facts
                if text_matches(poi.name, f"{item.statement} {item.evidence}")
            ),
            None,
        )
        if fact is None:
            amap_known = _amap_opening_value(poi, fetched.fetched_at)
            if amap_known is None:
                continue
            text, provenance = amap_known
            entities.append(
                build_attraction(
                    city_adcode=None,
                    provider_poi_id=poi.provider_id,
                    name=poi.name,
                    category="ATTRACTION",
                    location=TravelEntityLocation(
                        poi.coordinates.longitude,
                        poi.coordinates.latitude,
                        poi.address,
                    ),
                    opening_hours=FactValue.known(text, provenance),
                )
            )
            continue
        source_type = "OFFICIAL" if fact.source_reviewed else "GUIDE"
        provenance = FactProvenance(
            source=fact.source_name,
            source_type=source_type,
            fetched_at=fact.checked_at,
            valid_until=fact.expires_at,
            confidence=1.0 if fact.source_reviewed else 0.7,
        )
        entities.append(
            build_attraction(
                city_adcode=None,
                provider_poi_id=poi.provider_id,
                name=poi.name,
                category="ATTRACTION",
                location=TravelEntityLocation(
                    poi.coordinates.longitude,
                    poi.coordinates.latitude,
                    poi.address,
                ),
                opening_hours=FactValue.known(fact.statement, provenance),
            )
        )
    return tuple(entities)


def _amap_opening_value(poi: Poi, fetched_at: datetime) -> tuple[str, FactProvenance] | None:
    """Project AMap business opening text onto a POI as provider evidence.

    ``opentime_today`` is today-scoped data: its effective date is the
    ``ProviderSuccess.fetched_at`` Asia/Shanghai local date.  The fetch time
    is passed explicitly across the projection boundary and never replaced
    by a downstream clock.
    """
    text = poi.business_hours_today or poi.business_hours_week
    if not text:
        return None
    provenance = FactProvenance(
        source="AMAP",
        source_type="PROVIDER",
        fetched_at=fetched_at,
        valid_until=fetched_at + timedelta(days=14),
        confidence=0.8,
    )
    return text, provenance


_COMPLEX_TERMS = (
    "泰山",
    "华山",
    "衡山",
    "黄山",
    "庐山",
    "峨眉",
    "峡谷",
    "迪士尼",
    "迪斯尼",
    "长隆",
    "乐园",
    "环球影城",
    "主题公园",
    "度假区",
    "古镇",
)
_DINING_TERMS = ("美食", "餐饮", "小吃", "火锅", "面馆", "粤菜", "咖啡", "茶")


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


# V3 P2-0: the context resolvers that used to live here
# (weather_statements_for_date / planning_context_weather_statements /
# weather_level_for_date / walking_threshold_seconds_for_date /
# trip_day_count / _attraction_cost_hints / budget_pressure_for /
# resolve_transport_strategy_for_date) moved verbatim to
# planning/context_view.py and are re-exported below for compatibility.


class AmapPlanningProvider:
    """Generates a real itinerary using AMap web-service APIs.

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

    # -- public API -----------------------------------------------------------

    async def plan(self, command: PlanningCreateCommand) -> PlanningResult:
        return await self._plan_with_skeleton(command)

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
        raw_pois = await self._collect_pois(command, max(day_count * 3, 2))
        # B13_FIX.2 R9: structured must-visit refs are fixed planning
        # inputs.  A ref whose exact id the search pages never repeated is
        # still pinned from the server-signed, canonicalized PlaceRef data —
        # the user's chosen place is never dropped just because page one of
        # an ordinary keyword search did not repeat the id.
        structured_refs = tuple(getattr(constraints, "must_visit_place_refs", ()))
        must_visit_ids = {ref.provider_poi_id for ref in structured_refs if ref.provider_poi_id}
        recalled_ids = {fetched.poi.provider_id for fetched in raw_pois}
        pinned_pois = tuple(
            self._poi_from_ref(ref, trip.destination)
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
            entity_facts=_entity_facts_for_pois(raw_pois, command),
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
            decision_traces.append(
                DecisionTrace(
                    subject_type="PLAN",
                    subject_id=None,
                    summary="候选排序匹配了你的兴趣偏好与导览推荐",
                    reason_codes=("INTEREST_MATCH",),
                    reasons=(
                        *(
                            f"偏好命中：{'、'.join(interest_titles) if interest_titles else '无'}",
                            f"导览推荐命中：{'、'.join(guide_titles) if guide_titles else '无'}",
                        ),
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
            self._to_candidate(poi, must_visit_text, score_by_id, must_visit_ids)
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
        anchors = await self._resolve_travel_anchors(command)
        special_date = self._special_day_date(command, candidates)

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
                day_candidates = self._with_opening_availability(day_candidates, context, trip_date)
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
                    for repair_attempt in range(_MAX_MOBILITY_REPAIR_ATTEMPTS + 1):
                        day_plan = plan_day(
                            trip_date=trip_date,
                            start_date=trip.start_date,
                            end_date=trip.end_date,
                            arrival=arrival_boundary,
                            departure=departure_boundary,
                            accommodation_known=anchors.accommodation is not None,
                            fixed_schedules=self._fixed_schedules_on(
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
                            meal_windows=self._meal_window_constraints(constraints),
                            window_override=window_override,
                        )
                        day, day_cost, day_warnings = await self._emit_day(
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
                            self._mobility_repair_candidate(day, day_candidates)
                            if mobility_reduced
                            else None
                        )
                        if (
                            rejected_poi_id is None
                            or repair_attempt == _MAX_MOBILITY_REPAIR_ATTEMPTS
                        ):
                            break
                        day_candidates = tuple(
                            candidate
                            for candidate in day_candidates
                            if candidate.poi_id != rejected_poi_id
                        )
                except PlanningInfeasibleError as error:
                    removable_poi_id = self._capacity_repair_candidate(
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
                    if self._can_relax_window_start(
                        day_plan, error, steps_taken=window_relax_steps
                    ):
                        window_relax_steps += 1
                        window_override = (
                            day_plan.window_start_minute - _WINDOW_RELAX_STEP_MINUTES,
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

    @staticmethod
    def _is_must_visit_poi(
        poi: Poi,
        must_visit_text: set[str],
        must_visit_ids: set[str] | None = None,
    ) -> bool:
        """Decide whether a recalled POI is the user's must-visit place.

        B18-A: delegates to the single shared predicate in
        ``planning.candidates.is_must_visit_poi`` so the scheduler
        (``must_include``) and the ranking boost (``MUST_VISIT_MATCH``) can
        never drift into two different semantics.

        Structured refs decide by exact providerPoiId only (B13_FIX R5 — a
        same-name sibling is never the must-visit place).  Legacy free text
        (no refs) keeps normalized exact-name equality; substring matching is
        forbidden so AMap sub-facilities (光孝寺(公交站), 小林蓝鳄正佳广场) are
        never mistaken for the named place.
        """
        return is_must_visit_poi(poi, tuple(must_visit_text), must_visit_ids)

    @staticmethod
    def _poi_from_ref(ref: object, default_city: str) -> Poi:
        """B13_FIX.2 R9: build a pinned POI identity from a server-signed,
        canonicalized PlaceRef.

        The ref is a fixed planning input: exact providerPoiId, name,
        address, city/district and coordinates all come from the canonical
        record.  Type taxonomy is deliberately left empty — the search pages
        never supplied it, so no category claims are invented and the
        duration profile falls back to SYSTEM_DEFAULT (never hard-eligible).
        """
        return Poi(
            provider_id=ref.provider_poi_id,
            name=ref.name,
            coordinates=Coordinates(longitude=ref.longitude, latitude=ref.latitude),
            type_name="",
            type_code="",
            province=ref.province,
            city=ref.city or default_city,
            district=ref.district,
            address=ref.address,
        )

    def _to_candidate(
        self,
        poi: Poi,
        must_visit_text: set[str],
        score_by_id: dict[str, int],
        must_visit_ids: set[str] | None = None,
    ) -> CandidateActivity:
        must = AmapPlanningProvider._is_must_visit_poi(poi, must_visit_text, must_visit_ids)
        # B5: compute the duration profile exactly once per POI; magnitude is
        # derived from it and the profile travels with the candidate so the
        # scheduler and the duration hard rule see the same numbers.
        profile = duration_profile_for(poi)
        magnitude = magnitude_for_duration(profile)
        kind: str = (
            "EXPERIENCE"
            if magnitude in {"FULL_DAY", "HALF_DAY"}
            and AmapPlanningProvider._is_complex_experience(poi)
            else "ATTRACTION"
        )
        return CandidateActivity(
            poi_id=poi.provider_id,
            title=poi.name,
            magnitude=magnitude,
            coordinates=(
                float(poi.coordinates.longitude),
                float(poi.coordinates.latitude),
            ),
            region=poi.district or None,
            must_include=must,
            kind=kind,  # type: ignore[arg-type]
            score=score_by_id.get(poi.provider_id, 0),
            visit_duration_profile=profile,
        )

    @staticmethod
    def _magnitude_for_poi(poi: Poi) -> str:
        return magnitude_for_duration(duration_profile_for(poi))

    @staticmethod
    def _meal_window_constraints(
        constraints: object,
    ) -> tuple[MealWindowConstraint, ...]:
        """Convert worker meal windows into planning-domain constraints.

        BREAKFAST is outside the planning domain (LUNCH/DINNER only) and is
        skipped rather than silently mapped to another meal.  The source
        (B13-F) travels with the constraint so the scheduler can distinguish
        hard USER windows from soft DEFAULT suggestions and DISABLED meals.
        """
        windows = tuple(getattr(constraints, "meal_windows", ()))
        converted: list[MealWindowConstraint] = []
        for window in windows:
            meal_type = getattr(window, "meal_type", None)
            if meal_type not in {"LUNCH", "DINNER"}:
                continue
            start_minute = window.start_time.hour * 60 + window.start_time.minute
            end_minute = window.end_time.hour * 60 + window.end_time.minute
            if end_minute <= start_minute:
                end_minute += 1440
            source = getattr(window, "source", "USER")
            converted.append(MealWindowConstraint(meal_type, start_minute, end_minute, source))
        return tuple(converted)

    @staticmethod
    def _with_opening_availability(
        candidates: tuple[CandidateActivity, ...],
        context: object,
        trip_date: date,
    ) -> tuple[CandidateActivity, ...]:
        """Attach verified opening constraints to candidates (B9.2).

        Only resolver VERIFIED_WINDOW / VERIFIED_CLOSED verdicts with
        ``hard_constraint_eligible=True`` constrain placement; AMap provider
        evidence is never hard-eligible, so it can never be upgraded here.
        """
        from dataclasses import replace

        from trip_agent.guide_intelligence.opening_evidence import (
            evidence_from_validated_fact,
        )
        from trip_agent.guide_intelligence.opening_resolver import (
            resolve_opening_hours,
        )
        from trip_agent.planning.daily_schedule import (
            opening_availability_from_resolved,
        )
        from trip_agent.planning.validation_projection import (
            validated_fact_from_planning_fact,
        )

        facts = tuple(getattr(context, "facts", ()))
        opening_facts = tuple(
            fact
            for fact in facts
            if getattr(fact, "category", None) in {"OPENING_HOURS", "TEMPORARY_CLOSURE"}
        )
        if not opening_facts:
            return candidates
        updated: list[CandidateActivity] = []
        for candidate in candidates:
            evidences = tuple(
                evidence
                for fact in opening_facts
                if text_matches(candidate.title, f"{fact.statement} {fact.evidence}")
                for evidence in (
                    evidence_from_validated_fact(
                        validated_fact_from_planning_fact(fact),
                        poi_key=candidate.poi_id,
                    ),
                )
                if evidence is not None
            )
            if not evidences:
                updated.append(candidate)
                continue
            resolved = resolve_opening_hours(
                evidences,
                poi_key=candidate.poi_id,
                trip_date=trip_date,
                resolver_as_of=_resolver_clock(facts),
            )
            availability = opening_availability_from_resolved(resolved)
            if availability.kind == "UNKNOWN":
                updated.append(candidate)
                continue
            updated.append(replace(candidate, opening=availability))
        return tuple(updated)

    @staticmethod
    def _is_complex_experience(poi: Poi) -> bool:
        text = f"{poi.name} {poi.type_name}"
        return any(term in text for term in _COMPLEX_TERMS)

    @staticmethod
    def _fixed_schedules_on(
        fixed_schedules: tuple[FixedSchedule, ...],
        trip_date: date,
    ) -> tuple[FixedSchedule, ...]:
        """Keep the schedules that fall on ``trip_date``.

        ``constraints.fixed_schedules`` are the worker-contract schedules with
        ``place_name``/``start_time``/``end_time``; the scheduler consumes
        ``planning.daily_schedule.FixedSchedule`` (``label``/``start``/``end``),
        so we map fields while filtering by day.
        """
        from trip_agent.planning.daily_schedule import (
            FixedSchedule as DailyFixedSchedule,
        )

        return tuple(
            DailyFixedSchedule(
                label=schedule.place_name,
                start=schedule.start_time,
                end=schedule.end_time,
            )
            for schedule in fixed_schedules
            if schedule.start_time.astimezone(CHINA_TIME_ZONE).date() == trip_date
        )

    @staticmethod
    def _mobility_repair_candidate(
        day: ItineraryDay,
        candidates: tuple[CandidateActivity, ...],
    ) -> str | None:
        candidate_by_id = {candidate.poi_id: candidate for candidate in candidates}
        for leg in day.transit_legs:
            if leg.distance_meters <= _REDUCED_MOBILITY_MAX_HOP_METERS:
                continue
            endpoints = (
                day.activities[leg.to_activity_index],
                day.activities[leg.from_activity_index],
            )
            for activity in endpoints:
                poi_id = activity.provider_poi_id
                candidate = candidate_by_id.get(poi_id) if poi_id else None
                if candidate is not None and not candidate.must_include:
                    return candidate.poi_id
        return None

    @staticmethod
    def _capacity_repair_candidate(
        error: PlanningInfeasibleError,
        day_plan: DayPlan,
        candidates: tuple[CandidateActivity, ...],
    ) -> str | None:
        """Choose one scheduled optional activity to drop after real routes
        consume more time than the deterministic skeleton estimated.

        The candidate tuple is already ranked highest-first, so walking it in
        reverse removes the lowest-priority scheduled optional item.  Required
        visits and every fixed boundary remain immutable.  The outer loop is
        bounded because every retry strictly removes one candidate.
        """
        if not any(conflict.code == "INSUFFICIENT_DAY_CAPACITY" for conflict in error.conflicts):
            return None
        scheduled_ids = {
            item.poi_id
            for item in day_plan.items
            if item.kind in {"ATTRACTION", "EXPERIENCE"} and item.poi_id is not None
        }
        return next(
            (
                candidate.poi_id
                for candidate in reversed(candidates)
                if candidate.poi_id in scheduled_ids and not candidate.must_include
            ),
            None,
        )

    @staticmethod
    def _can_relax_window_start(
        day_plan: DayPlan,
        error: PlanningInfeasibleError,
        *,
        steps_taken: int,
    ) -> bool:
        """Whether the bounded B17 start-relaxation may run once more.

        The gate: only a SYSTEM-DEFAULT start boundary may be pulled earlier.
        The repair site has every input to ``day_window_minutes`` plus the
        computed plan, so provenance is exact — a start that differs from the
        default was moved by the user's arrival/departure anchor and is never
        touched.  The ARRIVAL-item check removes the boundary case where the
        arrival minute equals the default start (09:00): the anchor is still
        present, so relaxing would create time before the user actually lands.
        Fixed schedules and meal hard windows are never moved either:
        ``compute_free_windows`` splits around them and relaxing only extends
        the window's leading edge.  Relaxation only fires for the
        departure-anchored capacity conflict and is bounded by the floor.
        """
        if not any(conflict.code == "INSUFFICIENT_DAY_CAPACITY" for conflict in error.conflicts):
            return False
        if steps_taken == 0:
            if day_plan.window_start_minute != DEFAULT_DAY_START_MINUTE:
                return False
            if any(item.kind == "ARRIVAL" for item in day_plan.items):
                return False
        return (
            day_plan.window_start_minute - _WINDOW_RELAX_STEP_MINUTES
            >= _WINDOW_RELAX_FLOOR_MINUTE
        )

    @staticmethod
    def _special_day_date(
        command: PlanningCreateCommand,
        candidates: tuple[CandidateActivity, ...],
    ) -> date | None:
        if not any(c.magnitude == "FULL_DAY" for c in candidates):
            return None
        trip = command.payload.trip
        arrival_boundary, departure_boundary = snapshot_boundary_times(trip)
        for offset in range((trip.end_date - trip.start_date).days + 1):
            trip_date = trip.start_date + timedelta(days=offset)
            day_type = classify_day_type(
                trip_date,
                trip.start_date,
                trip.end_date,
                arrival_boundary,
                departure_boundary,
            )
            if day_type == "FULL_DAY":
                return trip_date
        return trip.start_date + timedelta(days=1)

    async def _emit_day(
        self,
        command: PlanningCreateCommand,
        offset: int,
        day_plan: DayPlan,
        anchors: ResolvedTravelAnchors,
        poi_by_id: dict[str, Poi],
        route_cache: dict[tuple[str, ...], ProviderSuccess[RoutePlan]],
        route_calls: list[int],
        excluded_meal_poi_ids: frozenset[str],
        *,
        decision_traces: list[DecisionTrace] | None = None,
        context_view: PlanningContextView | None = None,
    ) -> tuple[ItineraryDay, Decimal, tuple[str, ...]]:
        trip_date = command.payload.trip.start_date + timedelta(days=offset)
        # V3 P2-0: the resolved context arrives pre-parsed — no per-day
        # re-resolution of weather/budget/strategy inside the emit loop.
        day_context = context_view.days[offset] if context_view is not None else None
        slots: list[dict[str, object]] = []
        unresolved: list[str] = []
        selected_meal_poi_ids = set(excluded_meal_poi_ids)
        # V1 Data-Truth: per-day cost resolution from trusted knowledge facts
        # (TICKET_PRICE / REFERENCE_SPEND) with honest fallback provenance.
        facts = context_view.facts if context_view is not None else ()
        travelers = command.payload.trip.constraints.travelers
        # P1-3: weather × budget × mobility resolved before optimization.
        strategy = (
            day_context.transport_strategy
            if day_context is not None
            else resolve_transport_strategy_for_date(command, trip_date)
        )
        for item in day_plan.items:
            if item.kind == "ARRIVAL" and anchors.arrival is not None:
                slots.append(self._slot_from_item(item, anchors.arrival, trip_date, 0))
            elif item.kind == "DEPARTURE" and anchors.departure is not None:
                slots.append(self._slot_from_item(item, anchors.departure, trip_date, 0))
            elif item.kind == "MEAL" and item.meal is not None:
                restaurant = await self._resolve_meal_poi(
                    item.meal,
                    command,
                    excluded_provider_ids=frozenset(selected_meal_poi_ids),
                    decision_traces=decision_traces,
                    context_view=context_view,
                )
                # A meal always happens: an unresolved restaurant is a
                # self-serve meal, not a free one — both carry a real
                # (documented default) estimate with explicit provenance.
                if restaurant is not None:
                    meal_cost = resolve_meal_cost(facts, restaurant.name, travelers=travelers)
                    selected_meal_poi_ids.add(restaurant.provider_id)
                    slots.append(
                        self._slot_from_item(
                            item,
                            restaurant,
                            trip_date,
                            meal_cost.amount,
                            cost_source=meal_cost.source,
                            title=restaurant.name,
                        )
                    )
                else:
                    label = "午餐" if item.meal.meal_type == "LUNCH" else "晚餐"
                    slots.append(
                        self._slot_from_item(
                            item,
                            None,
                            trip_date,
                            DEFAULT_MEAL_COST * max(travelers, 1),
                            cost_source="RULE_ESTIMATE",
                            title=f"{label}（建议在当前区域自行选择餐馆）",
                        )
                    )
                    unresolved.append("MEAL_POI_UNRESOLVED")
            else:
                poi = poi_by_id.get(item.poi_id) if item.poi_id else None
                # Fixed arrangements (place-level schedules) are not recalled
                # with the candidate POIs; resolve their location so the node
                # is a real AMAP activity and transit endpoints stay continuous.
                if poi is None and item.time_fixed and item.kind == "ATTRACTION":
                    poi = await self._resolve_fixed_place(item.title, command)
                if item.kind in {"ARRIVAL", "DEPARTURE", "ACCOMMODATION", "MEAL"}:
                    cost, cost_source = Decimal("0"), "UNKNOWN"
                else:
                    # P2-0: candidates (and pinned POIs) already carry their
                    # resolved cost in the view's hints — reuse instead of
                    # re-resolving.  Only non-pool places (fixed arrangements)
                    # resolve live; the inputs are identical, so the value is.
                    hint = (
                        context_view.cost_hints.get(poi.provider_id)
                        if context_view is not None and poi is not None
                        else None
                    )
                    if hint is not None:
                        activity_cost = hint
                    else:
                        activity_cost = resolve_attraction_cost(
                            facts,
                            poi.name if poi is not None else item.title,
                            travelers=travelers,
                        )
                    cost, cost_source = activity_cost.amount, activity_cost.source
                slots.append(
                    self._slot_from_item(item, poi, trip_date, cost, cost_source=cost_source)
                )

        day_count = (command.payload.trip.end_date - command.payload.trip.start_date).days + 1
        if day_count > 1:
            hotel = anchors.accommodation
            start_time = minute_datetime(trip_date, day_plan.window_start_minute)
            end_slot = minute_datetime(trip_date, day_plan.window_end_minute)
            hotel_label = hotel.name if hotel is not None else "住宿地点待确认"
        if day_count > 1 and offset > 0:
            slots.insert(
                0,
                {
                    "title": f"从{hotel_label}出发",
                    "start": start_time - timedelta(minutes=15),
                    "end": start_time,
                    "poi": hotel,
                    "kind": "ACCOMMODATION",
                    "time_fixed": False,
                    "magnitude": None,
                    "cost": Decimal("0"),
                    "cost_source": "UNKNOWN",
                },
            )
        if day_count > 1 and offset < day_count - 1:
            # P1-5: this slot exists exactly once per night, so it carries the
            # night's lodging cost.  A room is shared, so the nightly rate
            # must NOT scale with the party size.
            slots.append(
                {
                    "title": f"返回{hotel_label}",
                    "start": end_slot,
                    "end": end_slot + timedelta(minutes=15),
                    "poi": hotel,
                    "kind": "ACCOMMODATION",
                    "time_fixed": False,
                    "magnitude": None,
                    "cost": DEFAULT_ACCOMMODATION_PER_NIGHT,
                    "cost_source": "CITY_ESTIMATE",
                }
            )

        legs: list[tuple[int, int, ProviderSuccess[RoutePlan]]] = []
        legs_total = len(slots) - 1
        for index in range(legs_total):
            origin = slots[index]
            destination = slots[index + 1]
            origin_poi = origin.get("poi")
            destination_poi = destination.get("poi")
            if origin_poi is None or destination_poi is None:
                continue
            # B19-C: per-leg staged recommendation — a plausible walk still
            # short-circuits to WALKING (B18-B semantics), everything else is
            # compared against real TRANSIT and DRIVING facts.  The remaining
            # leg count feeds the dynamic route-budget reservation so an extra
            # TRANSIT probe never starves later baseline queries.
            route = await self._route_for_pair(
                origin_poi,
                destination_poi,
                origin["end"],
                route_cache,
                route_calls,
                city=command.payload.trip.destination or None,
                remaining_legs=legs_total - index,
                mobility_reduced=command.payload.trip.constraints.mobility_level == "REDUCED",
                # V3 P2-2c: a leg INTO a fixed appointment resolves the
                # conflict "arrival certainty > budget comfort" — the
                # tight-budget widened tolerance must not cost the slot.
                transport_strategy=(
                    deadline_strategy(strategy)
                    if bool(destination.get("time_fixed"))
                    else strategy
                ),
                weather_level=(
                    day_context.weather_level
                    if day_context is not None
                    else weather_level_for_date(command, trip_date)
                ),
                decision_traces=decision_traces,
            )
            # forward-fit: shift the destination and everything after it so the
            # real transit duration fits between activities.
            gap_seconds = (destination["start"] - origin["end"]).total_seconds()
            if gap_seconds < route.data.duration_seconds:
                if bool(destination.get("time_fixed")):
                    raise self._fixed_slot_timing_error(destination)
                shift = timedelta(seconds=route.data.duration_seconds - gap_seconds)
                for later in slots[index + 1 :]:
                    # Flexible work may consume slack before the next fixed
                    # boundary, but it must never move that boundary or any
                    # node on its far side.  A later pair then either fits the
                    # remaining route or fails closed.
                    if bool(later.get("time_fixed")):
                        break
                    later["start"] = later["start"] + shift
                    later["end"] = later["end"] + shift
            legs.append((index, index + 1, route))

        # B13_FIX.2 R12: the forward-fit loop only shifts the destination of
        # each *routed* pair onward.  Pairs that skip routing — unresolved
        # anchors, meals without a resolved POI, accommodation placeholders —
        # never re-check their boundary, so a long route can push a later
        # resolved activity past an intervening placeholder (observed with a
        # real AMap meal POI overlapping the trailing "返回住宿地点待确认"
        # node).  The event consumer rejects such review events and the task
        # stays QUEUED.  A final monotonic sweep restores strict ordering
        # without changing the forward-fit decisions themselves.
        carry = timedelta(0)
        previous_end: datetime | None = None
        for slot in slots:
            if carry and bool(slot.get("time_fixed")):
                raise self._fixed_slot_timing_error(slot)
            slot["start"] = slot["start"] + carry
            slot["end"] = slot["end"] + carry
            if previous_end is not None and slot["start"] < previous_end:
                if bool(slot.get("time_fixed")):
                    raise self._fixed_slot_timing_error(slot)
                carry = previous_end - slot["start"]
                slot["start"] = previous_end
                slot["end"] = slot["end"] + carry
            previous_end = slot["end"]

        activities = tuple(
            self._activity_from_slot(slot, trip_date, command.task_id, index)
            for index, slot in enumerate(slots)
        )
        transit_legs = tuple(
            self._leg_from_route(
                command.task_id,
                trip_date,
                from_index,
                to_index,
                route,
                travelers=command.payload.trip.constraints.travelers,
            )
            for from_index, to_index, route in legs
        )
        # F3: the itinerary total must include activity costs AND every
        # transit leg fare (a TRANSIT ticket is a real monetary cost even
        # though it is never compared against driving tolls across modes).
        total_cost = sum((slot.get("cost") or Decimal("0")) for slot in slots) + sum(
            (leg.estimated_cost or Decimal("0")) for leg in transit_legs
        )
        return (
            ItineraryDay(
                date=trip_date,
                day_type=day_plan.day_type,
                activities=activities,
                transit_legs=transit_legs,
            ),
            total_cost,
            tuple(unresolved),
        )

    @staticmethod
    def _fixed_slot_timing_error(slot: dict[str, object]) -> PlanningInfeasibleError:
        departure = slot.get("kind") == "DEPARTURE"
        return PlanningInfeasibleError(
            conflicts=(
                OptimizationConflict(
                    "INSUFFICIENT_DAY_CAPACITY" if departure else "FIXED_SCHEDULE_OVERLAP",
                    "实际交通时长无法在固定返程时间前完成"
                    if departure
                    else "实际交通时长与固定安排时间冲突",
                    (str(slot.get("title") or ""),),
                ),
            ),
            relaxations=(
                RelaxationSuggestion(
                    "EXTEND_AVAILABLE_TIME" if departure else "CHANGE_FIXED_SCHEDULE",
                    "请提前出发、延后返程时间，或减少前序行程"
                    if departure
                    else "请调整固定安排时间或减少前序行程",
                ),
            ),
        )

    def _slot_from_item(
        self,
        item: DayPlanItem,
        poi: Poi | None,
        trip_date: date,
        cost: Decimal,
        *,
        title: str | None = None,
        cost_source: str = "UNKNOWN",
    ) -> dict[str, object]:
        return {
            "title": title or item.title,
            "start": minute_datetime(trip_date, item.start_minute),
            "end": minute_datetime(trip_date, item.end_minute),
            "poi": poi,
            "kind": item.kind,
            "time_fixed": item.time_fixed,
            "magnitude": item.magnitude,
            "cost": cost,
            "cost_source": cost_source,
            # B13_FIX R3 (P0-3): MEAL slots carry the explicit meal type so
            # the validation projection can bind by identity.
            "meal_type": item.meal.meal_type if item.meal is not None else None,
        }

    def _activity_from_slot(
        self, slot: dict[str, object], trip_date: date, task_id: UUID, index: int
    ) -> ItineraryActivity:
        poi = slot.get("poi")
        title = str(slot["title"])
        start = slot["start"]
        end = slot["end"]
        kind = str(slot["kind"])
        time_fixed = bool(slot["time_fixed"])
        if poi is not None:
            activity_id = uuid5(
                task_id,
                f"activity:{trip_date}:{poi.provider_id}:{index}:{start.isoformat()}",
            )
            return ItineraryActivity(
                activity_id=activity_id,
                title=title,
                start_time=start,
                end_time=end,
                estimated_cost=Decimal(str(slot["cost"])),
                cost_source=str(slot.get("cost_source") or "UNKNOWN"),  # type: ignore[arg-type]
                source="AMAP",
                provider_poi_id=poi.provider_id,
                coordinates=ActivityCoordinates(
                    longitude=coordinate_decimal(poi.coordinates.longitude),
                    latitude=coordinate_decimal(poi.coordinates.latitude),
                ),
                address=poi.address or poi.name,
                type_code=poi.type_code,
                type_name=poi.type_name,
                kind=kind,  # type: ignore[arg-type]
                time_fixed=time_fixed,
                # B13_FIX R3 (P0-3): MEAL activities carry their explicit
                # meal type in-process for identity binding.
                meal_type=slot.get("meal_type") if kind == "MEAL" else None,
            )
        return ItineraryActivity(
            activity_id=uuid5(
                task_id,
                f"activity:{trip_date}:{title}:{index}:{start.isoformat()}",
            ),
            title=title,
            start_time=start,
            end_time=end,
            estimated_cost=Decimal(str(slot["cost"])),
            cost_source=str(slot.get("cost_source") or "UNKNOWN"),  # type: ignore[arg-type]
            source="AMAP",
            kind=kind,  # type: ignore[arg-type]
            time_fixed=time_fixed,
            meal_type=slot.get("meal_type") if kind == "MEAL" else None,
        )

    def _leg_from_route(
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
            self._transit_cost(route.data), mode=route.data.mode, travelers=travelers
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
            cost_source=self._transit_cost_source(route),
            fallback_operation=fallback_operation,
        )

    async def _resolve_fixed_place(
        self,
        place_name: str,
        command: PlanningCreateCommand,
    ) -> Poi | None:
        """Resolve a fixed-arrangement place to a real POI.

        Fixed schedules carry a user-provided place name but no provider POI.
        Search the destination so the scheduled node gets a real AMap identity,
        coordinates, and transit endpoints.  Returns ``None`` when the place is
        not found so the caller degrades gracefully (unresolved node).
        """
        trip = command.payload.trip
        search = await self._map_provider.search_pois(
            PoiSearchRequest(
                city=trip.destination,
                keyword=place_name,
                limit=5,
            )
        )
        if isinstance(search, ProviderFailure) or not search.data:
            return None
        matching = next(
            (poi for poi in search.data if text_matches(place_name, poi.name)),
            None,
        )
        return matching or search.data[0]

    async def _resolve_meal_poi(
        self,
        meal: MealDemand,
        command: PlanningCreateCommand,
        *,
        excluded_provider_ids: frozenset[str] = frozenset(),
        decision_traces: list[DecisionTrace] | None = None,
        context_view: PlanningContextView | None = None,
    ) -> Poi | None:
        trip = command.payload.trip
        # V3 P2-1: the soft per-meal dining envelope rides on the meal demand
        # (attached by build_meal_demands).  None → no budget stated, the
        # pre-P2-1 selection order applies unchanged.
        envelope = meal.budget_per_person
        facts = context_view.facts if context_view is not None else ()
        pressure = context_view.budget_pressure if context_view is not None else None
        for keyword in self._meal_keywords(meal):
            search = await self._map_provider.search_pois(
                PoiSearchRequest(
                    city=trip.destination,
                    keyword=keyword,
                    limit=5,
                )
            )
            if isinstance(search, ProviderFailure):
                continue
            candidates = tuple(
                poi
                for poi in search.data
                if poi.provider_id not in excluded_provider_ids
                # V2 (SI-5): only dining-classified POIs may serve a meal.
                # A mall food court or a scenic "美食街" recorded under a
                # non-dining class is skipped; if no keyword batch yields a
                # restaurant the caller keeps the placeholder meal (the
                # self-serve fallback below is unchanged).
                and classify_place(poi) == "RESTAURANT"
            )
            if not candidates:
                continue
            pool = candidates
            if meal.region:
                regional = tuple(
                    poi
                    for poi in candidates
                    if poi.district and text_matches(meal.region, poi.district)
                )
                if regional:
                    pool = regional
            if envelope is None:
                return pool[0]
            # V3 P2-1 (first-match-wins over the soft envelope): prefer the
            # first restaurant whose per-person price fits; if every candidate
            # exceeds the envelope, still serve the first one — a meal always
            # happens, the overspend is recorded, never punished with hunger.
            within_envelope = tuple(
                poi
                for poi in pool
                if resolve_meal_cost(facts, poi.name, travelers=1).amount <= envelope
            )
            if within_envelope:
                return within_envelope[0]
            chosen = pool[0]
            spend = resolve_meal_cost(facts, chosen.name, travelers=1)
            if decision_traces is not None:
                decision_traces.append(
                    DecisionTrace(
                        subject_type="PLAN",
                        subject_id=None,
                        summary=(
                            f"餐厅「{chosen.name}」人均 {spend.amount} 元超出当日"
                            f"餐费包络 {envelope} 元：仍安排用餐（不拒绝吃饭）"
                        ),
                        reason_codes=("BUDGET_CONSTRAINT",),
                        reasons=(
                            "当日餐费为软包络：超支仅降低优先级并留痕，"
                            "不会移除餐食或替换为空建议",
                        ),
                        evidence=(
                            DecisionEvidence(
                                key="meal_envelope_per_person",
                                label="单餐人均包络",
                                value=str(envelope),
                            ),
                            DecisionEvidence(
                                key="restaurant_spend_per_person",
                                label="餐厅人均消费",
                                value=str(spend.amount),
                            ),
                            DecisionEvidence(
                                key="spend_source",
                                label="消费来源",
                                value=str(spend.source),
                            ),
                            DecisionEvidence(
                                key="budget_pressure",
                                label="预算压力",
                                value=str(pressure) if pressure else "UNKNOWN",
                            ),
                        ),
                    )
                )
            return chosen
        return None

    @staticmethod
    def _meal_keywords(meal: MealDemand) -> tuple[str, ...]:
        region = f"{meal.region} 美食" if meal.region else None
        # Only dining-related preferences drive restaurant search; arbitrary
        # preferences (e.g. "历史") must not pull non-restaurant POIs in.
        dining = tuple(
            item.strip()
            for item in meal.preferences
            if item.strip() and any(term in item for term in _DINING_TERMS)
        )
        return tuple(dict.fromkeys((*(() if region is None else (region,)), *dining, "美食")))

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

    async def _resolve_travel_anchors(
        self,
        command: PlanningCreateCommand,
    ) -> ResolvedTravelAnchors:
        constraints = command.payload.trip.constraints
        resolved: dict[str, Poi] = {}
        for anchor in (
            constraints.arrival,
            constraints.departure,
            constraints.accommodation,
        ):
            if anchor is None or anchor.place_name in resolved:
                continue
            search = await self._map_provider.search_pois(
                PoiSearchRequest(
                    city=command.payload.trip.destination,
                    keyword=anchor.place_name,
                    limit=5,
                )
            )
            if isinstance(search, ProviderFailure):
                if search.error_code == "POI_NOT_FOUND":
                    raise self._anchor_unavailable(anchor.place_name)
                raise PlanningProviderError.from_failure(
                    search,
                    operation=ProviderOperation.POI_SEARCH,
                )
            if search.provider != "AMAP":
                raise PlanningProviderError("UNEXPECTED_MAP_PROVIDER")
            # B13_FIX R5 (P1-2): a structured anchor (with a placeRef) is
            # exact-identity only — the recalled POI must carry the exact
            # provider id.  Same-name text fallback is forbidden so a
            # structured choice never silently becomes a different POI.
            place_ref = getattr(anchor, "place_ref", None)
            if place_ref is not None:
                matching = next(
                    (poi for poi in search.data if poi.provider_id == place_ref.provider_poi_id),
                    None,
                )
                if matching is None:
                    raise self._anchor_unavailable(anchor.place_name)
            else:
                matching = next(
                    (poi for poi in search.data if text_matches(anchor.place_name, poi.name)),
                    None,
                )
                if matching is None:
                    raise self._anchor_unavailable(anchor.place_name)
            # V2 (SI-8): the accommodation anchor must resolve to an
            # accommodation-class place.  UNKNOWN (missing type_code) stays
            # allowed as a lenient fallback; anything else (the scenic spot
            # sharing the hotel's name, a mall) fails closed with the same
            # anchor-unavailable semantics as an unmatched anchor.
            if anchor is constraints.accommodation and classify_place(matching) not in (
                "ACCOMMODATION",
                "UNKNOWN",
            ):
                raise self._anchor_unavailable(
                    anchor.place_name,
                    conflict_detail="住宿地点匹配到的场所类型不是住宿（可能命中同名景点或商场）",
                    relaxation="请重新搜索并选择住宿本身（酒店/民宿/公寓式酒店）后重试",
                )
            resolved[anchor.place_name] = matching
        return ResolvedTravelAnchors(
            arrival=(
                resolved.get(constraints.arrival.place_name)
                if constraints.arrival is not None
                else None
            ),
            departure=(
                resolved.get(constraints.departure.place_name)
                if constraints.departure is not None
                else None
            ),
            accommodation=(
                resolved.get(constraints.accommodation.place_name)
                if constraints.accommodation is not None
                else None
            ),
        )

    @staticmethod
    def _anchor_unavailable(
        place_name: str,
        *,
        conflict_detail: str = "到返或住宿地点未能在地图中确认",
        relaxation: str = "补充更完整的车站、机场或住宿名称后重试",
    ) -> PlanningInfeasibleError:
        return PlanningInfeasibleError(
            conflicts=(
                OptimizationConflict(
                    "TRAVEL_ANCHOR_UNAVAILABLE",
                    conflict_detail,
                    (place_name,),
                ),
            ),
            relaxations=(
                RelaxationSuggestion(
                    "CHECK_TRAVEL_ANCHOR",
                    relaxation,
                ),
            ),
        )

    async def _collect_pois(
        self, command: PlanningCreateCommand, required_count: int
    ) -> tuple[_FetchedPoi, ...]:
        trip = command.payload.trip
        candidates: list[_FetchedPoi] = []
        keywords = candidate_keywords(
            trip.constraints.preferences,
            trip.constraints.must_visit_places,
        )
        # B18-A (P18-R2): the recall loop always executes the FULL allowed
        # keyword set (MAX_POI_QUERIES cap) and never stops early on a count.
        # The old ``required_preference_queries``/``len(ranking.selected) >=
        # required_count`` early-stop let the FIRST must-visit keyword end the
        # whole recall once it returned enough nearby POIs, so 历史/景点/博物馆/
        # 公园 exploration keywords never ran and the candidate pool became
        # must-visit-dominated (the 正佳广场 case: 56% of the pool was inside
        # the mall).  Raw candidates from every source are collected first and
        # ranked exactly once afterwards by the caller.
        structured_ids = {
            ref.provider_poi_id
            for ref in getattr(trip.constraints, "must_visit_place_refs", ())
            if ref.provider_poi_id
        }
        recalled_ids: set[str] = set()
        for keyword in keywords:
            search = await self._map_provider.search_pois(
                PoiSearchRequest(
                    city=trip.destination,
                    keyword=keyword,
                    limit=min(required_count * 3, 25),
                )
            )
            if isinstance(search, ProviderFailure):
                if search.error_code == "POI_NOT_FOUND":
                    continue
                raise PlanningProviderError.from_failure(
                    search,
                    operation=ProviderOperation.POI_SEARCH,
                )
            if search.provider != "AMAP":
                raise PlanningProviderError("UNEXPECTED_MAP_PROVIDER")
            # ProviderSuccess.fetched_at is the single fetch-time source for
            # this search batch; each batch keeps its own time.
            fetched_at = search.fetched_at
            candidates.extend(_FetchedPoi(poi=item, fetched_at=fetched_at) for item in search.data)
            recalled_ids.update(item.provider_id for item in search.data)
        # B18-A: the structured ref integrity check is preserved.  Exact
        # must-visit ids are guaranteed to enter the candidate set: any id the
        # keyword loop never recalled is still pinned from the server-signed
        # ref data by the caller (_plan_with_skeleton), and if that pinned
        # candidate is not an arrangeable attraction the existing
        # MUST_VISIT_UNAVAILABLE fail-closed resolution still applies.
        if structured_ids and not structured_ids <= recalled_ids:
            missing_ids = sorted(structured_ids - recalled_ids)
            logger.info("must_visit_ids_missing_from_recall ids=%s", ",".join(missing_ids))
        return tuple(candidates)

    @staticmethod
    def _transit_cost(plan: RoutePlan) -> Decimal | None:
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
    def _transit_cost_source(
        route: ProviderSuccess[RoutePlan],
    ) -> Literal["PROVIDER", "RULE_ESTIMATE", "DEMO", "UNKNOWN"]:
        if route.provider == "DEMO":
            return "DEMO"
        if route.data.mode == "WALKING":
            return "RULE_ESTIMATE"
        if route.data.estimated_cost is not None:
            return "PROVIDER"
        return "UNKNOWN"

    async def _route(self, request: RouteRequest) -> ProviderSuccess[RoutePlan]:
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
            walk_route = await self._try_walking_route(
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
        recommendation = await self._recommend_transit_or_road(
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
            decision_traces.append(
                DecisionTrace(
                    subject_type="TRANSIT",
                    subject_id=None,
                    summary=(
                        f"该段步行超出策略阈值 {strategy.walking_threshold_seconds}s，"
                        f"按规则选择 {recommendation.selected_route.data.mode}"
                    ),
                    reason_codes=(
                        ("TRANSIT_MODE", "FIXED_APPOINTMENT")
                        if strategy.reason == "FIXED_SCHEDULE_DEADLINE"
                        else ("TRANSIT_MODE",)
                    ),
                    reasons=(
                        f"步行不可行（阈值 {strategy.walking_threshold_seconds}s），"
                        f"模式规则判定原因：{recommendation.reason.value}",
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

    async def _recommend_transit_or_road(
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
                transit_route = await self._route_cached(
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
            road_route = await self._route_cached(
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
                considered=_considered_modes(transit_route, road_route),
            )
        if road_route is None:
            return ModeRecommendation(
                selected_route=transit_route,
                reason=ModeRecommendationReason.ROAD_UNAVAILABLE,
                considered=_considered_modes(transit_route, road_route),
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
            considered=_considered_modes(transit_route, road_route),
        )

    async def _try_walking_route(
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
            return await self._route_cached(request, route_cache, route_calls)
        except PlanningProviderError as error:
            if error.details.category not in RECOVERABLE_ROUTE_CATEGORIES:
                raise
            logger.warning(
                "walking_route_unavailable category=%s code=%s — falling back to driving",
                error.details.category.value,
                error.details.error_code,
            )
            return None

    async def _route_cached(
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
        result = await self._route(request)
        cache[key] = result
        return result
