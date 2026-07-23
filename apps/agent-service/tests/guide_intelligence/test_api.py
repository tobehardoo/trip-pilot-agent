from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from trip_agent.guide_intelligence.models import GuideImportResult, TravelFact
from trip_agent.main import app


class StubImportService:
    async def import_url(self, source_url: str) -> GuideImportResult:
        fetched_at = datetime(2026, 7, 23, 8, 0, tzinfo=UTC)
        return GuideImportResult(
            source_url=source_url,
            final_url=source_url,
            source_host="example.com",
            title="Public guide",
            excerpt="Take metro line 2.",
            content_hash="a" * 64,
            fetched_at=fetched_at,
            facts=(
                TravelFact(
                    category="TRANSPORT",
                    statement="Take metro line 2.",
                    evidence="Take metro line 2.",
                    confidence=0.84,
                    observed_at=fetched_at,
                    expires_at=fetched_at + timedelta(days=14),
                ),
            ),
        )


def test_internal_token_is_required(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")

    response = TestClient(app).post(
        "/internal/v1/guide-imports",
        json={"sourceUrl": "https://example.com/guide"},
    )

    assert response.status_code == 401


def test_returns_camel_case_traceable_guide_contract(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")
    monkeypatch.setattr(
        "trip_agent.guide_intelligence.api.GuideImportService",
        StubImportService,
    )

    response = TestClient(app).post(
        "/internal/v1/guide-imports",
        headers={"X-Internal-Token": "test-internal-token"},
        json={"sourceUrl": "https://example.com/guide"},
    )

    assert response.status_code == 200
    assert response.json()["sourceHost"] == "example.com"
    assert response.json()["facts"][0]["category"] == "TRANSPORT"
    assert response.json()["facts"][0]["expiresAt"] == "2026-08-06T08:00:00Z"
