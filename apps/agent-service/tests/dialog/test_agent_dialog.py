"""Dialog slice behaviour: fail-closed proposals, tiered wizard, ready
projection.  The LLM is only ever allowed to propose; only user actions
confirm.  These tests use ``run_async`` to match the rest of the suite."""

from __future__ import annotations

from datetime import date
from typing import Any

from trip_agent.agent.state import SlotState
from trip_agent.dialog.models import (
    CardOption,
    DialogueRequest,
    SlotSource,
    TripContext,
)
from trip_agent.dialog.service import (
    AgentDialogService,
    _city_from_destination,
    _parse_date_text,
)
from trip_agent.dialog.store import InMemoryDialogStore
from trip_agent.platform_util import run_async

CONTEXT = TripContext(destination="成都", start_date="2026-10-01", end_date="2026-10-04")


class _ScriptedExtractor:
    """Returns a fixed proposal set; records the last prompt it saw."""

    def __init__(self, result: dict[str, Any] | None, *, fail: bool = False) -> None:
        self._result = result
        self._fail = fail
        self.calls: list[str] = []

    async def extract(self, text: str) -> dict[str, Any] | None:
        self.calls.append(text)
        if self._fail:
            raise RuntimeError("provider down")
        return self._result


def _service(extractor: Any = None, places: Any = None) -> AgentDialogService:
    return AgentDialogService(store=InMemoryDialogStore(), extractor=extractor, places=places)


def _places_with(mapping: dict[str, list[dict[str, str]]]) -> Any:
    """Fake in-process place search: keyword-fragment → candidates."""

    async def search(*, city: str, keyword: str, limit: int = 3) -> list[dict[str, str]]:
        for fragment, candidates in mapping.items():
            if fragment in keyword:
                return candidates
        return []

    return search


def _handle(service: AgentDialogService, **kwargs: Any):
    request = DialogueRequest(trip_id="trip-1", **kwargs)
    return run_async(service.handle("trip:trip-1", CONTEXT, request))


def _create(service: AgentDialogService, session_id: str = "s1", **kwargs: Any):
    request = DialogueRequest(session_id=session_id, **kwargs)
    return run_async(service.handle(f"create:{session_id}", None, request))


def _confirmed(service: AgentDialogService, session_id: str = "s1"):
    return run_async(service.confirmed_creation(f"create:{session_id}"))


def _chip(label: str, value: Any) -> CardOption:
    return CardOption(action="SET", label=label, value=value)


def _confirm() -> CardOption:
    return CardOption(action="CONFIRM", label="可以")


def _ask(slot: str) -> CardOption:
    return CardOption(action="ASK", label=slot, value=slot)


def _skip_t1() -> CardOption:
    return CardOption(action="SKIP", label="先跳过，直接创建", value="T1")


def _first() -> Any:
    return _handle(_service())


def _trip_ready_flow(service: AgentDialogService) -> Any:
    """Drive a trip-mode run to READY: T0 chips → must_visit → skip T1 rest."""
    _handle(service)
    _handle(service, option=_chip("2 位", 2))
    _handle(service, option=_chip("3000-8000", 5500))
    _handle(service, option=_ask("must_visit"))
    _handle(service, message="大熊猫基地")
    _handle(service, option=_confirm())
    return _handle(service, option=_skip_t1())


# ── trip mode ───────────────────────────────────────────────────────


def test_trip_context_seeds_read_only_slots() -> None:
    result = _first()
    assert result.slots["destination"].state is SlotState.CONFIRMED
    assert result.slots["destination"].source is SlotSource.TRIP
    assert result.slots["start_date"].value == "2026-10-01"
    # the tier-0 wizard opens with the first unconfirmed slot
    assert result.messages[-1].text.startswith("这次出行几位")
    assert result.messages[-1].kind == "CLARIFY"


def test_wizard_chip_confirms_immediately_and_advances() -> None:
    service = _service()
    _handle(service)
    result = _handle(service, option=_chip("2 位", 2))
    assert result.slots["travelers"].state is SlotState.CONFIRMED
    assert result.slots["travelers"].source is SlotSource.USER_EXPLICIT
    assert result.messages[-1].text.startswith("总预算")


