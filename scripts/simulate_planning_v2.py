"""TripPilot Planning Intelligence V2 — counterfactual verification suite.

Runs the REAL planning pipeline (candidate ranking → scheduling → transport
→ cost → hard validation → evaluation → decision traces) against
deterministic fake providers, then verifies the V2 core claim:

    改变一个输入 → 系统决策是否真的变化 → Trace 是否能解释这个变化

Groups (one variable changed at a time):
    A. POI 语义完整性   — restaurants / hotels / malls / transit never enter
                          the sightseeing pool, yet still serve meals
    B. 天气反事实       — 晴 vs 暴雨: walking threshold → mode change + trace
    C. 预算反事实       — 10000 vs 1500: transport strategy + ranking + trace
    D. 人数反事实       — 1 vs 4: per-person cost scaling
    E. 节奏反事实       — BALANCED vs RELAXED vs INTENSIVE: day load
    F. 组合压力         — ideal vs adverse plan must differ explainably
    G. Trace 覆盖       — every key decision carries a reason + evidence

Usage:
    python scripts/simulate_planning_v2.py

Exit code 0 only when every group's acceptance check passes.
"""

from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid5

_SERVICE = Path(__file__).resolve().parents[1] / "apps" / "agent-service" / "src"
sys.path.insert(0, str(_SERVICE))

from trip_agent.domain.planning.protocols import PlanningResult  # noqa: E402
from trip_agent.evaluation.evaluator import PlanEvaluator  # noqa: E402
from trip_agent.evaluation.explanations import themed_user_explanations  # noqa: E402
from trip_agent.infrastructure.amap.planning_provider import (  # noqa: E402
    AmapPlanningProvider,
    budget_pressure_for,
    classify_place,
    resolve_transport_strategy_for_date,
)
from trip_agent.planning.poi_quality import activity_candidate_eligible  # noqa: E402
from trip_agent.providers._route_contracts import RoutePlan, RouteStep  # noqa: E402
from trip_agent.providers.errors import PlanningProviderError  # noqa: E402
from trip_agent.providers.map import (  # noqa: E402
    Coordinates,
    Poi,
    PoiSearchRequest,
    ProviderSuccess,
)
from trip_agent.worker.contracts import PlanningCreateCommand  # noqa: E402

# ── the simulated trip ───────────────────────────────────────────────────────

TRIP_START = date(2026, 9, 12)
TRIP_END = date(2026, 9, 14)
DESTINATION = "杭州"

# (id, name, type_name, type_code, district) — includes the audited leak
# classes ON PURPOSE: restaurants, a mall, a hotel and a rail station all
# flow through the same recall batch as the attractions.
POIS = (
    ("hz-xihu", "西湖", "风景名胜", "110000", "西湖区"),
    ("hz-lingyin", "灵隐寺", "风景名胜", "110000", "西湖区"),
    ("hz-museum", "浙江省博物馆", "博物馆", "140000", "西湖区"),
    ("hz-songcheng", "宋城", "风景名胜", "110000", "之江区"),
    ("hz-taiziwan", "太子湾公园", "风景名胜", "110000", "西湖区"),
    ("hz-huagang", "花港观鱼", "风景名胜", "110000", "西湖区"),
    ("hz-leifeng", "雷峰塔", "风景名胜", "110000", "西湖区"),
    ("hz-hefang", "河坊街", "步行街", "060000", "上城区"),
    ("hz-louwailou", "楼外楼", "餐饮", "050000", "西湖区"),
    ("hz-waipojia", "外婆家", "餐饮", "050000", "上城区"),
    ("hz-mall", "杭州大厦", "购物", "060000", "下城区"),
    ("hz-hotel", "杭州君悦酒店", "住宿", "100000", "上城区"),
    ("hz-east", "杭州东站", "交通设施", "150200", "上城区"),
)

TICKET_PRICES = {"灵隐寺": 75.0, "宋城": 320.0, "浙江省博物馆": 0.0, "河坊街": 0.0}
REFERENCE_SPEND = {"楼外楼": 180.0, "外婆家": 60.0}

# Deterministic routes: (duration_seconds, distance_meters, cost)
ROUTES = {
    "WALKING": (900, 900, None),
    "TRANSIT": (1_200, 4_000, 4.0),  # ¥4 per traveller
    "DRIVING": (1_000, 5_000, 28.0),  # ¥28 toll per vehicle
}

LEAK_CLASSES = {"楼外楼", "外婆家", "杭州大厦", "杭州君悦酒店", "杭州东站"}
RESTAURANTS = {"楼外楼", "外婆家"}


