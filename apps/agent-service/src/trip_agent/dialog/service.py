"""Agent-driven dialog (Plan C): one thin service over the single agent loop.

P3-T2 convergence: the creation dialog is NO LONGER a second slot wizard.  It
reuses the very same LangGraph ``AgentLoop``, ``AgentState`` and
``ConstraintSlots`` that the trip-mode ``agent_processor`` uses, with a single
deterministic creation decider and the ``update_constraints``/``ask_user``
tools.  ``ConstraintSlots`` is the one constraint state source; the wizard's
``_DialogState``/``SlotView``/``SlotSpecs`` state machine is retired here.

Wire contract is unchanged: ``/internal/v1/agent/dialogue`` still reads
``DialogueRequest`` and answers ``DialogueResponse``; the confirmed-slot
projection still answers ``ConfirmedSlotsResponse`` with TripConstraints
field names (``budget``, not ``budget_amount``).
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import date, datetime
from typing import Any, Final

from trip_agent.agent.graph import AgentLoop, AskingDecider, Decision, run_agent
from trip_agent.agent.state import (
    AgentState,
    ConstraintSlots,
    SlotState,
    agent_state_from_dict,
    agent_state_to_dict,
    to_constraint_patch,
    to_trip_fields,
)
from trip_agent.agent.tools import ToolCall, ToolRegistry, ToolRuntime
from trip_agent.dialog.models import (
    AgentMessage,
    CardOption,
    ConfirmedSlotsResponse,
    DialogueRequest,
    DialogueResponse,
    SlotSource,
    SlotView,
)
from trip_agent.domain.shared import normalize_trip_date

logger = logging.getLogger(__name__)

PACE_LABELS: Final[dict[str, str]] = {
    "RELAXED": "轻松悠闲",
    "BALANCED": "劳逸结合",
    "INTENSIVE": "尽量多玩",
}
PACE_ALIASES: Final[dict[str, str]] = {
    "轻松": "RELAXED", "悠闲": "RELAXED", "慢": "RELAXED",
    "均衡": "BALANCED", "适中": "BALANCED", "正常": "BALANCED",
    "紧凑": "INTENSIVE", "多玩": "INTENSIVE", "赶": "INTENSIVE",
}

SLOT_LABELS: Final[dict[str, str]] = {
    "destination": "目的地",
    "start_date": "开始日期",
    "end_date": "结束日期",
    "travelers": "出行人数",
    "budget": "总预算",
    "pace": "节奏",
    "accommodation": "住宿锚点",
    "arrival": "到达",
    "departure": "离开",
    "must_visit": "必去地点",
    "avoid": "避开地点",
    "preferences": "偏好标签",
    "mobility": "无障碍",
}

MOBILITY_LABELS: Final[dict[str, str]] = {
    "STANDARD": "标准",
    "REDUCED": "减少步行",
    "STEP_FREE": "无台阶",
}

# 出行设置（人数/预算）：创建模式由 Composer 右下组件 + 自由文本提供；与
# destination/start_date/end_date 同为创建模式的必填门槛。
CREATION_EXTERNAL_SLOTS: Final = ("travelers", "budget")

# 创建模式 decider 收集的槽位（destination/dates + 人数/预算）。
CREATION_SLOTS: Final = ("destination", "start_date", "end_date", "travelers", "budget")
# trip 面板（历史退化路径，规划调整走 AMQP agent）只收集三个必填槽位。
TRIP_SLOTS: Final = ("destination", "start_date", "end_date")

_CREATION_QUESTION: Final[dict[str, str]] = {
    "destination": "想去哪个城市？",
    "start_date": "行程从哪天开始？",
    "end_date": "行程到哪天结束？",
    "travelers": "这次出行几位？",
    "budget": "总预算大概多少（人民币元）？",
}

_CHINESE_DIGITS: Final[dict[str, int]] = {
    "一": 1, "两": 2, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

_INVALID = object()

_DESTINATION_LEADS: Final = (
    "我想", "我们要", "我们", "想要", "准备", "打算", "计划",
    "要去", "想", "去", "前往", "去往", "到", "住在", "入住", "住",
)
_DESTINATION_TAILS: Final = ("之旅", "吧", "呀", "哦", "呢", "啦", "哈")

_CITY_LEAD_RE = re.compile(
    r"^(?:周末|假期|长假|小长假|黄金周|国庆|春节|五一|十一|端午|中秋|元旦)*"
    r"(?:我想去|我想玩|想要去|准备去|打算去|计划去|想去|要去|希望去|去|前往|去往|到|玩)"
)
_CITY_TAIL_RE = re.compile(
    r"(?:两|二|三|四|五|六|七|八|九|十|\d+)\s*天$|(?:玩|游玩|旅游|旅行)$"
)

_DESTINATION_IN_TEXT: Final = re.compile(
    r"(?:想去|就去|去|前往|到)([\u4e00-\u9fa5]{2,8}?)(?:玩|旅游|旅行|，|,|。|！|\s|$)"
)
_TRAVELERS_IN_TEXT: Final = re.compile(
    r"(\d{1,2})\s*个?人|(\d{1,2})\s*位|([一两二三四五六七八九十])\s*个?人"
)
_BUDGET_IN_TEXT: Final = re.compile(r"预算[^\d]{0,3}([0-9][0-9,]{2,})|([0-9]{3,7})\s*元")


def _check_value(slot: str, value: Any) -> Any:
    """Validate a candidate value; return the normalized value or _INVALID."""
    if slot == "destination":
        if not isinstance(value, str):
            return _INVALID
        cleaned = _clean_destination(value)
        if re.search(r"\d", cleaned) or re.search(r"[，,。；;、]", cleaned):
            # 城市名不含数字与分隔符——含有多槽内容的整句话必须走扫描
            return _INVALID
        city = _city_from_destination(cleaned)
        if re.search(r"\d", city):
            return _INVALID
        return city if 2 <= len(city) <= 20 else _INVALID
    if slot in ("start_date", "end_date"):
        return _norm_date(value)
    if slot == "travelers":
        if isinstance(value, bool) or not isinstance(value, int):
            return _INVALID
        return value if 1 <= value <= 20 else _INVALID
    if slot == "budget":
        if isinstance(value, bool) or not isinstance(value, int):
            return _INVALID
        return value if 100 <= value <= 1_000_000 else _INVALID
    if slot == "pace":
        return value if value in PACE_LABELS else _INVALID
    if slot == "accommodation":
        if not isinstance(value, str):
            return _INVALID
        cleaned = _clean_destination(value)
        return cleaned if 2 <= len(cleaned) <= 30 else _INVALID
    if slot in ("arrival", "departure"):
        anchor = _norm_anchor(value)
        return anchor if anchor is not None else _INVALID
    if slot == "mobility":
        return value if value in ("STANDARD", "REDUCED", "STEP_FREE") else _INVALID
    if slot == "preferences":
        items = [text.strip() for text in value] if isinstance(value, list) else []
        if not items or len(items) > 8 or any(not 1 <= len(item) <= 12 for item in items):
            return _INVALID
        return items
    if slot in ("must_visit", "avoid"):
        items = [text.strip() for text in value] if isinstance(value, list) else []
        if not items or len(items) > 8 or any(not 1 <= len(item) <= 20 for item in items):
            return _INVALID
        return items
    return _INVALID


def _norm_anchor(value: Any) -> dict[str, str] | None:
    """Normalize {"place", "time"} anchors; time must be a real HH:MM."""
    if not isinstance(value, dict):
        return None
    place = value.get("place")
    anchor_time = value.get("time")
    if not isinstance(place, str) or not isinstance(anchor_time, str):
        return None
    place = place.strip()
    if not 2 <= len(place) <= 30:
        return None
    if not re.fullmatch(r"\d{1,2}:\d{2}", anchor_time.strip()):
        return None
    hour, minute = (int(part) for part in anchor_time.strip().split(":"))
    if hour > 23 or minute > 59:
        return None
    return {"place": place, "time": f"{hour:02d}:{minute:02d}"}


def _norm_date(value: Any) -> str | None:
    """Normalize ISO strings / datetime.date into an ISO date string."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()).isoformat()
        except ValueError:
            return None
    return None