def test_free_text_is_only_a_proposal_until_confirmed() -> None:
    service = _service()
    _handle(service)
    result = _handle(service, message="两个人去")
    assert result.slots["travelers"].state is SlotState.INFERRED
    assert result.slots["travelers"].value == 2
    assert result.messages[-1].kind == "CLARIFY"
    confirmed = _handle(service, option=_confirm())
    assert confirmed.slots["travelers"].state is SlotState.CONFIRMED
    assert confirmed.slots["travelers"].source is SlotSource.USER_CONFIRMED


def test_edit_roundtrip_replaces_value_then_reconfirms() -> None:
    service = _service()
    _handle(service)
    # a free-text answer becomes a proposal with an explicit confirm card
    _handle(service, message="两个人")
    _handle(service, option=CardOption(action="EDIT", label="改一下"))
    result = _handle(service, message="6")
    assert result.slots["travelers"].value == 6
    assert result.slots["travelers"].state is SlotState.INFERRED
    _handle(service, option=_confirm())
    _handle(service, option=_chip("3000-8000", 5500))
    final = _handle(service, message="随便聊聊")  # unrelated text changes nothing
    assert final.slots["travelers"].value == 6
    assert final.slots["travelers"].state is SlotState.CONFIRMED


def test_llm_proposals_are_confirmed_one_by_one() -> None:
    extractor = _ScriptedExtractor(
        {"budget_amount": 8000, "pace": "RELAXED", "must_visit": ["大熊猫基地"]},
    )
    service = _service(extractor)
    result = _handle(service, message="两个人，预算8000，轻松一点，必去大熊猫基地")
    assert result.slots["budget"].value == 8000
    assert result.slots["budget"].state is SlotState.INFERRED
    assert result.slots["budget"].source is SlotSource.LLM_INFERRED
    assert result.slots["pace"].value == "RELAXED"
    # wizard has not been reached yet — confirmation cards come first
    assert result.messages[-1].kind == "CLARIFY"
    _handle(service, option=_confirm())
    _handle(service, option=_confirm())
    _handle(service, option=CardOption(action="EDIT", label="改一下"))
    renamed = _handle(service, message="大熊猫繁育研究基地、宽窄巷子")
    assert renamed.slots["must_visit"].value == ["大熊猫繁育研究基地", "宽窄巷子"]
    _handle(service, option=_confirm())
    # all proposals confirmed — tier-1 suggestion card follows, then ready
    final = _handle(service, option=_skip_t1())
    assert final.ready is True
    assert final.phase == "READY"


def test_llm_failure_degrades_gracefully() -> None:
    extractor = _ScriptedExtractor(None, fail=True)
    service = _service(extractor)
    result = _handle(service, message="预算8000轻松一点")
    assert extractor.calls  # the model was attempted
    # graceful: the model failed, but the deterministic scan still proposes
    # the clearly stated budget — as a proposal only (never auto-confirmed);
    # schedule-looking text never answers the open travelers question
    assert result.slots["travelers"].state is SlotState.UNKNOWN
    assert result.slots["budget"].state is SlotState.INFERRED
    assert result.slots["budget"].value == 8000
    assert result.messages[-1].kind == "CLARIFY"
    assert result.messages[-1].text.startswith("总预算")


def test_skip_drops_proposal_and_reaches_ready() -> None:
    service = _service()
    _handle(service)
    _handle(service, option=_chip("2 位", 2))
    _handle(service, option=_chip("3000-8000", 5500))
    _handle(service, option=_ask("must_visit"))
    _handle(service, message="大熊猫基地")
    result = _handle(service, option=CardOption(action="SKIP", label="不用管这个"))
    assert result.slots["must_visit"].state is SlotState.UNKNOWN
    assert result.ready is False  # tier-1 suggestion card comes next
    result = _handle(service, option=_skip_t1())
    assert result.ready is True
    summary = result.messages[-1]
    assert summary.kind == "SUMMARY"
    assert "成都" in summary.text and "总预算 5,500 元" in summary.text


