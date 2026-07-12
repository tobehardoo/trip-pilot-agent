from fastapi.testclient import TestClient

from trip_agent.main import app


def test_health_returns_service_status() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "UP", "service": "agent-service"}
