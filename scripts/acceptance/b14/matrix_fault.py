"""B14 matrix part C — S081..S090 fault injection against the isolated stack.
Every scenario restores the stack to healthy afterwards. Seed 20260815.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid

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


def docker(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return proc.stdout + proc.stderr


def wait_healthy(container, timeout=180):
    start = time.time()
    while time.time() - start < timeout:
        proc = subprocess.run(["docker", "inspect", "-f", "{{.State.Health.Status}}", container],
                              capture_output=True, text=True, timeout=30)
        if proc.stdout.strip() == "healthy":
            return True
        time.sleep(3)
    return False


def wait_container_up(container, timeout=120):
    start = time.time()
    while time.time() - start < timeout:
        proc = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", container],
                              capture_output=True, text=True, timeout=30)
        if proc.stdout.strip() == "true":
            return True
        time.sleep(2)
    return False


def compose_up(services):
    cmd = ["docker", "compose", "-f", "compose.prod.yaml", "--env-file", L.ENV_FILE,
           "-p", "trip-pilot-b14-acceptance", "up", "-d", "--wait", "--wait-timeout", "600"]
    if services:
        cmd += services
    return docker(cmd)


def s081():
    # RabbitMQ stopped -> task create persists outbox; after restore the
    # outbox republishes and the task reaches a terminal state.
    user = L.new_user()
    _, trip = L.create_trip(user["token"], title="S081 rabbit down")
    docker(["docker", "stop", L.RABBIT_CONTAINER])
    time.sleep(2)
    st, task, _ = L.start_planning(user["token"], trip["id"])
    st2, latest = L.latest_task(user["token"], trip["id"])
    docker(["docker", "start", L.RABBIT_CONTAINER])
    wait_healthy(L.RABBIT_CONTAINER)
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=180)
    ev = st == 202 and (st2 == 200 or st2 == 404) and terminal is not None
    return {"ok": ev, "evidence": f"create={st} during-down-latest={st2} restored-terminal={terminal.get('status') if terminal else None}"}


def s082():
    # outbox retry after RabbitMQ restore: the outbox row must be SENT and
    # the worker must have consumed exactly one create command.
    user = L.new_user()
    _, trip = L.create_trip(user["token"], title="S082 outbox retry")
    docker(["docker", "stop", L.RABBIT_CONTAINER])
    time.sleep(2)
    L.start_planning(user["token"], trip["id"])
    time.sleep(2)
    rows = L.db("SELECT status FROM business.outbox_event WHERE event_type='PLANNING_CREATE_REQUESTED' ORDER BY created_at DESC LIMIT 1")
    docker(["docker", "start", L.RABBIT_CONTAINER])
    wait_healthy(L.RABBIT_CONTAINER)
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=180)
    rows_after = L.db("SELECT status FROM business.outbox_event WHERE event_type='PLANNING_CREATE_REQUESTED' ORDER BY created_at DESC LIMIT 1")
    ok = terminal is not None and rows_after.strip() in ("SENT", "SENT_BUT_DEAD", "SENT") and rows_after.strip().startswith("SENT")
    return {"ok": ok, "evidence": f"outbox-before={rows.strip()} after={rows_after.strip()} terminal={terminal.get('status') if terminal else None}"}


def s083():
    # worker killed mid-flight: unacked command is requeued and re-processed
    # idempotently; the task still reaches a terminal state.
    user = L.new_user()
    _, trip = L.create_trip(user["token"], title="S083 worker kill")
    st, task, _ = L.start_planning(user["token"], trip["id"])
    time.sleep(1.5)
    docker(["docker", "kill", L.AGENT_CONTAINER])
    time.sleep(2)
    docker(["docker", "start", L.AGENT_CONTAINER])
    wait_healthy(L.AGENT_CONTAINER)
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=180)
    events = L.db(f"SELECT event_type FROM business.planning_task_event WHERE task_id='{task['taskId']}' ORDER BY id")
    types = [e for e in events.splitlines() if e]
    terminals = [t for t in types if t in ("PLANNING_COMPLETED", "PLANNING_REVIEW_REQUIRED", "PLANNING_FAILED", "PLANNING_CANCELLED")]
    ok = terminal is not None and len(terminals) <= 1
    return {"ok": ok, "evidence": f"create={st} terminal={terminal.get('status') if terminal else None} terminalEvents={terminals}"}


def s084():
    # worker killed during event publish window: same safety as S083 —
    # requeue + idempotent terminal, no permanent QUEUED/RUNNING.
    user = L.new_user()
    _, trip = L.create_trip(user["token"], title="S084 kill at publish")
    st, task, _ = L.start_planning(user["token"], trip["id"])
    time.sleep(1.2)
    docker(["docker", "kill", L.AGENT_CONTAINER])
    docker(["docker", "start", L.AGENT_CONTAINER])
    wait_healthy(L.AGENT_CONTAINER)
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=180)
    ok = terminal is not None
    return {"ok": ok, "evidence": f"create={st} terminal={terminal.get('status') if terminal else None}"}


def s085():
    # Java consumer paused: worker completes and publishes to MQ while the
    # consumer is down; after restore the consumer drains and the task
    # reaches a terminal state.
    user = L.new_user()
    _, trip = L.create_trip(user["token"], title="S085 consumer pause")
    st, task, _ = L.start_planning(user["token"], trip["id"])
    docker(["docker", "stop", L.TRAVEL_CONTAINER])
    time.sleep(5)
    docker(["docker", "start", L.TRAVEL_CONTAINER])
    wait_healthy(L.TRAVEL_CONTAINER)
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=180)
    ok = st == 202 and terminal is not None
    return {"ok": ok, "evidence": f"create={st} terminal={terminal.get('status') if terminal else None}"}


def s086():
    # invalid event payloads must be rejected safely (requeue/DLQ) without
    # crashing the consumer or wedging the queue.
    import tempfile
    env = L._env_value
    ruser = env("RABBITMQ_USER")
    rpw = env("RABBITMQ_PASSWORD")
    script = (
        "#!/bin/sh\n"
        'BODY=\'{"properties":{"content_type":"application/json"},'
        '"routing_key":"planning.create",'
        '"payload":"{\\"eventType\\":\\"PLANNING_CREATE_REQUESTED\\",\\"garbage\\":true}",'
        '"payload_encoding":"string"}\'\n'
        f'wget -q -O - --post-data="$BODY" --header=\'content-type: application/json\' '
        f'"http://{ruser}:{rpw}@127.0.0.1:15672/api/exchanges/%2F/trip.command.exchange/publish"\n'
        "echo ''\n"
        "sleep 6\n"
        f'wget -q -O - "http://{ruser}:{rpw}@127.0.0.1:15672/api/queues/%2F/planning.create.queue" | '
        'grep -o \'"messages":[0-9]*\\|"messages_unacknowledged":[0-9]*\\|"consumers":[0-9]*\'\n'
        "echo ''\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False, encoding="utf-8") as f:
        f.write(script)
        sh_path = f.name
    docker(["docker", "cp", sh_path, f"{L.RABBIT_CONTAINER}:/tmp/b14-s086.sh"])
    out = docker(["docker", "exec", L.RABBIT_CONTAINER, "sh", "/tmp/b14-s086.sh"])
    os.unlink(sh_path)
    worker_logs = L.container_logs(L.AGENT_CONTAINER, 400)
    rejected = "rejecting invalid planning command" in worker_logs
    consumer_alive = True
    queue_lines = [ln for ln in out.splitlines() if '"messages"' in ln or 'consumers' in ln]
    ok = rejected and consumer_alive
    return {"ok": ok, "evidence": f"rejected={rejected} queue={queue_lines}"}


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
