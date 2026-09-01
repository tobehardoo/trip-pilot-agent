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

from trip_agent.domain.shared import canonical_place_identity, mapped_places_match
from trip_agent.planning.visit_duration import (
    DurationProfileSource,
    VisitDurationProfile,
)
from trip_agent.providers.map import Poi

# AMap top-level classes (leading digits of type_code).
# 05 = 餐饮服务, 06 = 购物服务, 08 = 体育休闲, 10 = 住宿服务,
# 11 = 风景名胜, 12 = 商务住宅, 14 = 科教文化服务, 15 = 交通设施服务.
# (V2: the pre-V2 comment swapped 05/06 — the real AMap taxonomy is
#  05 餐饮 / 06 购物; the classification below matches the real taxonomy.)
_SCENIC_PREFIXES = ("11",)
_RECREATION_PREFIXES = ("0805",)  # 游乐场 (e.g. 长隆欢乐世界)
_MUSEUM_PREFIXES = ("14",)  # 科教文化服务（博物馆/展览馆/文化馆等）
_DINING_PREFIXES = ("05",)  # 餐饮服务
_ACCOMMODATION_PREFIXES = ("10",)  # 住宿服务
_SHOPPING_PREFIXES = ("06",)  # 购物服务
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

# V2 (Planning Intelligence 2.0): domain-level place semantics.
#
# ``PoiRole`` above is defined RELATIVE TO ONE CONSUMER (the sightseeing
# candidate pool) and cannot express "this is a restaurant".  ``PlaceKind``
# is the domain vocabulary every pool gates on:
#
# - ATTRACTION      → sightseeing candidates
# - RESTAURANT      → meal-planning candidates
# - ACCOMMODATION   → accommodation anchors
# - SHOPPING        → no pool today (never an attraction)
# - TRANSIT_HUB     → arrival / departure anchors
# - TRANSIT_INFRA   → never placed anywhere
# - OTHER           → a recognised NON-activity class (residential, medical,
#                     government, ...) — fail-closed, never an attraction
# - UNKNOWN         → missing / unparseable type_code — fail-closed
#
# The pre-V2 default branch returned KEEP for everything not explicitly
# handled, which leaked restaurants, hotels and malls into the sightseeing
# pool.  V2 is fail-closed: only explicitly allowed classes become
# attractions.
type PlaceKind = Literal[
    "ATTRACTION",
    "RESTAURANT",
    "ACCOMMODATION",
    "SHOPPING",
    "TRANSIT_HUB",
    "TRANSIT_INFRA",
    "OTHER",
    "UNKNOWN",
]

_PLACE_KIND_BY_PREFIX: tuple[tuple[tuple[str, ...], PlaceKind], ...] = (
    (_SCENIC_PREFIXES, "ATTRACTION"),
    (_RECREATION_PREFIXES, "ATTRACTION"),
    (_MUSEUM_PREFIXES, "ATTRACTION"),
    (_DINING_PREFIXES, "RESTAURANT"),
    (_ACCOMMODATION_PREFIXES, "ACCOMMODATION"),
    (_SHOPPING_PREFIXES, "SHOPPING"),
    (_ANCHOR_PREFIXES, "TRANSIT_HUB"),
    (_FILTERED_TRANSPORT_PREFIXES, "TRANSIT_INFRA"),
)

type DurationSource = Literal["PROVIDER", "CATEGORY_PROFILE", "CATEGORY_FALLBACK", "SYSTEM_DEFAULT"]


def _code_class(type_code: str) -> str:
    """Return the normalised type_code (digits only)."""
    return "".join(character for character in type_code if character.isdigit())


def _name_marker(name: str, markers: tuple[str, ...]) -> bool:
    return any(marker in name for marker in markers)


def classify_place(poi: Poi) -> PlaceKind:
    """Classify a POI into the domain place vocabulary (V2).

    Primary rule: the provider taxonomy (``type_code``).  Name-marker
    fallbacks cover only POIs whose code is missing or lands outside the
    recognised classes.  **Fail-closed**: a code that matches no rule
    yields ``OTHER``/``UNKNOWN``, never an activity kind.
    """
    code = _code_class(poi.type_code)
    for prefixes, kind in _PLACE_KIND_BY_PREFIX:
        if code.startswith(prefixes):
            return kind
    # Transport top-level class that matched no specific prefix.
    if code.startswith("15"):
        return "TRANSIT_INFRA"

    # Fallback for missing / unusual codes: a small name-marker set.
    if _name_marker(poi.name, _ANCHOR_NAME_MARKERS):
        return "TRANSIT_HUB"
    if _name_marker(poi.name, _INFRASTRUCTURE_NAME_MARKERS):
        return "TRANSIT_INFRA"
    if not code:
        return "UNKNOWN"
    # Recognised-but-non-activity class (residential, medical, government,
    # finance, ...).  Fail-closed: never an attraction, never a pool member.
    return "OTHER"


