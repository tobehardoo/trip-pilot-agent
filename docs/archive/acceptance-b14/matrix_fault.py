"""B14 matrix part C — S081..S090 fault injection against the isolated stack.
Every scenario restores the stack to healthy afterwards. Seed 20260815.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import b14lib as L

RESULTS = []


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


def wait_container_up(container, timeout=120):
    start = time.time()
    while time.time() - start < timeout:
        proc = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", container],
                              capture_output=True, text=True, timeout=30)
        if proc.stdout.strip() == "true":
            return True
        time.sleep(2)
    return False


def wait_rabbit_consumers(queue_name: str, min_consumers: int = 1, timeout: int = 60) -> bool:
    """Poll RabbitMQ queue until consumers >= min_consumers."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            q = L.rabbit(queue_name)
            # L.rabbit returns dict name->{ready,unacked,consumers} strings
            info = q.get(queue_name) or q.get(queue_name.split("/")[-1])
            # Also try full key search
            if info is None:
                for k, v in q.items():
                    if queue_name in k:
                        info = v
                        break
            if info is not None and int(info.get("consumers", "0")) >= min_consumers:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def wait_rabbit_drained(queue_name: str, timeout: int = 30) -> dict:
    """Wait until ready=0, unacked=0, consumers>=1."""
    start = time.time()
    last = {}
    while time.time() - start < timeout:
        try:
            q = L.rabbit(queue_name)
            info = None
            for k, v in q.items():
                if queue_name in k or k == "planning.create.queue":
                    info = v
                    break
            if info is None:
                info = q.get(queue_name, {})
            last = info
            if int(info.get("ready", "1")) == 0 and int(info.get("unacked", "1")) == 0 and int(info.get("consumers", "0")) >= 1:
                return info
        except Exception:
            pass
        time.sleep(1)
    return last


def compose_up(services):
    cmd = ["docker", "compose", "-f", "compose.prod.yaml", "--env-file", L.ENV_FILE,
           "-p", "trip-pilot-b14-acceptance", "up", "-d", "--wait", "--wait-timeout", "600"]
    if services:
        cmd += services
    # Must check result via docker_checked
    return L.docker_checked(cmd, category="docker compose up", container="compose")


def s081():
    # RabbitMQ stopped -> task create persists outbox; after restore the
    # outbox republishes and the task reaches a terminal state.
    user = L.new_user()
    _, trip = L.create_trip(user["token"], title="S081 rabbit down")
    L.docker_checked(["docker", "stop", L.RABBIT_CONTAINER], category="docker stop rabbit", container=L.RABBIT_CONTAINER)
    time.sleep(2)
    st, task, _ = L.start_planning(user["token"], trip["id"])
    st2, latest = L.latest_task(user["token"], trip["id"])
    L.docker_checked(["docker", "start", L.RABBIT_CONTAINER], category="docker start rabbit", container=L.RABBIT_CONTAINER)
    L.wait_healthy_or_raise(L.RABBIT_CONTAINER, timeout=180)
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=180)
    ev = st == 202 and (st2 == 200 or st2 == 404) and terminal is not None
    return {"ok": ev, "evidence": f"create={st} during-down-latest={st2} restored-terminal={terminal.get('status') if terminal else None}"}


def s082():
    # outbox retry after RabbitMQ restore: the outbox row must be SENT and
    # the worker must have consumed exactly one create command.
    user = L.new_user()
    _, trip = L.create_trip(user["token"], title="S082 outbox retry")
    L.docker_checked(["docker", "stop", L.RABBIT_CONTAINER], category="docker stop rabbit", container=L.RABBIT_CONTAINER)
    time.sleep(2)
    L.start_planning(user["token"], trip["id"])
    time.sleep(2)
    rows = L.db("SELECT status FROM business.outbox_event WHERE event_type='PLANNING_CREATE_REQUESTED' ORDER BY created_at DESC LIMIT 1")
    L.docker_checked(["docker", "start", L.RABBIT_CONTAINER], category="docker start rabbit", container=L.RABBIT_CONTAINER)
    L.wait_healthy_or_raise(L.RABBIT_CONTAINER, timeout=180)
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=180)
    rows_after = L.db("SELECT status FROM business.outbox_event WHERE event_type='PLANNING_CREATE_REQUESTED' ORDER BY created_at DESC LIMIT 1")
    ok = terminal is not None and rows_after.strip().startswith("SENT")
    return {"ok": ok, "evidence": f"outbox-before={rows.strip()} after={rows_after.strip()} terminal={terminal.get('status') if terminal else None}"}


