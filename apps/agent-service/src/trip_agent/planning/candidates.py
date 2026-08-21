"""Explainable POI filtering and preference ranking."""

import re
from dataclasses import dataclass
from typing import Literal

from trip_agent.guide_intelligence.travel_entities import Attraction
from trip_agent.planning.poi_quality import same_mapped_place
from trip_agent.providers.map import Poi

type TravelerType = Literal["SOLO", "COUPLE", "FAMILY", "FRIENDS", "BUSINESS"]
type RejectionReason = Literal[
    "EMPTY_ADDRESS",
    "CITY_MISMATCH",
    "DUPLICATE_PROVIDER_ID",
    "DUPLICATE_PLACE",
    "AVOID_PLACE",
    "BELOW_SELECTION_CUTOFF",
]

_CITY_SUFFIXES = ("特别行政区", "自治州", "地区", "盟", "市")
_FAMILY_FRIENDLY_TERMS = ("公园", "博物馆", "科技馆", "动物园", "植物园", "儿童")
_RAIN_TERMS = ("雨", "雷阵雨", "暴雨", "台风", "降水")
_INDOOR_TERMS = ("博物馆", "美术馆", "科技馆", "展览馆", "室内", "商场", "剧院")
_OUTDOOR_TERMS = ("公园", "广场", "山", "湖", "海滩", "步行街", "户外")
_POSITIVE_GUIDE_TERMS = (
    "推荐",
    "值得",
    "适合",
    "人少",
    "方便",
    "优先",
    "必去",
    "好吃",
)
_NEGATIVE_GUIDE_TERMS = (
    "不",
    "没",
    "无",
    "勿",
    "避免",
    "不推荐",
    "避雷",
    "排队",
    "拥挤",
    "关闭",
    "暂停",
    "绕行",
    "涨价",
)
_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    poi: Poi
    score: int
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RejectedCandidate:
    poi: Poi
    reason: RejectionReason


@dataclass(frozen=True, slots=True)
class CandidateRanking:
    selected: tuple[RankedCandidate, ...]
    rejected: tuple[RejectedCandidate, ...]


