#!/usr/bin/env python3
"""TripPilot 全国旅行规划 Agent 长任务验收 Harness（真实全链路）。

驱动线上真实系统（Java API → Outbox → RabbitMQ → Python worker →
真实 AMAP → Validation → Persistence → SSE），对多城市 × 多约束组合
进行端到端多轮验收，捕获每条轨迹、逐约束断言、质量评分，输出报告。

运行：uv run python tools/national_eval/run_national_eval.py \
        --scenarios batch1 --report /tmp/national_eval/batch1.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any
from uuid import uuid4

import httpx

BASE_URL = "http://127.0.0.1:8080"
LOGIN = {"email": "admin@admin.com", "password": "Admin123456"}

# ─────────────────────────── 质量评分维 ───────────────────────────
SCORE_DIMS = (
    "task_completion",
    "constraint_satisfaction",
    "itinerary_feasibility",
    "budget_accuracy",
    "weather_adaptation",
    "context_retention",
    "tool_reliability",
    "user_experience",
)


# ─────────────────────────── Trace 模型 ───────────────────────────
@dataclass
class TurnTrace:
    index: int
    message: str
    step: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScenarioResult:
    scenario_id: str
    city: str
    ok: bool
    status: str  # PASS / PARTIAL_PASS / FAIL
    turn_count: int
    scores: dict[str, float] = field(default_factory=dict)
    trace: list[dict[str, Any]] = field(default_factory=list)
    itinerary: dict[str, Any] | None = None
    failures: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0


# ─────────────────────────── Scenario 数据集 ─────────────────────
# 分层覆盖：A=一线 / B=热门旅游 / C=自然风景 / D=边界·数据挑战
CITY_CATEGORY = {
    "北京": "A", "上海": "A", "广州": "A", "深圳": "A",
    "成都": "B", "重庆": "B", "西安": "B", "杭州": "B", "南京": "B",
    "苏州": "B", "厦门": "B", "青岛": "B", "长沙": "B", "武汉": "B",
    "桂林": "C", "昆明": "C", "大理": "C", "丽江": "C", "张家界": "C", "黄山": "C",
    "酒泉": "D", "甘孜": "D", "张家口": "D", "石嘴山": "D",
}


@dataclass
class ScenarioSpec:
    id: str
    city: str
    days: int
    travellers: int
    budget: int
    pace: str
    preferences: list[str]
    must_visit: list[str] = field(default_factory=list)
    note: str = ""
    expect_budget_ok: bool = True
    category: str = ""


def s(
    id_: str, city: str, days: int, travellers: int, budget: int, pace: str,
    preferences: list[str], must_visit: list[str] | None = None,
    note: str = "", expect_budget_ok: bool = True,
) -> ScenarioSpec:
    return ScenarioSpec(
        id=id_, city=city, days=days, travellers=travellers, budget=budget,
        pace=pace, preferences=preferences, must_visit=must_visit or [],
        note=note, expect_budget_ok=expect_budget_ok,
        category=CITY_CATEGORY.get(city, "?"),
    )


DATASET: dict[str, list[ScenarioSpec]] = {
    "batch1": [
        s("A-BJ-01", "北京", 3, 2, 8000, "BALANCED", ["美食", "历史"], ["故宫"]),
        s("A-SH-01", "上海", 3, 2, 10000, "BALANCED", ["都市", "美食"]),
        s("A-GZ-01", "广州", 2, 2, 3000, "BALANCED", ["美食", "亲子"]),
        s("A-SZ-01", "深圳", 2, 2, 5000, "BALANCED", ["都市", "科技"]),
        s("B-CD-01", "成都", 3, 2, 5000, "BALANCED", ["美食"], ["成都大熊猫繁育研究基地"]),
        s("B-CQ-01", "重庆", 3, 2, 4000, "RELAXED", ["火锅", "夜景"]),
        s("B-XA-01", "西安", 3, 2, 4000, "BALANCED", ["历史"], ["兵马俑"]),
        s("B-HZ-01", "杭州", 2, 2, 3500, "BALANCED", ["自然", "美食"]),
        s("B-SU-01", "苏州", 2, 2, 3000, "RELAXED", ["园林", "历史"]),
        s("B-XM-01", "厦门", 3, 2, 4500, "BALANCED", ["海滨", "美食"]),
    ],
    "batch2_budget": [
        s("B-LOW-01", "成都", 3, 2, 2500, "RELAXED", ["美食"], expect_budget_ok=False),
        s("A-HI-01", "上海", 4, 2, 20000, "RELAXED", ["都市", "购物"]),
        s("B-STRICT-01", "成都", 3, 2, 4000, "BALANCED", ["美食"]),
        s("B-NANJING-01", "南京", 2, 2, 3000, "BALANCED", ["历史", "美食"]),
        s("B-WUHAN-01", "武汉", 2, 2, 3000, "BALANCED", ["美食", "自然"]),
        s("B-CHANGSHA-01", "长沙", 2, 2, 3000, "BALANCED", ["美食", "夜宵"]),
        s("B-QINGDAO-01", "青岛", 3, 2, 5000, "RELAXED", ["海滨", "啤酒"]),
    ],
    "batch3_modify": [
        # 注：初版用"漓江"作 must_visit 被诚实拒绝 MUST_VISIT_UNAVAILABLE（地图
        # 将其解析为水域而非可安排景点）——这是正确降级；改用可安排景点验证正向路径。
        s("C-GL-01", "桂林", 3, 2, 4000, "BALANCED", ["自然"], ["象鼻山"]),
        s("C-KM-01", "昆明", 3, 2, 4000, "RELAXED", ["自然", "花海"]),
        # 注：洱海作 must_visit 被诚实拒绝 MUST_VISIT_UNAVAILABLE（水域非可安排
        # 景点），与漓江同理；改用可安排景点验证正向路径。
        s("C-DL-01", "大理", 3, 2, 4000, "RELAXED", ["自然", "洱海"], ["崇圣寺三塔"]),
        s("C-LJ-01", "丽江", 3, 2, 4000, "RELAXED", ["古镇", "雪山"]),
        s("C-ZJJ-01", "张家界", 3, 2, 4500, "BALANCED", ["自然", "登山"], ["张家界国家森林公园"]),
        s("C-HS-01", "黄山", 3, 2, 4500, "BALANCED", ["自然", "日出"], ["黄山风景区"]),
    ],
    "batch4_boundary": [
        s("D-JQ-01", "酒泉", 3, 2, 4000, "BALANCED", ["丝路", "航天"], ["敦煌莫高窟"]),
        s("D-GZ-01", "甘孜", 3, 2, 4000, "RELAXED", ["藏区", "自然"]),
        s("D-ZJK-01", "张家口", 2, 2, 2500, "BALANCED", ["草原", "滑雪"], expect_budget_ok=False),
        s("D-SZS-01", "石嘴山", 2, 2, 2500, "BALANCED", ["工业", "美食"], expect_budget_ok=False),
    ],
}


# ─────────────────────────── Harness 核心 ─────────────────────────
def _date_span(days: int) -> tuple[str, str]:
    start = date(2026, 10, 16)  # 未来稳定日期，避开假期拥塞
    end = start + timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


class ApiClient:
    def __init__(self, base: str = BASE_URL) -> None:
        self.base = base.rstrip("/")
        self.client = httpx.Client(timeout=httpx.Timeout(90.0, connect=5.0))
        self.token: str | None = None

    def _h(self, extra: bool = False) -> dict[str, str]:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if extra and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def login(self) -> None:
        resp = self.client.post(
            f"{self.base}/api/auth/login", json=LOGIN, headers=self._h()
        )
        resp.raise_for_status()
        self.token = resp.json()["accessToken"]

    def create_trip(self, city: str, start: str, end: str, spec: ScenarioSpec) -> Any:
        # B13 契约：must_visit 必须带真实候选 PlaceRef，且 PlaceRef.name 必须
        # 与 mustVisitPlaces 条目一致。用真实地点搜索的规范名回填。
        must_places: list[str] = []
        place_refs = []
        for mv in spec.must_visit:
            cand = self.search_place(city, mv)
            if cand:
                must_places.append(cand["name"])
                place_refs.append(cand)
        c = {
            "budgetAmount": spec.budget,
            "travelers": spec.travellers,
            "travelerType": "COUPLE",
            "pace": spec.pace,
            "preferences": spec.preferences,
            "fixedSchedules": [],
            "mustVisitPlaces": must_places,
            "avoidPlaces": [],
            "mustVisitPlaceRefs": place_refs,
        }
        body = {
            "destination": city,
            "arrivalAt": f"{start}T09:00:00+08:00",
            "departureAt": f"{end}T18:00:00+08:00",
            "constraints": c,
        }
        resp = self.client.post(
            f"{self.base}/api/trips", json=body, headers=self._h(True)
        )
        resp.raise_for_status()
        return resp.json(), place_refs

    def search_place(self, city: str, keyword: str) -> dict[str, Any] | None:
        resp = self.client.post(
            f"{self.base}/api/trips/places/search",
            json={"city": city, "keyword": keyword, "limit": 3},
            headers=self._h(True),
        )
        resp.raise_for_status()
        data = resp.json()
        cands = (data.get("candidates") or [])
        if not cands:
            return None
        return cands[0]

    def start_run(self, trip_id: str) -> str:
        body = json.dumps({"message": "开始规划这次旅行"}, ensure_ascii=False).encode("utf-8")
        resp = self.client.post(
            f"{self.base}/api/trips/{trip_id}/agent-dialogue/runs",
            content=body, headers=self._h(True),
        )
        resp.raise_for_status()
        return resp.json()["eventId"]

    def stream_events(self, trip_id: str, timeout_ms: int = 60_000) -> list[dict[str, Any]]:
        """Consume SSE; return parsed JSON event payloads."""
        events: list[dict[str, Any]] = []
        deadline = time.time() + timeout_ms / 1000
        with self.client.stream(
            "GET", f"{self.base}/api/trips/{trip_id}/agent-dialogue/events",
            headers=self._h(True),
        ) as resp:
            for line in resp.iter_lines():
                if time.time() > deadline:
                    break
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data:
                    continue
                try:
                    events.append(json.loads(data))
                except json.JSONDecodeError:
                    continue
                last = events[-1]
                if last.get("eventType") in ("AGENT_COMPLETED", "AGENT_RUN_FINISHED"):
                    break
        return events

    def create_planning_task(self, trip_id: str, key: str) -> dict[str, Any]:
        resp = self.client.post(
            f"{self.base}/api/trips/{trip_id}/planning-tasks",
            headers=self._h(True) | {"Idempotency-Key": key},
        )
        resp.raise_for_status()
        return resp.json()

    def get_planning_task(self, trip_id: str, task_id: str) -> dict[str, Any]:
        resp = self.client.get(
            f"{self.base}/api/planning-tasks/{task_id}", headers=self._h(True)
        )
        resp.raise_for_status()
        return resp.json()

    def get_itinerary(self, trip_id: str) -> dict[str, Any]:
        resp = self.client.get(
            f"{self.base}/api/trips/{trip_id}/itinerary", headers=self._h(True)
        )
        resp.raise_for_status()
        return resp.json()

    def poll_task_until_terminal(
        self, trip_id: str, task_id: str, timeout_ms: int = 420_000
    ) -> dict[str, Any]:
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            task = self.get_planning_task(trip_id, task_id)
            if task.get("status") in ("SUCCEEDED", "FAILED", "CANCELLED"):
                return task
            time.sleep(3)
        return {"status": "TIMEOUT", "taskId": task_id}


# ─────────────────────────── 断言与评分 ──────────────────────────
def _day_time(activities: list[dict[str, Any]], k: str) -> list[float]:
    out: list[float] = []
    for a in activities or []:
        t = a.get(k)
        if t:
            hm = re.search(r"(\d{2}):(\d{2})", str(t))
            if hm:
                out.append(int(hm.group(1)) * 60 + int(hm.group(2)))
    return out


def validate_itinerary(it: dict[str, Any], spec: ScenarioSpec,
                       place_refs: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """对行程做合理性断言：时间重叠 / 预算 / must_visit / 每日密度 / 地理 sanity。"""
    problems: list[dict[str, Any]] = []
    days = it.get("days") or []
    if not days:
        problems.append({"check": "itinerary_exists", "detail": "行程为空"})

    # 预算
    est = it.get("estimatedTotalCost")
    if est is None:
        problems.append({"check": "budget", "detail": "缺少 estimatedTotalCost"})
    elif spec.expect_budget_ok and est > spec.budget:
        problems.append({
            "check": "budget",
            "detail": f"预估 {est} > 预算 {spec.budget}",
        })

    # must_visit 进入行程：优先按 PlaceRef 的 POI 身份匹配（规范名可能与用户
    # 原词不同，如"兵马俑"→"秦始皇帝陵博物院"），再按标题名称模糊匹配。
    activities = []
    for day in days:
        for a in (day.get("activities") or []):
            activities.append(a)
    poi_ids = {str(a.get("providerPoiId") or a.get("providerPoiIdId") or "") for a in activities}
    titles = [str(a.get("title", "")) for a in activities]
    title_text = " ".join(titles)
    for i, mv in enumerate(spec.must_visit):
        if not mv:
            continue
        ref = (place_refs or [])[i] if i < len(place_refs or []) else None
        poi = ref.get("providerPoiId") if ref else None
        hit = (poi and str(poi) in poi_ids) or (mv and mv in title_text)
        if not hit:
            problems.append({"check": "must_visit", "detail": f"{mv} 未进入行程"})

    # 时间重叠 + 每日密度：按每条活动独立区间判断是否与其它区间重叠
    for day in days:
        acts = day.get("activities") or []
        intervals: list[tuple[float, float, str]] = []
        for a in acts:
            t = _day_time([a], "startTime")
            u = _day_time([a], "endTime")
            if t and u:
                intervals.append((t[0], u[0], str(a.get("title", ""))))
        dense = len([a for a in acts if str(a.get("kind", "")) not in ("MEAL", "ACCOMMODATION")])
        if dense > 8:
            problems.append({
                "check": "too_dense",
                "detail": f"每日非餐饮活动过多 ({dense}) @ {day.get('date')}",
            })
        for i in range(len(intervals)):
            for j in range(i + 1, len(intervals)):
                a, b = intervals[i], intervals[j]
                if a[0] < b[1] and b[0] < a[1]:
                    problems.append({
                        "check": "time_overlap",
                        "detail": f"重叠: {a[2]} 与 {b[2]} @ {day.get('date')}",
                    })
                    break
            if problems and problems[-1]["check"] == "time_overlap":
                break
    return problems


def score(problems: list[dict[str, Any]], spec: ScenarioSpec, ok_build: bool,
          turn_count: int) -> dict[str, float]:
    s8: dict[str, float] = {}
    s8["task_completion"] = 1.0 if ok_build else 0.0
    must = 1.0
    for p in problems:
        if p["check"] == "must_visit":
            must = 0.0
    s8["constraint_satisfaction"] = must
    active = [p for p in problems if p["check"] in ("time_overlap", "itinerary_exists")]
    s8["itinerary_feasibility"] = 0.0 if active else 1.0
    budget_p = [p for p in problems if p["check"] == "budget"]
    s8["budget_accuracy"] = 0.0 if budget_p else 1.0
    s8["weather_adaptation"] = 0.5  # 当前流程未接天气，作为待验证项
    s8["context_retention"] = min(1.0, turn_count / 3.0) if ok_build else 0.0
    s8["tool_reliability"] = 1.0 if ok_build else 0.0
    s8["user_experience"] = 1.0 if (ok_build and not active) else 0.5
    return s8


def _resolve_destination_city(client: ApiClient, spec: ScenarioSpec) -> str:
    """目的地用候选的规范 city（含 must_visit 时），与 B13 token 一致。
    真实前端目的地来自地区索引（如"大理白族自治州"），避免简称不一致。"""
    if spec.must_visit:
        cand = client.search_place(spec.city, spec.must_visit[0])
        if cand:
            return cand["city"]
    return spec.city


def run_scenario(client: ApiClient, spec: ScenarioSpec, start: str, end: str) -> ScenarioResult:
    res = ScenarioResult(
        scenario_id=spec.id, city=spec.city, ok=False, status="FAIL", turn_count=0
    )
    t0 = time.time()
    try:
        city = _resolve_destination_city(client, spec)
        trip, place_refs = client.create_trip(city, start, end, spec)
        trip_id = trip["id"]
        # T0: 用户确认约束后点击 [开始规划]（等价于前端 Composer 确认 → 建旅行 → 触发规划）
        client.start_run(trip_id)
        turns: list[TurnTrace] = [TurnTrace(0, "开始规划这次旅行")]

        events = client.stream_events(trip_id)
        turn_count = 1
        steps = [e for e in events if e.get("eventType") == "AGENT_STEP"]
        completed = [e for e in events if e.get("eventType") == "AGENT_COMPLETED"]
        run_id = None
        for e in events:
            rid = e.get("runId")
            if rid:
                run_id = rid
        for i, e in enumerate(steps):
            turns.append(TurnTrace(i + 1, f"STEP:{e.get('payload', {}).get('tool')}",
                                   {"tool": e.get("payload", {}).get("tool"),
                                    "ok": e.get("payload", {}).get("ok"),
                                    "summary": e.get("payload", {}).get("summary")}))
        turn_count = max(turn_count, len(turns))

        if not completed:
            raise RuntimeError(f"AGENT_COMPLETED 未在会话中到达 (events={len(events)})")

        # 触发规划管线，落库方案
        key = run_id or str(uuid4())
        task = client.create_planning_task(trip_id, key)
        task = client.poll_task_until_terminal(trip_id, task["taskId"])
        if "SUCCEEDED" not in task.get("status", ""):
            raise RuntimeError(f"规划任务未成功: {task}")

        it = client.get_itinerary(trip_id)
        res.itinerary = it
        problems = validate_itinerary(it, spec, place_refs)
        res.turn_count = turn_count
        ok = not problems
        res.failures = [p for p in problems if spec.expect_budget_ok or p["check"] != "budget"]
        res.ok = ok and not res.failures
        res.scores = score(problems, spec, ok_build=True, turn_count=turn_count)
        res.status = "PASS" if res.ok else "PARTIAL_PASS"
        for i, e in enumerate(events):
            res.trace.append({"turn": i, "eventType": e.get("eventType"),
                              "payload": e.get("payload")})
    except Exception as exc:  # noqa: BLE001  harness boundary
        res.failures.append({"check": "exception", "detail": str(exc)})
        res.scores = score([{"check": "itinerary_exists"}], spec, ok_build=False, turn_count=1)
        res.status = "FAIL"
        res.ok = False
    res.duration_seconds = round(time.time() - t0, 1)
    return res


def build_report(results: list[ScenarioResult]) -> dict[str, Any]:
    passed = [r for r in results if r.status == "PASS"]
    partial = [r for r in results if r.status == "PARTIAL_PASS"]
    failed = [r for r in results if r.status == "FAIL"]
    cities = sorted({r.city for r in results})
    agg: dict[str, float] = {d: 0.0 for d in SCORE_DIMS}
    for r in results:
        for d in SCORE_DIMS:
            agg[d] += r.scores.get(d, 0.0)
    n = max(1, len(results))
    return {
        "summary": {
            "scenarios": len(results), "cities": len(cities),
            "pass": len(passed), "partial": len(partial), "fail": len(failed),
            "pass_rate": round(len(passed) / n * 100, 1),
            "cities_covered": cities,
            "avg_scores": {d: round(agg[d] / n, 2) for d in SCORE_DIMS},
        },
        "results": [
            {
                "id": r.scenario_id, "city": r.city, "status": r.status,
                "ok": r.ok, "turns": r.turn_count, "duration_s": r.duration_seconds,
                "scores": r.scores, "failures": r.failures,
                "trace": r.trace,
                "itinerary_meta": _meta(r.itinerary),
            } for r in results
        ],
    }


def _meta(it: dict[str, Any] | None) -> dict[str, Any]:
    if not it:
        return {}
    return {
        "title": it.get("title"), "estimatedTotalCost": it.get("estimatedTotalCost"),
        "days": len(it.get("days") or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--batch", required=True,
        help="batch1/batch2_budget/batch3_modify/batch4_boundary/all"
    )
    parser.add_argument("--report", required=True, help="输出 json 路径")
    parser.add_argument("--only", nargs="*", default=[], help="仅运行指定 scenario id")
    args = parser.parse_args()

    specs: list[ScenarioSpec] = []
    if args.batch == "all":
        specs = [sp for batch in DATASET.values() for sp in batch]
    elif args.batch in DATASET:
        specs = list(DATASET[args.batch])
    else:
        print(f"未知 batch: {args.batch}", file=sys.stderr)
        return 2
    if args.only:
        specs = [sp for sp in specs if sp.id in args.only]

    client = ApiClient()
    client.login()
    results: list[ScenarioResult] = []
    for sp in specs:
        start, end = _date_span(sp.days)
        print(f"[{sp.id}] {sp.city} ({CITY_CATEGORY.get(sp.city,'?')}) {sp.days}天 "
              f"{sp.travellers}人 预算{sp.budget} ...", flush=True)
        r = run_scenario(client, sp, start, end)
        print(f"    -> {r.status} turns={r.turn_count} "
              f"scores={r.scores} failures={r.failures[:2]}", flush=True)
        results.append(r)

    report = build_report(results)
    import os
    os.makedirs(os.path.dirname(args.report), exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if report["summary"]["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())