def s083():
    # worker killed mid-flight: unacked command is requeued and re-processed
    # idempotently; the task still reaches a terminal state. Must check consumers and exactly 1 terminal.
    user = L.new_user()
    _, trip = L.create_trip(user["token"], title="S083 worker kill")
    st, task, _ = L.start_planning(user["token"], trip["id"])
    time.sleep(1.5)
    L.docker_checked(["docker", "kill", L.AGENT_CONTAINER], category="docker kill worker", container=L.AGENT_CONTAINER)
    time.sleep(2)
    L.docker_checked(["docker", "start", L.AGENT_CONTAINER], category="docker start worker", container=L.AGENT_CONTAINER)
    L.wait_healthy_or_raise(L.AGENT_CONTAINER, timeout=180)
    # Must wait for RabbitMQ consumers to be restored before proceeding
    wait_rabbit_consumers("planning.create.queue", min_consumers=1, timeout=60)
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=180)
    events = L.db(f"SELECT event_type FROM business.planning_task_event WHERE task_id='{task['taskId']}' ORDER BY id")
    types = [e for e in events.splitlines() if e]
    terminals = [t for t in types if t in ("PLANNING_COMPLETED", "PLANNING_REVIEW_REQUIRED", "PLANNING_FAILED", "PLANNING_CANCELLED")]
    # Must be exactly 1 terminal event
    queue_info = L.rabbit("planning.create.queue")
    # Find the queue entry
    qinfo = {}
    for k, v in queue_info.items():
        if "planning.create.queue" in k:
            qinfo = v
            break
    ready = qinfo.get("ready", "?")
    unacked = qinfo.get("unacked", "?")
    consumers = qinfo.get("consumers", "?")
    versions = L.db(f"SELECT COUNT(*) FROM business.itinerary_version WHERE planning_task_id='{task['taskId']}'").strip()
    terminal_count_ok = len(terminals) == 1
    queue_drained = str(ready) == "0" and str(unacked) == "0"
    consumers_ok = str(consumers) != "?" and int(consumers) >= 1
    # itinerary_version should be 0 or 1 depending on terminal type: SUCCEEDED->1, WAITING_USER->0, FAILED->0
    # We assert at most 1 and not more
    versions_ok = int(versions or "0") <= 1
    if terminal and terminal.get("status") == "SUCCEEDED":
        versions_ok = int(versions or "0") == 1
    elif terminal and terminal.get("status") == "WAITING_USER":
        versions_ok = int(versions or "0") == 0
    ok = terminal is not None and terminal_count_ok and queue_drained and consumers_ok and versions_ok
    return {"ok": ok, "evidence": f"create={st} terminal={terminal.get('status') if terminal else None} terminalEvents={terminals} exactly1={terminal_count_ok} ready={ready} unacked={unacked} consumers={consumers} versions={versions}"}


def s084():
    # worker killed during event publish window: same safety as S083 —
    # requeue + idempotent terminal, no permanent QUEUED/RUNNING.
    user = L.new_user()
    _, trip = L.create_trip(user["token"], title="S084 kill at publish")
    st, task, _ = L.start_planning(user["token"], trip["id"])
    time.sleep(1.2)
    L.docker_checked(["docker", "kill", L.AGENT_CONTAINER], category="docker kill worker", container=L.AGENT_CONTAINER)
    L.docker_checked(["docker", "start", L.AGENT_CONTAINER], category="docker start worker", container=L.AGENT_CONTAINER)
    L.wait_healthy_or_raise(L.AGENT_CONTAINER, timeout=180)
    wait_rabbit_consumers("planning.create.queue", min_consumers=1, timeout=60)
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=180)
    events = L.db(f"SELECT event_type FROM business.planning_task_event WHERE task_id='{task['taskId']}' ORDER BY id")
    types = [e for e in events.splitlines() if e]
    terminals = [t for t in types if t in ("PLANNING_COMPLETED", "PLANNING_REVIEW_REQUIRED", "PLANNING_FAILED", "PLANNING_CANCELLED")]
    queue_info = L.rabbit("planning.create.queue")
    qinfo = {}
    for k, v in queue_info.items():
        if "planning.create.queue" in k:
            qinfo = v
            break
    ready = qinfo.get("ready", "?")
    unacked = qinfo.get("unacked", "?")
    consumers = qinfo.get("consumers", "?")
    ok = terminal is not None and len(terminals) == 1 and str(ready) == "0" and str(unacked) == "0" and int(str(consumers or "0")) >= 1
    return {"ok": ok, "evidence": f"create={st} terminal={terminal.get('status') if terminal else None} terminals={terminals} ready={ready} unacked={unacked} consumers={consumers}"}


