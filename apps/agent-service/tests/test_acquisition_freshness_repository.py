import asyncio
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from trip_agent.acquisition import PsycopgAcquisitionRepository
from trip_agent.acquisition.cli import main
from trip_agent.acquisition.models import resource_id_for

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def database_url() -> str:
    value = os.environ.get("KNOWLEDGE_TEST_DATABASE_URL", "").strip()
    if not value:
        pytest.skip("KNOWLEDGE_TEST_DATABASE_URL is not configured")
    return value


@pytest.fixture(autouse=True)
def reset_acquisition_tables() -> Iterator[None]:
    url = database_url()
    asyncio.run(PsycopgAcquisitionRepository(url).migrate())
    with psycopg.connect(url) as connection:
        connection.execute(
            "TRUNCATE agent.knowledge_fetch_run, agent.knowledge_snapshot, "
            "agent.knowledge_resource RESTART IDENTITY CASCADE"
        )
    yield


def test_repository_returns_resource_dates_and_latest_run_result() -> None:
    resource_id = resource_id_for("official-a", "https://example.com/article")
    verified_at = datetime(2026, 7, 22, 1, tzinfo=UTC)
    failed_at = verified_at + timedelta(hours=2)
    with psycopg.connect(database_url()) as connection:
        connection.execute(
            """
            INSERT INTO agent.knowledge_resource (
                resource_id, source_id, source_name, reliability_level, city,
                source_url, final_url, last_attempted_at, last_verified_at, last_changed_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                resource_id,
                "official-a",
                "Official A",
                "OFFICIAL",
                "广州",
                "https://example.com/article",
                "https://example.com/article",
                failed_at,
                verified_at,
                verified_at - timedelta(days=3),
            ),
        )
        connection.execute(
            """
            INSERT INTO agent.knowledge_fetch_run (
                run_id, resource_id, started_at, completed_at, status,
                attempt_count, attempts, error_code, error_message, retryable, http_status
            ) VALUES (
                'older-304', %s, %s, %s, 'NOT_MODIFIED', 1, %s::jsonb,
                NULL, NULL, NULL, NULL
            )
            """,
            (
                resource_id,
                verified_at - timedelta(seconds=1),
                verified_at,
                json.dumps([
                    {
                        "status": "SUCCEEDED",
                        "attempt_number": 1,
                        "started_at": "2026-07-22T00:59:59Z",
                        "completed_at": "2026-07-22T01:00:00Z",
                    }
                ]),
            ),
        )
        connection.execute(
            """
            INSERT INTO agent.knowledge_fetch_run (
                run_id, resource_id, started_at, completed_at, status,
                attempt_count, attempts, error_code, error_message, retryable, http_status
            ) VALUES (
                'latest-failure', %s, %s, %s, 'FAILED', 1, %s::jsonb,
                'HTTP_STATUS_ERROR', 'resource returned HTTP 503', TRUE, 503
            )
            """,
            (
                resource_id,
                failed_at - timedelta(seconds=1),
                failed_at,
                json.dumps([
                    {
                        "status": "FAILED",
                        "attempt_number": 1,
                        "started_at": "2026-07-22T02:59:59Z",
                        "completed_at": "2026-07-22T03:00:00Z",
                        "error_code": "HTTP_STATUS_ERROR",
                        "message": "resource returned HTTP 503",
                        "retryable": True,
                        "status_code": 503,
                    }
                ]),
            ),
        )

    states = asyncio.run(PsycopgAcquisitionRepository(database_url()).list_resource_freshness())

    assert len(states) == 1
    assert states[0].resource_id == resource_id
    assert states[0].last_attempted_at == failed_at
    assert states[0].last_verified_at == verified_at
    assert states[0].last_changed_at == verified_at - timedelta(days=3)
    assert states[0].latest_run_status == "FAILED"
    assert states[0].latest_error_code == "HTTP_STATUS_ERROR"
    assert states[0].latest_error_message == "resource returned HTTP 503"


def test_freshness_cli_reports_all_configured_resources(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    read_only_url = (
        f"{database_url()}?options=-c%20default_transaction_read_only%3Don"
    )
    monkeypatch.setenv("KNOWLEDGE_DATABASE_URL", read_only_url)

    exit_code = main(
        ["freshness", str(PROJECT_ROOT / "knowledge" / "sources")]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "STALE"
    assert payload["source_count"] == 1
    assert payload["resource_count"] == 3
    assert payload["stale_resource_count"] == 3
    assert {
        resource["stale_reason"]
        for resource in payload["sources"][0]["resources"]
    } == {"NEVER_ATTEMPTED"}
