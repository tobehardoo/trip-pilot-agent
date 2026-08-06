"""10-city full-chain integration test."""
import json, os, sys, time, urllib.request, urllib.error, uuid

BASE = os.environ.get("TRIPPILOT_BASE", "http://127.0.0.1:8081")

CITIES = [
    ("广州", ["历史文化", "美食"], ["陈家祠"]),
    ("北京", ["历史文化", "博物馆"], ["故宫"]),
    ("上海", ["购物", "美食"], ["外滩"]),
    ("深圳", ["自然", "户外"], []),
    ("杭州", ["自然", "历史文化"], ["西湖"]),
    ("成都", ["美食", "休闲"], []),
    ("西安", ["历史文化"], ["兵马俑"]),
    ("南京", ["历史文化", "自然"], []),
    ("重庆", ["美食", "自然"], []),
    ("武汉", ["历史文化"], ["黄鹤楼"]),
]

def api(method, path, body=None, token=None, extra_headers=None):
    headers = {"Content-Type": "application/json"}
    if token: headers["Authorization"] = f"Bearer {token}"
    if extra_headers: headers.update(extra_headers)
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read())
        except: return e.code, {"raw": e.read().decode()[:200]}

def log(msg):
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}")

def test_city(city, prefs, must_visit, token):
    t0 = time.time()
    # Create trip
    s, trip = api("POST", "/api/trips", {
        "destination": city, "startDate": "2026-08-10",
        "endDate": "2026-08-11", "title": f"{city} Test",
        "constraints": {"budgetAmount": 3000, "preferences": prefs,
            "mustVisitPlaces": must_visit, "fixedSchedules": [],
            "travelers": 1, "pace": "BALANCED", "travelerType": "SOLO"},
    }, token=token)
    if s not in (200, 201): return {"status": "FAIL", "error": f"trip={s}"}
    trip_id = trip["id"]

    # Create task
    s, task = api("POST", f"/api/trips/{trip_id}/planning-tasks",
                  token=token, extra_headers={"Idempotency-Key": str(uuid.uuid4())})
    if s not in (200, 201, 202): return {"status": "FAIL", "error": f"task={s}"}
    task_id = task["taskId"]

    # Poll
    for _ in range(60):
        time.sleep(2)
        s, ts = api("GET", f"/api/planning-tasks/{task_id}", token=token)
        st = ts.get("status", "?")
        if st in ("SUCCEEDED", "COMPLETED", "FAILED", "CANCELLED"):
            if st == "FAILED":
                return {"status": "FAIL", "error": ts.get("errorCode", "?"), "elapsed": time.time()-t0}
            if st in ("SUCCEEDED", "COMPLETED"):
                s2, itin = api("GET", f"/api/trips/{trip_id}/itinerary", token=token)
                days = itin.get("days", []) if s2 == 200 else []
                acts = sum(len(d.get("activities", [])) for d in days)
                trans = sum(len(d.get("transitLegs", [])) for d in days)
                ev = ts.get("evaluation", {})
                score = ev.get("overallScore") if ev else None
                act_sources = list(set(
                    a.get("source","?") for d in days for a in d.get("activities",[])
                ))
                return {
                    "status": "PASS", "elapsed": round(time.time()-t0, 1),
                    "score": score, "days": len(days), "activities": acts,
                    "transit": trans, "sources": act_sources,
                    "trip_id": trip_id, "task_id": task_id,
                }
            return {"status": st, "elapsed": time.time()-t0}
    return {"status": "TIMEOUT", "elapsed": time.time()-t0}


def main():
    print("=== TripPilot 10-City Integration Test ===\n")
    # Register
    uid = str(uuid.uuid4())[:8]
    s, reg = api("POST", "/api/auth/register", {
        "username": f"mc{uid}", "password": "MultiCity123!",
        "confirmPassword": "MultiCity123!", "displayName": "MC", "email": f"mc{uid}@test.local",
    })
    token = reg["accessToken"]
    log(f"Registered, token expires {reg['expiresIn']}s\n")

    results = []
    for city, prefs, must_visit in CITIES:
        log(f"Testing {city} (prefs={prefs}, must_visit={must_visit})...")
        r = test_city(city, prefs, must_visit, token)
        status_icon = "PASS" if r["status"] == "PASS" else "FAIL"
        print(f"  [{status_icon}] {city}: {r['status']} | score={r.get('score','?')} | "
              f"{r.get('days','?')}d/{r.get('activities','?')}a/{r.get('transit','?')}t | "
              f"sources={r.get('sources','?')} | {r.get('elapsed','?')}s")
        if r.get("error"):
            print(f"       error: {r['error']}")
        results.append((city, r))

    # Summary
    passed = sum(1 for _, r in results if r["status"] == "PASS")
    failed = sum(1 for _, r in results if r["status"] == "FAIL")
    scores = [r["score"] for _, r in results if r.get("score") is not None]
    avg_score = sum(scores)/len(scores) if scores else 0

    print(f"\n=== RESULTS ===")
    print(f"  Passed: {passed}/{len(CITIES)}")
    print(f"  Failed: {failed}/{len(CITIES)}")
    print(f"  Avg Score: {avg_score:.0f}")
    for city, r in results:
        icon = "[PASS]" if r["status"] == "PASS" else "[FAIL]"
        print(f"  {icon} {city}: {r['status']} score={r.get('score','?')} "
              f"elapsed={r.get('elapsed','?')}s")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