def test_reset_clears_state_but_keeps_trip_context() -> None:
    service = _service()
    _handle(service)
    _handle(service, option=_chip("2 位", 2))
    result = _handle(service, reset=True)
    assert result.slots["travelers"].state is SlotState.UNKNOWN
    assert result.slots["destination"].value == "成都"
    assert len(result.messages) == 2  # greeting + opening question only


def test_garbage_input_reasks_the_open_question() -> None:
    service = _service()
    _handle(service)
    _handle(service, option=_chip("2 位", 2))
    result = _handle(service, message="哈哈哈")
    assert result.slots["budget"].state is SlotState.UNKNOWN
    # the unclear text gets a hint, then the same question is re-asked
    assert "点选下方选项" in result.messages[-2].text
    assert result.messages[-1].kind == "CLARIFY"
    assert result.messages[-1].text.startswith("总预算")


# ── creation mode (Plan C) ──────────────────────────────────────────


def test_parse_date_text_variants() -> None:
    today = date(2026, 8, 29)
    assert _parse_date_text("2026-10-01", today=today) == "2026-10-01"
    assert _parse_date_text("2026年10月1日", today=today) == "2026-10-01"
    assert _parse_date_text("10月1日", today=today) == "2026-10-01"
    # a passed date rolls to next year
    assert _parse_date_text("1月1日", today=today) == "2027-01-01"
    assert _parse_date_text("下周三", today=today) is None


def test_creation_wizard_asks_destination_first() -> None:
    result = _create(_service())
    assert result.slots["destination"].state is SlotState.UNKNOWN
    assert result.messages[-1].text.startswith("想去哪个城市")


def test_creation_end_before_start_is_rejected() -> None:
    service = _service()
    _create(service)
    _create(service, message="成都")
    _create(service, option=_confirm())
    _create(service, message="2026-10-04")
    _create(service, option=_confirm())
    result = _create(service, message="2026-10-01")
    assert result.slots["end_date"].state is SlotState.UNKNOWN
    # the rejection is followed by a re-ask of the same question
    assert "结束日期要晚于开始日期" in result.messages[-2].text
    assert result.messages[-1].text.startswith("行程哪天结束")


def test_creation_full_flow_reaches_ready_with_projection() -> None:
    service = _service()
    _create(service)
    _create(service, message="成都")
    _create(service, option=_confirm())
    _create(service, message="2026-10-01到2026-10-04")
    _create(service, option=_confirm())
    _create(service, option=_confirm())
    _create(service, option=_chip("2 位", 2))
    _create(service, option=_chip("3000-8000", 5500))
    _create(service, option=_ask("accommodation"))
    _create(service, message="春熙路附近")
    _create(service, option=_confirm())
    result = _create(service, option=_skip_t1())
    assert result.ready is True
    assert result.phase == "READY"
    projection = _confirmed(service)
    assert projection.ready is True
    assert projection.confirmed["destination"] == "成都"
    assert projection.confirmed["start_date"] == "2026-10-01"
    assert projection.confirmed["end_date"] == "2026-10-04"
    assert projection.confirmed["travelers"] == 2
    assert projection.confirmed["budget"] == 5500
    assert projection.confirmed["accommodation"] == "春熙路附近"


def test_creation_projection_not_ready_until_dates_confirmed() -> None:
    service = _service()
    _create(service)
    _create(service, message="成都")
    _create(service, option=_confirm())
    projection = _confirmed(service)
    assert projection.ready is False
    assert projection.confirmed["destination"] == "成都"
    assert "start_date" not in projection.confirmed


# ── transcript-driven fixes ─────────────────────────────────────────


def test_destination_spoken_wrapper_is_cleaned() -> None:
    service = _service()
    _create(service)
    result = _create(service, message="去北京")
    assert result.slots["destination"].value == "北京"  # not "去北京"
    confirmed = _create(service, option=_confirm())
    assert confirmed.slots["destination"].value == "北京"
    assert confirmed.slots["destination"].state is SlotState.CONFIRMED


