"""POI taxonomy, candidate quality, canonical identity, and duration profile.

This module owns the *place* semantics that the rest of the planning
pipeline relies on:

- whether a provider POI may be placed as a normal travel activity
  (``activity_candidate_eligible``);
- which POIs are legitimate travel anchors (railway/air/coach stations) that
  must NOT be filtered out because they serve ARRIVAL / DEPARTURE;
- a lightweight canonical identity for duplicate detection that is more
  stable than ``provider_poi_id``;
- a category-driven visit-duration profile with an explicit source, so a
  duration is never an untraceable magic number.

The provider taxonomy is AMap's ``type_code`` (a dotless numeric string whose
leading digits are the top-level class).  The primary rule uses that code;
a tiny name-based fallback covers only the POIs whose code is missing or
already ambiguous.
"""

from __future__ import annotations

from typing import Literal

from trip_agent.planning.visit_duration import (
    DurationProfileSource,
    VisitDurationProfile,
)
from trip_agent.providers.map import Poi

# AMap top-level classes (leading digits of type_code).
# 11 = 风景名胜, 08 = 体育休闲, 06 = 餐饮, 05 = 购物, 12 = 商务住宅.
_SCENIC_PREFIXES = ("11",)
_RECREATION_PREFIXES = ("0805",)  # 游乐场 (e.g. 长隆欢乐世界)
_ANCHOR_PREFIXES = (
    "1501",  # 机场 / 飞机场
    "150200",  # 火车站本体
    "1503",  # 港口 / 轮渡码头
    "150400",  # 长途汽车站本体
    "1508",  # 客运站
)
# Same transport top-level class but NOT the hub itself: station gates,
# entrances, metro lines, bus stops, parking, service areas, refuelling.
_FILTERED_TRANSPORT_PREFIXES = (
    "150201",  # 火车站 - 其他 / 附属
    "150202",  # 进站口 / 检票口
    "150203",  # 出站口
    "1505",  # 地铁站
    "1506",  # 地铁线 / 轻轨
    "1507",  # 公交车站
    "1509",  # 停车场
    "1510",  # 加油站
    "1511",  # 充电站
    "1512",  # 服务区
    "1513",  # 火车站内部通道 / 出入口附属
)

# Name-based fallback for a small set of transport-adjacent facilities whose
# type_code is missing or lands in a non-transport class.  This is a fallback
# only — the primary rule is the provider taxonomy above.
_INFRASTRUCTURE_NAME_MARKERS = (
    "公交站",
    "地铁站",
    "停车场",
    "充电站",
    "加油站",
    "服务区",
    "售票处",
    "出入口",
    "进站口",
    "出站口",
)
_ANCHOR_NAME_MARKERS = (
    "火车站",
    "高铁站",
    "机场",
    "客运站",
    "汽车站",
)

type PoiRole = Literal["KEEP", "FILTER", "ANCHOR_ONLY"]
type DurationSource = Literal[
    "PROVIDER", "CATEGORY_PROFILE", "CATEGORY_FALLBACK", "SYSTEM_DEFAULT"
]


def _code_class(type_code: str) -> str:
    """Return the normalised type_code (digits only)."""
    return "".join(character for character in type_code if character.isdigit())


def _name_marker(name: str, markers: tuple[str, ...]) -> bool:
    return any(marker in name for marker in markers)


def classify_poi_role(poi: Poi) -> PoiRole:
    """Classify a POI into KEEP / FILTER / ANCHOR_ONLY.

    - KEEP        : a normal travel-activity candidate (scenic, museum, ...).
    - FILTER      : pure infrastructure that is neither an activity nor an
                    anchor (bus stops, metro, parking, station gates, ...).
    - ANCHOR_ONLY : transport hubs usable for ARRIVAL / DEPARTURE but not as
                    a normal activity (airport, railway station, coach station).
    """
    code = _code_class(poi.type_code)
    if code.startswith(_SCENIC_PREFIXES) or code.startswith(_RECREATION_PREFIXES):
        return "KEEP"
    if code.startswith(_ANCHOR_PREFIXES):
        return "ANCHOR_ONLY"
    if code.startswith(_FILTERED_TRANSPORT_PREFIXES):
        return "FILTER"

    # Fallback for missing / unusual codes: rely on a small name marker set.
    if _name_marker(poi.name, _INFRASTRUCTURE_NAME_MARKERS):
        return "FILTER"
    if _name_marker(poi.name, _ANCHOR_NAME_MARKERS):
        return "ANCHOR_ONLY"

    # Unknown transport-class codes default to FILTER unless they are one of
    # the recognised top-level activity classes.
    if code.startswith("15"):
        return "FILTER"
    return "KEEP"


def activity_candidate_eligible(poi: Poi) -> bool:
    """Return whether ``poi`` may be placed as a normal travel activity.

    ``ANCHOR_ONLY`` transport hubs are NOT activities but stay usable as
    arrival/departure anchors elsewhere.
    """
    return classify_poi_role(poi) == "KEEP"