def _parse_date_text(text: str, *, today: date) -> str | None:
    """Parse human date input (2026-10-01 / 2026年10月1日 / 10月1日) to ISO."""
    parsed = normalize_trip_date(text, today=today)
    return parsed.isoformat() if parsed is not None else None


def _parse_date_range(text: str, *, today: date) -> tuple[str, str] | None:
    """Parse a spoken date range ("9月1日到9月3日", "A~B", "ISO-ISO")."""
    paired = re.search(
        r"(\d{4}-\d{2}-\d{2})\s*[-到至~～]\s*(\d{4}-\d{2}-\d{2})", text,
    )
    if paired:
        start, end = paired.group(1), paired.group(2)
        if start < end:
            return start, end
    for separator in ("到", "至", "~", "～", "—", "–"):
        if separator in text:
            left, _, right = text.partition(separator)
            start = _parse_date_text(left, today=today)
            end = _parse_date_text(right, today=today)
            if start and end and start < end:
                return start, end
    return None


def _clean_destination(text: str) -> str:
    """Strip spoken wrappers ("去北京" → "北京", "我想去成都吧" → "成都")."""
    value = text.strip()
    changed = True
    while changed and value:
        changed = False
        for lead in _DESTINATION_LEADS:
            if value.startswith(lead) and len(value) - len(lead) >= 2:
                value = value[len(lead):]
                changed = True
        for tail in _DESTINATION_TAILS:
            if value.endswith(tail) and len(value) - len(tail) >= 2:
                value = value[: -len(tail)]
                changed = True
    return value.strip()


