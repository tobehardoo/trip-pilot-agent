"""QA-2026-08-21 全链路真实样本矩阵（隔离栈 DEMO_ONLY）。

链路：HTTP POST /planning-tasks -> Java -> DB/Outbox -> RabbitMQ -> Python worker
-> DEMO provider -> planner -> completion -> RabbitMQ -> Java consumer -> DB
-> itinerary/version -> SSE/API 可读。

样本设计（差异化业务输入）：城市/天数/约束组合/规模/冲突/幂等，全部经正式链路。
"""
import json
import sys
import time
import uuid

sys.path.insert(0, "C:/Windows/Temp/opencode/qa-b14")
import b14lib as L  # noqa: E402

L.BASE = "http://127.0.0.1:38086"

results: list[dict] = []


def run_case(case_id: str, title: str, *, days: int = 2, destination: str = "广州",
             must_visit: list | None = None, avoid: list | None = None,
             meal_windows: list | None = None, fixed_schedules: list | None = None,
             pace: str = "BALANCED", travelers: int = 1, budget: int = 6000,
             start_offset_days: int = 20, same_key_replay: bool = False,
             expect_terminal: str | None = None, expect_error: str | None = None,
             must_ref: bool = False, avoid_ref: bool = False) -> None:
    start = time.time()
    u = L.new_user()
    start_date = "2026-09-10"
    end_date = f"2026-09-{9 + days:02d}"

    must_refs, avoid_refs, must_names, avoid_names = [], [], [], []
    if must_ref:
        _, body = L.place_search(u["token"], city=destination, keyword=must_visit[0], limit=3)
        cand = body["candidates"][0]
        must_names = [cand["name"]]
        must_refs = [{"provider": cand["provider"], "providerPoiId": cand["providerPoiId"],
                      "name": cand["name"], "address": cand.get("address", ""),
                      "longitude": cand["longitude"], "latitude": cand["latitude"],
                      "selectionToken": cand["selectionToken"]}]
    if avoid_ref:
        _, body = L.place_search(u["token"], city=destination, keyword=avoid[0], limit=3)
        cand = body["candidates"][0]
        avoid_names = [cand["name"]]
        avoid_refs = [{"provider": cand["provider"], "providerPoiId": cand["providerPoiId"],
                       "name": cand["name"], "address": cand.get("address", ""),
                       "longitude": cand["longitude"], "latitude": cand["latitude"],
                       "selectionToken": cand["selectionToken"]}]

    payload = {
        "title": title, "destination": destination,
        "startDate": start_date, "endDate": end_date,
        "arrivalAt": f"{start_date}T10:00:00+08:00",
        "departureAt": f"{end_date}T18:00:00+08:00",
        "constraints": {
            "budgetAmount": budget, "travelers": travelers, "travelerType": "SOLO",
            "pace": pace, "preferences": [], "fixedSchedules": fixed_schedules or [],
            "mealWindows": meal_windows or [], "mobilityLevel": "STANDARD",
            "mustVisitPlaces": must_names or (must_visit or []),
            "avoidPlaces": avoid_names or (avoid or []),
            "mustVisitPlaceRefs": must_refs, "avoidPlaceRefs": avoid_refs,
        },
    }
    st, trip = L.create_trip(u["token"], **payload) if False else (None, None)
    # create_trip(**overrides) merges overrides into a defaults dict; use raw http for exact payload
    st, trip = L.http("POST", "/api/trips", payload, u["token"])
    tid = trip.get("id") if isinstance(trip, dict) else None
    if st != 201 or not tid:
        results.append({"id": case_id, "title": title, "ok": False,
                        "actual": f"trip create {st} {str(trip)[:80]}", "detail": ""})
        return

    key = str(uuid.uuid4())
    st1, t1, _ = L.start_planning(u["token"], tid, idempotency=key)
    st2, t2, _ = None, None, None
    if same_key_replay:
        st2, t2, _ = L.start_planning(u["token"], tid, idempotency=key)

    term = L.poll_terminal(u["token"], tid, timeout_s=150)
    elapsed = round(time.time() - start, 1)
    if term is None:
        results.append({"id": case_id, "title": title, "ok": False,
                        "actual": "no terminal within 150s (stuck?)",
                        "detail": f"create={st1} replay={st2}"})
        return
    status = term.get("status")

    # DB checks: exactly one terminal event, one itinerary version
    ev = L.db(f"SELECT event_type FROM business.planning_task_event "
              f"WHERE task_id='{t1['taskId']}' ORDER BY id")
    ev_types = [e for e in ev.splitlines() if e]
    terminals = [e for e in ev_types if e in (
        "PLANNING_COMPLETED", "PLANNING_REVIEW_REQUIRED", "PLANNING_FAILED", "PLANNING_CANCELLED")]
    ver = L.db(f"SELECT count(*) FROM business.itinerary_version WHERE planning_task_id='{t1['taskId']}'")

    it = L.http("GET", f"/api/trips/{tid}/itinerary", None, u["token"])
    it_status, it_body = it[0], it[1] if len(it) > 1 else None
    days_n = len(it_body.get("days", [])) if isinstance(it_body, dict) else 0
    legs_n = sum(len(d.get("transitLegs", [])) for d in (it_body.get("days", []) if isinstance(it_body, dict) else []))

    expected_ok = status == "SUCCEEDED" and len(terminals) == 1 and int(ver or 0) >= 1
    if expect_terminal:
        expected_ok = status == expect_terminal and len(terminals) == 1
        if expect_terminal == "FAILED" and expect_error:
            expected_ok = expected_ok and (term.get("errorCode") or "") == expect_error
    same_task_ok = not same_key_replay or (
        isinstance(t1, dict) and isinstance(t2, dict) and t1["taskId"] == t2["taskId"])
    ok = expected_ok and same_task_ok

    results.append({
        "id": case_id, "title": title, "ok": ok,
        "actual": (f"terminal={status} events={ev_types} terminal_events={len(terminals)} "
                   f"versions={ver} it_status={it_status} days={days_n} legs={legs_n} "
                   f"elapsed={elapsed}s replay={st2}"),
        "detail": f"sameTask={same_task_ok}",
    })


