"""Single-city smoke test — full distributed chain verification."""
import json, sys, time, urllib.request, urllib.error, uuid

BASE = "http://127.0.0.1:8081"


def api(method, path, body=None, token=None, extra_headers=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra_headers:
        headers.update(extra_headers)
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        try:
            return e.code, json.loads(body_text)
        except json.JSONDecodeError:
            return e.code, {"raw": body_text[:200]}


def log(msg):
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}")


def main():
    print("=== TripPilot Smoke Test (Guangzhou) ===\n")
    uid = str(uuid.uuid4())[:8]

    # 1. Register
    uname = f"smoke{uid}"
    email = f"{uname}@test.local"
    log(f"Registering {uname}...")
    s, body = api("POST", "/api/auth/register", {
        "username": uname, "password": "Test123456!",
        "confirmPassword": "Test123456!", "displayName": "Smoke", "email": email,
    })
    assert s in (200, 201), f"Register failed: {s} {body}"
    token = body["accessToken"]
    log("OK - registered")

    # 2. Health
    s, hc = api("GET", "/api/health")
    log(f"Health: {hc['status']}")

    # 3. Create trip
    log("Creating trip...")
    s, trip = api("POST", "/api/trips", {
        "destination": "广州", "startDate": "2026-08-10",
        "endDate": "2026-08-11", "title": "Smoke Test",
        "constraints": {
            "budgetAmount": 2000, "preferences": ["历史文化"],
            "mustVisitPlaces": [], "fixedSchedules": [],
            "travelers": 1, "pace": "BALANCED", "travelerType": "SOLO",
        },
    }, token=token)
    assert s in (200, 201), f"Create trip failed: {s} {body}"
    trip_id = trip["id"]
    log(f"Trip: {trip_id}")

    # 4. Create planning task
    log("Creating planning task...")
    idempotency_key = str(uuid.uuid4())
    s, task = api("POST", f"/api/trips/{trip_id}/planning-tasks",
                  token=token, extra_headers={"Idempotency-Key": idempotency_key})
    assert s in (200, 201, 202), f"Create task failed: {s} {task}"
    task_id = task["taskId"]
    log(f"Task: {task_id} status={task['status']}")

    # 5. Poll until completion
    log("Polling for completion...")
    deadline = time.time() + 120
    status = None
    while time.time() < deadline:
        s, ts = api("GET", f"/api/planning-tasks/{task_id}", token=token)
        status = ts.get("status")
        if status in ("COMPLETED", "SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(2)

    log(f"Final status: {status}")
    assert status in ("COMPLETED", "SUCCEEDED"), f"Task failed: {status}"

    # 6. Verify itinerary
    s, itin = api("GET", f"/api/trips/{trip_id}/itinerary", token=token)
    assert s == 200, f"Itinerary failed: {s}"
    days = itin.get("days", [])
    acts = sum(len(d.get("activities", [])) for d in days)
    trans = sum(len(d.get("transitLegs", [])) for d in days)
    log(f"Itinerary: {len(days)}d {acts}a {trans}t")

    for i, d in enumerate(days):
        names = [a["title"] for a in d.get("activities", [])]
        modes = [t.get("mode") for t in d.get("transitLegs", [])]
        log(f"  Day{i+1}: {names} | {modes}")

    # 7. Evaluation
    s, tf = api("GET", f"/api/planning-tasks/{task_id}", token=token)
    ev = tf.get("evaluation")
    if ev:
        log(f"Score: {ev['overallScore']} dims={ev['dimensions']}")

    print(f"\n=== RESULT: PASS ===")
    print(f"Trip: {trip_id}  Task: {task_id}  Score: {ev.get('overallScore') if ev else 'N/A'}")
    return 0 if status in ("COMPLETED", "SUCCEEDED") else 1


if __name__ == "__main__":
    sys.exit(main())
