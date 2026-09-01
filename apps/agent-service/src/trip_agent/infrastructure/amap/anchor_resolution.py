"""Travel-anchor and meal-place resolution for the AMap planning provider.

``AnchorResolver`` owns every live AMap POI search that is NOT part of
candidate recall: the arrival/departure/accommodation anchors, fixed-arrangement
places, and meal restaurants.  It is a stateless collaborator of
:class:`~trip_agent.infrastructure.amap.planning_provider.AmapPlanningProvider`.
"""

from trip_agent.domain.planning.protocols import (
    OptimizationConflict,
    PlanningInfeasibleError,
    PlanningProviderError,
    RelaxationSuggestion,
    ResolvedTravelAnchors,
)
from trip_agent.domain.shared import text_matches
from trip_agent.planning.context_view import PlanningContextView
from trip_agent.planning.cost_model import resolve_meal_cost
from trip_agent.planning.daily_schedule import MealDemand
from trip_agent.planning.decision_trace import DecisionEvidence, DecisionTrace
from trip_agent.planning.poi_quality import classify_place
from trip_agent.providers.errors import ProviderOperation
from trip_agent.providers.map import MapProvider, Poi, PoiSearchRequest, ProviderFailure
from trip_agent.worker.contracts import PlanningCreateCommand

_DINING_TERMS = ("美食", "餐饮", "小吃", "火锅", "面馆", "粤菜", "咖啡", "茶")


class AnchorResolver:
    """Live POI resolution for anchors, fixed places, and meals."""

    def __init__(self, map_provider: MapProvider) -> None:
        self._map_provider = map_provider

    async def resolve_travel_anchors(
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
                    raise self.anchor_unavailable(anchor.place_name)
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
                    raise self.anchor_unavailable(anchor.place_name)
            else:
                matching = next(
                    (poi for poi in search.data if text_matches(anchor.place_name, poi.name)),
                    None,
                )
                if matching is None:
                    raise self.anchor_unavailable(anchor.place_name)
            # V2 (SI-8): the accommodation anchor must resolve to an
            # accommodation-class place.  UNKNOWN (missing type_code) stays
            # allowed as a lenient fallback; anything else (the scenic spot
            # sharing the hotel's name, a mall) fails closed with the same
            # anchor-unavailable semantics as an unmatched anchor.
            if anchor is constraints.accommodation and classify_place(matching) not in (
                "ACCOMMODATION",
                "UNKNOWN",
            ):
                raise self.anchor_unavailable(
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

    async def resolve_fixed_place(
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

    async def resolve_meal_poi(
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
        for keyword in self.meal_keywords(meal):
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
    def meal_keywords(meal: MealDemand) -> tuple[str, ...]:
        region = f"{meal.region} 美食" if meal.region else None
        # Only dining-related preferences drive restaurant search; arbitrary
        # preferences (e.g. "历史") must not pull non-restaurant POIs in.
        dining = tuple(
            item.strip()
            for item in meal.preferences
            if item.strip() and any(term in item for term in _DINING_TERMS)
        )
        return tuple(dict.fromkeys((*(() if region is None else (region,)), *dining, "美食")))

    @staticmethod
    def anchor_unavailable(
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
