"""B8-5: run the four golden scenarios as real HTTP trips against the stack.

Verifies day-type semantics of the daily-skeleton path end-to-end.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
import uuid

BASE = os.environ.get("TRIPPILOT_BASE", "http://127.0.0.1:8081")

SCENARIOS = [
    {
        "name": "1-广州下午到达/离开",
        "trip": {
            "destination": "广州", "startDate": "2026-08-10", "endDate": "2026-08-12",
            "title": "广州三日",
            "constraints": {
                "budgetAmount": 3000, "preferences": ["历史文化", "美食"],
                "mustVisitPlaces": ["陈家祠"], "fixedSchedules": [],
                "travelers": 1, "pace": "BALANCED", "travelerType": "SOLO",
                "arrival": {"placeName": "广州站", "time": "2026-08-10T14:00:00+08:00"},
                "departure": {"placeName": "广州南站", "time": "2026-08-12T16:00:00+08:00"},
            },
        },
        "expect_day_types": ["ARRIVAL_DAY", "FULL_DAY", "DEPARTURE_DAY"],
    },
    {
        "name": "2-泰安含泰山",
        "trip": {
            "destination": "泰安", "startDate": "2026-08-10", "endDate": "2026-08-12",
            "title": "泰安三日",
            "constraints": {
                "budgetAmount": 3000, "preferences": ["自然", "历史文化"],
                "mustVisitPlaces": ["泰山"], "fixedSchedules": [],
                "travelers": 1, "pace": "BALANCED", "travelerType": "SOLO",
            },
        },
        "expect_experience": "泰山",
    },
    {
        "name": "3-上海含迪士尼",
        "trip": {
            "destination": "上海", "startDate": "2026-08-10", "endDate": "2026-08-11",
            "title": "上海两日",
            "constraints": {
                "budgetAmount": 3000, "preferences": ["娱乐"],
                "mustVisitPlaces": ["上海迪士尼乐园"], "fixedSchedules": [],
                "travelers": 1, "pace": "BALANCED", "travelerType": "SOLO",
            },
        },
        "expect_experience": "迪士尼",
    },
    {
        "name": "4-老人轻游无锚点",
        "trip": {
            "destination": "广州", "startDate": "2026-08-10", "endDate": "2026-08-11",
            "title": "老人轻游",
            "constraints": {
                "budgetAmount": 3000, "preferences": [],
                "mustVisitPlaces": [], "fixedSchedules": [],
                "travelers": 3, "pace": "RELAXED", "travelerType": "FAMILY",
            },
        },
        "expect_no_fake_hotel": True,
    },
]


def api(method, path, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"raw": e.read().decode()[:200]}


def plan_trip(token, trip):
    s, created = api("POST", "/api/trips", trip, token=token)
    if s not in (200, 201):
        return {"status": "TRIP_FAIL", "http": s}
    trip_id = created["id"]
    req = urllib.request.Request(
        f"{BASE}/api/trips/{trip_id}/planning-tasks", data=b"", method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}",
                 "Idempotency-Key": str(uuid.uuid4())},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            task = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"status": "TASK_FAIL", "http": e.code}
    task_id = task["taskId"]
    for _ in range(90):
        time.sleep(2)
        s, ts = api("GET", f"/api/planning-tasks/{task_id}", token=token)
        st = ts.get("status", "?")
        if st in ("SUCCEEDED", "COMPLETED", "FAILED", "CANCELLED"):
            if st in ("SUCCEEDED", "COMPLETED"):
                s2, itin = api("GET", f"/api/trips/{trip_id}/itinerary", token=token)
                return {"status": "OK", "itinerary": itin, "score": (ts.get("evaluation") or {}).get("overallScore")}
            return {"status": st, "errorCode": ts.get("errorCode"), "message": ts.get("safeMessage")}
    return {"status": "TIMEOUT"}


def main():
    uid = str(uuid.uuid4())[:8]
    s, reg = api("POST", "/api/auth/register", {
        "username": f"gs{uid}", "password": "Golden123!", "confirmPassword": "Golden123!",
        "displayName": "GS", "email": f"gs{uid}@test.local",
    })
    token = reg["accessToken"]
    ok = True
    for sc in SCENARIOS:
        res = plan_trip(token, sc["trip"])
        checks = []
        if res["status"] != "OK":
            checks.append(f"STATUS={res['status']}")
            ok = False
        else:
            days = res["itinerary"].get("days", [])
            types = [d.get("dayType") for d in days]
            if "expect_day_types" in sc:
                checks.append(f"types={types} expect={sc['expect_day_types']} -> {'OK' if types == sc['expect_day_types'] else 'MISMATCH'}")
                if types != sc["expect_day_types"]:
                    ok = False
            if "expect_experience" in sc:
                exp = [a.get("title") for d in days for a in d.get("activities", []) if a.get("kind") == "EXPERIENCE"]
                match = any(sc["expect_experience"] in (t or "") for t in exp)
                checks.append(f"experience={exp} expect~{sc['expect_experience']} -> {'OK' if match else 'MISSING'}")
                if not match:
                    ok = False
            if sc.get("expect_no_fake_hotel"):
                hotels = [a.get("kind") for d in days for a in d.get("activities", []) if a.get("kind") == "ACCOMMODATION"]
                checks.append(f"accommodation_nodes={hotels} -> {'OK' if not hotels else 'FAKE_HOTEL'}")
                if hotels:
                    ok = False
        print(f"[{'PASS' if checks and all('MISMATCH' not in c and 'MISSING' not in c and 'FAKE_HOTEL' not in c for c in checks) else 'FAIL'}] {sc['name']}: {checks} score={res.get('score')}")
    print("GOLDEN_OVERALL=", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
