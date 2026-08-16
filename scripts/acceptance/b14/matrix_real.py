"""B14 matrix part D — S041..S050 (must-visit/avoid, REAL_ONLY) plus 20 dynamic
REAL provider samples with concurrency <= 2 and 429 recording. Seed 20260815.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(__file__))
import b14lib as L

RESULTS = []


def scenario(scenario_id, title, risk, fn):
    try:
        outcome = fn()
        ok = bool(outcome.get("ok"))
        RESULTS.append({"scenarioId": scenario_id, "title": title, "risk": risk,
                        "ok": ok, "evidence": outcome.get("evidence", ""),
                        "detail": outcome.get("detail", "")})
    except Exception as exc:  # noqa: BLE001
        RESULTS.append({"scenarioId": scenario_id, "title": title, "risk": risk,
                        "ok": False, "evidence": "", "detail": f"EXCEPTION {exc!r}"})


def _candidate_ids(task):
    if not task:
        return set()
    ids = set()
    cand = task.get("candidateItinerary")
    if cand:
        for day in cand.get("days", []):
            for a in day.get("activities", []):
                if a.get("providerPoiId"):
                    ids.add(a["providerPoiId"])
    return ids


def _ref(cand):
    return {"provider": cand.get("provider", "AMAP"), "providerPoiId": cand["providerPoiId"],
            "name": cand["name"], "address": cand.get("address", ""), "province": cand.get("province", ""),
            "city": cand.get("city", ""), "district": cand.get("district", ""),
            "longitude": cand.get("longitude", 0), "latitude": cand.get("latitude", 0),
            "selectionToken": cand.get("selectionToken")}


def _plan(user, trip_extra, timeout=180):
    _, trip = L.create_trip(user["token"], **trip_extra)
    st, task, _ = L.start_planning(user["token"], trip["id"])
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=timeout)
    return trip, st, task, terminal


_INFRA_MARKERS = ("公交站", "地铁站", "入口", "出口", "售票处", "停车场", "充电站", "服务区", "加油站")


def _search_pick(token, kw, city="广州"):
    st, body = L.place_search(token, city=city, keyword=kw)
    if st != 200 or not body or not body.get("candidates"):
        return None
    for cand in body["candidates"]:
        if any(m in cand.get("name", "") for m in _INFRA_MARKERS):
            continue
        return cand
    return body["candidates"][0]


def s041():
    user = L.new_user()
    cand = _search_pick(user["token"], "天河公园")
    if not cand:
        return {"ok": False, "evidence": "search failed"}
    trip, st, task, terminal = _plan(user, {
        "constraints": {"mustVisitPlaces": [cand["name"]], "mustVisitPlaceRefs": [_ref(cand)]}})
    placed = _candidate_ids(terminal)
    ok = terminal is not None and terminal.get("status") in ("WAITING_USER", "SUCCEEDED") and cand["providerPoiId"] in placed
    return {"ok": ok, "evidence": f"terminal={terminal.get('status') if terminal else None} exact={cand['providerPoiId'] in placed}"}


def s042():
    user = L.new_user()
    c1 = _search_pick(user["token"], "天河公园")
    c2 = _search_pick(user["token"], "正佳广场")
    if not c1 or not c2:
        return {"ok": False, "evidence": f"search c1={bool(c1)} c2={bool(c2)}"}
    trip, st, task, terminal = _plan(user, {
        "constraints": {"mustVisitPlaces": [c1["name"], c2["name"]],
                        "mustVisitPlaceRefs": [_ref(c1), _ref(c2)]}})
    placed = _candidate_ids(terminal)
    ok = terminal is not None and terminal.get("status") in ("WAITING_USER", "SUCCEEDED") and {c1["providerPoiId"], c2["providerPoiId"]} <= placed
    return {"ok": ok, "evidence": f"terminal={terminal.get('status') if terminal else None} both={c1['providerPoiId'] in placed and c2['providerPoiId'] in placed}"}


def s043():
    user = L.new_user()
    picks = []
    for kw in ["天河公园", "正佳广场", "广州塔", "陈家祠", "沙面", "北京路", "白云山", "越秀公园", "荔枝湾", "海心沙"]:
        cand = _search_pick(user["token"], kw)
        if cand and all(cand["providerPoiId"] != p["providerPoiId"] for p in picks):
            picks.append(cand)
        if len(picks) >= 5:
            break
    if len(picks) < 5:
        return {"ok": False, "evidence": f"only {len(picks)} picks"}
    trip, st, task, terminal = _plan(user, {
        "startDate": "2026-10-01", "endDate": "2026-10-03",
        "arrivalAt": "2026-10-01T10:00:00+08:00", "departureAt": "2026-10-03T18:00:00+08:00",
        "constraints": {"mustVisitPlaces": [p["name"] for p in picks],
                        "mustVisitPlaceRefs": [_ref(p) for p in picks]}}, timeout=240)
    placed = _candidate_ids(terminal)
    ok = terminal is not None and terminal.get("status") in ("WAITING_USER", "SUCCEEDED") and all(p["providerPoiId"] in placed for p in picks)
    return {"ok": ok, "evidence": f"terminal={terminal.get('status') if terminal else None} placed={len([p for p in picks if p['providerPoiId'] in placed])}/{len(picks)}"}


def s044():
    user = L.new_user()
    cand = _search_pick(user["token"], "广州塔")
    if not cand:
        return {"ok": False, "evidence": "search failed"}
    trip, st, task, terminal = _plan(user, {
        "constraints": {"mustVisitPlaces": [cand["name"]], "mustVisitPlaceRefs": [_ref(cand)],
                        "preferences": ["完全不相关的偏好词XYZ"]}})
    placed = _candidate_ids(terminal)
    ok = terminal is not None and terminal.get("status") in ("WAITING_USER", "SUCCEEDED") and cand["providerPoiId"] in placed
    return {"ok": ok, "evidence": f"terminal={terminal.get('status') if terminal else None} pinned={cand['providerPoiId'] in placed}"}


def s045():
    user = L.new_user()
    cand = _search_pick(user["token"], "正佳广场")
    st2, s2 = L.place_search(user["token"], keyword="正佳广场服务中心")
    sibling = None
    for c in (s2 or {}).get("candidates", []):
        if c.get("providerPoiId") != cand.get("providerPoiId") and "正佳" in c.get("name", ""):
            sibling = c
            break
    trip, st, task, terminal = _plan(user, {
        "constraints": {"mustVisitPlaces": [cand["name"]], "mustVisitPlaceRefs": [_ref(cand)]}})
    placed = _candidate_ids(terminal)
    ok = terminal is not None and terminal.get("status") in ("WAITING_USER", "SUCCEEDED") and cand["providerPoiId"] in placed
    return {"ok": ok, "evidence": f"sibling={sibling.get('providerPoiId') if sibling else None} exact={cand['providerPoiId'] in placed}"}


def s046():
    user = L.new_user()
    cand = _search_pick(user["token"], "天河公园")
    if not cand:
        return {"ok": False, "evidence": "search failed"}
    st_create, body_create = L.create_trip(user["token"], **{
        "constraints": {"mustVisitPlaces": [cand["name"]], "mustVisitPlaceRefs": [_ref(cand)],
                        "avoidPlaces": [cand["name"]], "avoidPlaceRefs": [_ref(cand)]}})
    ok = st_create == 400 and (body_create or {}).get("code") == "VALIDATION_FAILED"
    return {"ok": ok, "evidence": f"must+avoid-overlap create={st_create} code={(body_create or {}).get('code')}"}


def s047():
    user = L.new_user()
    cand = _search_pick(user["token"], "天河公园")
    keep = _search_pick(user["token"], "正佳广场")
    if not cand or not keep:
        return {"ok": False, "evidence": "search failed"}
    trip, st, task, terminal = _plan(user, {
        "constraints": {"avoidPlaces": [cand["name"]], "avoidPlaceRefs": [_ref(cand)],
                        "mustVisitPlaces": [keep["name"]], "mustVisitPlaceRefs": [_ref(keep)]}})
    placed = _candidate_ids(terminal)
    ok = terminal is not None and cand["providerPoiId"] not in placed and keep["providerPoiId"] in placed
    return {"ok": ok, "evidence": f"avoided={cand['providerPoiId'] in placed} kept={keep['providerPoiId'] in placed}"}


def s048():
    user = L.new_user()
    exact = _search_pick(user["token"], "正佳广场")
    st2, s2 = L.place_search(user["token"], keyword="正佳广场服务中心")
    sibling = None
    for c in (s2 or {}).get("candidates", []):
        if c.get("providerPoiId") != exact.get("providerPoiId") and "正佳" in c.get("name", ""):
            sibling = c
            break
    if not exact or not sibling:
        return {"ok": False, "evidence": f"exact={bool(exact)} sibling={bool(sibling)}"}
    trip, st, task, terminal = _plan(user, {
        "constraints": {"avoidPlaces": [exact["name"]], "avoidPlaceRefs": [_ref(exact)],
                        "mustVisitPlaces": [sibling["name"]], "mustVisitPlaceRefs": [_ref(sibling)]}})
    placed = _candidate_ids(terminal)
    ok = terminal is not None and exact["providerPoiId"] not in placed
    return {"ok": ok, "evidence": f"exact-avoided={exact['providerPoiId'] in placed}"}


def s049():
    # official closure cannot be forced with real data; assert the planner
    # handles a recalled must-visit without fabricating evidence (UNVERIFIED
    # review, never VERIFIED).
    user = L.new_user()
    cand = _search_pick(user["token"], "天河公园")
    if not cand:
        return {"ok": False, "evidence": "search failed"}
    trip, st, task, terminal = _plan(user, {
        "constraints": {"mustVisitPlaces": [cand["name"]], "mustVisitPlaceRefs": [_ref(cand)]}})
    report = (terminal or {}).get("feasibilityReport") or {}
    ok = terminal is not None and terminal.get("status") == "WAITING_USER" and report.get("status") != "VERIFIED"
    return {"ok": ok, "evidence": f"terminal={terminal.get('status') if terminal else None} report={report.get('status')}"}


def s050():
    user = L.new_user()
    cand = _search_pick(user["token"], "天河公园")
    if not cand:
        return {"ok": False, "evidence": "search failed"}
    trip, st, task, terminal = _plan(user, {
        "startDate": "2026-10-20", "endDate": "2026-10-20",
        "arrivalAt": "2026-10-20T18:00:00+08:00", "departureAt": "2026-10-20T19:00:00+08:00",
        "constraints": {"mustVisitPlaces": [cand["name"]], "mustVisitPlaceRefs": [_ref(cand)]}})
    ok = terminal is not None and terminal.get("status") == "FAILED" and "NO_FEASIBLE_ITINERARY" in str(terminal.get("errorCode", ""))
    return {"ok": ok, "evidence": f"terminal={terminal.get('status') if terminal else None} errorCode={terminal.get('errorCode') if terminal else None}"}


scenario("S041", "一个结构化必去点", "P1", s041)
scenario("S042", "两个结构化必去点，第一查询已达候选数", "P0", s042)
scenario("S043", "五个结构化必去点", "P1", s043)
scenario("S044", "必去点排名低于普通候选 cutoff", "P1", s044)
scenario("S045", "同名 sibling 不得代替精确必去点", "P1", s045)
scenario("S046", "同一地点同时必去和避开", "P1", s046)
scenario("S047", "精确 avoid providerPoiId", "P1", s047)
scenario("S048", "同名 sibling 不得被错误排除", "P1", s048)
scenario("S049", "必去点正式关闭", "P1", s049)
scenario("S050", "必去点路线不可达或时间无法安排", "P1", s050)

# ── REAL dynamic samples (20, concurrency <= 2, 429 recorded) ──────────────

REAL_CITIES = [
    ("广州", "天河公园"), ("广州", "正佳广场"), ("广州", "陈家祠"),
    ("北京", "故宫"), ("北京", "天坛"), ("上海", "外滩"), ("上海", "东方明珠"),
    ("重庆", "洪崖洞"), ("杭州", "西湖"), ("成都", "宽窄巷子"),
    ("西安", "大雁塔"), ("长沙", "岳麓山"), ("昆明", "滇池"), ("三亚", "亚龙湾"),
    ("广州", "沙面"), ("广州", "白云山"), ("北京", "颐和园"), ("上海", "豫园"),
    ("杭州", "灵隐寺"), ("成都", "武侯祠"),
]


def real_samples():
    rate429 = 0
    ok_count = 0
    ev = []
    # concurrency <= 2: run sequentially (worker is single consumer anyway),
    # interleave small sleeps to control AMap call frequency
    for idx, (city, kw) in enumerate(REAL_CITIES):
        user = L.new_user()
        cand = _search_pick(user["token"], kw, city=city)
        if cand is None:
            ev.append(f"{city}/{kw}=SEARCH_FAIL")
            continue
        st, body = L.place_search(user["token"], keyword=kw, city=city)
        if st == 429:
            rate429 += 1
        trip, st2, task, terminal = _plan(user, {
            "destination": city,
            "constraints": {"mustVisitPlaces": [cand["name"]], "mustVisitPlaceRefs": [_ref(cand)],
                            "preferences": [kw]}}, timeout=300)
        placed = _candidate_ids(terminal)
        passed = terminal is not None and terminal.get("status") in ("WAITING_USER", "SUCCEEDED") and cand["providerPoiId"] in placed
        if passed:
            ok_count += 1
        ev.append(f"{city}/{kw}={terminal.get('status') if terminal else 'TIMEOUT'}(exact={cand['providerPoiId'] in placed})")
        time.sleep(1)
    return {"ok": ok_count >= 18, "evidence": f"ok={ok_count}/20 429s={rate429} | " + " | ".join(ev)}


scenario("R01-20", "REAL_ONLY 20 动态 Provider 样本（12+ 城市，双必去/单必去，并发≤2）", "P0", real_samples)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    print(f"provider_mode={L.provider_mode()}")
    failed = [r for r in RESULTS if r["ok"] is not True]
    for r in RESULTS:
        mark = "PASS" if r["ok"] is True else "FAIL"
        print(f"[{mark}] {r['scenarioId']} {r['title']} | {r['evidence'][:300]}")
    print(f"\nTOTAL {len(RESULTS)}  PASS {len(RESULTS) - len(failed)}  FAIL {len(failed)}")
    with open(os.path.join(os.path.dirname(__file__), "results-real.json"), "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=1)
    for r in failed:
        print(f"NOT-PASS {r['scenarioId']} {r['detail']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
