"""B13_FIX.1 R6 — structured avoid refs exclude by exact provider id.

Legacy ``avoid_places`` text still filters by substring; a non-empty
``avoid_provider_ids`` set excludes only the exact provider ids, so a
same-name sibling POI is never over-excluded and an unrecalled structured id
never falls back to text matching.
"""

from trip_agent.planning.candidates import CandidateRanker
from trip_agent.providers.map import Coordinates, Poi


def _poi(provider_id: str, name: str) -> Poi:
    return Poi(
        provider_id=provider_id,
        name=name,
        coordinates=Coordinates(longitude=113.26, latitude=23.13),
        type_name="风景名胜",
        type_code="110000",
        province="广东省",
        city="广州市",
        district="越秀区",
        address=f"{name}地址",
    )


def test_ranker_structured_avoid_excludes_exact_id_only() -> None:
    # Two POIs share the same display name; only the structured avoid id
    # (avoid-a) may be excluded — its same-name sibling (sibling-b) survives.
    result = CandidateRanker().rank(
        (
            _poi("avoid-a", "陈家祠"),
            _poi("sibling-b", "陈家祠"),
        ),
        destination="广州",
        preferences=(),
        traveler_type="FRIENDS",
        limit=2,
        avoid_provider_ids=frozenset({"avoid-a"}),
    )

    selected = [item.poi.provider_id for item in result.selected]
    rejected = [item.poi.provider_id for item in result.rejected]
    assert "sibling-b" in selected
    assert "avoid-a" not in selected
    assert "avoid-a" in rejected


def test_ranker_structured_avoid_order_independent() -> None:
    first = CandidateRanker().rank(
        (
            _poi("avoid-a", "陈家祠"),
            _poi("sibling-b", "陈家祠"),
            _poi("park", "越秀公园"),
        ),
        destination="广州",
        preferences=(),
        traveler_type="FRIENDS",
        limit=3,
        avoid_provider_ids=frozenset({"sibling-b"}),
    )
    second = CandidateRanker().rank(
        (
            _poi("park", "越秀公园"),
            _poi("sibling-b", "陈家祠"),
            _poi("avoid-a", "陈家祠"),
        ),
        destination="广州",
        preferences=(),
        traveler_type="FRIENDS",
        limit=3,
        avoid_provider_ids=frozenset({"sibling-b"}),
    )

    assert [item.poi.provider_id for item in first.selected] == [
        item.poi.provider_id for item in second.selected
    ]
    assert "sibling-b" not in [item.poi.provider_id for item in first.selected]


def test_ranker_unrecalled_structured_avoid_id_does_not_exclude_same_name() -> None:
    # The structured avoid id is not among the recalled POIs; a same-name
    # POI with a different id must NOT be excluded by text fallback.
    result = CandidateRanker().rank(
        (_poi("recalled", "陈家祠"),),
        destination="广州",
        preferences=(),
        traveler_type="FRIENDS",
        limit=1,
        avoid_provider_ids=frozenset({"unrecalled-id"}),
    )

    assert [item.poi.provider_id for item in result.selected] == ["recalled"]


def test_ranker_legacy_avoid_text_still_filters_by_text() -> None:
    result = CandidateRanker().rank(
        (
            _poi("tower", "广州塔"),
            _poi("chen", "陈家祠"),
        ),
        destination="广州",
        preferences=(),
        traveler_type="FRIENDS",
        limit=2,
        avoid_places=("广州塔",),
    )

    assert "tower" not in [item.poi.provider_id for item in result.selected]
    assert "chen" in [item.poi.provider_id for item in result.selected]


def test_ranker_structured_avoid_takes_precedence_over_legacy_text() -> None:
    # When structured ids are present, the exact-id semantics wins: the
    # same-name sibling is NOT text-excluded.
    result = CandidateRanker().rank(
        (
            _poi("avoid-a", "陈家祠"),
            _poi("sibling-b", "陈家祠"),
        ),
        destination="广州",
        preferences=(),
        traveler_type="FRIENDS",
        limit=2,
        avoid_provider_ids=frozenset({"avoid-a"}),
        avoid_places=("陈家祠",),
    )

    selected = [item.poi.provider_id for item in result.selected]
    assert "sibling-b" in selected
    assert "avoid-a" not in selected
