"""Demo knowledge-evidence provider — returns a fixed UNAVAILABLE response.

Extracted from ``worker/processor.py``.
"""

from trip_agent.worker.contracts import KnowledgeEvidence, KnowledgeFreshness, PlanningCreateCommand
from trip_agent.worker.knowledge import build_knowledge_query


class DemoKnowledgeEvidenceProvider:
    """Always returns DEMO/UNAVAILABLE evidence — no real retrieval."""

    async def get_evidence(
        self, command: PlanningCreateCommand
    ) -> KnowledgeEvidence:
        return KnowledgeEvidence(
            status="DEMO",
            query=build_knowledge_query(command),
            citations=(),
            freshness=KnowledgeFreshness(status="UNAVAILABLE"),
            message="演示模式未使用生产知识检索",
        )