def _poi(provider_id: str, name: str, type_name: str, type_code: str, district: str) -> Poi:
    return Poi(
        provider_id=provider_id,
        name=name,
        coordinates=Coordinates(longitude=120.15, latitude=30.25),
        type_name=type_name,
        type_code=type_code,
        province="浙江省",
        city=DESTINATION,
        district=district,
        address=f"杭州市{district}{name}",
    )


class FakeMapProvider:
    """Serves the candidate set and, for meal searches, the restaurants."""

    async def search_pois(self, request: PoiSearchRequest):
        if "美食" in request.keyword or "餐厅" in request.keyword:
            data = tuple(_poi(*row) for row in POIS if row[1] in REFERENCE_SPEND)
        else:
            data = tuple(_poi(*row) for row in POIS if row[1] not in REFERENCE_SPEND)
        return ProviderSuccess(
            data=data,
            provider="AMAP",
            latency_ms=1,
            cached=False,
            fetched_at=datetime(2026, 9, 1, tzinfo=UTC),
            estimated=False,
        )


class FakeRouteProvider:
    def __init__(
        self, walking_duration: int = 900, transit_duration: int | None = None
    ) -> None:
        self.walking_duration = walking_duration
        self.transit_duration = transit_duration

    async def get_route(self, request):
        mode = request.mode
        duration, distance, cost = ROUTES[mode]
        if mode == "WALKING":
            duration = self.walking_duration
        if mode == "TRANSIT" and self.transit_duration is not None:
            duration = self.transit_duration
        origin = Coordinates(longitude=120.15, latitude=30.25)
        destination = Coordinates(longitude=120.16, latitude=30.26)
        return ProviderSuccess(
            data=RoutePlan(
                mode=mode,
                distance_meters=distance,
                duration_seconds=duration,
                steps=(
                    RouteStep(
                        instruction=mode,
                        distance_meters=distance,
                        duration_seconds=duration,
                        polyline=(origin, destination),
                    ),
                ),
                polyline=(origin, destination),
                estimated_cost=cost,
                walking_distance_meters=200 if mode == "TRANSIT" else None,
                transfer_count=1 if mode == "TRANSIT" else None,
            ),
            provider="AMAP",
            latency_ms=1,
            cached=False,
            fetched_at=datetime(2026, 9, 1, tzinfo=UTC),
            estimated=False,
        )


# ── command construction (as the Java server would emit it) ───────────────────

BASE_COMMAND = {
    "eventType": "PLANNING_CREATE_REQUESTED",
    "schemaVersion": 3,
    "eventId": "11111111-1111-1111-1111-111111111111",
    "traceId": "22222222-2222-2222-2222-222222222222",
    "taskId": "33333333-3333-3333-3333-333333333333",
    "tripId": "44444444-4444-4444-4444-444444444444",
    "occurredAt": "2026-09-11T03:00:00Z",
    "payload": {
        "taskType": "CREATE",
        "baselineTripVersion": 0,
        "idempotencyKey": "55555555-5555-5555-5555-555555555555",
        "trip": {
            "title": "杭州三日",
            "destination": DESTINATION,
            "startDate": TRIP_START.isoformat(),
            "endDate": TRIP_END.isoformat(),
            "status": "DRAFT",
            "version": 0,
            "constraints": {
                "budgetAmount": 8000,
                "travelers": 2,
                "travelerType": "COUPLE",
                "pace": "BALANCED",
                "preferences": ["历史", "文化"],
                "fixedSchedules": [],
                "mobilityLevel": "STANDARD",
                "schemaVersion": 2,
            },
        },
        "guideEvidence": {"facts": []},
        "planningContext": {
            "snapshotId": "66666666-6666-6666-6666-666666666666",
            "schemaVersion": 3,
            "tripId": "44444444-4444-4444-4444-444444444444",
            "planningTaskId": "33333333-3333-3333-3333-333333333333",
            "city": DESTINATION,
            "travelStartDate": TRIP_START.isoformat(),
            "travelEndDate": TRIP_END.isoformat(),
            "generatedAt": "2026-09-10T00:00:00Z",
            "stale": False,
            "sources": [
                {
                    "sourceName": "杭州市文化广电旅游局",
                    "sourceType": "OFFICIAL_TOURISM",
                    "sourceUrl": "https://www.gotohz.gov.cn/",
                    "reliabilityLevel": "OFFICIAL_TOURISM",
                }
            ],
            "facts": [],
            "conflicts": [],
            "excludedFacts": [],
            "diagnostics": [],
        },
    },
}