def test_date_range_fills_both_ends_in_one_turn() -> None:
    service = _service()
    _create(service)
    _create(service, message="成都")
    _create(service, option=_confirm())
    result = _create(service, message="2026-09-01到2026-09-03")
    assert result.slots["start_date"].value == "2026-09-01"
    assert result.slots["start_date"].state is SlotState.INFERRED
    assert result.slots["end_date"].value == "2026-09-03"
    assert result.slots["end_date"].state is SlotState.INFERRED
    # confirm cards chain: start first, then end
    _create(service, option=_confirm())
    final = _create(service, option=_confirm())
    assert final.slots["start_date"].state is SlotState.CONFIRMED
    assert final.slots["end_date"].state is SlotState.CONFIRMED


def test_post_ready_place_text_adds_must_visit_and_skip_restores() -> None:
    service = _service()
    ready = _trip_ready_flow(service)
    assert ready.ready is True

    added = _handle(service, message="故宫")
    assert added.slots["must_visit"].value == ["大熊猫基地", "故宫"]
    assert added.slots["must_visit"].state is SlotState.INFERRED
    # skipping the addition keeps the previously confirmed list
    restored = _handle(service, option=CardOption(action="SKIP", label="不用管这个"))
    assert restored.slots["must_visit"].value == ["大熊猫基地"]
    assert restored.slots["must_visit"].state is SlotState.CONFIRMED


def test_post_ready_budget_text_proposes_new_value() -> None:
    service = _service()
    _trip_ready_flow(service)
    result = _handle(service, message="预算改成12000")
    assert result.slots["budget"].value == 12000
    assert result.slots["budget"].state is SlotState.INFERRED


def test_post_ready_accommodation_and_anchor_routing() -> None:
    service = _service()
    _trip_ready_flow(service)
    stay = _handle(service, message="住春熙路附近")
    assert stay.slots["accommodation"].value == "春熙路附近"
    assert stay.slots["accommodation"].state is SlotState.INFERRED
    _handle(service, option=_confirm())
    anchored = _handle(service, message="14点到成都东站")
    assert anchored.slots["arrival"].value == {"place": "成都东站", "time": "14:00"}
    assert anchored.slots["arrival"].state is SlotState.INFERRED


def test_stale_option_click_replies_with_progress() -> None:
    service = _service()
    _trip_ready_flow(service)
    stale = _handle(service, option=_confirm())
    assert stale.messages[-1].text.startswith("这一步已经完成啦")
    assert "当前约束" in stale.messages[-1].text


def test_trip_mode_dates_are_locked_against_post_ready_changes() -> None:
    service = _service()
    _trip_ready_flow(service)
    result = _handle(service, message="改成10月5日到10月8日")
    # trip facts are Java-owned: the date proposal must be ignored
    assert result.slots["start_date"].value == "2026-10-01"
    assert result.slots["start_date"].source is SlotSource.TRIP
    assert result.slots["start_date"].state is SlotState.CONFIRMED


# ── grounding: place slots verify through the search tool ──────────

AIRPORT = {
    "name": "北京大兴国际机场",
    "city": "北京市",
    "district": "大兴区",
    "address": "北京市大兴区",
}


def test_confirm_grounds_place_to_canonical_name() -> None:
    service = _service(places=_places_with({"大兴机场": [AIRPORT]}))
    _create(service)
    _create(service, message="北京")
    _create(service, option=_confirm())
    _create(service, message="2026-09-01到2026-09-03")
    _create(service, option=_confirm())
    _create(service, option=_confirm())
    _create(service, option=_chip("1 位", 1))
    _create(service, option=_chip("3000 以内", 2500))
    _create(service, option=_ask("arrival"))
    # colloquial input: time-of-day word + suffix time, still parsed & cleaned
    _create(service, message="早上到北京大兴机场07:00")
    proposed = _create(service, option=_confirm())
    view = proposed.slots["arrival"]
    assert view.value == {"place": "北京大兴国际机场", "time": "07:00"}
    assert view.state is SlotState.CONFIRMED
    assert view.ref is not None and view.ref["name"] == "北京大兴国际机场"
    assert any("已定位" in message.text for message in proposed.messages)