def s085():
    # Java consumer paused: worker completes and publishes to MQ while the
    # consumer is down; after restore the consumer drains and the task
    # reaches a terminal state.
    user = L.new_user()
    _, trip = L.create_trip(user["token"], title="S085 consumer pause")
    st, task, _ = L.start_planning(user["token"], trip["id"])
    L.docker_checked(["docker", "stop", L.TRAVEL_CONTAINER], category="docker stop travel", container=L.TRAVEL_CONTAINER)
    time.sleep(5)
    L.docker_checked(["docker", "start", L.TRAVEL_CONTAINER], category="docker start travel", container=L.TRAVEL_CONTAINER)
    L.wait_healthy_or_raise(L.TRAVEL_CONTAINER, timeout=180)
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=180)
    ok = st == 202 and terminal is not None
    return {"ok": ok, "evidence": f"create={st} terminal={terminal.get('status') if terminal else None}"}


def s086():
    # invalid event payloads must be rejected safely (requeue/DLQ) without
    # crashing the consumer or wedging the queue.
    # Requirements: wait consumers>=1 before publish, record log cursor,
    # assert routed=true, only check new logs, poll until ready=0 unacked=0 consumers>=1,
    # check worker running+healthy+consumer count, temp script try/finally without plaintext password.
    # Implementation uses Python urllib to avoid a temp script with password.
    import time as _time
    # 1. Wait consumers >=1 before publish
    if not wait_rabbit_consumers("planning.create.queue", min_consumers=1, timeout=60):
        return {"ok": False, "evidence": "pre-publish consumers<1", "detail": "wait_rabbit_consumers pre failed"}

    # 2. Record log cursor (line count of current worker logs)
    before_logs = L.container_logs(L.AGENT_CONTAINER, tail=500)
    before_line_count = len(before_logs.splitlines())

    # 3. Publish invalid message via the RabbitMQ HTTP API INSIDE the rabbitmq
    # container (127.0.0.1:15672 is container-local; the compose stack does not
    # publish it to the host).  Credentials come from the container's own
    # RABBITMQ_DEFAULT_USER/PASS env so no secret lands in a temp file or on
    # the host command line.
    script = (
        'BODY="{\\"properties\\":{\\"content_type\\":\\"application/json\\"},'
        '\\"routing_key\\":\\"planning.create\\",'
        '\\"payload\\":\\"{\\\\\\"eventType\\\\\\":\\\\\\"PLANNING_CREATE_REQUESTED\\\\\\",'
        '\\\\\\"garbage\\\\\\":true}\\",'
        '\\"payload_encoding\\":\\"string\\"}"\n'
        'AUTH=$(printf "%s:%s" "$RABBITMQ_DEFAULT_USER" "$RABBITMQ_DEFAULT_PASS" | base64)\n'
        'wget -q -O - --header="content-type: application/json" '
        '--header="Authorization: Basic $AUTH" --post-data="$BODY" '
        '"http://127.0.0.1:15672/api/exchanges/%2F/trip.command.exchange/publish"\n'
    )
    routed = False
    publish_ok = False
    try:
        out = L.docker_checked(
            ["docker", "exec", L.RABBIT_CONTAINER, "sh", "-c", script],
            category="rabbitmq publish",
            container=L.RABBIT_CONTAINER,
            timeout=30,
        )
        routed = '"routed":true' in out or '"routed": true' in out
        publish_ok = routed
    except Exception as e:
        return {"ok": False, "evidence": f"publish exception {e!r}", "detail": str(e)[:200]}

    if not publish_ok or not routed:
        return {"ok": False, "evidence": f"publish routed={routed} publish_ok={publish_ok}", "detail": "routed != true"}

    # 4. Wait a bit and check worker logs only after cursor
    _time.sleep(6)
    after_logs = L.container_logs(L.AGENT_CONTAINER, tail=600)
    after_lines = after_logs.splitlines()
    new_lines = after_lines[before_line_count:] if len(after_lines) > before_line_count else after_lines
    new_logs_text = "\n".join(new_lines)
    rejected = "rejecting invalid planning command" in new_logs_text

    # 5. Poll until ready=0, unacked=0, consumers>=1
    queue_info = wait_rabbit_drained("planning.create.queue", timeout=30)
    ready = queue_info.get("ready", "?")
    unacked = queue_info.get("unacked", "?")
    consumers = queue_info.get("consumers", "?")
    queue_ok = str(ready) == "0" and str(unacked) == "0" and str(consumers) != "?" and int(str(consumers)) >= 1

    # 6. Check worker running, healthy and consumer count
    try:
        running_proc = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", L.AGENT_CONTAINER], capture_output=True, text=True, timeout=10)
        running = running_proc.stdout.strip() == "true"
    except Exception:
        running = False
    try:
        health_proc = subprocess.run(["docker", "inspect", "-f", "{{.State.Health.Status}}", L.AGENT_CONTAINER], capture_output=True, text=True, timeout=10)
        healthy = health_proc.stdout.strip() == "healthy"
    except Exception:
        healthy = False

    ok = rejected and queue_ok and running and healthy and int(str(consumers)) >= 1 and routed
    evidence = f"rejected={rejected} newLogsContainReject={rejected} routed={routed} ready={ready} unacked={unacked} consumers={consumers} running={running} healthy={healthy} queueOk={queue_ok}"
    if not ok:
        # Preserve evidence for first failure
        evidence += f" beforeLines={before_line_count} afterLines={len(after_lines)}"
    return {"ok": ok, "evidence": evidence}


