"""Targeted tests for POI candidate quality, canonical identity, and duration.

Covers the polish goals:
- transport noise never becomes a normal activity candidate;
- railway/airport/coach hubs stay available as ARRIVAL / DEPARTURE anchors;
- canonical identity collapses same-place sub-facilities without merging
  genuinely different attractions;
- duration profile emits LIGHT for small attractions and never compresses
  a FULL_DAY into a short slot.
"""

import pytest

from trip_agent.planning.poi_quality import (
    activity_candidate_eligible,
    canonical_poi_key,
    classify_poi_role,
    duration_profile_for,
    magnitude_for_duration,
    same_mapped_place,
)
from trip_agent.providers.map import Coordinates, Poi


def _poi(
    name: str,
    type_code: str,
    type_name: str,
    *,
    lon: float = 113.31,
    lat: float = 23.13,
) -> Poi:
    return Poi(
        provider_id=f"id-{name}",
        name=name,
        coordinates=Coordinates(longitude=lon, latitude=lat),
        type_name=type_name,
        type_code=type_code,
        province="广东省",
        city="广州市",
        district="越秀区",
        address=f"{name}地址",
    )


# ── Candidate Quality ────────────────────────────────────────────────────


def test_bus_stop_is_not_activity_candidate() -> None:
    bus_stop = _poi("光孝寺(公交站)", "150700", "交通设施服务;公交车站;公交车站相关")
    assert activity_candidate_eligible(bus_stop) is False
    assert classify_poi_role(bus_stop) == "FILTER"


def test_parking_is_not_activity_candidate() -> None:
    parking = _poi("花园酒店地下停车场", "150904", "交通设施服务;停车场;公共停车场")
    assert activity_candidate_eligible(parking) is False
    assert classify_poi_role(parking) == "FILTER"


def test_metro_and_station_gates_are_filtered() -> None:
    metro = _poi("广州塔(地铁站)", "150500", "交通设施服务;地铁站;地铁站")
    gate = _poi("广州南站(东进站口)", "150202", "交通设施服务;火车站;进站口/检票口")
    assert classify_poi_role(metro) == "FILTER"
    assert classify_poi_role(gate) == "FILTER"


def test_railway_station_is_anchor_only_not_activity() -> None:
    station = _poi("广州南站", "150200", "交通设施服务;火车站;火车站")
    assert classify_poi_role(station) == "ANCHOR_ONLY"
    assert activity_candidate_eligible(station) is False


def test_airport_and_coach_station_are_anchor_only() -> None:
    airport = _poi("广州白云国际机场", "150104", "交通设施服务;机场相关;飞机场")
    coach = _poi("天河汽车客运站", "150400", "交通设施服务;长途汽车站;长途汽车站")
    assert classify_poi_role(airport) == "ANCHOR_ONLY"
    assert classify_poi_role(coach) == "ANCHOR_ONLY"


def test_normal_attractions_are_kept() -> None:
    tower = _poi("广州塔", "110202", "风景名胜;风景名胜;国家级景点")
    museum = _poi("陈家祠堂", "110202", "风景名胜;风景名胜;国家级景点")
    park = _poi("白云山风景名胜区", "110202", "风景名胜;风景名胜;国家级景点")
    amusement = _poi("长隆欢乐世界", "080501", "体育休闲服务;休闲场所;游乐场")
    for poi in (tower, museum, park, amusement):
        assert activity_candidate_eligible(poi) is True


def test_scenic_attraction_never_filtered_by_name() -> None:
    # "塔" is a light marker but the POI stays a valid candidate.
    temple = _poi("光孝寺", "110204", "风景名胜;风景名胜;寺庙道观")
    assert activity_candidate_eligible(temple) is True


# ── Canonical Identity ───────────────────────────────────────────────────


def test_same_name_nearby_records_share_canonical_identity() -> None:
    main = _poi("光孝寺", "110204", "风景名胜;风景名胜;寺庙道观", lon=113.250, lat=23.130)
    duplicate = _poi("光孝寺", "110204", "风景名胜;风景名胜;寺庙道观", lon=113.251, lat=23.131)
    assert canonical_poi_key(main) == canonical_poi_key(duplicate)


def test_sub_facility_shares_the_parent_attraction_identity() -> None:
    # Sub-facilities are useful as map details, not independent itinerary
    # visits. Treating both as activities produces a visibly duplicated day.
    main = _poi("光孝寺", "110204", "风景名胜;风景名胜;寺庙道观", lon=113.25, lat=23.13)
    hall = _poi("光孝寺-六祖殿", "110204", "风景名胜;风景名胜;寺庙道观", lon=113.251, lat=23.131)
    assert canonical_poi_key(main) == canonical_poi_key(hall)


