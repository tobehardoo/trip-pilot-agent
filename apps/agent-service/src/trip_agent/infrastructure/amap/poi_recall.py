"""POI recall and planning-candidate construction for the AMap planning provider.

``PoiRecaller`` owns the AMap POI search loop and the projection of raw
``Poi`` records into planning-domain :class:`CandidateActivity` values
(duration profile, magnitude, must-visit identity, complex-experience
classification).  It is a stateless collaborator of
:class:`~trip_agent.infrastructure.amap.planning_provider.AmapPlanningProvider`;
all call sites are the provider's orchestration method or this module.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from trip_agent.domain.planning.protocols import PlanningProviderError
from trip_agent.domain.shared import candidate_keywords
from trip_agent.planning.candidates import is_must_visit_poi
from trip_agent.planning.daily_schedule import CandidateActivity
from trip_agent.planning.poi_quality import duration_profile_for, magnitude_for_duration
from trip_agent.providers.errors import ProviderOperation
from trip_agent.providers.map import (
    Coordinates,
    MapProvider,
    Poi,
    PoiSearchRequest,
    ProviderFailure,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FetchedPoi:
    """A recalled POI paired with the fetch time of the response that
    produced it.

    ``ProviderSuccess.fetched_at`` is the single source of fetch time;
    it travels through the recall/projection boundary here instead of being
    stored on :class:`Poi`.  Never replaced by a downstream clock.
    """

    poi: Poi
    fetched_at: datetime


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


class PoiRecaller:
    """AMap POI recall + planning-candidate construction."""

    def __init__(self, map_provider: MapProvider) -> None:
        self._map_provider = map_provider

    async def collect(
        self, command: object, required_count: int
    ) -> tuple[FetchedPoi, ...]:
        trip = command.payload.trip  # type: ignore[attr-defined]
        candidates: list[FetchedPoi] = []
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
            candidates.extend(FetchedPoi(poi=item, fetched_at=fetched_at) for item in search.data)
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
    def poi_from_ref(ref: object, default_city: str) -> Poi:
        """B13_FIX.2 R9: build a pinned POI identity from a server-signed,
        canonicalized PlaceRef.

        The ref is a fixed planning input: exact providerPoiId, name,
        address, city/district and coordinates all come from the canonical
        record.  Type taxonomy is deliberately left empty — the search pages
        never supplied it, so no category claims are invented and the
        duration profile falls back to SYSTEM_DEFAULT (never hard-eligible).
        """
        return Poi(
            provider_id=ref.provider_poi_id,  # type: ignore[attr-defined]
            name=ref.name,  # type: ignore[attr-defined]
            coordinates=Coordinates(
                longitude=ref.longitude,  # type: ignore[attr-defined]
                latitude=ref.latitude,  # type: ignore[attr-defined]
            ),
            type_name="",
            type_code="",
            province=ref.province,  # type: ignore[attr-defined]
            city=ref.city or default_city,  # type: ignore[attr-defined]
            district=ref.district,  # type: ignore[attr-defined]
            address=ref.address,  # type: ignore[attr-defined]
        )

    def to_candidate(
        self,
        poi: Poi,
        must_visit_text: set[str],
        score_by_id: dict[str, int],
        must_visit_ids: set[str] | None = None,
    ) -> CandidateActivity:
        must = self.is_must_visit_poi(poi, must_visit_text, must_visit_ids)
        # B5: compute the duration profile exactly once per POI; magnitude is
        # derived from it and the profile travels with the candidate so the
        # scheduler and the duration hard rule see the same numbers.
        profile = duration_profile_for(poi)
        magnitude = magnitude_for_duration(profile)
        kind: str = (
            "EXPERIENCE"
            if magnitude in {"FULL_DAY", "HALF_DAY"}
            and self.is_complex_experience(poi)
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
    def is_must_visit_poi(
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
    def is_complex_experience(poi: Poi) -> bool:
        text = f"{poi.name} {poi.type_name}"
        return any(term in text for term in _COMPLEX_TERMS)

    @staticmethod
    def magnitude_for_poi(poi: Poi) -> str:
        return magnitude_for_duration(duration_profile_for(poi))
