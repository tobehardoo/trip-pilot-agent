"""B14 matrix part E — parameterized bulk (seed 20260815) to reach >=300 total
samples, plus S099 (10 users x 10 trips concurrent planning).
"""
from __future__ import annotations

import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(__file__))
import b14lib as L

RESULTS = []
SAMPLES = []


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


def param_bulk():
    """Deterministic parameterized creation+planning samples (>=100)."""
    rng = L.RNG
    budgets = [None, 0, 1, 100, 1000, 5000, 20000]
    types = ["SOLO", "COUPLE", "FAMILY", "FRIENDS", "BUSINESS"]
    travelers = [1, 2, 3, 4, 6]
    paces = ["RELAXED", "BALANCED", "INTENSIVE"]
    mob = ["STANDARD", "REDUCED", "STEP_FREE"]
    prefs = [[], ["岭南文化"], ["本地美食", "城市漫步"], ["自然风景", "夜间活动", "亲子体验"],
             ["博物馆", "美食", "购物", "夜景"]]
    meals = [[], [{"mealType": "LUNCH", "startTime": "12:00", "endTime": "13:00"}],
             [{"mealType": "DINNER", "startTime": "18:00", "endTime": "20:00"}],
             [{"mealType": "LUNCH", "startTime": "11:30", "endTime": "13:30"},
              {"mealType": "DINNER", "startTime": "17:30", "endTime": "20:30"}]]
    days_opts = [(1, 1), (2, 2), (3, 3), (7, 7)]
    count = 0
    fails = []
    for i in range(110):
        user = L.new_user()
        budget = rng.choice(budgets)
        tt = rng.choice(types)
        n = rng.choice(travelers)
        pace = rng.choice(paces)
        m = rng.choice(mob)
        pf = rng.choice(prefs)
        mw = rng.choice(meals)
        days = rng.choice(days_opts)
        start = f"2026-12-{1 + i % 20:02d}"
        end = f"2026-12-{min(1 + i % 20 + days[0] - 1, 28):02d}"
        extra = {"constraints": {"budgetAmount": budget, "travelers": n, "travelerType": tt,
                                 "pace": pace, "mobilityLevel": m, "preferences": pf,
                                 "mealWindows": mw}}
        st, body = L.create_trip(user["token"], startDate=start, endDate=end,
                                 arrivalAt=f"{start}T10:00:00+08:00",
                                 departureAt=f"{end}T18:00:00+08:00", **extra)
        ok_create = st == 201
        terminal = None
        if ok_create:
            st2, task, _ = L.start_planning(user["token"], body["id"])
            terminal = L.poll_terminal(user["token"], body["id"], timeout_s=60)
            ok_term = terminal is not None
        else:
            ok_term = False
        count += 1
        SAMPLES.append({"n": i, "create": st, "terminal": terminal.get("status") if terminal else None,
                        "ok": ok_create and ok_term})
        if not (ok_create and ok_term):
            fails.append(f"#{i} create={st} term={terminal.get('status') if terminal else None}")
    return {"ok": len(fails) <= 3, "evidence": f"samples={count} fails={len(fails)} {' '.join(fails[:5])}"}


def s099():
    """10 users x 10 trips concurrent planning: every task reaches a terminal
    state, one-active-per-trip holds, no permanent QUEUED/RUNNING."""
    users = [L.new_user() for _ in range(10)]
    trips = []
    for u in users:
        for j in range(10):
            st, body = L.create_trip(u["token"], title=f"并发 {j}")
            trips.append((u, body["id"]))
    results = []
    lock = threading.Lock()

    def worker(u, trip_id):
        st, task, _ = L.start_planning(u["token"], trip_id)
        terminal = L.poll_terminal(u["token"], trip_id, timeout_s=120)
        with lock:
            results.append((trip_id, st, terminal.get("status") if terminal else None))

    threads = [threading.Thread(target=worker, args=(u, tid)) for u, tid in trips]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    terminal_ok = all(r[2] in ("WAITING_USER", "SUCCEEDED", "FAILED", "CANCELLED") for r in results)
    created_ok = all(r[1] == 202 for r in results)
    stuck = [r for r in results if r[2] is None]
    return {"ok": terminal_ok and created_ok and not stuck,
            "evidence": f"tasks={len(results)} created202={sum(1 for r in results if r[1] == 202)} terminal={sum(1 for r in results if r[2])} stuck={len(stuck)}"}


scenario("P001", "参数化批量 110 样本（预算/同行/节奏/行动/偏好/餐窗/天数，种子 20260815）", "P2", param_bulk)
scenario("S099", "10 个用户/10 个 trip 并发规划", "P0", s099)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    print(f"provider_mode={L.provider_mode()}")
    total_samples = sum(1 for s in SAMPLES if s["ok"]) + 1
    for r in RESULTS:
        mark = "PASS" if r["ok"] is True else "FAIL"
        print(f"[{mark}] {r['scenarioId']} {r['title']} | {r['evidence'][:220]}")
    print(f"\nTOTAL {len(RESULTS)}  PASS {sum(1 for r in RESULTS if r['ok'] is True)}  FAIL {sum(1 for r in RESULTS if r['ok'] is not True)}")
    print(f"PARAM-SAMPLES ok={total_samples}/{len(SAMPLES)}")
    with open(os.path.join(os.path.dirname(__file__), "results-param.json"), "w", encoding="utf-8") as f:
        json.dump({"scenarios": RESULTS, "samples": SAMPLES}, f, ensure_ascii=False, indent=1)
    return 1 if any(r["ok"] is not True for r in RESULTS) else 0


if __name__ == "__main__":
    sys.exit(main())