@pytest.mark.parametrize(
    ("canonical_name", "variant_name"),
    [
        ("陈家祠", "陈家祠堂"),
        ("广州塔", "广州塔-东广场"),
        ("广州塔", "广州塔（南门）"),
    ],
)
def test_common_provider_name_variants_share_canonical_identity(
    canonical_name: str,
    variant_name: str,
) -> None:
    canonical = _poi(
        canonical_name,
        "110202",
        "风景名胜;风景名胜;景点",
        lon=113.32,
        lat=23.11,
    )
    variant = _poi(
        variant_name,
        "110202",
        "风景名胜;风景名胜;景点",
        lon=113.321,
        lat=23.111,
    )
    assert canonical_poi_key(canonical) == canonical_poi_key(variant)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (
            ("广州塔", "110202", 113.324521, 23.106428),
            ("广州塔-东广场", "110105", 113.325324, 23.106236),
        ),
        (
            ("广州塔", "110202", 113.324521, 23.106428),
            ("广州塔A区", "110000|120000", 113.324516, 23.106432),
        ),
        (
            ("广州塔", "110202", 113.324521, 23.106428),
            ("广州塔广场", "060101", 113.324520, 23.105442),
        ),
        (
            ("广州塔", "110202", 113.324521, 23.106428),
            ("广州塔旅游区游客中心", "070000", 113.324212, 23.106001),
        ),
        (
            ("广州塔", "110202", 113.324521, 23.106428),
            ("广州塔观光区西登塔", "110000", 113.323890, 23.105933),
        ),
        (
            ("陈家祠", "190700", 113.246930, 23.127050),
            ("陈家祠堂", "110202", 113.245158, 23.126692),
        ),
        (
            ("陈家祠", "190700", 113.246930, 23.127050),
            ("陈家祠广场", "110105", 113.246887, 23.126938),
        ),
    ],
)
def test_real_amap_same_place_variants_match_across_type_and_grid_boundaries(
    left: tuple[str, str, float, float],
    right: tuple[str, str, float, float],
) -> None:
    first = _poi(left[0], left[1], "Provider category", lon=left[2], lat=left[3])
    second = _poi(right[0], right[1], "Provider category", lon=right[2], lat=right[3])

    assert same_mapped_place(first, second) is True


def test_transport_child_does_not_merge_with_attraction() -> None:
    main = _poi("光孝寺", "110204", "风景名胜;风景名胜;寺庙道观", lon=113.25, lat=23.13)
    bus_stop = _poi(
        "光孝寺(公交站)", "150700", "交通设施服务;公交车站;公交车站相关", lon=113.251, lat=23.131
    )
    assert canonical_poi_key(main) != canonical_poi_key(bus_stop)


def test_distinct_attractions_keep_distinct_identity() -> None:
    wildlife = _poi("长隆野生动物世界", "110102", "风景名胜;公园广场;动物园", lon=113.30, lat=22.98)
    funworld = _poi("长隆欢乐世界", "080501", "体育休闲服务;休闲场所;游乐场", lon=113.32, lat=22.99)
    assert canonical_poi_key(wildlife) != canonical_poi_key(funworld)


def test_must_visit_strict_match_not_reverted() -> None:
    # The provider's strict must-visit matching (previous fix) must stay:
    # child facilities are not flagged.  Here we just assert the canonical
    # identity keeps the attraction and its transport child apart.
    from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider

    must_set = {"光孝寺"}
    provider = AmapPlanningProvider(None, None)  # type: ignore[arg-type]
    main = _poi("光孝寺", "110204", "风景名胜;风景名胜;寺庙道观")
    hall = _poi("光孝寺-六祖殿", "110204", "风景名胜;风景名胜;寺庙道观")
    bus_stop = _poi("光孝寺(公交站)", "150700", "交通设施服务;公交车站;公交车站相关")
    assert provider._is_must_visit_poi(main, must_set) is True
    assert provider._is_must_visit_poi(hall, must_set) is False
    assert provider._is_must_visit_poi(bus_stop, must_set) is False


# ── Visit Duration Profile ───────────────────────────────────────────────


def test_small_attraction_produces_light_magnitude() -> None:
    temple = _poi("光孝寺", "110204", "风景名胜;风景名胜;寺庙道观")
    profile = duration_profile_for(temple)
    assert profile.recommended_minutes <= 90
    assert magnitude_for_duration(profile) == "LIGHT"


def test_normal_attraction_keeps_normal_magnitude() -> None:
    tower = _poi("广州塔", "110202", "风景名胜;风景名胜;国家级景点")
    profile = duration_profile_for(tower)
    assert profile.recommended_minutes == 150
    assert magnitude_for_duration(profile) == "NORMAL"


def test_full_day_is_not_compressed() -> None:
    resort = _poi("长隆野生动物世界", "110102", "风景名胜;公园广场;动物园")
    profile = duration_profile_for(resort)
    assert magnitude_for_duration(profile) == "FULL_DAY"
    assert profile.min_minutes >= 360


def test_provider_missing_duration_has_stable_fallback() -> None:
    # A POI with a generic category and no duration data gets the system
    # default via the category profile, never an arbitrary 150.
    generic = _poi("某街区", "190700", "地名地址信息;热点地名;热点地名")
    profile = duration_profile_for(generic)
    assert profile.source in {"CATEGORY_PROFILE", "SYSTEM_DEFAULT"}
    assert 0 < profile.recommended_minutes <= 180
