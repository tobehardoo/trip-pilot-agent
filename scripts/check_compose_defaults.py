"""B12: regression-lock local-first compose defaults.

Guards the local-first configuration contract so compose files, .env.example
and the documented defaults cannot silently drift apart:

- compose.prod.yaml resolves PROVIDER_MODE to DEMO_ONLY by default;
- compose.prod.yaml passes OUTBOX_PUBLISHER_ENABLED and EVENT_CONSUMER_ENABLED
  through to travel-server (default true, matching application.yml);
- .env.example documents the same defaults;
- REAL_ONLY + missing AMap key still fails fast at WorkerSettings (covered by
  the Python test suite, see test_amqp_worker.py) and DEMO_ONLY with an empty
  key still builds DemoPlanningProvider (test_demo_worker_factory_*).

Run with `--with-docker` to additionally expand compose.prod.yaml through
`docker compose config --format json` using .env.example as the env file
(placeholder secrets satisfy the required-variable interpolation).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PROD = ROOT / "compose.prod.yaml"
ENV_EXAMPLE = ROOT / ".env.example"

SERVICE_LINE = re.compile(r"^  [A-Za-z0-9_-]+:$")


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    sys.exit(1)


def service_block(text: str, service: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line == f"  {service}:":
            for end in range(index + 1, len(lines)):
                if SERVICE_LINE.match(lines[end]):
                    return "\n".join(lines[index:end])
            return "\n".join(lines[index:])
    return ""


def check_static() -> None:
    compose = COMPOSE_PROD.read_text(encoding="utf-8")
    agent_service = service_block(compose, "agent-service")
    travel_server = service_block(compose, "travel-server")

    if "PROVIDER_MODE: ${PROVIDER_MODE:-DEMO_ONLY}" not in agent_service:
        fail("compose.prod.yaml agent-service must default PROVIDER_MODE to DEMO_ONLY")
    if "OUTBOX_PUBLISHER_ENABLED: ${OUTBOX_PUBLISHER_ENABLED:-true}" not in travel_server:
        fail("compose.prod.yaml must pass OUTBOX_PUBLISHER_ENABLED to travel-server")
    if "EVENT_CONSUMER_ENABLED: ${EVENT_CONSUMER_ENABLED:-true}" not in travel_server:
        fail("compose.prod.yaml must pass EVENT_CONSUMER_ENABLED to travel-server")

    env = ENV_EXAMPLE.read_text(encoding="utf-8")
    for pattern in (
        r"^PROVIDER_MODE=DEMO_ONLY$",
        r"^OUTBOX_PUBLISHER_ENABLED=true$",
        r"^EVENT_CONSUMER_ENABLED=true$",
    ):
        if not re.search(pattern, env, re.MULTILINE):
            fail(f".env.example must contain {pattern}")
    print("OK: static compose defaults match the local-first contract")


def check_docker_expansion() -> None:
    try:
        proc = subprocess.run(
            [
                "docker", "compose",
                "-f", str(COMPOSE_PROD),
                "--env-file", str(ENV_EXAMPLE),
                "config", "--format", "json",
            ],
            capture_output=True,
            cwd=ROOT,
            timeout=120,
        )
    except FileNotFoundError:
        print("SKIP: docker CLI not found; expansion checks skipped")
        return
    stdout = proc.stdout.decode("utf-8", errors="replace")
    stderr = proc.stderr.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        fail(f"docker compose config failed:\n{stderr[-2000:]}")
    try:
        config = json.loads(stdout)
    except json.JSONDecodeError as exc:
        fail(f"compose config JSON parse failed: {exc}")
    services = config.get("services", {})
    agent_env = services.get("agent-service", {}).get("environment", {})
    server_env = services.get("travel-server", {}).get("environment", {})
    if agent_env.get("PROVIDER_MODE") != "DEMO_ONLY":
        fail(f"expanded PROVIDER_MODE={agent_env.get('PROVIDER_MODE')!r}, expected 'DEMO_ONLY'")
    for key in ("OUTBOX_PUBLISHER_ENABLED", "EVENT_CONSUMER_ENABLED"):
        value = server_env.get(key)
        if str(value).lower() != "true":
            fail(f"expanded travel-server {key}={value!r}, expected 'true'")
    print("OK: docker compose expansion resolves DEMO_ONLY and messaging switches true")


def main() -> None:
    check_static()
    if "--with-docker" in sys.argv[1:]:
        check_docker_expansion()


if __name__ == "__main__":
    main()