def _city_from_destination(value: str) -> str:
    """Extract the actual city name from a spoken destination phrase."""
    for segment in re.split(r"[，,。；;、\s]+", value or ""):
        token = _CITY_TAIL_RE.sub("", _CITY_LEAD_RE.sub("", segment.strip()))
        token = _clean_destination(token)
        if 2 <= len(token) <= 5 and not re.search(r"\d", token):
            return token
    return _clean_destination(value or "")


def _render(slot: str, value: Any) -> str:
    if slot == "budget":
        return f"{value:,} 元"
    if slot == "travelers":
        return f"{value} 位"
    if slot == "pace":
        return PACE_LABELS.get(str(value), str(value))
    if slot == "mobility":
        return MOBILITY_LABELS.get(str(value), str(value))
    if isinstance(value, list):
        return "、".join(str(item) for item in value)
    return str(value)


def _scan_free_text(text: str) -> dict[str, Any]:
    """Deterministic multi-slot scan: only well-formed phrasings are noticed."""
    found: dict[str, Any] = {}
    matched = _DESTINATION_IN_TEXT.search(text)
    if matched:
        checked = _check_value("destination", matched.group(1))
        if checked is not _INVALID:
            found["destination"] = checked
    rng = _parse_date_range(text, today=date.today())
    if rng:
        found["start_date"], found["end_date"] = rng
    people = _TRAVELERS_IN_TEXT.search(text)
    if people:
        digits = people.group(1) or people.group(2)
        value = int(digits) if digits else _CHINESE_DIGITS.get(people.group(3))
        checked = _check_value("travelers", value)
        if checked is not _INVALID:
            found["travelers"] = checked
    budget = _BUDGET_IN_TEXT.search(text)
    if budget:
        raw = (budget.group(1) or budget.group(2) or "").replace(",", "")
        checked = _check_value("budget", int(raw)) if raw else _INVALID
        if checked is not _INVALID:
            found["budget"] = checked

    for alias, value in PACE_ALIASES.items():
        if alias in text:
            checked = _check_value("pace", value)
            if checked is not _INVALID:
                found["pace"] = checked
                break
    preference_keywords = [
        "美食", "历史", "文化", "自然", "风景", "城市", "购物",
        "摄影", "亲子", "休闲", "遗迹", "古迹", "博物馆",
        "艺术", "建筑", "公园", "海滩", "夜景", "温泉",
    ]
    matched_prefs = [kw for kw in preference_keywords if kw in text]
    if matched_prefs:
        found["preferences"] = matched_prefs
    return found


