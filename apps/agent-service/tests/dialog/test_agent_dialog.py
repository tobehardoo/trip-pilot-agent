"""Agent-driven creation dialog (P3-T2): single-agent-loop behaviour.

The creation dialog shares the LangGraph ``AgentLoop`` + ``ConstraintSlots``
engine with trip mode.  These tests drive the same external contract
(DialogueResponse slots + ready, ConfirmedSlotsResponse projection) through
free-text messages and the seeded Composer context.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from trip_agent.agent.state import SlotState
from trip_agent.dialog.models import CardOption, DialogueRequest, SlotSource, TripContext
from trip_agent.dialog.service import (
    AgentDialogService,
    _city_from_destination,
    _parse_date_text,
)
from trip_agent.dialog.store import InMemoryDialogStore
from trip_agent.platform_util import run_async

FULL_CONTEXT = TripContext(
    destination="成都", start_date="2026-10-01", end_date="2026-10-04",
    travelers=2, budget_amount=5500,
)
DATES_CONTEXT = TripContext(
    destination="成都", start_date="2026-10-01", end_date="2026-10-04",
)


def _service() -> AgentDialogService:
    return AgentDialogService(store=InMemoryDialogStore())


def _create(
    service: AgentDialogService,
    session_id: str = "s1",
    context: TripContext | None = None,
    **kwargs: Any,
):
    request = DialogueRequest(session_id=session_id, **kwargs)
    return run_async(service.handle(f"create:{session_id}", context, request))


def _confirmed(service: AgentDialogService, session_id: str = "s1"):
    return run_async(service.confirmed_creation(f"create:{session_id}"))


# ── parsing helpers (kept pure) ─────────────────────────────────────


def test_parse_date_text_variants() -> None:
    today = date(2026, 8, 29)
    assert _parse_date_text("2026-10-01", today=today) == "2026-10-01"
    assert _parse_date_text("2026年10月1日", today=today) == "2026-10-01"
    assert _parse_date_text("10月1日", today=today) == "2026-10-01"
    assert _parse_date_text("下周三", today=today) is None


def test_city_from_destination_extracts_the_city_from_a_phrase() -> None:
    assert _city_from_destination("周末去杭州两天，两个人，轻松一点") == "杭州"
    assert _city_from_destination("国庆去成都四天") == "成都"
    assert _city_from_destination("三亚") == "三亚"
    assert _city_from_destination("") == ""


# ── creation mode ───────────────────────────────────────────────────


def test_creation_asks_destination_first() -> None:
    result = _create(_service())
    assert result.slots["destination"].state is SlotState.UNKNOWN
    assert result.ready is False
    assert result.messages[-1].text.startswith("想去哪个城市")
    assert result.messages[-1].kind == "CLARIFY"


def test_creation_bare_city_confirms_destination() -> None:
    service = _service()
    result = _create(service, message="成都")
    assert result.slots["destination"].value == "成都"
    assert result.slots["destination"].state is SlotState.CONFIRMED
    # next question is the start date
    assert result.messages[-1].text == "行程从哪天开始？"
    assert result.ready is False


def test_creation_end_before_start_is_rejected_by_date_parse() -> None:
    service = _service()
    _create(service, message="成都")
    _create(service, message="2026-10-04到2026-10-01")
    result = _create(service)
    # a reversed range is not parsed as a date range; the driver re-asks dates
    assert result.slots["start_date"].state is not SlotState.CONFIRMED
    assert result.ready is False


def test_creation_full_flow_reaches_ready_with_projection() -> None:
    service = _service()
    _create(service)
    _create(service, message="成都")
    _create(service, message="2026-10-01到2026-10-04")
    _create(service, message="一行2位")
    result = _create(service, message="总预算5500元")
    assert result.ready is True
    assert result.phase == "READY"
    # ready 后：SUMMARY 摘要卡在前，紧接着是「是否开始规划」CLARIFY 确认卡。
    assert any(message.kind == "SUMMARY" for message in result.messages)
    assert result.messages[-1].kind == "CLARIFY"
    assert "开始规划" in result.messages[-1].text
    # confirmed 投影与 Java TripConstraints 字段对齐（budget，非 budget_amount）
    projection = _confirmed(service)
    assert projection.ready is True
    assert projection.confirmed["destination"] == "成都"
    assert projection.confirmed["start_date"] == "2026-10-01"
    assert projection.confirmed["end_date"] == "2026-10-04"
    assert projection.confirmed["travelers"] == 2
    assert projection.confirmed["budget"] == 5500


def test_creation_not_ready_until_dates_confirmed() -> None:
    service = _service()
    _create(service)
    _create(service, message="成都")
    projection = _confirmed(service)
    assert projection.ready is False
    assert projection.confirmed["destination"] == "成都"
    assert "start_date" not in projection.confirmed


def test_creation_seeded_context_reaches_ready_in_the_first_turn() -> None:
    """Composer 送全量 Required Context（destination/dates + travelers/budget）→ 首轮即 ready。"""
    service = _service()
    request = DialogueRequest(
        session_id="s2", trip_context=FULL_CONTEXT,
    )
    result = run_async(service.handle("create:s2", FULL_CONTEXT, request))
    assert result.ready is True
    assert result.phase == "READY"
    assert result.slots["destination"].state is SlotState.CONFIRMED
    assert result.slots["destination"].source is SlotSource.TRIP
    assert result.slots["travelers"].state is SlotState.CONFIRMED
    assert result.slots["travelers"].value == 2
    projection = _confirmed(service, "s2")
    assert projection.ready is True
    assert projection.confirmed["budget"] == 5500


def test_creation_without_seed_is_not_ready_but_does_not_deadlock() -> None:
    """destination/dates seed via chat but travelers/budget missing → not ready;
    the agent keeps asking them (bounded per turn), never crashes."""
    service = _service()
    _create(service)  # ask destination
    _create(service, message="成都")  # ask start date
    _create(service, message="2026-10-01到2026-10-04")  # ask travelers
    for _ in range(3):
        result = _create(service)
        assert result.ready is False
        assert result.messages[-1].kind == "CLARIFY"  # still asking, no deadlock
    # provide both via free text → ready
    result = _create(service, message="2个人，预算5000")
    assert result.ready is True


def test_creation_rich_first_message_scans_all_slots() -> None:
    service = _service()
    result = _create(
        service,
        message="想去成都玩，预算5000，2个人，2026-10-01到2026-10-03",
    )
    for name in ("destination", "start_date", "end_date", "travelers", "budget"):
        assert result.slots[name].state is SlotState.CONFIRMED, name
    assert result.slots["destination"].value == "成都"
    assert result.slots["budget"].value == 5000
    assert result.slots["travelers"].value == 2
    assert result.ready is True


def test_creation_dates_are_locked_from_trip_context() -> None:
    """创建模式种子化的 destination/dates 是 TRIP 事实——不被后续文本改掉。"""
    service = _service()
    request = DialogueRequest(session_id="s3", trip_context=DATES_CONTEXT)
    run_async(service.handle("create:s3", DATES_CONTEXT, request))
    result = _create(service, session_id="s3", message="想去重庆玩，预算6000，3个人")
    assert result.slots["destination"].value == "成都"
    assert result.slots["destination"].source is SlotSource.TRIP
    assert result.slots["start_date"].value == "2026-10-01"
    assert result.slots["travelers"].value == 3


def test_reset_clears_state_and_reseeds_context() -> None:
    service = _service()
    request = DialogueRequest(session_id="s4", trip_context=FULL_CONTEXT)
    run_async(service.handle("create:s4", FULL_CONTEXT, request))
    _create(service, session_id="s4", message="随便聊聊")
    result = _create(service, session_id="s4", context=FULL_CONTEXT, reset=True)
    # travellers/budget 也随 reset 重新种入（来自 Composer context）
    assert result.slots["destination"].value == "成都"
    assert result.slots["travelers"].state is SlotState.CONFIRMED


# ── option (chip) path ──────────────────────────────────────────────


def test_option_set_translates_into_agent_update() -> None:
    service = _service()
    _create(service)
    _create(service, message="成都")
    _create(service, message="2026-10-01到2026-10-04")
    result = _create(service, option=CardOption(action="SET", label="2 位", value=2))
    assert result.slots["travelers"].value == 2
    assert result.slots["travelers"].state is SlotState.CONFIRMED
    assert result.messages[0].text == "[点选] 2 位"


# ── trip scope (legacy panel) ───────────────────────────────────────


def test_trip_scope_seeds_read_only_facts() -> None:
    service = _service()
    context = TripContext(destination="广州", start_date="2026-09-10", end_date="2026-09-13")
    request = DialogueRequest(trip_id="t1", trip_context=context)
    result = run_async(service.handle("trip:t1", context, request))
    assert result.slots["destination"].state is SlotState.CONFIRMED
    assert result.slots["destination"].source is SlotSource.TRIP
    assert result.slots["start_date"].value == "2026-09-10"