def _fact(category: str, statement: str, amount: float | None, target: str) -> dict:
    value = {"closed": True} if amount is None else {"amount": amount, "currency": "CNY"}
    return {
        "factId": f"fact_{category.lower()}_{target}",
        "category": category,
        "statement": statement,
        "normalizedValue": value,
        "evidence": statement,
        "effectiveDate": None,
        "checkedAt": "2026-09-08T00:00:00Z",
        "expiresAt": "2026-09-30T00:00:00Z",
        "stale": False,
        "sourceName": "杭州市文化广电旅游局",
        "sourceType": "OFFICIAL_TOURISM",
        "sourceUrl": "https://www.gotohz.gov.cn/",
        "reliabilityLevel": "OFFICIAL_TOURISM",
        "sourceReviewed": True,
        "hardConstraintEligible": False,
    }


def _weather_fact(statement: str) -> dict:
    # effectiveDate=None → the fact applies to EVERY trip day (the
    # planning_context_weather_statements applicability rule), so one
    # statement covers the whole 3-day window.
    return {
        "factId": "fact_weather_hangzhou",
        "category": "WEATHER",
        "statement": statement,
        "evidence": statement,
        "effectiveDate": None,
        "checkedAt": "2026-09-11T00:00:00Z",
        "expiresAt": "2026-09-15T00:00:00Z",
        "stale": False,
        "sourceName": "和风天气",
        "sourceType": "OFFICIAL_TOURISM",
        "sourceUrl": "https://www.qweather.com",
        "reliabilityLevel": "OFFICIAL_TOURISM",
        "sourceReviewed": True,
        "hardConstraintEligible": False,
    }


def build_command(
    *,
    budget: int = 8000,
    travelers: int = 2,
    weather: str | None = None,
    pace: str = "BALANCED",
    must_visit: tuple[str, ...] = ("西湖",),
) -> PlanningCreateCommand:
    payload = deepcopy(BASE_COMMAND)
    constraints = payload["payload"]["trip"]["constraints"]
    constraints["budgetAmount"] = budget
    constraints["travelers"] = travelers
    constraints["pace"] = pace
    constraints["mustVisitPlaces"] = list(must_visit)

    facts: list[dict] = [
        _fact("TICKET_PRICE", f"{name}成人门票 {price:g} 元", price, name)
        for name, price in TICKET_PRICES.items()
    ]
    facts += [
        _fact("REFERENCE_SPEND", f"{name}人均 {spend:g} 元", spend, name)
        for name, spend in REFERENCE_SPEND.items()
    ]
    if weather is not None:
        facts.append(_weather_fact(weather))
    payload["payload"]["planningContext"]["facts"] = facts
    return PlanningCreateCommand.model_validate(payload)


# ── run one plan through the real pipeline ───────────────────────────────────


def run(
    command: PlanningCreateCommand,
    *,
    walking_duration: int = 800,
    transit_duration: int | None = None,
) -> dict:
    route_provider = FakeRouteProvider(
        walking_duration=walking_duration, transit_duration=transit_duration
    )
    provider = AmapPlanningProvider(FakeMapProvider(), route_provider, route_provider)
    result: PlanningResult = asyncio.run(provider.plan(command))

    validated_at = datetime(2026, 9, 11, 2, 0, tzinfo=UTC)
    validation = None
    evaluation = None
    blocked: str | None = None
    try:
        from trip_agent.feasibility.validator import run_validation

        validation = run_validation(
            command=command,
            itinerary=result.itinerary,
            report_id=uuid5(command.task_id, "simulation"),
            validated_at=validated_at,
            trip_skeleton=result.trip_skeleton,
            validation_inputs=result.validation_inputs,
        )
    except PlanningProviderError as error:
        blocked = error.details.safe_message
    try:
        evaluation = PlanEvaluator().evaluate(command, result)
    except PlanningProviderError as error:
        blocked = error.details.safe_message
    strategy = resolve_transport_strategy_for_date(command, TRIP_START)

    return {
        "result": result,
        "validation": validation,
        "evaluation": evaluation,
        "blocked": blocked,
        "strategy": strategy,
        "pressure": budget_pressure_for(command),
    }


# ── inspection helpers ───────────────────────────────────────────────────────


def attraction_titles(out: dict) -> list[str]:
    return [
        activity.title
        for day in out["result"].itinerary.days
        for activity in day.activities
        if activity.kind in {"ATTRACTION", "EXPERIENCE"}
    ]