def _create_slot_values(message: str, slots: ConstraintSlots) -> dict[str, Any]:
    """Extract candidate values from a creation-mode message.

    Reuses the deterministic scan, then adds bare-value handling for the
    creation grammar (a bare city name, a bare party size, a bare budget).
    Only verbatim user words are ever proposed — nothing is invented.
    """
    found = dict(_scan_free_text(message))
    text = message.strip()
    if (
        "destination" not in found
        and not slots.get("destination").hard
        and re.fullmatch(r"[\u4e00-\u9fa5]{2,8}", text)
    ):
        checked = _check_value("destination", text)
        if checked is not _INVALID:
            found["destination"] = checked
    if "travelers" not in found and re.fullmatch(r"\d{1,2}", text):
        checked = _check_value("travelers", int(text))
        if checked is not _INVALID:
            found["travelers"] = checked
    if "budget" not in found and re.fullmatch(r"\d{3,7}", text):
        checked = _check_value("budget", int(text))
        if checked is not _INVALID:
            found["budget"] = checked
    return found


def _slots_for_scope(scope_key: str) -> tuple[str, ...]:
    return CREATION_SLOTS if scope_key.startswith("create:") else TRIP_SLOTS


def _seed_slots(slots: ConstraintSlots, context: Any) -> ConstraintSlots:
    """Seed TripContext facts as CONFIRMED at the appropriate provenance.

    destination/dates are TRIP-owned facts; travelers/budget arrive explicitly
    from the Composer (user-explicit).  Only non-None values are seeded.
    """
    if context is None:
        return slots
    for name, value, verified_by in (
        ("destination", getattr(context, "destination", None) or None, "trip"),
        ("start_date", getattr(context, "start_date", None) or None, "trip"),
        ("end_date", getattr(context, "end_date", None) or None, "trip"),
    ):
        if value:
            slots = slots.fill(name, value, state=SlotState.CONFIRMED, verified_by=verified_by)
    for name, value, verified_by in (
        ("travelers", getattr(context, "travelers", None), "user-explicit"),
        ("budget", getattr(context, "budget_amount", None), "user-explicit"),
    ):
        if value is not None:
            slots = slots.fill(name, value, state=SlotState.CONFIRMED, verified_by=verified_by)
    return slots


def _sync_context(state: AgentState, context: Any) -> AgentState:
    """Keep the Composer's travelers/budget authoritative when not already set."""
    if context is None:
        return state
    slots = state.slots
    for name, value, verified_by in (
        ("travelers", getattr(context, "travelers", None), "user-explicit"),
        ("budget", getattr(context, "budget_amount", None), "user-explicit"),
    ):
        if value is not None and not slots.get(name).hard:
            slots = slots.fill(name, value, state=SlotState.CONFIRMED, verified_by=verified_by)
    return replace(state, slots=slots)


def _slot_source(slot: Any) -> SlotSource:
    """Map a ConstraintSlot's provenance onto the wire SlotSource enum."""
    if slot.verified_by == "trip":
        return SlotSource.TRIP
    if slot.verified_by == "user-explicit":
        return SlotSource.USER_EXPLICIT
    if slot.state is SlotState.INFERRED:
        return SlotSource.LLM_INFERRED if slot.verified_by == "llm" else SlotSource.USER_EXPLICIT
    return SlotSource.USER_CONFIRMED


def _to_slot_views(slots: ConstraintSlots) -> dict[str, SlotView]:
    return {
        name: SlotView(value=slot.value, state=slot.state, source=_slot_source(slot))
        for name, slot in slots.slots.items()
    }


def _summary_text(slots: ConstraintSlots) -> str:
    parts = []
    for name in slots.slots:
        slot = slots.get(name)
        if slot is not None and slot.hard and slot.value is not None:
            parts.append(f"{SLOT_LABELS.get(name, name)} {_render(name, slot.value)}")
    if not parts:
        return "约束已确认。"
    return "约束已确认：" + "；".join(parts) + "。"


def _progress_text(slots: ConstraintSlots) -> str:
    parts = []
    for name in slots.slots:
        slot = slots.get(name)
        if slot is not None and slot.hard and slot.value is not None:
            parts.append(f"{SLOT_LABELS.get(name, name)} {_render(name, slot.value)}")
    return f"当前约束：{'；'.join(parts)}。" if parts else "当前还没有已确认的约束。"


