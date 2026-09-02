"""Agent orchestration layer.

The orchestration layer decides *what to do*; the deterministic planner,
feasibility gate and providers below it decide *what is true*.  Nothing here
may invent a hard fact.

Heavy imports (factory, graph, etc.) are deferred so that consumers who only
need ``SlotState`` from ``trip_agent.agent.state`` don't trigger the full
langgraph dependency chain at import time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Lightweight exports — always available
from trip_agent.agent.state import (
    REQUIRED_SLOTS,
    SLOT_NAMES,
    TRIP_CONSTRAINT_FIELD,
    TRIP_LEVEL_SLOTS,
    AgentState,
    ConstraintSlot,
    ConstraintSlots,
    SlotState,
    ToolObservation,
    agent_state_from_dict,
    agent_state_to_dict,
    to_constraint_patch,
    to_trip_fields,
)

# Heavy exports — lazy-loaded on first access via __getattr__
_LAZY_MODULES: dict[str, str] = {
    "DecisionModelConfig": "trip_agent.agent.factory",
    "build_decision_maker": "trip_agent.agent.factory",
    "StructuralFeasibilityGate": "trip_agent.agent.feasibility_gate",
    "AgentLoop": "trip_agent.agent.graph",
    "AgentRunResult": "trip_agent.agent.graph",
    "AskingDecider": "trip_agent.agent.graph",
    "Decision": "trip_agent.agent.graph",
    "StructuredOutputDecider": "trip_agent.agent.graph",
    "run_agent": "trip_agent.agent.graph",
    "MAX_LLM_CALLS": "trip_agent.agent.graph",
    "MAX_STEPS": "trip_agent.agent.graph",
    "MAX_TOOL_CALLS": "trip_agent.agent.graph",
    "BuiltItinerary": "trip_agent.agent.itinerary_builder",
    "DemoItineraryBuilder": "trip_agent.agent.itinerary_builder",
    "RealItineraryBuilder": "trip_agent.agent.itinerary_builder",
    "build_demo_command": "trip_agent.agent.itinerary_builder",
    "normalize_trip_date": "trip_agent.agent.itinerary_builder",
    "AgentRunRecord": "trip_agent.agent.persistence",
    "AgentRunRecorder": "trip_agent.agent.persistence",
    "AgentRunStarted": "trip_agent.agent.persistence",
    "PsycopgAgentRunRepository": "trip_agent.agent.persistence",
    "status_for_stop_reason": "trip_agent.agent.persistence",
    "ToolCall": "trip_agent.agent.tools",
    "ToolRegistry": "trip_agent.agent.tools",
    "ToolResult": "trip_agent.agent.tools",
    "ToolRuntime": "trip_agent.agent.tools",
    "ToolSpec": "trip_agent.agent.tools",
}


def __getattr__(name: str):
    if name in _LAZY_MODULES:
        import importlib
        mod = importlib.import_module(_LAZY_MODULES[name])
        attr = getattr(mod, name)
        # Cache on the module so subsequent accesses are fast
        globals()[name] = attr
        return attr
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "MAX_LLM_CALLS",
    "MAX_STEPS",
    "MAX_TOOL_CALLS",
    "REQUIRED_SLOTS",
    "SLOT_NAMES",
    "TRIP_CONSTRAINT_FIELD",
    "TRIP_LEVEL_SLOTS",
    "AgentLoop",
    "AgentRunRecord",
    "AgentRunRecorder",
    "AgentRunResult",
    "AgentRunStarted",
    "AgentState",
    "AskingDecider",
    "ConstraintSlot",
    "ConstraintSlots",
    "Decision",
    "DecisionModelConfig",
    "BuiltItinerary",
    "DemoItineraryBuilder",
    "RealItineraryBuilder",
    "PsycopgAgentRunRepository",
    "SlotState",
    "StructuredOutputDecider",
    "StructuralFeasibilityGate",
    "ToolCall",
    "ToolObservation",
    "ToolRegistry",
    "ToolResult",
    "ToolRuntime",
    "ToolSpec",
    "agent_state_from_dict",
    "agent_state_to_dict",
    "build_decision_maker",
    "build_demo_command",
    "normalize_trip_date",
    "run_agent",
    "status_for_stop_reason",
    "to_constraint_patch",
    "to_trip_fields",
]