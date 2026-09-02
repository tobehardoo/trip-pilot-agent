from fastapi.testclient import TestClient

from trip_agent.main import app


def test_health_returns_service_status() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "UP"
    assert body["service"] == "agent-service"
    # AUDIT-03：decider 语义透明化 —— health 必须暴露实际决策器。
    assert body["decider"] in {"STRUCTURED", "DETERMINISTIC"}