def test_confirm_miss_keeps_proposal_and_explains() -> None:
    service = _service(places=_places_with({}))  # nothing resolvable
    _create(service)
    _create(service, message="北京")
    _create(service, option=_confirm())
    _create(service, message="2026-09-01到2026-09-03")
    _create(service, option=_confirm())
    _create(service, option=_confirm())
    _create(service, option=_chip("1 位", 1))
    _create(service, option=_chip("3000 以内", 2500))
    _create(service, option=_ask("accommodation"))
    _create(service, message="春熙路附近")
    result = _create(service, option=_confirm())
    assert result.slots["accommodation"].state is SlotState.INFERRED  # not confirmed
    assert "没找到" in result.messages[-2].text
    assert "春熙路附近" in result.messages[-2].text
    # the user can still skip and continue — no dead end
    skipped = _create(service, option=CardOption(action="SKIP", label="不用管这个"))
    assert skipped.slots["accommodation"].state is SlotState.UNKNOWN


def test_ground_rejects_place_outside_destination() -> None:
    """Agent UX 3.0 反馈：跨城命中不得被确认——保定 POI 不是杭州的住宿。"""
    chunxi = {"name": "春熙路", "city": "成都市", "district": "锦江区", "address": "成都市锦江区"}
    service = _service(places=_places_with({"春熙路": [chunxi]}))
    _create(service)
    _create(service, message="北京")
    _create(service, option=_confirm())
    _create(service, message="2026-09-01到2026-09-03")
    _create(service, option=_confirm())
    _create(service, option=_confirm())
    _create(service, option=_chip("1 位", 1))
    _create(service, option=_chip("3000 以内", 2500))
    _create(service, option=_ask("accommodation"))
    _create(service, message="春熙路附近")
    result = _create(service, option=_confirm())
    # 提案保持待确认、槽位不落 CONFIRMED，并明确告知跨城不采用
    assert result.slots["accommodation"].state is not SlotState.CONFIRMED
    transcript = "".join(message.text for message in result.messages)
    assert "最接近的结果在成都市" in transcript
    assert "已定位：春熙路" not in transcript


def test_grounding_searches_within_the_extracted_city() -> None:
    """目的地槽位是整句话时，搜索城市必须取清洗后的城市名（杭州，非原句）。"""
    west_lake = {"name": "西湖", "city": "杭州市", "district": "西湖区", "address": "杭州市西湖区"}
    seen_cities: list[str] = []

    async def search(*, city: str, keyword: str, limit: int = 3) -> list[dict[str, str]]:
        seen_cities.append(city)
        if "西湖" in keyword:
            return [west_lake]
        return []

    service = _service(places=search)
    _create(service)
    _create(service, message="周末去杭州两天，两个人，轻松一点")
    _create(service, option=_confirm())
    _create(service, message="2026-10-01到2026-10-02")
    _create(service, option=_confirm())
    _create(service, option=_confirm())
    _create(service, message="2")
    _create(service, option=_confirm())
    _create(service, message="2500")
    _create(service, option=_confirm())
    _create(service, option=_ask("accommodation"))
    _create(service, message="西湖附近")
    result = _create(service, option=_confirm())

    assert "杭州" in seen_cities
    assert all(city != "周末去杭州" for city in seen_cities)
    assert result.slots["accommodation"].state is SlotState.CONFIRMED
    assert "已定位：西湖" in "".join(message.text for message in result.messages)


def test_city_from_destination_extracts_the_city_from_a_phrase() -> None:
    assert _city_from_destination("周末去杭州两天，两个人，轻松一点") == "杭州"
    assert _city_from_destination("国庆去成都四天") == "成都"
    assert _city_from_destination("三亚") == "三亚"
    assert _city_from_destination("") == ""