class CandidateRanker:
    """Apply hard filters first, then a small deterministic preference model."""

    def rank(
        self,
        pois: tuple[Poi, ...],
        *,
        destination: str,
        preferences: tuple[str, ...],
        traveler_type: TravelerType,
        limit: int,
        must_visit_places: tuple[str, ...] = (),
        avoid_places: tuple[str, ...] = (),
        # B13_FIX.1 R6: structured avoid refs exclude by exact provider id.
        # When non-empty, only these ids are excluded — legacy text matching
        # is suppressed so a same-name sibling is never over-excluded.
        avoid_provider_ids: frozenset[str] = frozenset(),
        # B13_FIX.2 R9: structured must-visit refs pin exact provider ids.
        # Pinned items are fixed planning inputs (server-signed refs): they
        # skip the provider-noise hard filters (empty address / city
        # mismatch / same-place dedup) that exist to filter *search noise*,
        # always outrank the ordinary selection cutoff, and the ordinary
        # quota can never delete them.  Exact-id avoidance still applies.
        pinned_provider_ids: frozenset[str] = frozenset(),
        # B18-A: structured must-visit refs boost by exact provider id only
        # (the same identity rule the scheduler uses for must_include).  When
        # non-empty, name matching is disabled for the must-visit boost so a
        # same-name sibling never inherits it; legacy free text (empty set)
        # keeps normalized exact-name matching.
        must_visit_provider_ids: frozenset[str] = frozenset(),
        guide_statements: tuple[str, ...] = (),
        weather_statements: tuple[str, ...] = (),
        entity_facts: tuple[Attraction, ...] = (),
    ) -> CandidateRanking:
        if limit < 1:
            raise ValueError("candidate limit must be positive")
        accepted: list[RankedCandidate] = []
        rejected: list[RejectedCandidate] = []
        provider_ids: set[str] = set()
        accepted_places: list[Poi] = []
        pinned_places = tuple(poi for poi in pois if poi.provider_id in pinned_provider_ids)
        destination_key = _city_key(destination)
        entities_by_provider_id = {entity.provider_poi_id: entity for entity in entity_facts}

        for poi in pois:
            pinned = poi.provider_id in pinned_provider_ids
            if poi.provider_id in provider_ids:
                rejected.append(RejectedCandidate(poi, "DUPLICATE_PROVIDER_ID"))
                continue
            provider_ids.add(poi.provider_id)
            if not pinned and not poi.address.strip():
                rejected.append(RejectedCandidate(poi, "EMPTY_ADDRESS"))
                continue
            if not pinned and _city_key(poi.city) != destination_key:
                rejected.append(RejectedCandidate(poi, "CITY_MISMATCH"))
                continue
            if _is_avoided(poi, avoid_provider_ids, avoid_places):
                rejected.append(RejectedCandidate(poi, "AVOID_PLACE"))
                continue
            duplicate_places = (*accepted_places, *pinned_places)
            if not pinned and any(
                existing.provider_id != poi.provider_id and same_mapped_place(poi, existing)
                for existing in duplicate_places
            ):
                rejected.append(RejectedCandidate(poi, "DUPLICATE_PLACE"))
                continue
            accepted_places.append(poi)
            accepted.append(
                self._score(
                    poi,
                    preferences,
                    traveler_type,
                    must_visit_places,
                    guide_statements,
                    weather_statements,
                    entities_by_provider_id.get(poi.provider_id),
                    must_visit_provider_ids,
                )
            )

        accepted.sort(
            key=lambda item: (
                not any(reason.startswith("MUST_VISIT_MATCH:") for reason in item.reasons),
                -item.score,
                _text_key(item.poi.name),
                item.poi.provider_id,
            )
        )
        if pinned_provider_ids:
            # Pinned items always select, sorted first; the ordinary quota
            # applies to the remaining accepted candidates only.
            pinned_items = [
                item for item in accepted if item.poi.provider_id in pinned_provider_ids
            ]
            rest = [item for item in accepted if item.poi.provider_id not in pinned_provider_ids]
            selected = (*pinned_items, *rest[: max(limit - len(pinned_items), 0)])
        else:
            selected = accepted[:limit]
        rejected.extend(
            RejectedCandidate(item.poi, "BELOW_SELECTION_CUTOFF")
            for item in accepted[len(selected) :]
        )
        return CandidateRanking(tuple(selected), tuple(rejected))

    def _score(
        self,
        poi: Poi,
        preferences: tuple[str, ...],
        traveler_type: TravelerType,
        must_visit_places: tuple[str, ...],
        guide_statements: tuple[str, ...],
        weather_statements: tuple[str, ...],
        entity: Attraction | None,
        must_visit_provider_ids: frozenset[str] = frozenset(),
    ) -> RankedCandidate:
        score = 20
        reasons = ["VALID_CITY_AND_METADATA"]
        searchable = _text_key(f"{poi.name} {poi.type_name} {poi.address}")
        for preference in dict.fromkeys(item.strip() for item in preferences if item.strip()):
            if _text_key(preference) in searchable:
                score += 40
                reasons.append(f"PREFERENCE_MATCH:{preference}")
        # B18-A: must-visit boost is exact-identity only (shared with the
        # scheduler's must_include rule).  The old substring match gave every
        # POI whose name/address merely contained the must-visit text the
        # same +100, e.g. 小林蓝鳄正佳广场 outranking ordinary city candidates.
        must_visit_ids = frozenset(must_visit_provider_ids)
        matched_places = [item.strip() for item in must_visit_places if item.strip()]
        if must_visit_ids:
            if is_must_visit_poi(poi, matched_places, must_visit_ids):
                score += 100
                reasons.append(
                    f"MUST_VISIT_MATCH:{matched_places[0] if matched_places else poi.name}"
                )
        elif matched_places:
            for place in dict.fromkeys(matched_places):
                if is_must_visit_poi(poi, (place,), None):
                    score += 100
                    reasons.append(f"MUST_VISIT_MATCH:{place}")
                    break
        poi_name = _text_key(poi.name)
        if poi_name and any(
            poi_name in _text_key(statement) and is_positive_guide_statement(statement)
            for statement in guide_statements
        ):
            score += 25
            reasons.append("GUIDE_FACT_MATCH")
        if entity is not None:
            reasons.append(
                "ENTITY_OPENING_HOURS_KNOWN"
                if entity.opening_hours.status == "KNOWN"
                else "ENTITY_OPENING_HOURS_UNKNOWN"
            )
        weather_text = _text_key(" ".join(weather_statements))
        if is_adverse_weather_statement(weather_text):
            if any(_text_key(term) in searchable for term in _INDOOR_TERMS):
                score += 20
                reasons.append("WEATHER_INDOOR_PREFERENCE")
            elif any(_text_key(term) in searchable for term in _OUTDOOR_TERMS):
                score -= 10
                reasons.append("WEATHER_OUTDOOR_PENALTY")
        if traveler_type == "FAMILY" and any(term in searchable for term in _FAMILY_FRIENDLY_TERMS):
            score += 15
            reasons.append("FAMILY_FRIENDLY")
        return RankedCandidate(poi=poi, score=score, reasons=tuple(reasons))