def meal_bindings(out: dict) -> list[tuple[str, str | None]]:
    return [
        (activity.title, activity.provider_poi_id)
        for day in out["result"].itinerary.days
        for activity in day.activities
        if activity.kind == "MEAL"
    ]


def leg_modes(out: dict) -> list[str]:
    return [
        leg.mode for day in out["result"].itinerary.days for leg in day.transit_legs
    ]


def trace_codes(out: dict) -> list[str]:
    codes: list[str] = []
    for trace in out["result"].decision_traces:
        codes.extend(trace.reason_codes)
    return codes


def traces_with(out: dict, code: str) -> int:
    return sum(1 for trace in out["result"].decision_traces if code in trace.reason_codes)


def trace_evidence(out: dict, code: str) -> dict[str, str]:
    for trace in out["result"].decision_traces:
        if code in trace.reason_codes:
            return {item.key: item.value for item in trace.evidence}
    return {}


def day_load(out: dict) -> list[tuple[int, int, str]]:
    """Per day: (attraction count, meal count, last activity end HH:MM)."""
    rows = []
    for day in out["result"].itinerary.days:
        attractions = sum(
            1 for a in day.activities if a.kind in {"ATTRACTION", "EXPERIENCE"}
        )
        meals = sum(1 for a in day.activities if a.kind == "MEAL")
        ends = [a.end_time for a in day.activities if a.end_time is not None]
        last = max(ends).strftime("%H:%M") if ends else "—"
        rows.append((attractions, meals, last))
    return rows


def explanation_codes(out: dict) -> list[str]:
    evaluation = out["evaluation"]
    if evaluation is None:
        return []
    codes: list[str] = []
    for decision in evaluation.decisions:
        codes.extend(decision.reason_codes)
    return codes


RESULTS: list[tuple[str, str, bool, str]] = []


