"""Dialog contracts — chat turns, cards, and slot views.

Slot provenance mirrors the fail-closed rule of ``agent/state.py``: only
CONFIRMED values may reach the planning constraints, and trip-level facts
arrive from Java as read-only context (Java is the business-fact authority).
"""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from trip_agent.agent.state import SlotState


class SlotSource(str, Enum):
    """Who supplied a slot value."""

    TRIP = "TRIP"                      # read-only fact from the trip entity
    USER_EXPLICIT = "USER_EXPLICIT"    # user typed or picked the value directly
    USER_CONFIRMED = "USER_CONFIRMED"  # user confirmed a proposal
    LLM_INFERRED = "LLM_INFERRED"      # model proposal, awaiting confirmation


class SlotView(BaseModel):
    value: Any = None
    state: SlotState = SlotState.UNKNOWN
    source: SlotSource = SlotSource.USER_EXPLICIT
    ref: dict[str, str] | None = None   # grounded place info (name/city/district/address)


class CardOption(BaseModel):
    """One clickable answer on a card; the reply is deterministic."""

    action: Literal["SET", "CONFIRM", "EDIT", "SKIP", "ASK"]
    label: str
    value: Any = None


class AgentMessage(BaseModel):
    role: Literal["user", "agent"]
    text: str
    kind: Literal["TEXT", "CLARIFY", "SUMMARY"] = "TEXT"
    options: list[CardOption] = Field(default_factory=list)


class TripContext(BaseModel):
    """Read-only trip facts injected by Java; never editable via dialog.

    Java serialises camelCase (Jackson records), so the inbound aliases keep
    the wire contract while the code stays snake_case.
    """

    model_config = ConfigDict(populate_by_name=True)

    destination: str
    start_date: str | None = Field(default=None, alias="startDate")
    end_date: str | None = Field(default=None, alias="endDate")
    # Composer 右侧出行设置（创建模式种入，travelers/budget 不再由 wizard 表单强问）
    travelers: int | None = Field(default=None, ge=1, le=20)
    budget_amount: int | None = Field(default=None, alias="budgetAmount", ge=100, le=1_000_000)


class DialogueRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    trip_id: str | None = Field(default=None, alias="tripId")
    session_id: str | None = Field(default=None, alias="sessionId")
    trip_context: TripContext | None = Field(default=None, alias="tripContext")
    message: str | None = None
    option: CardOption | None = None
    reset: bool = False


class ConfirmedSlotsResponse(BaseModel):
    """Confirmed-slot projection for agent-driven trip creation."""

    ready: bool
    confirmed: dict[str, Any]


class DialogueResponse(BaseModel):
    phase: Literal["COLLECTING", "READY"]
    ready: bool
    messages: list[AgentMessage]
    slots: dict[str, SlotView]
