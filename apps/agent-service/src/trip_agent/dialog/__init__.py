"""Agent dialog slice (Plan B v0.1): chat + clarification cards over the
deterministic constraint kernel.

The LLM only *proposes* slot values; every value becomes CONFIRMED solely
through an explicit user action (the bounded-agent trust boundary, see
docs/decisions.md D5).
"""

from trip_agent.dialog.api import router
from trip_agent.dialog.models import (
    AgentMessage,
    CardOption,
    DialogueRequest,
    DialogueResponse,
    SlotSource,
    SlotView,
    TripContext,
)
from trip_agent.dialog.service import AgentDialogService
from trip_agent.dialog.store import InMemoryDialogStore, build_store

__all__ = [
    "AgentDialogService",
    "AgentMessage",
    "CardOption",
    "DialogueRequest",
    "DialogueResponse",
    "InMemoryDialogStore",
    "SlotSource",
    "SlotView",
    "TripContext",
    "build_store",
    "router",
]