def canonical_poi_key(poi: Poi) -> str:
    """Return a lightweight canonical identity for a POI.

    Combines a normalised name, the activity-vs-anchor role, and rounded
    coordinates.  Child facilities of the same place (``光孝寺`` vs
    ``光孝寺-六祖殿``) share the same normalised base only when their role
    also matches — a transport child never merges with the attraction.

    This is deliberately conservative: two genuinely different attractions
    (``长隆野生动物世界`` vs ``长隆欢乐世界``) keep distinct keys.
    """
    role = classify_poi_role(poi)
    base = "".join(character for character in poi.name.casefold() if character.isalnum())
    # Round to ~1 km so near-identical records of the same place collapse;
    # distinct attractions at different locations stay apart.
    lon = round(poi.coordinates.longitude, 2)
    lat = round(poi.coordinates.latitude, 2)
    return f"{role}:{base}:{lon}:{lat}"


# B5: the canonical duration model lives in planning/visit_duration.py; keep
# the legacy name importable for existing callers.
DurationProfile = VisitDurationProfile


# Deterministic category -> duration profile.  The numbers are design guidance
# for the current domain model (LIGHT ~45-90, NORMAL ~90-180, HALF ~180-300,
# FULL ~360+).  A provider with explicit duration data can override these.
# Category/system profiles are never hard-constraint eligible.
_CATEGORY_VERSION = "category-profile-v1"
_LIGHT_PROFILE = VisitDurationProfile(
    45, 90, 120,
    DurationProfileSource.CATEGORY_PROFILE,
    source_ref="category:light",
    confidence=0.5,
    profile_version=_CATEGORY_VERSION,
)
_NORMAL_PROFILE = VisitDurationProfile(
    90, 150, 180,
    DurationProfileSource.CATEGORY_PROFILE,
    source_ref="category:normal",
    confidence=0.5,
    profile_version=_CATEGORY_VERSION,
)
_HALF_DAY_PROFILE = VisitDurationProfile(
    180, 240, 300,
    DurationProfileSource.CATEGORY_PROFILE,
    source_ref="category:half-day",
    confidence=0.5,
    profile_version=_CATEGORY_VERSION,
)
_FULL_DAY_PROFILE = VisitDurationProfile(
    360, 480, 540,
    DurationProfileSource.CATEGORY_PROFILE,
    source_ref="category:full-day",
    confidence=0.5,
    profile_version=_CATEGORY_VERSION,
)
_DEFAULT_PROFILE = VisitDurationProfile(
    90, 150, 180,
    DurationProfileSource.SYSTEM_DEFAULT,
    source_ref="system:default",
    confidence=0.3,
    profile_version=_CATEGORY_VERSION,
)

# Lightweight scalar markers that indicate a small/simple attraction.
# Deliberately excludes ambiguous landmark words ("塔", "楼") so that
# destination landmarks like 广州塔 are not treated as small sites.
_LIGHT_NAME_MARKERS = (
    "庙",
    "祠",
    "寺",
    "故居",
    "旧居",
    "纪念馆",
    "牌坊",
    "亭",
    "遗址",
    "石室",
    "教堂",
)
# Half-day markers (inherited from the provider's previous term list).
_HALF_DAY_MARKERS = (
    "风景区",
    "古镇",
    "遗址",
    "博物馆群",
    "国家公园",
    "森林公园",
    "湿地公园",
    "动物园",
    "植物园",
)
_FULL_DAY_MARKERS = (
    "泰山",
    "华山",
    "衡山",
    "黄山",
    "庐山",
    "峨眉",
    "山岳",
    "迪士尼",
    "迪斯尼",
    "长隆",
    "乐园",
    "环球影城",
    "主题公园",
    "度假区",
)


def _category_family(name: str, type_name: str) -> str:
    return f"{name} {type_name}"


def duration_profile_for(poi: Poi) -> DurationProfile:
    """Return the visit-duration profile for a POI.

    The profile is derived from the POI's category / scale markers.  No
    provider duration data is consulted here (the provider layer supplies that
    explicitly); this is the deterministic fallback used by the planner.
    """
    text = _category_family(poi.name, poi.type_name)
    if any(term in text for term in _FULL_DAY_MARKERS):
        return _FULL_DAY_PROFILE
    if any(term in text for term in _HALF_DAY_MARKERS):
        return _HALF_DAY_PROFILE
    if any(term in text for term in _LIGHT_NAME_MARKERS):
        return _LIGHT_PROFILE
    return _NORMAL_PROFILE


def magnitude_for_duration(profile: DurationProfile) -> str:
    """Map a duration profile to the current domain magnitude enum."""
    if profile.max_minutes >= 360:
        return "FULL_DAY"
    if profile.max_minutes >= 300:
        return "HALF_DAY"
    if profile.max_minutes <= 120:
        return "LIGHT"
    return "NORMAL"
