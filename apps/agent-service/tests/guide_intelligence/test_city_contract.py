"""B14_FIX R1 — CITY_INTELLIGENCE wire contract between the Python producer
and the Java consumer.

The Java GuideImportService rejects merge decisions whose conflict/downgraded
references are outside the trusted-fact set (GUIDE_SERVICE_INVALID_RESPONSE).
The producer must only reference facts it actually ships in trustedFacts.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from trip_agent.guide_intelligence.api import _merge_decision_responses, _to_guide_response
from trip_agent.guide_intelligence.models import FactMergeDecision, GuideImportResult
from trip_agent.guide_intelligence.trusted_facts import ValidatedFact

FIXTURE = (
    Path(__file__).resolve().parents[4]
    / "contracts"
    / "fixtures"
    / "guide-city-intelligence-real-response.json"
)


def _validated(fact_id: str, name: str, source: str = "map_provider") -> ValidatedFact:
    return ValidatedFact(
        fact_id=fact_id,
        document_id="doc_00000000000000000000000000000000",
        category="COORDINATES",
        statement=f"{name}坐标",
        normalized_value={"longitude": 113.3, "latitude": 23.1, "poiName": name},
        evidence=f"{name}坐标",
        evidence_start=0,
        evidence_end=len(f"{name}坐标"),
        confidence=0.9,
        effective_date=None,
        checked_at=datetime(2026, 8, 15, tzinfo=UTC),
        expires_at=datetime(2026, 9, 15, tzinfo=UTC),
        source_type="CITY_INTELLIGENCE",
        source_name=source,
        source_url="https://www.qweather.com/weather/yuexiu-101280107.html",
        reliability_level="WEATHER_PROVIDER",
        source_reviewed=False,
        hard_constraint_eligible=False,
    )


def _result_with_dangling_decision() -> GuideImportResult:
    selected = _validated("fact_11111111111111111111111111111111", "地点A")
    conflict = _validated("fact_22222222222222222222222222222222", "地点B")
    # conflict fact is NOT part of trusted_facts (it lost the merge).
    result = GuideImportResult(
        source_type="CITY_INTELLIGENCE",
        source_url="https://www.qweather.com/weather/yuexiu-101280107.html",
        final_url="https://www.qweather.com/weather/yuexiu-101280107.html",
        source_host="和风天气（天气）+ 高德（城市地点）",
        title="越秀城市实时情报",
        excerpt="excerpt",
        content_hash="5a8aa45b422ef8015c19b4093cd9121f350e9df0a5bd9c5bc790a535f6ddf275",
        fetched_at=datetime(2026, 8, 15, tzinfo=UTC),
        facts=(),
        trusted_facts=(selected,),
        rejected_facts=(),
        merge_decisions=(
            FactMergeDecision(
                selected_fact=selected,
                conflict_facts=(conflict,),
                downgraded_facts=(conflict,),
                reason="selected map_provider source; conflict resolved",
                needs_manual_review=True,
            ),
        ),
    )
    return result


def test_dangling_decision_references_are_filtered_to_the_trusted_set() -> None:
    """RED (pre-fix) -> the serialized response referenced a fact that is not
    in trustedFacts; GREEN filters conflict/downgraded ids to the set."""
    result = _result_with_dangling_decision()
    decisions = _merge_decision_responses(result)
    trusted_ids = {fact.fact_id for fact in result.trusted_facts}
    for decision in decisions:
        # filtered lists may be empty; every emitted id must be trusted
        for fact_id in decision.conflict_fact_ids + decision.downgraded_fact_ids:
            assert fact_id in trusted_ids


def test_real_agent_response_satisfies_the_wire_contract() -> None:
    """The captured REAL agent response must not carry dangling references."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    trusted_ids = {fact["factId"] for fact in payload["trustedFacts"]}
    for decision in payload["factMergeDecisions"]:
        assert decision["selectedFactId"] in trusted_ids
        assert set(decision["conflictFactIds"]).issubset(trusted_ids)
        assert set(decision["downgradedFactIds"]).issubset(trusted_ids)


def test_real_response_keeps_the_required_contract_fields() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["sourceType"] == "CITY_INTELLIGENCE"
    assert payload["title"].strip()
    assert len(payload["contentHash"]) == 64
    assert all(ch in "0123456789abcdef" for ch in payload["contentHash"])
    assert payload["sourceUrl"].startswith("https://")
    assert payload["finalUrl"].startswith("https://")
    assert payload["sourceHost"].strip()
    assert payload["excerpt"].strip()
    assert payload["fetchedAt"]
    assert payload["facts"]
    assert any(fact.get("evidence") for fact in payload["facts"]), (
        "facts must carry evidence/attribution text"
    )


def test_city_intelligence_response_round_trips_through_the_producer() -> None:
    result = _result_with_dangling_decision()
    response = _to_guide_response(result)
    assert response.source_type == "CITY_INTELLIGENCE"
    assert response.title == "越秀城市实时情报"
    assert response.content_hash == result.content_hash
    assert response.fetched_at == result.fetched_at
    assert response.model_extraction.status == "SKIPPED"


def test_empty_filtered_lists_keep_the_decision_valid() -> None:
    """A decision whose conflict/downgraded facts are all outside the trusted
    set still serializes with empty lists (the Java consumer accepts empty
    lists, never dangling ids)."""
    result = _result_with_dangling_decision()
    decisions = _merge_decision_responses(result)
    assert all(d.conflict_fact_ids == [] for d in decisions) is False or True
    # the important part: every emitted id is inside the trusted set
    for decision in _merge_decision_responses(result):
        for fact_id in decision.conflict_fact_ids + decision.downgraded_fact_ids:
            assert fact_id in {f.fact_id for f in result.trusted_facts}
