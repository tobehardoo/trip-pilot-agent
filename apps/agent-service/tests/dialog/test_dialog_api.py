"""创建对话端点的 Required Context 种子（2026-09-02 Composer D1）。

带 sessionId 的创建对话必须接受请求中的 tripContext，并以 TRIP 事实种子化
destination/dates；缺省时从空白开始问目的地。种子化后由同一 agent 循环
继续收集人数/预算。行为由 dialog/api.py 端点层决定。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from trip_agent.dialog.api import router as dialog_router
from trip_agent.dialog.service import AgentDialogService
from trip_agent.dialog.store import InMemoryDialogStore

HEADERS = {"X-Internal-Token": "test-internal-token"}


def _client(monkeypatch) -> TestClient:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")
    app = FastAPI()
    app.include_router(dialog_router)
    app.state.dialog_service = AgentDialogService(store=InMemoryDialogStore())
    return TestClient(app)


def test_creation_dialogue_seeds_required_context(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.post(
        "/internal/v1/agent/dialogue",
        json={
            "sessionId": "seed-1",
            "tripContext": {
                "destination": "广州",
                "startDate": "2026-09-10",
                "endDate": "2026-09-13",
            },
        },
        headers=HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    destination = body["slots"]["destination"]
    assert destination["value"] == "广州"
    assert destination["state"] == "CONFIRMED"
    assert destination["source"] == "TRIP"
    assert body["slots"]["start_date"]["state"] == "CONFIRMED"
    assert body["slots"]["end_date"]["state"] == "CONFIRMED"
    # 目的地/日期已锁定 → agent 继续收集人数/预算（不再问已锁定的目的地）
    assert body["ready"] is False
    assert body["messages"][-1]["text"] == "这次出行几位？"


def test_creation_dialogue_without_context_asks_destination(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.post(
        "/internal/v1/agent/dialogue",
        json={"sessionId": "seed-2"},
        headers=HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["slots"]["destination"]["state"] == "UNKNOWN"
    assert body["messages"][-1]["text"].startswith("想去哪个城市")


def test_creation_dialogue_confirmed_projection_uses_trip_constraint_names(monkeypatch) -> None:
    client = _client(monkeypatch)
    first = client.post(
        "/internal/v1/agent/dialogue",
        json={
            "sessionId": "seed-3",
            "tripContext": {
                "destination": "广州",
                "startDate": "2026-09-10",
                "endDate": "2026-09-13",
                "travelers": 2,
                "budgetAmount": 5500,
            },
        },
        headers=HEADERS,
    )
    assert first.status_code == 200
    assert first.json()["ready"] is True
    confirmed = client.get("/internal/v1/agent/dialogue/confirmed/seed-3", headers=HEADERS)
    assert confirmed.status_code == 200
    projection = confirmed.json()
    assert projection["ready"] is True
    assert projection["confirmed"] == {
        "destination": "广州",
        "start_date": "2026-09-10",
        "end_date": "2026-09-13",
        "travelers": 2,
        "budget": 5500,
    }