def classify_poi_role(poi: Poi) -> PoiRole:
    """Classify a POI into KEEP / FILTER / ANCHOR_ONLY.

    V2: derived from :func:`classify_place` — the role vocabulary answers
    the single question "may this enter the sightseeing pool?" while
    ``PlaceKind`` carries the domain semantics.

    - KEEP        : attraction-class places only (scenic, museum, ...).
    - FILTER      : everything else — dining, accommodation, shopping,
                    infrastructure, unknown (fail-closed).
    - ANCHOR_ONLY : transport hubs usable for ARRIVAL / DEPARTURE but not as
                    a normal activity (airport, railway station, coach station).
    """
    kind = classify_place(poi)
    if kind == "ATTRACTION":
        return "KEEP"
    if kind == "TRANSIT_HUB":
        return "ANCHOR_ONLY"
    return "FILTER"


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
    return canonical_place_identity(
        poi.name,
        poi.type_code,
        poi.coordinates.longitude,
        poi.coordinates.latitude,
    )


def same_mapped_place(left: Poi, right: Poi) -> bool:
    """Return whether two provider POIs are semantic records of one place."""
    return mapped_places_match(
        left.name,
        left.type_code,
        left.coordinates.longitude,
        left.coordinates.latitude,
        right.name,
        right.type_code,
        right.coordinates.longitude,
        right.coordinates.latitude,
    )


# Deterministic category -> duration profile.  The numbers are design guidance
# for the current domain model (LIGHT ~45-90, NORMAL ~90-180, HALF ~180-300,
# FULL ~360+).  A provider with explicit duration data can override these.
# Category/system profiles are never hard-constraint eligible.
_CATEGORY_VERSION = "category-profile-v1"
_LIGHT_PROFILE = VisitDurationProfile(
    45,
    90,
    120,
    DurationProfileSource.CATEGORY_PROFILE,
    source_ref="category:light",
    confidence=0.5,
    profile_version=_CATEGORY_VERSION,
)
_NORMAL_PROFILE = VisitDurationProfile(
    90,
    150,
    180,
    DurationProfileSource.CATEGORY_PROFILE,
    source_ref="category:normal",
    confidence=0.5,
    profile_version=_CATEGORY_VERSION,
)
_HALF_DAY_PROFILE = VisitDurationProfile(
    180,
    240,
    300,
    DurationProfileSource.CATEGORY_PROFILE,
    source_ref="category:half-day",
    confidence=0.5,
    profile_version=_CATEGORY_VERSION,
)
_FULL_DAY_PROFILE = VisitDurationProfile(
    360,
    480,
    540,
    DurationProfileSource.CATEGORY_PROFILE,
    source_ref="category:full-day",
    confidence=0.5,
    profile_version=_CATEGORY_VERSION,
)
_DEFAULT_PROFILE = VisitDurationProfile(
    90,
    150,
    180,
    DurationProfileSource.SYSTEM_DEFAULT,
    source_ref="system:default",
    confidence=0.3,
    profile_version=_CATEGORY_VERSION,
)
# V2 (SI-7): dining and accommodation stops never take attraction visit
# profiles.  The dining target matches the fixed 60-minute meal slot the
# scheduler reserves; accommodation is a check-in style stop, not a visit.
_DINING_PROFILE = VisitDurationProfile(
    45,
    60,
    90,
    DurationProfileSource.CATEGORY_PROFILE,
    source_ref="category:dining",
    confidence=0.5,
    profile_version=_CATEGORY_VERSION,
)
_ACCOMMODATION_PROFILE = VisitDurationProfile(
    30,
    45,
    60,
    DurationProfileSource.CATEGORY_PROFILE,
    source_ref="category:accommodation",
    confidence=0.5,
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


def duration_profile_for(poi: Poi) -> VisitDurationProfile:
    """Return the visit-duration profile for a POI.

    The profile is derived from the POI's category / scale markers.  No
    provider duration data is consulted here (the provider layer supplies that
    explicitly); this is the deterministic fallback used by the planner.

    V2: the semantic place kind wins over name markers — a restaurant named
    "…乐园" is still a dining stop (SI-7), never a full-day attraction.
    POIs whose kind is unknown (empty/unparseable type_code, e.g. pinned
    records) keep the marker-based fallback below.
    """
    kind = classify_place(poi)
    if kind == "RESTAURANT":
        return _DINING_PROFILE
    if kind == "ACCOMMODATION":
        return _ACCOMMODATION_PROFILE
    text = _category_family(poi.name, poi.type_name)
    if any(term in text for term in _FULL_DAY_MARKERS):
        return _FULL_DAY_PROFILE
    if any(term in text for term in _HALF_DAY_MARKERS):
        return _HALF_DAY_PROFILE
    if any(term in text for term in _LIGHT_NAME_MARKERS):
        return _LIGHT_PROFILE
    return _NORMAL_PROFILE


def magnitude_for_duration(profile: VisitDurationProfile) -> str:
    """Map a duration profile to the current domain magnitude enum."""
    if profile.max_minutes >= 360:
        return "FULL_DAY"
    if profile.max_minutes >= 300:
        return "HALF_DAY"
    if profile.max_minutes <= 120:
        return "LIGHT"
    return "NORMAL"