class CreationDecider(AskingDecider):
    """Creation-mode deterministic decider over the shared agent loop.

    Collects the creation slots (destination/dates + travelers/budget),
    proposes user words through ``update_constraints``, and never builds an
    itinerary — creation hands off to Java when the constraints are ready.
    """

    def __init__(self, *, collect_slots: tuple[str, ...] = CREATION_SLOTS) -> None:
        super().__init__()
        self._collect_slots = collect_slots

    async def decide(self, state: AgentState) -> Decision:
        missing = [name for name in self._collect_slots if not state.slots.get(name).hard]
        if not missing:
            return Decision(
                thought="all creation constraints are confirmed",
                answer="约束已收集完整，可以创建行程。",
                strategy="DIRECT",
            )
        message = (state.user_message or "").strip()
        if message:
            values = _create_slot_values(message, state.slots)
            fresh = {
                name: value
                for name, value in values.items()
                if not state.slots.get(name).hard
            }
            if fresh:
                return Decision(
                    thought="the user message answers pending constraints",
                    call=ToolCall(
                        "update_constraints", {"values": fresh, "evidence": message}
                    ),
                    strategy="DIRECT",
                )
            pending = self._pending_question_slot(state)
            if pending:
                return Decision(
                    thought="the answer was not recognizable; ask once more",
                    call=ToolCall(
                        "ask_user",
                        {
                            "question": (
                                f"没太理解「{message}」——"
                                f"{_CREATION_QUESTION.get(pending, pending)}"
                            )
                        },
                    ),
                    strategy="CLARIFY",
                )
        name = missing[0]
        return Decision(
            thought=f"required slot '{name}' is not confirmed yet",
            call=ToolCall(
                "ask_user", {"question": _CREATION_QUESTION.get(name, f"请补充约束：{name}")}
            ),
            strategy="CLARIFY",
        )


def _default_loop(*, collect_slots: tuple[str, ...]) -> AgentLoop:
    """The dialog loop: creation decider over capability-free tools.

    ``update_constraints``/``ask_user`` need no provider; the build/validate
    tools are absent and never reachable in creation mode.
    """
    return AgentLoop(
        decider=CreationDecider(collect_slots=collect_slots),
        tools=ToolRegistry.with_runtime(ToolRuntime()),
    )


def _confirm_start(scope_key: str) -> bool:
    return scope_key.startswith("create:")