def _city_key(value: str) -> str:
    result = value.strip().casefold()
    for suffix in _CITY_SUFFIXES:
        if result.endswith(suffix):
            return result[: -len(suffix)]
    return result


def _text_key(value: str) -> str:
    return _NON_WORD.sub("", value.casefold())


def _matches_any(poi: Poi, values: tuple[str, ...]) -> bool:
    searchable = _text_key(f"{poi.name} {poi.type_name} {poi.address}")
    return any(normalized in searchable for value in values if (normalized := _text_key(value)))


def is_must_visit_poi(
    poi: Poi,
    must_visit_places: tuple[str, ...] | set[str],
    must_visit_provider_ids: frozenset[str] | set[str] | None = None,
) -> bool:
    """B18-A: single, shared must-visit identity predicate.

    Structured refs (server-signed PlaceRefs with a providerPoiId) decide by
    EXACT provider identity only — a same-name sibling with a different id is
    never the must-visit place, and name/substring/similar-name matching is
    disabled entirely so the structured choice cannot silently become a
    different POI (B13_FIX R5 semantics).

    Legacy free text (no refs at all) falls back to NORMALIZED EXACT NAME
    equality: case-folded, alphanumeric-only.  Substring containment
    (``contains``/``startswith``/``endswith``) is forbidden — e.g.
    ``小林蓝鳄正佳广场`` must never match a ``正佳广场`` must-visit.
    """
    if must_visit_provider_ids:
        return poi.provider_id in must_visit_provider_ids
    normalised = "".join(character for character in poi.name.casefold() if character.isalnum())
    return any(
        "".join(character for character in place.casefold() if character.isalnum()) == normalised
        for place in must_visit_places
    )


def _is_avoided(
    poi: Poi,
    avoid_provider_ids: frozenset[str],
    avoid_places: tuple[str, ...],
) -> bool:
    """Structured avoid ids take precedence: when present, only exact provider
    ids are excluded.  Legacy text matching is the fallback only when no
    structured ids were provided (historical free-text trips)."""
    if avoid_provider_ids:
        return poi.provider_id in avoid_provider_ids
    return _matches_any(poi, avoid_places)


def is_positive_guide_statement(value: str) -> bool:
    normalized = _text_key(value)
    return any(_text_key(term) in normalized for term in _POSITIVE_GUIDE_TERMS) and not any(
        _text_key(term) in normalized for term in _NEGATIVE_GUIDE_TERMS
    )


def is_adverse_weather_statement(value: str) -> bool:
    normalized = _text_key(value)
    return any(_text_key(term) in normalized for term in _RAIN_TERMS)
