"""A7: 有限 soak — DEMO_ONLY 隔离栈连续 10 个规划任务（真实链路），验证 stuck=0/无重复版本/无积压。"""
import json, sys, time, uuid
sys.path.insert(0, "C:/Windows/Temp/opencode/qa-b14")
import b14lib as L
L.BASE = "http://127.0.0.1:38086"

rows = []
ok_all = True
for i in range(10):
    t0 = time.time()
    u = L.new_user()
    payload = {"title": f"soak-{i}", "destination": "广州", "startDate": "2026-09-10",
               "endDate": "2026-09-11", "arrivalAt": "2026-09-10T10:00:00+08:00",
               "departureAt": "2026-09-11T18:00:00+08:00",
               "constraints": {"budgetAmount": 3000, "travelers": 1, "travelerType": "SOLO",
                               "pace": "BALANCED", "preferences": [], "fixedSchedules": [],
                               "mealWindows": [], "mobilityLevel": "STANDARD"}}
    st, trip = L.http("POST", "/api/trips", payload, u["token"])
    tid = trip["id"]
    L.start_planning(u["token"], tid)
    term = L.poll_terminal(u["token"], tid, timeout_s=90)
    el = round(time.time() - t0, 1)
    if term is None:
        rows.append({"i": i, "ok": False, "detail": "no terminal (stuck?)"})
        ok_all = False
        continue
    status = term.get("status")
    ver = L.db(f"SELECT count(*) FROM business.itinerary_version WHERE planning_task_id IN "
               f"(SELECT id FROM business.planning_task WHERE trip_id='{tid}')")
    rows.append({"i": i, "ok": status in ("SUCCEEDED", "WAITING_USER", "FAILED"),
                 "detail": f"status={status} elapsed={el}s versions={ver}"})
    if status not in ("SUCCEEDED", "WAITING_USER", "FAILED"):
        ok_all = False
    time.sleep(2)

# queue backlog + duplicate-version checks
q = L.db("SELECT count(*) FROM business.planning_task WHERE status IN ('QUEUED','RUNNING')")
dup = L.db("SELECT count(*) FROM (SELECT planning_task_id FROM business.itinerary_version "
           "GROUP BY planning_task_id HAVING count(*)>1) x")
print(f"soak rows=10 all_ok={ok_all} active_tasks={q} duplicate_version_tasks={dup}")
for r in rows:
    print(("PASS " if r["ok"] else "FAIL "), r)
json.dump({"rows": rows, "active_tasks": q, "duplicate_version_tasks": dup},
          open("C:/Windows/Temp/opencode/qa-soak-results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