def test_reasked_question_is_not_duplicated_in_the_transcript() -> None:
    """Agent UX 3.0 反馈：未回答被重复追问时，同一问题只出现一次。"""
    service = _service()
    _create(service)
    _create(service, message="北京")
    _create(service, option=_confirm())
    _create(service, option=_confirm())  # 日期提问 → 确认填充
    _create(service, option=_confirm())
    _create(service, option=_chip("1 位", 1))
    _create(service, option=_chip("3000 以内", 2500))
    _create(service, option=_ask("accommodation"))
    _create(service, message="嗯……让我想想")  # 无法解析 → 重问
    result = _create(service, message="还没想好")  # 再触发一次重问
    ask_texts = [m.text for m in result.messages if m.role == "agent" and "住哪儿" in m.text]
    assert len(ask_texts) == 1, f"repeated question: {ask_texts}"


def test_must_visit_partial_grounding_keeps_unresolved_open() -> None:
    panda = {
        "name": "成都大熊猫繁育研究基地",
        "city": "成都市",
        "district": "成华区",
        "address": "成都市外北熊猫大道",
    }
    service = _service(places=_places_with({"大熊猫": [panda]}))
    _create(service)
    _create(service, message="成都")
    _create(service, option=_confirm())
    _create(service, message="2026-10-01到2026-10-04")
    _create(service, option=_confirm())
    _create(service, option=_confirm())
    _create(service, option=_chip("2 位", 2))
    _create(service, option=_chip("3000-8000", 5500))
    _create(service, option=_ask("must_visit"))
    _create(service, message="大熊猫基地、不存在的地方")
    result = _create(service, option=_confirm())
    assert result.slots["must_visit"].value == ["成都大熊猫繁育研究基地"]
    assert result.slots["must_visit"].state is SlotState.INFERRED  # unresolved keeps it open
    assert "没找到：不存在的地方" in result.messages[-2].text


def test_first_message_routes_to_destination_question() -> None:
    """A free-text first turn answers the opening question, never the
    post-ready heuristics (transcript regression: "北京" became a must-visit)."""
    service = _service()
    result = _create(service, message="北京")
    assert result.slots["destination"].state is SlotState.INFERRED
    assert result.slots["destination"].value == "北京"
    assert result.slots["must_visit"].state is SlotState.UNKNOWN
    confirmed = _create(service, option=_confirm())
    assert confirmed.slots["destination"].state is SlotState.CONFIRMED



def test_creation_rich_first_message_scans_all_slots() -> None:
    """No-LLM runtime: a rich first message fills every slot it clearly
    states via the deterministic scan, instead of dead-ending on 没太看懂."""
    service = _service()
    result = _create(
        service,
        message="想去成都玩，预算5000，2个人，10月1日到10月3日",
    )
    for name in ("destination", "start_date", "end_date", "travelers", "budget"):
        assert result.slots[name].state is SlotState.INFERRED, name
    assert result.slots["destination"].value == "成都"
    assert result.slots["budget"].value == 5000
    assert result.slots["travelers"].value == 2
    assert result.slots["start_date"].value == "2026-10-01"
    assert result.slots["end_date"].value == "2026-10-03"
    assert any("我从你的描述里注意到" in message.text for message in result.messages)
    confirmed = _create(service, option=_confirm())
    assert confirmed.slots["destination"].state is SlotState.CONFIRMED


def test_creation_unclear_first_message_still_falls_back_to_wizard() -> None:
    """Text the direct parse rejects and the scan cannot match: the wizard
    re-asks as before."""
    service = _service()
    result = _create(service, message="嗯嗯好的111")
    assert result.slots["destination"].state is SlotState.UNKNOWN
    assert any("没太看懂" in message.text for message in result.messages)


def test_scan_respects_trip_locked_facts() -> None:
    """Trip mode: destination/dates are Java-owned facts — the scan only
    proposes what the dialog manages (travelers/budget)."""
    service = _service()
    result = _handle(
        service,
        message="想去重庆玩，预算6000，3个人，11月1日到11月3日",
    )
    assert result.slots["destination"].value == "成都"          # TRIP fact untouched
    assert result.slots["destination"].source is SlotSource.TRIP
    assert result.slots["travelers"].value == 3
    assert result.slots["travelers"].state is SlotState.INFERRED
    assert result.slots["budget"].value == 6000
    assert result.slots["start_date"].value == "2026-10-01"    # TRIP fact untouched