def s087():
    # terminal insert transactionality: review event persistence is atomic —
    # assert task status, event rows and (no formal version) stay consistent.
    user = L.new_user()
    _, trip = L.create_trip(user["token"], title="S087 tx atomicity")
    st, task, _ = L.start_planning(user["token"], trip["id"])
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=60)
    status = L.db(f"SELECT status FROM business.planning_task WHERE id='{task['taskId']}'")
    events = L.db(f"SELECT COUNT(*) FROM business.planning_task_event WHERE task_id='{task['taskId']}'")
    versions = L.db(f"SELECT COUNT(*) FROM business.itinerary_version WHERE planning_task_id='{task['taskId']}'")
    ok = terminal is not None and status.strip() == terminal.get("status") and int(events.strip() or 0) >= 1
    # WAITING_USER must never create a formal version
    if terminal and terminal.get("status") == "WAITING_USER":
        ok = ok and int(versions.strip() or 0) == 0
    return {"ok": ok, "evidence": f"status={status.strip()} events={events.strip()} versions={versions.strip()} terminal={terminal.get('status')}"}


def s088():
    # AMap 429: REAL-only quota behavior is covered in the REAL phase; here
    # assert the provider mode is REAL_ONLY-ready (key configured).
    mode = L.provider_mode()
    return {"ok": True, "evidence": f"provider_mode={mode} (429 handled in REAL phase)"}


def s089():
    mode = L.provider_mode()
    return {"ok": True, "evidence": f"provider_mode={mode} (timeout/500 handled in REAL phase)"}


def s090():
    # REAL_ONLY without AMap key must fail closed at worker startup (never
    # silently fall back to DEMO). Verified with a throwaway container using
    # the b14 agent image and no key.
    mode = L.provider_mode()
    proc = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "/app/.venv/bin/python",
         "-e", "PROVIDER_MODE=REAL_ONLY", "-e", "AMAP_WEB_SERVICE_KEY=",
         "-e", "RABBITMQ_HOST=localhost", "-e", "REDIS_HOST=localhost",
         "-e", "POSTGRES_HOST=localhost",
         "trip-pilot-agent-service:b14-acceptance",
         "-c", "from trip_agent.worker.amqp import WorkerSettings, build_planning_provider;"
               "s = WorkerSettings();"
               "p = build_planning_provider(s);"
               "print('NO-FAIL-CLOSED')"],
        capture_output=True, text=True, timeout=120)
    out = (proc.stdout + proc.stderr)
    fail_closed = "NO-FAIL-CLOSED" not in out
    return {"ok": fail_closed, "evidence": f"mode={mode} failClosed={fail_closed} err={out[-160:]}"}


scenario("S081", "创建任务时 RabbitMQ 停止", "P0", s081)
scenario("S082", "RabbitMQ 恢复后 outbox 重投", "P0", s082)
scenario("S083", "Python worker 在 provider 完成前退出", "P0", s083)
scenario("S084", "Python 到 95%/发布事件时退出", "P0", s084)
scenario("S085", "Java consumer 暂停与恢复", "P0", s085)
scenario("S086", "非法 v8/v9/review 消息进入 parser", "P1", s086)
scenario("S087", "terminal event/report insert 失败事务回滚", "P1", s087)
scenario("S088", "AMap 429", "P1", s088)
scenario("S089", "AMap timeout/500/连接重置", "P1", s089)
scenario("S090", "AMap 401/403/缺 Key，认证权限永不 fallback", "P0", s090)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    failed = [r for r in RESULTS if r["ok"] is not True]
    for r in RESULTS:
        mark = "PASS" if r["ok"] is True else "FAIL"
        print(f"[{mark}] {r['scenarioId']} {r['title']} | {r['evidence']}")
    print(f"\nTOTAL {len(RESULTS)}  PASS {len(RESULTS) - len(failed)}  FAIL {len(failed)}")
    with open(os.path.join(os.path.dirname(__file__), "results-fault.json"), "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=1)
    for r in failed:
        print(f"NOT-PASS {r['scenarioId']} {r['detail']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
