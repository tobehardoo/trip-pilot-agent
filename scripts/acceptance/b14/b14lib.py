"""B14 acceptance library — API/DB/MQ reconciliation helpers for the 100-scenario
matrix against the isolated trip-pilot-b14-acceptance stack. Temp tooling under
scripts/acceptance/b14/ (allowed by the B14 charter); no production code touched.
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import time
import urllib.error
import urllib.request
import uuid

# Functional matrices talk to the isolated travel-server directly (host port
# 38086) so nginx auth rate-limiting (10r/m + burst 5, intentional product
# config on the web image) cannot turn into spurious 503s.  Set B14_BASE_URL
# to http://127.0.0.1:38085 to exercise the full web/nginx path explicitly.
BASE = os.environ.get("B14_BASE_URL", "http://127.0.0.1:38086")
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


def _redacted_error(category: str, container: str | None, detail: str) -> str:
    """Build a redacted error without echoing command arguments or secrets."""
    container_part = f", container={container}" if container else ""
    # Never include raw cmd or env values; only category and container.
    return f"{category} failed{container_part}: {detail[:300] or 'no stderr'}"


def docker_checked(cmd: list[str], *, category: str = "docker", container: str | None = None, timeout: int = 120) -> str:
    """Run a docker command, raising a redacted RuntimeError on non-zero or timeout.

    - Non-zero exit -> RuntimeError with category, container, exit code and stderr snippet (no password/token).
    - TimeoutExpired -> RuntimeError with category, container and timeout (no command args leaked).
    """
    inferred_container = container
    if inferred_container is None and len(cmd) >= 3 and cmd[0] == "docker":
        # Try to infer container from common patterns: docker ... <container> ...
        for token in cmd:
            if token.startswith("trip-pilot-"):
                inferred_container = token
                break
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{category} timed out (container={inferred_container or 'unknown'}, timeout={timeout}s)"
        ) from exc
    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "").strip()
        # Q2 redaction: never echo the raw cmd (may contain secrets) and scrub
        # secret-looking VALUES out of the stderr snippet itself, so a provider
        # message such as "password mySecret123" cannot leak through the error.
        raise RuntimeError(
            f"{category} failed (container={inferred_container or container or 'unknown'}, "
            f"exit={proc.returncode}): {_redact_secrets(stderr)[:300] or 'no stderr'}"
        )
    return (proc.stdout or "") + (proc.stderr or "")


_SECRET_VALUE_PATTERN = (
    r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|authorization|"
    r"refresh[_-]?cookie|amap[_-]?key)\b\s*[=: ]\s*[^\s,;]+"
)


def _redact_secrets(text: str) -> str:
    """Replace secret VALUES with a placeholder; keeps the label.

    Example: ``password mySecret123`` -> ``password <redacted>`` so the error
    message stays debuggable without leaking the value.
    """
    import re

    return re.sub(_SECRET_VALUE_PATTERN, r"\1 <redacted>", text)





def wait_healthy_or_raise(container: str, timeout: int = 180) -> None:
    """Poll a container's health status until healthy, raising on timeout."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            proc = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Health.Status}}", container],
                capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"health check timed out (container={container}, timeout=30s)"
            ) from exc
        if proc.returncode == 0 and proc.stdout.strip() == "healthy":
            return
        time.sleep(3)
    raise RuntimeError(f"Container {container} not healthy after {timeout}s")


def docker(cmd):
    """Run a docker command against the isolated stack and return output."""
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return proc.stdout + proc.stderr


def wait_healthy(container, timeout=180):
    """Poll a container's health status until healthy."""
    start = time.time()
    while time.time() - start < timeout:
        proc = subprocess.run(["docker", "inspect", "-f", "{{.State.Health.Status}}", container],
                              capture_output=True, text=True, timeout=30)
        if proc.stdout.strip() == "healthy":
            return True
        time.sleep(3)
    return False


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
    """Run a psql query inside the isolated PostgreSQL container.

    Credentials come from the container's own POSTGRES_USER/POSTGRES_DB
    environment (psql -U "$POSTGRES_USER" inside the container) — never
    guessed from the host env file, never echoed as plaintext.  A non-zero
    psql exit raises a redacted RuntimeError instead of silently returning
    an empty string, so harness bugs cannot masquerade as "no rows".
    """
    cmd = ["docker", "exec", POSTGRES_CONTAINER, "sh", "-c",
           'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -A -v ON_ERROR_STOP=1 -c "$1"',
           "b14-db", sql]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise RuntimeError(
            "psql failed "
            f"(exit={proc.returncode}, container={POSTGRES_CONTAINER}): "
            f"{stderr[:300] or 'no stderr'}"
        )
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
