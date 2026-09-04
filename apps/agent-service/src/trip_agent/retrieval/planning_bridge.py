"""Bridge retrieved knowledge-model :class:`KnowledgeCitation` into planning evidence.

The planner's deterministic ranker already consumes positive guide facts
(``guide_evidence.facts`` -> ``guide_evidence_validated_facts`` ->
``CandidateRanker._evidence_guide_bonus``) and rewards them by
reliability x freshness.  To let knowledge-base knowledge *change* the plan
(rather than only appear as post-hoc citations), the worker retrieves eligible
knowledge **before** ``provider.plan`` and maps each fresh, allowed citation
into a ``GuideFactEvidence`` so it ranks like any other trusted guide fact.

Nothing here elevates a source: source_type is derived 1:1 from the document's
own reliability level, so a community post "recommends" (UGC tier) while an
official source ranks higher — exactly the trust model everywhere else.
"""

from __future__ import annotations

from datetime import UTC, timedelta
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, UUID, uuid5

from trip_agent.retrieval.governance import FRESH_WINDOW_DAYS

if TYPE_CHECKING:
    from trip_agent.retrieval.repository import KnowledgeCitation
    from trip_agent.worker.contracts import (
        GuideFactEvidence,
        PlanningCreateCommand,
    )

# source_type (allowed by the planning wire contract) per reliability level.
# The planning provider maps these back to reliability via ``_SOURCE_TYPE_RELIABILITY``
# (OFFICIAL_TOURISM->OFFICIAL_PORTAL, PUBLIC_GUIDE_URL->PUBLIC_GUIDE,
#  XIAOHONGSHU_SHARED_TEXT->UGC), keeping ranks consistent with retrieval.
_SOURCE_TYPE_BY_RELIABILITY = {
    "OFFICIAL": "OFFICIAL_TOURISM",
    "CURATED": "PUBLIC_GUIDE_URL",
    "COMMUNITY": "XIAOHONGSHU_SHARED_TEXT",
}

_KB_NAMESPACE = uuid5(NAMESPACE_URL, "trip-pilot/kb")
_KB_FACT_NAMESPACE = uuid5(NAMESPACE_URL, "trip-pilot/kb-fact")
_MAX_GUIDE_FACTS = 100


def _guide_import_id(document_id: str) -> UUID:
    return uuid5(_KB_NAMESPACE, document_id)


def _guide_fact_id(chunk_id: str) -> UUID:
    return uuid5(_KB_FACT_NAMESPACE, chunk_id)


def knowledge_citation_to_guide_fact(
    citation: KnowledgeCitation,
) -> GuideFactEvidence | None:
    """Map one eligible knowledge citation into a planning guide fact.

    Returns ``None`` when the citation does not carry a supported reliability
    level (it cannot be trusted to back any claim in planning).
    """
    from trip_agent.worker.contracts import GuideFactEvidence

    source_type = _SOURCE_TYPE_BY_RELIABILITY.get(citation.reliability_level)
    if source_type is None:
        return None
    observed_at = citation.collected_at.astimezone(UTC)
    expires_at = observed_at + timedelta(days=FRESH_WINDOW_DAYS)
    return GuideFactEvidence.model_validate(
        {
            "guideImportId": _guide_import_id(citation.document_id),
            "factId": _guide_fact_id(citation.chunk_id),
            "category": "TIP",
            "statement": citation.title[:1000],
            "evidence": citation.content[:1000],
            "sourceType": source_type,
            "sourceUrl": citation.source_url,
            "sourceHost": citation.source_name[:253],
            "sourceTitle": citation.title[:300],
            "confidence": min(max(0.0, citation.similarity), 1.0),
            "effectiveDate": None,
            "observedAt": observed_at,
            "expiresAt": expires_at,
        }
    )


def inject_knowledge_guide_facts(
    command: PlanningCreateCommand,
    knowledge: object,
) -> PlanningCreateCommand:
    """Append eligible REAL knowledge citations as planning guide facts.

    Only ``status == REAL`` evidence participates; demo/unavailable knowledge
    leaves the command untouched.  Existing guide facts are preserved.
    """
    if knowledge is None or getattr(knowledge, "status", None) != "REAL":
        return command
    citations = getattr(knowledge, "citations", ())
    facts = list(command.payload.guide_evidence.facts)
    for citation in citations:
        if len(facts) >= _MAX_GUIDE_FACTS:
            break
        guide_fact = knowledge_citation_to_guide_fact(citation)
        if guide_fact is None:
            continue
        facts.append(guide_fact)
    if len(facts) == len(command.payload.guide_evidence.facts):
        return command
    guide_evidence = command.payload.guide_evidence.model_copy(
        update={"facts": tuple(facts)}
    )
    payload = command.payload.model_copy(update={"guide_evidence": guide_evidence})
    return command.model_copy(update={"payload": payload})