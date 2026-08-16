"""B14 acceptance library — API/DB/MQ reconciliation helpers for the 100-scenario
matrix against the isolated trip-pilot-b14-acceptance stack. Temp tooling under
scripts/acceptance/b14/ (allowed by the B14 charter); no production code touched.
"""
from __future__ import annotations

import json
import random
import subprocess
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://127.0.0.1:38085"
ENV_FILE = r"C:\Windows\Temp\opencode\b14-acceptance.env"
POSTGRES_CONTAINER = "trip-pilot-b14-acceptance-postgres-1"
WEB_CONTAINER = "trip-pilot-b14-acceptance-web-1"
AGENT_CONTAINER = "trip-pilot-b14-acceptance-agent-service-1"
TRAVEL_CONTAINER = "trip-pilot-b14-acceptance-travel-server-1"
RABBIT_CONTAINER = "trip-pilot-b14-acceptance-rabbitmq-1"

SEED = 20260815
RNG = random.Random(SEED)


def _env_value(key: str) -> str:
    for line in open(ENV_FILE, encoding="utf-8"):
        line = line.strip()
        if line.startswith(key + "="):
            return line.split("=", 1)[1]
    raise KeyError(key)


def http(method: str, path: str, body=None, token=None, headers=None, timeout=30):
    url = BASE + path
    data = None if body is None else json.dumps(body).encode("utf-8")
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read()
            return res.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            parsed = json.loads(raw) if raw else None
        except ValueError:
            parsed = {"raw": raw.decode("utf-8", "replace")[:300]}
        return err.code, parsed
    except urllib.error.URLError as err:
        return -1, {"error": str(err.reason)}


def register(email=None, password="b14-pass-123456", display="B14 User"):
    email = email or f"b14-{uuid.uuid4().hex[:12]}@example.com"
    status, body = http("POST", "/api/auth/register", {"email": email, "password": password, "displayName": display})
    return status, body, email, password


def login(email, password="b14-pass-123456"):
    status, body = http("POST", "/api/auth/login", {"email": email, "password": password})
    return status, (body or {}).get("accessToken")


def new_user():
    status, body, email, password = register()
    _, token = login(email, password)
    return {"email": email, "password": password, "token": token, "regStatus": status}


def create_trip(token, **overrides):
    trip = {
        "title": "B14 行程",
        "destination": "广州",
        "startDate": "2026-09-10",
        "endDate": "2026-09-11",
        "arrivalAt": "2026-09-10T10:00:00+08:00",
        "departureAt": "2026-09-11T18:00:00+08:00",
        "constraints": {
            "budgetAmount": 3000,
            "travelers": 2,
            "travelerType": "FRIENDS",
            "pace": "BALANCED",
            "preferences": [],
            "fixedSchedules": [],
            "arrival": None,
            "departure": None,
            "accommodation": None,
            "mustVisitPlaces": [],
            "avoidPlaces": [],
            "mustVisitPlaceRefs": [],
            "avoidPlaceRefs": [],
            "mealWindows": [],
            "mobilityLevel": "STANDARD",
        },
    }
    def deep_merge(base, extra):
        for k, v in extra.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                deep_merge(base[k], v)
            else:
                base[k] = v
    deep_merge(trip, overrides)
    status, body = http("POST", "/api/trips", trip, token)
    return status, body


def start_planning(token, trip_id, idempotency=None):
    idempotency = idempotency or str(uuid.uuid4())
    status, body = http(
        "POST", f"/api/trips/{trip_id}/planning-tasks", None, token,
        headers={"Idempotency-Key": idempotency}, timeout=60,
    )
    return status, body, idempotency


def latest_task(token, trip_id):
    return http("GET", f"/api/trips/{trip_id}/planning-tasks/latest", None, token)


def poll_terminal(token, trip_id, timeout_s=120):
    start = time.time()
    while time.time() - start < timeout_s:
        status, body = latest_task(token, trip_id)
        if status == 200 and body and body.get("status") in {"SUCCEEDED", "WAITING_USER", "FAILED", "CANCELLED"}:
            return body
        time.sleep(1)
    return None


def cancel_task(token, task_id):
    return http("DELETE", f"/api/planning-tasks/{task_id}", None, token)


def place_search(token, city="广州", keyword="天河公园", limit=5):
    return http("POST", "/api/trips/places/search", {"city": city, "keyword": keyword, "limit": limit}, token)


def db(sql):
    user = _env_value("POSTGRES_USER")
    pw = _env_value("POSTGRES_PASSWORD")
    dbname = _env_value("POSTGRES_DB")
    cmd = ["docker", "exec", "-e", f"PGPASSWORD={pw}", POSTGRES_CONTAINER,
           "psql", "-U", user, "-d", dbname, "-t", "-A", "-c", sql]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return proc.stdout.strip()


def rabbit(qname):
    cmd = ["docker", "exec", RABBIT_CONTAINER, "rabbitmqctl", "list_queues",
           "name", "messages_ready", "messages_unacknowledged", "consumers"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    rows = [line.split("\t") for line in proc.stdout.strip().splitlines() if "\t" in line]
    return {r[0]: {"ready": r[1], "unacked": r[2], "consumers": r[3]} for r in rows}


def rabbit_bindings():
    cmd = ["docker", "exec", RABBIT_CONTAINER, "rabbitmqctl", "list_bindings", "source_name",
           "destination_name", "routing_key"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return proc.stdout.strip()


def container_logs(name, tail=200):
    proc = subprocess.run(["docker", "logs", "--tail", str(tail), name],
                          capture_output=True, text=True, timeout=60)
    return proc.stdout + proc.stderr


def provider_mode():
    proc = subprocess.run(["docker", "exec", AGENT_CONTAINER, "printenv", "PROVIDER_MODE"],
                          capture_output=True, text=True, timeout=30)
    return proc.stdout.strip()
