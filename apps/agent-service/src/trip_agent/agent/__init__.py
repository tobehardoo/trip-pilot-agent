"""Agent orchestration layer.

The orchestration layer decides *what to do*; the deterministic planner,
feasibility gate and providers below it decide *what is true*.  Nothing here
may invent a hard fact.
"""

from trip_agent.agent.factory import DecisionModelConfig, build_decision_maker
from trip_agent.agent.feasibility_gate import StructuralFeasibilityGate
from trip_agent.agent.graph import (
    MAX_LLM_CALLS,
    MAX_STEPS,
    MAX_TOOL_CALLS,
    AgentLoop,
    AgentRunResult,
    AskingDecider,
    Decision,
    StructuredOutputDecider,
    run_agent,
)
from trip_agent.agent.itinerary_builder import (
    BuiltItinerary,
    DemoItineraryBuilder,
    RealItineraryBuilder,
    build_demo_command,
    normalize_trip_date,
)
from trip_agent.agent.persistence import (
    AgentRunRecord,
    AgentRunRecorder,
    AgentRunStarted,
    PsycopgAgentRunRepository,
    status_for_stop_reason,
)
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
from trip_agent.agent.tools import (
    ToolCall,
    ToolRegistry,
    ToolResult,
    ToolRuntime,
    ToolSpec,
)

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
