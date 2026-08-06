"""B8-2: reproduce the round-1 广州 PROVIDER_TIMEOUT failure with identical input.

Runs the exact multi_city_test 广州 scenario 3 times in one process and prints
the terminal status, error code, and planning-task evaluation for each run.
"""

import json, os, sys, time, urllib.request, urllib.error, uuid

BASE = os.environ.get("TRIPPILOT_BASE", "http://127.0.0.1:8081")


def api(method, path, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        f"{BASE}{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"raw": e.read().decode()[:200]}


def run_scenario(token, run_no):
    trip = {
        "destination": "广州",
        "startDate": "2026-08-10",
        "endDate": "2026-08-11",
        "title": "广州 Test",
        "constraints": {
            "budgetAmount": 3000,
            "preferences": ["历史文化", "美食"],
            "mustVisitPlaces": ["陈家祠"],
            "fixedSchedules": [],
            "travelers": 1,
            "pace": "BALANCED",
            "travelerType": "SOLO",
        },
    }
    s, created = api("POST", "/api/trips", trip, token=token)
    if s not in (200, 201):
        return {"run": run_no, "status": "TRIP_FAIL", "http": s}
    trip_id = created["id"]
    import urllib.request as _ur
    req = _ur.Request(
        f"{BASE}/api/trips/{trip_id}/planning-tasks",
        data=b"",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    try:
        with _ur.urlopen(req, timeout=30) as r:
            s, task = r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            s, task = e.code, json.loads(e.read())
        except Exception:
            s, task = e.code, {"raw": e.read().decode()[:200]}
    if s not in (200, 201, 202):
        return {"run": run_no, "status": "TASK_FAIL", "http": s}
    task_id = task["taskId"]
    start = time.time()
    for _ in range(60):
        time.sleep(2)
        s, ts = api("GET", f"/api/planning-tasks/{task_id}", token=token)
        st = ts.get("status", "?")
        if st in ("SUCCEEDED", "COMPLETED", "FAILED", "CANCELLED"):
            ev = ts.get("evaluation") or {}
            return {
                "run": run_no,
                "status": st,
                "elapsed": round(time.time() - start, 1),
                "errorCode": ts.get("errorCode"),
                "errorCategory": ts.get("errorCategory"),
                "safeMessage": ts.get("safeMessage"),
                "score": ev.get("overallScore"),
                "trip_id": trip_id,
                "task_id": task_id,
            }
    return {"run": run_no, "status": "TIMEOUT", "elapsed": round(time.time() - start, 1)}


def main():
    uid = str(uuid.uuid4())[:8]
    s, reg = api("POST", "/api/auth/register", {
        "username": f"gz{uid}",
        "password": "GzRepro123!",
        "confirmPassword": "GzRepro123!",
        "displayName": "GZ",
        "email": f"gz{uid}@test.local",
    })
    token = reg["accessToken"]
    results = [run_scenario(token, i) for i in range(1, 4)]
    print("=== 广州 reproduction (3 identical runs) ===")
    for r in results:
        print(json.dumps(r, ensure_ascii=False))
    print("summary:", [r["status"] for r in results])
    return 0 if all(r["status"] in ("SUCCEEDED", "COMPLETED") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
