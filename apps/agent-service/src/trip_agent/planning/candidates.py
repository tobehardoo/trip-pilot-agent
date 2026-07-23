"""Explainable POI filtering and preference ranking."""

import re
from dataclasses import dataclass
from typing import Literal

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
        guide_statements: tuple[str, ...] = (),
    ) -> CandidateRanking:
        if limit < 1:
            raise ValueError("candidate limit must be positive")
        accepted: list[RankedCandidate] = []
        rejected: list[RejectedCandidate] = []
        provider_ids: set[str] = set()
        place_keys: set[tuple[str, int, int]] = set()
        destination_key = _city_key(destination)

        for poi in pois:
            if poi.provider_id in provider_ids:
                rejected.append(RejectedCandidate(poi, "DUPLICATE_PROVIDER_ID"))
                continue
            provider_ids.add(poi.provider_id)
            if not poi.address.strip():
                rejected.append(RejectedCandidate(poi, "EMPTY_ADDRESS"))
                continue
            if _city_key(poi.city) != destination_key:
                rejected.append(RejectedCandidate(poi, "CITY_MISMATCH"))
                continue
            if _matches_any(poi, avoid_places):
                rejected.append(RejectedCandidate(poi, "AVOID_PLACE"))
                continue
            place_key = (
                _text_key(poi.name),
                round(poi.coordinates.longitude * 1_000),
                round(poi.coordinates.latitude * 1_000),
            )
            if place_key in place_keys:
                rejected.append(RejectedCandidate(poi, "DUPLICATE_PLACE"))
                continue
            place_keys.add(place_key)
            accepted.append(
                self._score(
                    poi,
                    preferences,
                    traveler_type,
                    must_visit_places,
                    guide_statements,
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
        selected = accepted[:limit]
        rejected.extend(
            RejectedCandidate(item.poi, "BELOW_SELECTION_CUTOFF") for item in accepted[limit:]
        )
        return CandidateRanking(tuple(selected), tuple(rejected))

    def _score(
        self,
        poi: Poi,
        preferences: tuple[str, ...],
        traveler_type: TravelerType,
        must_visit_places: tuple[str, ...],
        guide_statements: tuple[str, ...],
    ) -> RankedCandidate:
        score = 20
        reasons = ["VALID_CITY_AND_METADATA"]
        searchable = _text_key(f"{poi.name} {poi.type_name} {poi.address}")
        for preference in dict.fromkeys(item.strip() for item in preferences if item.strip()):
            if _text_key(preference) in searchable:
                score += 40
                reasons.append(f"PREFERENCE_MATCH:{preference}")
        for place in dict.fromkeys(item.strip() for item in must_visit_places if item.strip()):
            if _text_key(place) in searchable:
                score += 100
                reasons.append(f"MUST_VISIT_MATCH:{place}")
        poi_name = _text_key(poi.name)
        if poi_name and any(
            poi_name in _text_key(statement) and is_positive_guide_statement(statement)
            for statement in guide_statements
        ):
            score += 25
            reasons.append("GUIDE_FACT_MATCH")
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
    return any(
        normalized in searchable
        for value in values
        if (normalized := _text_key(value))
    )


def is_positive_guide_statement(value: str) -> bool:
    normalized = _text_key(value)
    return (
        any(_text_key(term) in normalized for term in _POSITIVE_GUIDE_TERMS)
        and not any(_text_key(term) in normalized for term in _NEGATIVE_GUIDE_TERMS)
    )