def check(group: str, name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((group, name, ok, detail))
    mark = "✅" if ok else "❌"
    print(f"    {mark} {name}" + (f"  — {detail}" if detail else ""))


def summarize_plan(label: str, out: dict) -> None:
    itinerary = out["result"].itinerary
    print(f"\n  ── {label} ──")
    for index, day in enumerate(itinerary.days, start=1):
        lines = []
        for activity in day.activities:
            cost = f"{activity.estimated_cost}元"
            lines.append(f"{activity.kind[:4]}:{activity.title}({cost})")
        modes = [leg.mode for leg in day.transit_legs]
        print(f"    Day{index} {' · '.join(lines)}")
        print(f"          legs: {modes if modes else '—'}")
    print(f"    总成本 {itinerary.estimated_total_cost} 元")


# ── group runners ────────────────────────────────────────────────────────────


def group_a() -> None:
    print(f"\n{'=' * 78}\n组 A · POI 语义完整性（餐厅/酒店/商场/车站 vs 景点池）\n{'=' * 78}")

    expected = {
        "西湖": "ATTRACTION",
        "灵隐寺": "ATTRACTION",
        "浙江省博物馆": "ATTRACTION",
        "宋城": "ATTRACTION",
        "太子湾公园": "ATTRACTION",
        "花港观鱼": "ATTRACTION",
        "雷峰塔": "ATTRACTION",
        "楼外楼": "RESTAURANT",
        "外婆家": "RESTAURANT",
        "杭州大厦": "SHOPPING",
        "河坊街": "SHOPPING",
        "杭州君悦酒店": "ACCOMMODATION",
        "杭州东站": "TRANSIT_HUB",
    }
    rows = {_poi(*row).name: classify_place(_poi(*row)) for row in POIS}
    print("\n  A1. 分类表（classify_place）")
    mismatches = {name: rows[name] for name, kind in expected.items() if rows.get(name) != kind}
    for name, kind in expected.items():
        print(f"        {name:<10} → {rows.get(name)}")
    check("A1", "14 类分类表全部符合语义", not mismatches, str(mismatches) if mismatches else "")

    # 景点池准入：只有 ATTRACTION 类可进（含被审计钉为“碰巧正确”的东站）
    ineligible = [name for name, kind in expected.items() if kind != "ATTRACTION"]
    pool_leaks = [
        name
        for name in ineligible
        if activity_candidate_eligible(next(_poi(*row) for row in POIS if row[1] == name))
    ]
    check("A1", "非景点类一律不进景点候选池（fail-closed）", not pool_leaks, str(pool_leaks))

    # 端到端：完整管道产出的行程不含任何泄漏 POI
    out = run(build_command(weather="9 月 12 日至 14 日杭州晴，26℃。"))
    attractions = attraction_titles(out)
    leaked_into_plan = [title for title in attractions if title in LEAK_CLASSES]
    summarize_plan("A 端到端（晴，BALANCED，预算 8000）", out)
    check("A1", "行程中 ATTRACTION/EXPERIENCE 不含餐厅/酒店/商场/车站", not leaked_into_plan, str(leaked_into_plan))

    print("\n  A2. 餐食绑定（RESTAURANT → Meal）")
    bindings = meal_bindings(out)
    for title, poi_id in bindings:
        print(f"        MEAL ← {title} ({poi_id})")
    with_poi = [title for title, poi_id in bindings if poi_id is not None]
    ok_a2 = bool(with_poi) and all(title in RESTAURANTS for title in with_poi)
    check("A2", "所有带 POI 的 MEAL 都绑定真实餐厅", ok_a2, f"绑定: {sorted(set(with_poi))}")


def group_b() -> None:
    print(f"\n{'=' * 78}\n组 B · 天气反事实（唯一变量：晴 → 暴雨；步行 800s）\n{'=' * 78}")

    sunny = run(build_command(weather="9 月 12 日至 14 日杭州晴，26℃。"), walking_duration=800)
    storm = run(build_command(weather="9 月 12 日至 14 日杭州暴雨。"), walking_duration=800)

    print(f"\n  晴:  阈值 {sunny['strategy'].walking_threshold_seconds}s 理由 {sunny['strategy'].reason} · legs {set(leg_modes(sunny))}")
    print(f"  暴雨: 阈值 {storm['strategy'].walking_threshold_seconds}s 理由 {storm['strategy'].reason} · legs {set(leg_modes(storm))}")
    summarize_plan("B 暴雨行程", storm)

    check("B1", "晴天 800s 步行在阈值内 → WALKING", "WALKING" in set(leg_modes(sunny)))
    check("B1", "晴天无模式决策 trace（默认策略，无话可说）", traces_with(sunny, "TRANSIT_MODE") == 0)
    check("B2", "暴雨 800s 步行超阈值 → 模式改变", set(leg_modes(storm)) - {"WALKING"}, f"legs {sorted(set(leg_modes(storm)))}")
    check("B", "晴 ≠ 暴雨（交通决策确实改变）", set(leg_modes(sunny)) != set(leg_modes(storm)))

    evidence = trace_evidence(storm, "TRANSIT_MODE")
    print(f"  暴雨 TRANSIT_MODE trace 证据: {evidence}")
    check(
        "B2",
        "TRANSIT_MODE trace 携带天气证据",
        evidence.get("weather_level") == "STORM"
        and evidence.get("walking_threshold_seconds") == "300"
        and evidence.get("walking_duration_seconds") == "800",
        str(evidence),
    )


def group_c() -> None:
    print(f"\n{'=' * 78}\n组 C · 预算反事实（唯一变量：预算 10000 → 1500；步行 3000s 不可行）\n{'=' * 78}")

    loose = run(build_command(budget=10000), walking_duration=3_000, transit_duration=1_300)
    tight = run(build_command(budget=1500), walking_duration=3_000, transit_duration=1_300)

    print(f"\n  宽松 10000: 压力 {loose['pressure']} · 容忍比 {loose['strategy'].max_transit_duration_ratio} · 理由 {loose['strategy'].reason} · legs {sorted(set(leg_modes(loose)))}")
    print(f"  紧张 1500:  压力 {tight['pressure']} · 容忍比 {tight['strategy'].max_transit_duration_ratio} · 理由 {tight['strategy'].reason} · legs {sorted(set(leg_modes(tight)))}")
    summarize_plan("C 紧张预算行程（1500）", tight)

    check("C", "预算压力 1500→TIGHT / 10000→非TIGHT", tight["pressure"] == "TIGHT" and loose["pressure"] != "TIGHT")
    check("C", "交通策略改变（公交容忍比 1.6 vs 1.2）", tight["strategy"].max_transit_duration_ratio != loose["strategy"].max_transit_duration_ratio)
    check("C", "交通方式改变（紧张→TRANSIT，宽松→DRIVING）", set(leg_modes(tight)) != set(leg_modes(loose)), f"{sorted(set(leg_modes(loose)))} → {sorted(set(leg_modes(tight)))}")
    check("C", "BUDGET_CONSTRAINT trace 仅出现在紧张侧", traces_with(tight, "BUDGET_CONSTRAINT") >= 1 and traces_with(loose, "BUDGET_CONSTRAINT") == 0)
    evidence = trace_evidence(tight, "BUDGET_CONSTRAINT")
    print(f"  BUDGET_CONSTRAINT trace 证据: {evidence}")
    check("C", "BUDGET_CONSTRAINT 证据含 budget_pressure", evidence.get("budget_pressure") == "TIGHT")
    print(f"  评估器硬约束: tight blocked={tight['blocked']!r} / loose blocked={loose['blocked']!r}")
    check(
        "C",
        "总成本超预算时评估器硬拦截（预算不止是排序信号）",
        tight["blocked"] is not None and loose["blocked"] is None,
        f"tight blocked={tight['blocked']}",
    )

    # 排序侧：宋城门票 320 元，紧张预算下上限 = 250×0.35 = 87.5 → 必然降权，
    # 池内有 7 个景点竞争时，降权的宋城应被挤出或减产。
    print(f"\n  候选排序对照: 宋城在宽松侧出现 {attraction_titles(loose).count('宋城')} 次，在紧张侧出现 {attraction_titles(tight).count('宋城')} 次")
    check(
        "C",
        "高票价候选在紧张预算下降权或被挤出（排序真的变了）",
        attraction_titles(loose).count("宋城") != attraction_titles(tight).count("宋城")
        or attraction_titles(loose) != attraction_titles(tight),
        f"宽松={attraction_titles(loose)} 紧张={attraction_titles(tight)}",
    )


def group_d() -> None:
    print(f"\n{'=' * 78}\n组 D · 人数反事实（唯一变量：1 人 → 4 人）\n{'=' * 78}")

    solo = run(build_command(travelers=1))
    quad = run(build_command(travelers=4))

    solo_total = solo["result"].itinerary.estimated_total_cost
    quad_total = quad["result"].itinerary.estimated_total_cost
    print(f"\n  1 人总成本 {solo_total} 元 · 4 人总成本 {quad_total} 元")
    summarize_plan("D 4 人行程", quad)

    ticket_solo = next(
        (a.estimated_cost for d in solo["result"].itinerary.days for a in d.activities if a.title == "灵隐寺"),
        None,
    )
    ticket_quad = next(
        (a.estimated_cost for d in quad["result"].itinerary.days for a in d.activities if a.title == "灵隐寺"),
        None,
    )
    print(f"  灵隐寺门票行: 1 人 {ticket_solo} 元 · 4 人 {ticket_quad} 元（75/人 × 人数）")
    check("D", "总成本随人数显著变化", quad_total > solo_total, f"{solo_total} → {quad_total}")
    check("D", "门票按人数缩放（1 人 75 / 4 人 300）", ticket_solo == 75 and ticket_quad == 300, f"{ticket_solo} → {ticket_quad}")


def group_e() -> None:
    print(f"\n{'=' * 78}\n组 E · 节奏反事实（唯一变量：BALANCED / RELAXED / INTENSIVE）⭐\n{'=' * 78}")

    runs = {
        pace: run(build_command(pace=pace))
        for pace in ("BALANCED", "RELAXED", "INTENSIVE")
    }
    loads = {pace: day_load(out) for pace, out in runs.items()}
    for pace, load in loads.items():
        print(f"\n  {pace}: (景点数, 餐数, 日终) 逐日 = {load}")
        summarize_plan(f"E {pace}", runs[pace])

    total = {pace: sum(row[0] for row in load) for pace, load in loads.items()}
    print(f"\n  三日景点总数: BALANCED {total['BALANCED']} · RELAXED {total['RELAXED']} · INTENSIVE {total['INTENSIVE']}")
    check("E", "RELAXED 日负载 < BALANCED（AC-5，行程级）", total["RELAXED"] < total["BALANCED"])
    check("E", "RELAXED 餐食时间不受影响（每天 2 餐）", all(row[1] == 2 for row in loads["RELAXED"]))
    check("E", "INTENSIVE 未因新增 RELAXED 策略退化", total["INTENSIVE"] >= total["BALANCED"] and total["INTENSIVE"] >= total["RELAXED"])
    pace_traces = traces_with(runs["RELAXED"], "PACE_POLICY")
    balanced_traces = traces_with(runs["BALANCED"], "PACE_POLICY")
    evidence = trace_evidence(runs["RELAXED"], "PACE_POLICY")
    print(f"  PACE_POLICY trace 证据: {evidence}")
    check("E", "RELAXED 的 PACE_POLICY trace 存在，BALANCED 无", pace_traces >= 1 and balanced_traces == 0)


def group_f() -> None:
    print(f"\n{'=' * 78}\n组 F · 组合压力（F1 理想 vs F2 恶劣：暴雨 + 低预算 + RELAXED）⭐⭐⭐\n{'=' * 78}")

    f1 = run(build_command(budget=8000, weather="9 月 12 日至 14 日杭州晴，26℃。", pace="BALANCED"))
    f2 = run(build_command(budget=2500, weather="9 月 12 日至 14 日杭州暴雨。", pace="RELAXED"))
    # F2'：把预算压到真正的 TIGHT（2500÷2÷3=417 元/日/人 ≥ 300，属 NORMAL 压力）
    f2_tight = run(build_command(budget=1500, weather="9 月 12 日至 14 日杭州暴雨。", pace="RELAXED"))

    summarize_plan("F1 理想（晴 / 8000 / BALANCED）", f1)
    summarize_plan("F2 恶劣（暴雨 / 2500 / RELAXED）", f2)
    summarize_plan("F2' 恶劣加强（暴雨 / 1500 / RELAXED）", f2_tight)

    print(f"\n  F1 legs {sorted(set(leg_modes(f1)))} vs F2 legs {sorted(set(leg_modes(f2)))}")
    print(f"  F1 总成本 {f1['result'].itinerary.estimated_total_cost} vs F2 {f2['result'].itinerary.estimated_total_cost}")
    print(f"  F1 景点总数 {sum(r[0] for r in day_load(f1))} vs F2 {sum(r[0] for r in day_load(f2))}")
    print(f"  F2  traces: {sorted(set(trace_codes(f2)))}")
    print(f"  F2' traces: {sorted(set(trace_codes(f2_tight)))}")

    check("F", "F1 ≠ F2（行程与交通明显不同）", attraction_titles(f1) != attraction_titles(f2) or set(leg_modes(f1)) != set(leg_modes(f2)))
    check("F", "F2 天气策略生效（暴雨 → 非步行主导）", "WALKING" not in set(leg_modes(f2)))
    check("F", "F2 节奏策略生效（RELAXED 总负载 < BALANCED）", sum(r[0] for r in day_load(f2)) < sum(r[0] for r in day_load(f1)))
    check(
        "F",
        "F2' 三个 Policy 同时留痕（WEATHER+PACE+TRACE）",
        traces_with(f2_tight, "TRANSIT_MODE") >= 1
        and traces_with(f2_tight, "PACE_POLICY") >= 1
        and traces_with(f2_tight, "BUDGET_CONSTRAINT") >= 1,
    )
    # 成本差异必须可解释：按活动类别精确分解（景点/餐食/住宿/交通），
    # 分类差之和必须等于总成本差——任何一笔钱都能说出去处。
    def cost_parts(out: dict) -> tuple[object, object, object, object, object]:
        it = out["result"].itinerary
        attr = sum(
            (a.estimated_cost for d in it.days for a in d.activities if a.kind in {"ATTRACTION", "EXPERIENCE"}),
            Decimal("0"),
        )
        meals = sum(
            (a.estimated_cost for d in it.days for a in d.activities if a.kind == "MEAL"),
            Decimal("0"),
        )
        accom = sum(
            (a.estimated_cost for d in it.days for a in d.activities if a.kind == "ACCOMMODATION"),
            Decimal("0"),
        )
        legs = sum(
            (leg.estimated_cost or Decimal("0") for d in it.days for leg in d.transit_legs),
            Decimal("0"),
        )
        return attr, meals, accom, legs, it.estimated_total_cost

    p1, p2t = cost_parts(f1), cost_parts(f2_tight)
    delta = p2t[4] - p1[4]
    breakdown = p2t[0] - p1[0], p2t[1] - p1[1], p2t[2] - p1[2], p2t[3] - p1[3]
    closes = delta == sum(breakdown, Decimal("0"))
    print(
        f"\n  成本分解 F1 → F2'（Δ={delta}）: 景点 {breakdown[0]} · 餐食 {breakdown[1]}"
        f" · 住宿 {breakdown[2]} · 交通 {breakdown[3]}"
    )
    check("F", "F2' 与 F1 的总成本差可被类别分解精确解释", closes, f"Δ={delta} 分解和={sum(breakdown, Decimal('0'))}")


def group_g() -> None:
    print(f"\n{'=' * 78}\n组 G · Trace 覆盖（每个关键决策都有理由与证据）\n{'=' * 78}")

    scenarios = {
        "暴雨": build_command(weather="9 月 12 日至 14 日杭州暴雨。"),
        "低预算": build_command(budget=1500),
        "RELAXED": build_command(pace="RELAXED"),
    }
    for label, command in scenarios.items():
        out = run(command)
        codes = sorted(set(trace_codes(out)))
        explained = sorted(set(explanation_codes(out)))
        print(f"\n  [{label}]")
        print(f"    决策 traces: {codes}")
        print(f"    评估器 DecisionExplanation codes: {explained}")
        for trace in out["result"].decision_traces:
            print(f"    · [{trace.subject_type}] {trace.summary}")
            print(f"      codes={list(trace.reason_codes)} evidence={{{', '.join(i.key + '=' + i.value for i in trace.evidence)}}}")

    storm = run(build_command(weather="9 月 12 日至 14 日杭州暴雨。"))
    tight = run(build_command(budget=1500), walking_duration=3_000, transit_duration=1_300)
    relaxed = run(build_command(pace="RELAXED"))
    check("G", "天气决策可解释（TRANSIT_MODE + evidence）", trace_evidence(storm, "TRANSIT_MODE").get("weather_level") == "STORM")
    check("G", "预算决策可解释（BUDGET_CONSTRAINT + budget_pressure）", trace_evidence(tight, "BUDGET_CONSTRAINT").get("budget_pressure") == "TIGHT")
    check("G", "节奏决策可解释（PACE_POLICY + 折扣证据）", trace_evidence(relaxed, "PACE_POLICY").get("pace") == "RELAXED")

    # V3 P2-3: themed user explanations ("为什么这份方案适合你")
    def themes(out: dict) -> tuple[str, ...]:
        evaluation = out["evaluation"]
        if evaluation is None:
            return ()
        return tuple(theme.topic for theme in themed_user_explanations(evaluation.decisions))

    combined = run(
        build_command(budget=1500, weather="9 月 12 日至 14 日杭州暴雨。", pace="RELAXED")
    )
    # 未拦截的组合（预算 3000 → NORMAL 压力）：主题解释正常产出
    combined_soft = run(
        build_command(budget=3000, weather="9 月 12 日至 14 日杭州暴雨。", pace="RELAXED")
    )
    storm_themes, relaxed_themes = themes(storm), themes(relaxed)
    soft_themes, combined_themes = themes(combined_soft), themes(combined)
    combined_codes = set(trace_codes(combined))
    print(
        f"\n  主题解释: 暴雨→{storm_themes} 节奏→{relaxed_themes}"
        f" 组合(3000)→{soft_themes} 组合(1500,拦截)→{combined_themes}"
    )
    check("G", "暴雨方案出现「天气调整」主题", "WEATHER" in storm_themes)
    check("G", "RELAXED 方案出现「旅行节奏」主题", "PACE" in relaxed_themes)
    check(
        "G",
        "未拦截组合方案同现天气/节奏主题",
        {"WEATHER", "PACE"} <= set(soft_themes),
        str(soft_themes),
    )
    check(
        "G",
        "被预算拦截的组合方案：三主题的原始 traces 仍完整（解释不因拦截丢失）",
        {"TRANSIT_MODE", "BUDGET_CONSTRAINT", "PACE_POLICY"} <= combined_codes,
        str(combined_codes),
    )


def main() -> None:
    print("=" * 78)
    print("TripPilot Planning Intelligence V2 — 反事实验证（输入变 → 决策变 → Trace 解释）")
    print("=" * 78)
    print(
        "\n统一输入: 杭州 · 3 天（9/12–9/14）· 2 人 · BALANCED · 预算 8000 · 必去西湖\n"
        "每次只改变一个变量；地图与路径为确定性假实现，其余全部生产代码路径。"
    )

    group_a()
    group_b()
    group_c()
    group_d()
    group_e()
    group_f()
    group_g()

    print(f"\n{'=' * 78}\n最终验收表\n{'=' * 78}")
    print(f"{'组':<6}{'检查项':<46}{'结果':<6}")
    print("-" * 78)
    failed = 0
    for group, name, ok, detail in RESULTS:
        mark = "✅" if ok else "❌"
        if not ok:
            failed += 1
        print(f"{group:<6}{name:<46}{mark:<6}")
        if detail and not ok:
            print(f"{'':<6}└ {detail}")
    print("-" * 78)
    print(f"通过 {len(RESULTS) - failed}/{len(RESULTS)}")
    if failed:
        print(f"\n❌ {failed} 项未通过")
        sys.exit(1)
    print(
        "\n结论: 同一城市、同样兴趣，仅改变天气/预算/人数/节奏，\n"
        "TripPilot 生成明显不同且可解释的方案 —— V2 决策闭环成立。"
    )


if __name__ == "__main__":
    main()