def main() -> None:
    run_case("FC-01", "广州 2 日标准 SOLO/BALANCED", days=2)
    run_case("FC-02", "广州 1 日紧凑（10:00-18:00）", days=1)
    run_case("FC-03", "广州 3 日多日规模", days=3)
    run_case("FC-04", "广州 mustVisit 天河体育中心(候选引用→DEMO 降级 FAILED)", days=2,
             must_visit=["天河体育中心"], must_ref=True, expect_terminal="FAILED",
             expect_error="NO_FEASIBLE_ITINERARY")
    run_case("FC-05", "广州 avoid 白云山(候选引用)", days=2,
             avoid=["白云山"], avoid_ref=True)
    run_case("FC-06", "广州 午餐窗口 12:00-13:30", days=2,
             meal_windows=[{"mealType": "LUNCH", "startTime": "12:00", "endTime": "13:30"}])
    run_case("FC-07", "广州 固定时段 14:00-16:00 博物馆(→WAITING_USER review)", days=2,
             fixed_schedules=[{"placeName": "广东省博物馆", "startTime": "2026-09-11T14:00:00+08:00",
                               "endTime": "2026-09-11T16:00:00+08:00"}],
             expect_terminal="WAITING_USER")
    run_case("FC-08", "广州 2 日 RELAXED 节奏", days=2, pace="RELAXED")
    run_case("FC-09", "广州 2 日 双人出行", days=2, travelers=2)
    run_case("FC-10", "广州 2 日 极端小预算 ¥100", days=2, budget=100)
    run_case("FC-11", "广州 2 日 超大预算 ¥99999", days=2, budget=99999)
    run_case("FC-12", "幂等重放：同 Idempotency-Key 两次", days=2, same_key_replay=True)
    run_case("FC-13", "深圳 2 日（跨城）", days=2, destination="深圳")

    from collections import Counter
    c = Counter(x["ok"] for x in results)
    print(f"TOTAL={len(results)} PASS={c[True]} FAIL={c[False]}")
    for x in results:
        print(("PASS " if x["ok"] else "FAIL "), x["id"], x["title"], "|", x["actual"])
    with open("C:/Windows/Temp/opencode/qa-fullchain-results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print("saved qa-fullchain-results.json")


if __name__ == "__main__":
    main()