class AgentDialogService:
    """One bounded agent turn per dialogue request, persisted by scope.

    ``scope_key`` is ``create:{sessionId}`` for agent-driven creation (the
    supported path) or ``trip:{id}`` for the legacy trip panel.  The checkpoint
    stored under the scope key is an ``AgentState`` (``ConstraintSlots``
    included) — the single constraint state source shared with trip mode.
    """

    def __init__(
        self,
        *,
        store: Any,
        loop: AgentLoop | None = None,
    ) -> None:
        self._store = store
        self._loop = loop

    async def handle(
        self,
        scope_key: str,
        context: Any,
        request: DialogueRequest,
    ) -> DialogueResponse:
        raw = None if request.reset else await self._store.load(scope_key)
        if raw is None or request.reset:
            state = AgentState(slots=_seed_slots(ConstraintSlots.empty(), context))
        else:
            state = agent_state_from_dict(raw)
            state = _sync_context(state, context)

        collect = _slots_for_scope(scope_key)
        require_external = _confirm_start(scope_key)

        # START_PLANNING is a chat-level confirmation the frontend intercepts —
        # the server just acknowledges and stays ready.
        if (
            request.option is not None
            and request.option.action == "CONFIRM"
            and request.option.value == "START_PLANNING"
        ):
            await self._store.save(scope_key, agent_state_to_dict(state))
            messages = [
                AgentMessage(role="user", text="[点选] 开始规划", kind="TEXT"),
                AgentMessage(role="agent", text="好的，开始创建行程！", kind="TEXT"),
            ]
            return DialogueResponse(
                phase="READY",
                ready=self._is_ready(state, require_external=require_external),
                messages=messages,
                slots=_to_slot_views(state.slots),
            )

        input_text: str | None = None
        if request.option is not None:
            input_text = _option_to_message(request.option)
        elif request.message and request.message.strip():
            input_text = request.message.strip()

        resumed = replace(
            state,
            user_message=input_text,
            pending_question=None,
            pending_options=None,
            pending_expected_type=None,
            pending_call=None,
            stop_reason=None,
            answer=None,
            steps=0,
            turn_baseline_observations=len(state.observations),
        )
        loop = self._loop or _default_loop(collect_slots=collect)
        holder: dict[str, AgentState] = {}

        async def sink(current: AgentState) -> None:
            holder["state"] = current

        await run_agent(loop, resumed, checkpoint_sink=sink)
        final = holder.get("state", resumed)
        await self._store.save(scope_key, agent_state_to_dict(final))

        ready = self._is_ready(final, require_external=require_external)
        return DialogueResponse(
            phase="READY" if ready else "COLLECTING",
            ready=ready,
            messages=self._build_messages(request, final, ready),
            slots=_to_slot_views(final.slots),
        )

    def _is_ready(self, state: AgentState, *, require_external: bool) -> bool:
        if state.pending_question is not None:
            return False
        if any(slot.state is SlotState.INFERRED for slot in state.slots.slots.values()):
            return False
        if state.slots.missing_required():
            return False
        if require_external:
            return all(state.slots.get(name).hard for name in CREATION_EXTERNAL_SLOTS)
        return True

    def _build_messages(
        self,
        request: DialogueRequest,
        state: AgentState,
        ready: bool,
    ) -> list[AgentMessage]:
        messages: list[AgentMessage] = []
        if request.option is not None:
            messages.append(
                AgentMessage(role="user", text=f"[点选] {request.option.label}", kind="TEXT")
            )
        elif request.message and request.message.strip():
            messages.append(
                AgentMessage(role="user", text=request.message.strip(), kind="TEXT")
            )

        inferred = [
            name for name, slot in state.slots.slots.items()
            if slot.state is SlotState.INFERRED and slot.value is not None
        ]
        if not ready and state.pending_question is None and inferred:
            parts = [f"{SLOT_LABELS.get(name, name)} {_render(name, state.slots.get(name).value)}"
                     for name in inferred]
            messages.append(
                AgentMessage(
                    role="agent",
                    text="我从你的描述里注意到：" + "；".join(parts) + "。逐项和你确认一下。",
                    kind="CLARIFY",
                )
            )

        if ready:
            messages.append(
                AgentMessage(role="agent", text=_summary_text(state.slots), kind="SUMMARY")
            )
            messages.append(
                AgentMessage(
                    role="agent",
                    text="所有信息已确认，是否开始规划行程？",
                    kind="CLARIFY",
                    options=[
                        CardOption(action="CONFIRM", label="开始规划", value="START_PLANNING"),
                        CardOption(action="SKIP", label="再补充一下"),
                    ],
                )
            )
        elif state.pending_question:
            options = [
                CardOption(action="SET", label=opt, value=opt)
                for opt in (state.pending_options or ())
            ]
            messages.append(
                AgentMessage(
                    role="agent", text=state.pending_question, kind="CLARIFY", options=options
                )
            )
        elif state.answer:
            messages.append(AgentMessage(role="agent", text=state.answer, kind="TEXT"))
        else:
            messages.append(
                AgentMessage(role="agent", text=_progress_text(state.slots), kind="TEXT")
            )
        return messages

    async def confirmed_creation(self, scope_key: str) -> ConfirmedSlotsResponse:
        """Confirmed-slot projection for agent-driven trip creation.

        Exposes trip-level fields plus TripConstraints fields (budget keyed as
        ``budget`` to match Java's TripAgentCreateController).
        """
        raw = await self._store.load(scope_key)
        if raw is None:
            raise KeyError(scope_key)
        state = agent_state_from_dict(raw)
        slots = state.slots
        confirmed: dict[str, Any] = {}
        confirmed.update(to_trip_fields(slots))
        confirmed.update(
            {
                ("budget" if key == "budget_amount" else key): value
                for key, value in to_constraint_patch(slots).items()
            }
        )
        ready = self._is_ready(state, require_external=True)
        return ConfirmedSlotsResponse(ready=ready, confirmed=confirmed)


def _option_to_message(option: CardOption) -> str:
    """Translate a chip (SET) option into a canonical user message.

    The agent confirms via evidence-match, so the value must appear verbatim:
    a party count becomes "N 位", a budget amount "预算 N 元".
    """
    if isinstance(option.value, bool) or option.value is None:
        return (option.label or "").strip()
    if isinstance(option.value, int):
        if 1 <= option.value <= 20:
            return f"{option.value} 位"
        return f"预算 {option.value} 元"
    value = str(option.value).strip()
    return value or (option.label or "").strip()