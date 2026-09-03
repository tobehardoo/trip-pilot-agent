"""The understand → confirm → ready loop, deterministic by default.

Fail-closed rules (design §1.3/§3.2, applied to the dialog slice):

- An LLM (or free-text) value is only ever an INFERRED proposal; it becomes
  CONFIRMED solely through an explicit user option click.
- Wizard chips are explicit user selections → CONFIRMED immediately.
- Trip facts (destination/dates) are seeded CONFIRMED with source=TRIP and
  are never editable here — Java owns those facts.
- Every run converges: unknown input degrades to the wizard, model failures
  degrade to the wizard, and the loop is bounded by the fixed slot set.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, Field

from trip_agent.agent.state import SlotState
from trip_agent.dialog.extractor import SlotExtractor
from trip_agent.dialog.models import (
    AgentMessage,
    CardOption,
    ConfirmedSlotsResponse,
    DialogueRequest,
    DialogueResponse,
    SlotSource,
    SlotView,
    TripContext,
)
from trip_agent.domain.shared import normalize_trip_date

logger = logging.getLogger(__name__)

MAX_MESSAGES: Final = 60

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

# extraction field names (TripConstraints-aligned) → dialog slot names
EXTRACTION_SLOT_ALIASES: Final[dict[str, str]] = {"budget_amount": "budget"}

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


@dataclass(frozen=True)
class SlotSpec:
    """Declarative slot definition — adding a constraint = adding a row."""

    name: str
    label: str
    question: str
    tier: int                                  # 0 required · 1 high-value · 2 optional
    options: tuple[tuple[str, Any], ...] = ()  # chip choices (label, value)
    allow_skip: bool = False
    note: str = ""                             # planner impact when missing
    ground: bool = False                       # place slot: verify via search tool on confirm



SLOT_SPECS: Final = (
    SlotSpec("destination", "目的地", "想去哪个城市？直接输入城市名。", 0),
    SlotSpec(
        "start_date", "开始日期",
        "行程哪天开始？如 2026-10-01 或 10月1日；也可以直接给区间，如 10月1日到10月4日。", 0,
    ),
    SlotSpec("end_date", "结束日期", "行程哪天结束？", 0),
    SlotSpec(
        "travelers", "出行人数", "这次出行几位？点选或直接输入数字。", 0,
        options=(("1 位", 1), ("2 位", 2), ("3 位", 3),
                 ("4 位", 4), ("5 位", 5), ("6 位及以上", 6)),
    ),
    SlotSpec(
        "budget", "总预算", "总预算大概多少（人民币元）？点选或直接输入数字。", 0,
        options=(
            ("3000 以内", 2500), ("3000-8000", 5500),
            ("8000-15000", 11500), ("15000 以上", 20000),
        ),
    ),
    SlotSpec(
        "pace", "节奏", "行程节奏偏好？", 1,
        options=(("轻松悠闲", "RELAXED"), ("劳逸结合", "BALANCED"), ("尽量多玩", "INTENSIVE")),
    ),
    SlotSpec(
        "accommodation", "住宿锚点", "住哪儿？直接说酒店名或大概区域（如“春熙路附近”）。", 1,
        allow_skip=True, note="没有住宿锚点，每天路线将从市中心出发", ground=True,
    ),
    SlotSpec(
        "arrival", "到达", "第一天几点到哪儿？如“14点到成都东站”。", 1,
        allow_skip=True, note="缺到达信息时，第一天的安排可能不准", ground=True,
    ),
    SlotSpec(
        "departure", "离开", "最后一天几点从哪儿走？如“18点从双流机场”。", 1,
        allow_skip=True, note="缺离开信息时，最后一天的安排可能不准", ground=True,
    ),
    SlotSpec(
        "must_visit", "必去地点", "有必去的地方吗？直接输入地名（多个用顿号分隔）。", 1,
        allow_skip=True, ground=True,
    ),
    SlotSpec("avoid", "避开地点", "有想避开的地方或类型吗？直接输入。", 2, allow_skip=True),
    SlotSpec(
        "preferences", "偏好标签", "有特别偏好吗？如“亲子、美食、夜景”。", 2, allow_skip=True,
    ),
    SlotSpec(
        "mobility", "无障碍", "有无障碍需求吗？", 2,
        options=(("标准", "STANDARD"), ("减少步行", "REDUCED"), ("无台阶", "STEP_FREE")),
        allow_skip=True,
    ),
)
SLOT_SPECS_BY_NAME: Final[dict[str, SlotSpec]] = {spec.name: spec for spec in SLOT_SPECS}

# Full wizard order.  Trip-mode pre-confirms destination/dates from Java so
# those slots are skipped there; creation mode asks them first.  Tier-1 slots
# are offered as a suggestion card instead of an interrogation; tier-2 slots
# are never auto-asked.
SLOT_ORDER: Final = tuple(spec.name for spec in SLOT_SPECS)
TIER0_SLOTS: Final = tuple(s.name for s in SLOT_SPECS if s.tier == 0)
TIER1_SLOTS: Final = tuple(s.name for s in SLOT_SPECS if s.tier == 1)
MANAGED_SLOTS: Final = SLOT_ORDER
REQUIRED_FOR_CREATION: Final = ("destination", "start_date", "end_date")
# 出行设置（人数/预算）改由 Composer 右下组件 + 自由文本提供，不再由 wizard 表单强问；
# 但创建行程仍要求其已确认（与目的地/日期同级的「必填」门槛）。
EXTERNAL_SLOTS: Final = ("travelers", "budget")

_CHINESE_DIGITS: Final[dict[str, int]] = {
    "一": 1, "两": 2, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

_INVALID = object()


class _Pending(BaseModel):
    slot: str
    mode: Literal["confirm", "edit"] = "confirm"
    # previous confirmed value; restored when the user skips a proposal that
    # replaced one (e.g. an added must-visit keeps the old list on skip)
    restore_view: SlotView | None = None


class _DialogState(BaseModel):
    run_id: str
    messages: list[AgentMessage] = Field(default_factory=list)
    slots: dict[str, SlotView] = Field(default_factory=dict)
    current_question: str | None = None
    asked: set[str] = Field(default_factory=set)
    pending: _Pending | None = None
    last_summary: str | None = None


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


def _parse_anchor_text(text: str) -> dict[str, str] | None:
    """Parse "14点到成都东站" / "晚上8点从双流机场" into an anchor."""
    matched = re.search(r"(\d{1,2})[:：点](\d{1,2})?分?", text)
    if not matched:
        return None
    hour = int(matched.group(1))
    minute = int(matched.group(2)) if matched.group(2) else 0
    if re.search(r"下午|傍晚|晚上", text[: matched.start() + 2]) and hour < 12:
        hour += 12
    if hour > 23 or minute > 59:
        return None
    place = (text[: matched.start()] + text[matched.end():]).strip()
    for word in ("凌晨", "清晨", "早上", "上午", "中午", "下午", "傍晚", "晚上", "半夜"):
        place = place.replace(word, "")
    place = place.strip()
    for lead in ("到达", "到", "从", "离开", "出发"):
        if place.startswith(lead) and len(place) - len(lead) >= 2:
            place = place[len(lead):]
            break
    for tail in _DESTINATION_TAILS:
        if place.endswith(tail) and len(place) - len(tail) >= 2:
            place = place[: -len(tail)]
            break
    place = place.strip()
    if not 2 <= len(place) <= 30:
        return None
    return {"place": place, "time": f"{hour:02d}:{minute:02d}"}


def _norm_date(value: Any, *, today: date | None = None) -> str | None:
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
    """Parse human date input (2026-10-01 / 2026年10月1日 / 10月1日) to ISO.

    A bare ``M月D日`` is anchored to the current year, rolling to next year
    once the date has passed — matching how people talk about upcoming trips.
    Delegates to the shared ``domain.shared.normalize_trip_date``.
    """
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


_DESTINATION_LEADS: Final = (
    "我想", "我们要", "我们", "想要", "准备", "打算", "计划",
    "要去", "想", "去", "前往", "去往", "到", "住在", "入住", "住",
)
_DESTINATION_TAILS: Final = ("之旅", "吧", "呀", "哦", "呢", "啦", "哈")
_STOP_WORDS: Final = ("没有", "无", "不用", "跳过", "随便", "都行", "不知道")


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


_CITY_LEAD_RE = re.compile(
    r"^(?:周末|假期|长假|小长假|黄金周|国庆|春节|五一|十一|端午|中秋|元旦)*"
    r"(?:我想去|我想玩|想要去|准备去|打算去|计划去|想去|要去|希望去|去|前往|去往|到|玩)"
)
_CITY_TAIL_RE = re.compile(
    r"(?:两|二|三|四|五|六|七|八|九|十|\d+)\s*天$|(?:玩|游玩|旅游|旅行)$"
)


def _city_from_destination(value: str) -> str:
    """Extract the actual city name from a spoken destination phrase.

    The destination slot may hold a whole utterance ("周末去杭州两天，
    两个人，轻松一点"); grounding must search within 杭州, not feed the
    phrase to the provider as a city.  Falls back to _clean_destination.
    """
    for segment in re.split(r"[，,。；;、\s]+", value or ""):
        token = _CITY_TAIL_RE.sub("", _CITY_LEAD_RE.sub("", segment.strip()))
        token = _clean_destination(token)
        if 2 <= len(token) <= 5 and not re.search(r"\d", token):
            return token
    return _clean_destination(value or "")


def _parse_free_value(slot: str, text: str, *, today: date | None = None) -> Any:
    """Parse one free-text answer for a wizard slot; _INVALID when unclear."""
    if slot in ("destination", "accommodation"):
        return _check_value(slot, text)
    if slot in ("arrival", "departure"):
        anchor = _parse_anchor_text(text)
        return anchor if anchor is not None else _INVALID
    if slot in ("start_date", "end_date"):
        if re.search(r"\d", text):
            iso = _parse_date_text(text, today=today or date.today())
            return iso if iso else _INVALID
        return _INVALID
    if slot in ("travelers", "budget"):
        digits = ""
        for char in text:
            if char.isdigit():
                digits += char
            elif digits:
                break
        if digits:
            return _check_value(slot, int(digits))
        for char in text:
            if char in _CHINESE_DIGITS and slot == "travelers":
                return _check_value(slot, _CHINESE_DIGITS[char])
        return _INVALID
    if slot == "pace":
        for alias, value in PACE_ALIASES.items():
            if alias in text:
                return _check_value(slot, value)
        return _INVALID
    if slot in ("must_visit", "avoid"):
        for separator in ("、", "，", ",", "/", " "):
            if separator in text:
                return _check_value(slot, [part for part in text.split(separator) if part.strip()])
        return _check_value(slot, [text])
    return _INVALID


MOBILITY_LABELS: Final[dict[str, str]] = {
    "STANDARD": "标准",
    "REDUCED": "减少步行",
    "STEP_FREE": "无台阶",
}


_DESTINATION_IN_TEXT: Final = re.compile(
    r"(?:想去|就去|去|前往|到)([\u4e00-\u9fa5]{2,8}?)(?:玩|旅游|旅行|，|,|。|！|\s|$)"
)
_TRAVELERS_IN_TEXT: Final = re.compile(
    r"(\d{1,2})\s*个?人|(\d{1,2})\s*位|([一两二三四五六七八九十])\s*个?人"
)
_BUDGET_IN_TEXT: Final = re.compile(r"预算[^\d]{0,3}([0-9][0-9,]{2,})|([0-9]{3,7})\s*元")


def _scan_free_text(text: str) -> dict[str, Any]:
    """Scan rich free text for unambiguous slot values (deterministic).

    Best-effort complement to the wizard: only well-formed phrasings are
    recognized (去成都玩 / 10月1日到10月3日 / 2个人 / 预算5000); anything
    unclear stays unknown so the wizard can ask.  Values are proposals —
    the confirm card still gates them.
    """
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

    # Extract pace from free text (轻松 → RELAXED, 紧凑 → INTENSIVE, etc.)
    for alias, value in PACE_ALIASES.items():
        if alias in text:
            checked = _check_value("pace", value)
            if checked is not _INVALID:
                found["pace"] = checked
                break

    # Extract preference keywords from free text
    _PREFERENCE_KEYWORDS: Final = [
        "美食", "历史", "文化", "自然", "风景", "城市", "购物",
        "摄影", "亲子", "休闲", "遗迹", "古迹", "博物馆",
        "艺术", "建筑", "公园", "海滩", "夜景", "温泉",
    ]
    matched_prefs = [kw for kw in _PREFERENCE_KEYWORDS if kw in text]
    if matched_prefs:
        found["preferences"] = matched_prefs

    return found


def _render(slot: str, value: Any) -> str:
    if slot == "budget":
        return f"{value:,} 元"
    if slot == "travelers":
        return f"{value} 位"
    if slot == "pace":
        return PACE_LABELS.get(str(value), str(value))
    if slot == "mobility":
        return MOBILITY_LABELS.get(str(value), str(value))
    if slot in ("arrival", "departure") and isinstance(value, dict):
        return f"{value.get('place', '')} {value.get('time', '')}".strip()
    if isinstance(value, list):
        return "、".join(str(item) for item in value)
    return str(value)


def _new_state(context: TripContext | None) -> _DialogState:
    """Pre-seed every managed slot (mirrors ``ConstraintSlots.empty()``).

    Trip facts are seeded CONFIRMED(source=TRIP) when a context is present
    (trip mode); creation mode starts from a blank slate.
    """
    slots: dict[str, SlotView] = {name: SlotView() for name in MANAGED_SLOTS}
    for name, value in (
        ("destination", context.destination if context else None),
        ("start_date", context.start_date if context else None),
        ("end_date", context.end_date if context else None),
    ):
        if value:
            slots[name] = SlotView(value=value, state=SlotState.CONFIRMED, source=SlotSource.TRIP)
    # Composer 右下出行设置：人数/预算由前端组件明确提供，种入为已确认。
    # source=USER_EXPLICIT（而非 TRIP），保证后续仍能被自然语言或组件更新。
    for name, value in (
        ("travelers", context.travelers if context else None),
        ("budget", context.budget_amount if context else None),
    ):
        if value is not None:
            slots[name] = SlotView(
                value=value, state=SlotState.CONFIRMED, source=SlotSource.USER_EXPLICIT
            )
    return _DialogState(run_id=uuid.uuid4().hex[:12], slots=slots)


def place_search_from_runtime(runtime: Any) -> Any:
    """Adapt the places runtime provider into the dialog's search callable.

    Returns async search(city=..., keyword=...) -> [{name, city, district,
    address}]; a NO_RESULT provider outcome is a legitimate empty set, any
    other provider failure raises (the caller degrades gracefully).
    """
    from trip_agent.providers.errors import ProviderErrorCategory
    from trip_agent.providers.map import PoiSearchRequest, ProviderFailure

    async def search(*, city: str, keyword: str, limit: int = 3) -> list[dict[str, str]]:
        result = await runtime.provider.search_pois(
            PoiSearchRequest(city=city or "全国", keyword=keyword, limit=limit)
        )
        if isinstance(result, ProviderFailure):
            if result.category == ProviderErrorCategory.NO_RESULT:
                return []
            raise RuntimeError(result.error_code)
        return [
            {
                "name": poi.name,
                "city": poi.city,
                "district": poi.district,
                "address": poi.address,
            }
            for poi in result.data
        ]

    return search


class AgentDialogService:
    def __init__(
        self,
        *,
        store: Any,
        extractor: SlotExtractor | None,
        places: Any = None,
    ) -> None:
        self._store = store
        self._extractor = extractor
        self._places = places  # async (city, keyword) -> [{name, city, district, address}]

    async def handle(
        self,
        scope_key: str,
        context: TripContext | None,
        request: DialogueRequest,
    ) -> DialogueResponse:
        """Run one dialog turn.

        ``scope_key`` addresses the conversation ("trip:{id}" for the trip
        panel, "create:{sessionId}" for agent-driven creation); ``context``
        is the read-only trip fact bundle in trip mode, None in creation
        mode.
        """
        raw = None if request.reset else await self._store.load(scope_key)
        if request.reset:
            state = _new_state(context)
            self._apply_context(state, context)
            self._reply(state, "好的，我们重新开始。")
        elif raw is None:
            state = _new_state(context)
            self._apply_context(state, context)
            self._reply(state, "你好！我是行程规划助手。可以直接告诉我你的需求，我会逐项和你确认。")
        else:
            state = _DialogState.model_validate(raw)
            # Composer 右下出行设置随每轮 tripContext 同步（组件是权威入口），
            # 避免首轮未填、后续轮次又无法把数值带进 wizard。
            self._apply_context(state, context)

        if raw is None and request.message and request.message.strip():
            # 首条消息路由到开场问题。创建模式因 travelers/budget 已从 wizard
            # 移除，开场问题就是目的地（而非"选择出行人数"），首条消息由此被真正解读。
            self._advance(state, creation=scope_key.startswith("create:"))
        if request.option is not None:
            await self._apply_option(state, request.option)
        elif request.message and request.message.strip():
            self._reply(state, request.message.strip(), role="user")
            await self._apply_message(state, request.message.strip())

        self._advance(state, creation=scope_key.startswith("create:"))
        ready = self._is_ready(state, require_external=scope_key.startswith("create:"))
        if ready:
            # re-send the summary whenever its content changed (e.g. after a
            # post-ready addition) so the latest card always reflects reality
            summary = self._summary_text(state)
            if state.last_summary != summary:
                self._reply(state, summary, kind="SUMMARY")
                # Add a "start planning" confirmation option in the chat
                self._reply(
                    state,
                    "所有信息已确认，是否开始规划行程？",
                    kind="CLARIFY",
                    options=[
                        CardOption(action="CONFIRM", label="开始规划", value="START_PLANNING"),
                        CardOption(action="SKIP", label="再补充一下"),
                    ],
                )
                state.last_summary = summary
        await self._store.save(scope_key, state.model_dump(mode="json"))
        return DialogueResponse(
            phase="READY" if ready else "COLLECTING",
            ready=ready,
            messages=state.messages,
            slots=state.slots,
        )

    def _apply_context(self, state: _DialogState, context: TripContext | None) -> None:
        """同步 Composer 右下出行设置（人数/预算）到槽位（每轮，组件优先）。

        source=USER_EXPLICIT 而非 TRIP：组件是用户明确输入，后续可被再次组件/文本更新。
        """
        if context is None:
            return
        for slot, value in (
            ("travelers", context.travelers),
            ("budget", context.budget_amount),
        ):
            if value is not None:
                state.slots[slot] = SlotView(
                    value=value, state=SlotState.CONFIRMED, source=SlotSource.USER_EXPLICIT,
                )

    # ── input application ────────────────────────────────────────────

    async def _apply_option(self, state: _DialogState, option: CardOption) -> None:
        self._reply(state, f"[点选] {option.label}", role="user")

        # START_PLANNING is a chat-level confirmation — the frontend
        # intercepts it and calls createTripFromAgent; the server just
        # acknowledges and stays ready.
        if option.action == "CONFIRM" and option.value == "START_PLANNING":
            self._reply(state, "好的，开始创建行程！")
            return

        pending = state.pending
        if pending is not None:
            if pending.mode == "edit":
                if option.action == "SET":
                    self._set_proposal(state, pending.slot, option.value)
                else:
                    name = SLOT_LABELS.get(pending.slot, pending.slot)
                    self._reply(state, f"请直接输入新的{name}。")
                return
            state.pending = None
            if option.action == "CONFIRM":
                view = state.slots.get(pending.slot)
                if view is not None and view.value is not None:
                    if self._ground_slot(pending.slot):
                        grounded = await self._ground_pending(state, pending)
                        if not grounded:
                            return  # miss: proposal stays, correction card sent
                        view = state.slots.get(pending.slot)
                    state.slots[pending.slot] = SlotView(
                        value=view.value,
                        state=SlotState.CONFIRMED,
                        source=SlotSource.USER_CONFIRMED,
                        ref=view.ref,
                    )
            elif option.action == "EDIT":
                state.pending = _Pending(slot=pending.slot, mode="edit")
                name = SLOT_LABELS.get(pending.slot, pending.slot)
                self._reply(state, f"请输入新的{name}。")
            elif option.action == "SKIP":
                if pending.restore_view is not None:
                    state.slots[pending.slot] = pending.restore_view
                else:
                    state.slots[pending.slot] = SlotView()
                state.asked.add(pending.slot)
                if state.current_question == pending.slot:
                    state.current_question = None
            return
        if option.action == "ASK" and option.value in SLOT_SPECS_BY_NAME:
            # from the tier-1 suggestion card: open that question now
            slot = option.value
            state.asked.add(slot)
            state.current_question = slot
            self._ask_wizard(state, slot)
            return
        if option.action == "SKIP" and option.value == "T1":
            # user declines all remaining tier-1 suggestions
            for t1_slot in TIER1_SLOTS:
                view = state.slots.get(t1_slot)
                if view is None or view.state is not SlotState.CONFIRMED:
                    state.asked.add(t1_slot)
            state.current_question = None
            return
        slot = state.current_question
        if slot is None:
            # a stale card from the scrollback — be useful instead of dead-ending
            self._reply(
                state,
                "这一步已经完成啦。" + self._progress_text(state)
                + "直接说想改的地方就行，比如“必去故宫”。",
            )
            return
        if option.action == "SET" and self._set_confirmed(state, slot, option.value):
            error = self._date_range_error(state, slot)
            if error:
                state.slots[slot] = SlotView()
                state.current_question = slot
                self._reply(state, error)
                return
            state.current_question = None
        elif option.action == "SKIP":
            state.asked.add(slot)
            state.current_question = None

    async def _apply_message(self, state: _DialogState, text: str) -> None:
        pending = state.pending
        if pending is not None and pending.mode == "edit":
            value = _parse_free_value(pending.slot, text)
            if value is _INVALID:
                name = SLOT_LABELS.get(pending.slot, pending.slot)
                self._reply(state, f"没太看懂这个{name}，换个说法试试？")
                return
            error = self._date_range_error(state, pending.slot, value)
            if error:
                self._reply(state, error)
                return
            state.slots[pending.slot] = SlotView(
                value=value, state=SlotState.INFERRED, source=SlotSource.USER_EXPLICIT,
            )
            state.pending = _Pending(slot=pending.slot, mode="confirm")
            return

        extracted = await self._extract(text)
        if extracted:
            noted = []
            for raw_slot, value in extracted.items():
                slot = EXTRACTION_SLOT_ALIASES.get(raw_slot, raw_slot)
                checked = _check_value(slot, value)
                if checked is _INVALID:
                    continue
                current = state.slots.get(slot)
                if current is not None and current.state is SlotState.CONFIRMED:
                    continue
                state.slots[slot] = SlotView(
                    value=checked, state=SlotState.INFERRED, source=SlotSource.LLM_INFERRED,
                )
                noted.append(f"{SLOT_LABELS.get(slot, slot)}：{_render(slot, checked)}")
            if noted:
                self._reply(
                    state,
                    "我从你的描述里注意到：" + "；".join(noted) + "。逐项和你确认一下。",
                )
                return

        if state.current_question is not None:
            slot = state.current_question
            if slot == "start_date":
                # a spoken range fills both ends in one turn
                rng = _parse_date_range(text, today=date.today())
                if rng:
                    state.slots["start_date"] = SlotView(
                        value=rng[0], state=SlotState.INFERRED, source=SlotSource.USER_EXPLICIT,
                    )
                    state.slots["end_date"] = SlotView(
                        value=rng[1], state=SlotState.INFERRED, source=SlotSource.USER_EXPLICIT,
                    )
                    return
            value = _parse_free_value(slot, text)
            if value is _INVALID:
                if self._apply_scanned(state, text):
                    return
                self._reply(state, "没太看懂，可以直接点选下方选项，或换个说法。")
                return
            error = self._date_range_error(state, slot, value)
            if error:
                self._reply(state, error)
                return
            state.slots[slot] = SlotView(
                value=value, state=SlotState.INFERRED, source=SlotSource.USER_EXPLICIT,
            )
            return
        if self._handle_completed_text(state, text):
            return
        self._reply(
            state,
            "收到！" + self._progress_text(state)
            + "可以直接说想改的地方，比如“必去故宫”“预算改成12000”。",
        )

    async def _extract(self, text: str) -> dict[str, Any] | None:
        if self._extractor is None:
            return None
        try:
            return await self._extractor.extract(text)
        except Exception as error:  # noqa: BLE001 - the model may never break the dialog
            logger.warning("dialog_extractor_crashed error=%s", type(error).__name__)
            return None

    def _apply_scanned(self, state: _DialogState, text: str) -> bool:
        """Apply the deterministic multi-slot scan (no-LLM fallback).

        Lands here only when the direct answer to the open question failed to
        parse: the scan fills every slot the message clearly states and sends
        one proposal summary, instead of dead-ending on "没太看懂".  Returns
        True when at least one slot was proposed.
        """
        noted = []
        for slot, value in _scan_free_text(text).items():
            current = state.slots.get(slot)
            if current is None or current.state is SlotState.CONFIRMED or self._locked(state, slot):
                continue
            state.slots[slot] = SlotView(
                value=value, state=SlotState.INFERRED, source=SlotSource.USER_EXPLICIT,
            )
            noted.append(f"{SLOT_LABELS.get(slot, slot)}：{_render(slot, value)}")
        if not noted:
            return False
        self._reply(state, "我从你的描述里注意到：" + "；".join(noted) + "。逐项和你确认一下。")
        return True

    # ── loop advance ─────────────────────────────────────────────────

    def _advance(self, state: _DialogState, *, creation: bool = False) -> None:
        pending = state.pending
        if pending is not None:
            if pending.mode == "confirm":
                self._ask_pending(state)
            return
        inferred = next(
            (slot for slot, view in state.slots.items() if view.state is SlotState.INFERRED),
            None,
        )
        if inferred is not None:
            state.pending = _Pending(slot=inferred, mode="confirm")
            self._ask_pending(state)
            return
        question = state.current_question
        if question is not None:
            view = state.slots.get(question)
            if view is None or view.state is SlotState.UNKNOWN:
                # the open question was not answered (e.g. unclear free text) —
                # re-ask it instead of silently moving on
                self._ask_wizard(state, question)
                return
            state.current_question = None
        for slot in SLOT_ORDER:
            spec = SLOT_SPECS_BY_NAME[slot]
            if spec.tier == 2:
                continue  # tier-2 slots are never auto-asked
            if creation and slot in EXTERNAL_SLOTS:
                # 创建模式的出行设置（人数/预算）：由 Composer 右下组件 + 自由文本
                # 提取提供，绝不用 wizard 表单强问（否则第一发消息会被吞成
                # "选择出行人数"）。旅行模式保持原 wizard 行为。
                continue
            view = state.slots.get(slot)
            if view is not None and view.state is SlotState.CONFIRMED:
                state.asked.add(slot)
                continue
            if slot in state.asked:
                continue
            if spec.tier == 1:
                # first open tier-1 slot → one suggestion card for all of them
                self._ask_t1_suggestions(state)
                return
            state.asked.add(slot)
            state.current_question = slot
            self._ask_wizard(state, slot)
            return
        state.current_question = None

    def _ask_t1_suggestions(self, state: _DialogState) -> None:
        missing = [
            name for name in TIER1_SLOTS
            if name not in state.asked
            and (name not in state.slots or state.slots[name].state is not SlotState.CONFIRMED)
        ]
        def _note(name: str) -> str:
            spec = SLOT_SPECS_BY_NAME[name]
            return f"{spec.label}（{spec.note}）" if spec.note else ""

        notes = "；".join(_note(name) for name in missing if _note(name))
        options = [
            CardOption(action="ASK", label=SLOT_SPECS_BY_NAME[name].label, value=name)
            for name in missing
        ]
        options.append(CardOption(action="SKIP", label="先跳过，直接创建", value="T1"))
        self._reply(
            state,
            "基础信息齐了！补充这些会明显提升路线质量："
            + (notes + "。" if notes else "点选下方任意一项开始。"),
            kind="CLARIFY",
            options=options,
        )

    def _ask_pending(self, state: _DialogState) -> None:
        pending = state.pending
        if pending is None:
            return
        view = state.slots.get(pending.slot)
        value = _render(pending.slot, view.value if view else None)
        name = SLOT_LABELS.get(pending.slot, pending.slot)
        self._reply(
            state,
            f"{name}：{value}，这样安排可以吗？",
            kind="CLARIFY",
            options=[
                CardOption(action="CONFIRM", label="可以"),
                CardOption(action="EDIT", label="改一下"),
                CardOption(action="SKIP", label="不用管这个"),
            ],
        )

    def _ask_wizard(self, state: _DialogState, slot: str) -> None:
        spec = SLOT_SPECS_BY_NAME[slot]
        options = [
            CardOption(action="SET", label=label, value=value)
            for label, value in spec.options
        ]
        if spec.allow_skip:
            options.append(CardOption(action="SKIP", label="跳过"))
        self._reply(state, spec.question, kind="CLARIFY", options=options)

    def _set_confirmed(self, state: _DialogState, slot: str, value: Any) -> bool:
        checked = _check_value(slot, value)
        if checked is _INVALID:
            self._reply(state, f"这个{SLOT_LABELS.get(slot, slot)}数值不太对，请重新选择。")
            return False
        state.slots[slot] = SlotView(
            value=checked, state=SlotState.CONFIRMED, source=SlotSource.USER_EXPLICIT,
        )
        return True

    def _set_proposal(self, state: _DialogState, slot: str, value: Any) -> None:
        checked = _check_value(slot, value)
        if checked is _INVALID:
            self._reply(state, f"这个{SLOT_LABELS.get(slot, slot)}数值不太对，请直接输入。")
            return
        state.slots[slot] = SlotView(
            value=checked, state=SlotState.INFERRED, source=SlotSource.USER_EXPLICIT,
        )
        state.pending = _Pending(slot=slot, mode="confirm")

    # ── readiness and summary ────────────────────────────────────────

    def _ground_slot(self, slot: str) -> bool:
        spec = SLOT_SPECS_BY_NAME.get(slot)
        return bool(spec and spec.ground)

    async def _ground_pending(self, state: _DialogState, pending: _Pending) -> bool:
        """Verify a place proposal through the search tool before confirming.

        Hits: value becomes the canonical POI name (kept INFERRED — the
        caller confirms it).  Misses: proposal stays and a correction card
        is sent.  Returns True when the caller may confirm, False when the
        user must correct first.  A broken search degrades to allowing the
        confirm — the planner's own validators remain the backstop.
        """
        view = state.slots.get(pending.slot)
        if view is None or view.value is None:
            return True
        if self._places is None:
            return True  # verification unavailable (tests / degraded runtime)
        city_view = state.slots.get("destination")
        city = _city_from_destination(
            str(city_view.value) if city_view is not None and city_view.value else ""
        )
        try:
            if pending.slot == "must_visit" and isinstance(view.value, list):
                grounded: list[dict[str, str]] = []
                misses: list[str] = []
                for item in view.value:
                    hits = await self._places(city=city, keyword=item)
                    if not hits:
                        misses.append(item)
                        continue
                    if (
                        city
                        and hits[0].get("city")
                        and city not in hits[0]["city"]
                        and hits[0]["city"] not in city
                    ):
                        # cross-city hit: a 保定 POI is not a 杭州 must-visit
                        misses.append(item)
                        continue
                    grounded.append(hits[0])
                if misses:
                    self._reply(
                        state,
                        "没找到：" + "、".join(misses) + "。"
                        + self._ground_hint(state),
                    )
                    state.slots[pending.slot] = SlotView(
                        value=[hit["name"] for hit in grounded],
                        state=SlotState.INFERRED,
                        source=SlotSource.USER_EXPLICIT,
                    )
                    state.pending = _Pending(
                        slot=pending.slot, mode="confirm", restore_view=pending.restore_view,
                    )
                    return False
                state.slots[pending.slot] = SlotView(
                    value=[hit["name"] for hit in grounded],
                    state=SlotState.INFERRED,
                    source=SlotSource.USER_EXPLICIT,
                    ref={"items": self._refs_json(grounded)},
                )
                self._reply(state, "已定位：" + "、".join(hit["name"] for hit in grounded))
                return True
            keyword = view.value.get("place") if isinstance(view.value, dict) else view.value
            hits = await self._places(city=city, keyword=str(keyword))
            if not hits:
                self._reply(
                    state,
                    f"在{city or '目的地'}没找到「{keyword}」。"
                    + self._ground_hint(state),
                )
                state.pending = _Pending(
                    slot=pending.slot, mode="confirm", restore_view=pending.restore_view,
                )
                return False
            hit = hits[0]
            if (
                city
                and hit.get("city")
                and city not in hit["city"]
                and hit["city"] not in city
            ):
                # cross-city hit: never confirm a POI outside the trip's city —
                # treat it as a miss so the user corrects the proposal.
                self._reply(
                    state,
                    f"在{city}没找到「{keyword}」，最接近的结果在{hit['city']}，先不采用。"
                    + self._ground_hint(state),
                )
                state.pending = _Pending(
                    slot=pending.slot, mode="confirm", restore_view=pending.restore_view,
                )
                return False
            located = f"已定位：{hit['name']}"
            if hit.get("district"):
                located += f"（{hit['district']}）"
            self._reply(state, located)
            if isinstance(view.value, dict):
                state.slots[pending.slot] = SlotView(
                    value={**view.value, "place": hit["name"]},
                    state=SlotState.INFERRED,
                    source=SlotSource.USER_EXPLICIT,
                    ref=self._refs_json([hit])[0],
                )
            else:
                state.slots[pending.slot] = SlotView(
                    value=hit["name"],
                    state=SlotState.INFERRED,
                    source=SlotSource.USER_EXPLICIT,
                    ref=self._refs_json([hit])[0],
                )
            return True
        except Exception as error:  # noqa: BLE001 - search must never kill the run
            logger.warning("dialog_grounding_failed error=%s", type(error).__name__)
            self._reply(state, "地点搜索暂时不可用，先按你的说法保存；创建时会再次校验。")
            return True

    def _ground_hint(self, state: _DialogState) -> str:
        return "换个说法试试（如去掉“附近”等后缀），或点“不用管”。"

    def _refs_json(self, hits: list[dict[str, str]]) -> list[dict[str, str]]:
        return [
            {key: hit.get(key, "") for key in ("name", "city", "district", "address")}
            for hit in hits
        ]

    def _is_ready(self, state: _DialogState, *, require_external: bool = False) -> bool:
        if state.pending is not None or state.current_question is not None:
            return False
        if any(view.state is SlotState.INFERRED for view in state.slots.values()):
            return False
        # tier-2 slots never block readiness — they are optional by design.
        # 创建模式下 EXTERNAL_SLOTS（人数/预算）不参与 wizard 的 asked 标记，
        # 改由外部组件提供并通过值门槛判定；旅行模式仍走原 asked 判定。
        if not all(
            slot in state.asked
            for slot in TIER0_SLOTS + TIER1_SLOTS
            if not (require_external and slot in EXTERNAL_SLOTS)
        ):
            return False
        return not (require_external and not all(
            (state.slots.get(slot) is not None and state.slots[slot].value is not None)
            for slot in EXTERNAL_SLOTS
        ))
        return True

    def _date_range_error(
        self,
        state: _DialogState,
        slot: str,
        value: Any = _INVALID,
    ) -> str | None:
        """Reject an end_date that is not after start_date (both modes)."""
        if slot != "end_date":
            return None
        end_text = value if value is not _INVALID else None
        if end_text is None:
            view = state.slots.get(slot)
            end_text = view.value if view else None
        start_view = state.slots.get("start_date")
        if end_text is None or start_view is None or start_view.value is None:
            return None
        try:
            end = date.fromisoformat(str(end_text))
            start = date.fromisoformat(str(start_view.value))
        except ValueError:
            return None
        if end <= start:
            return "结束日期要晚于开始日期，再看看？"
        return None

    def _locked(self, state: _DialogState, slot: str) -> bool:
        """Trip-fact slots (source=TRIP) are read-only inside the dialog."""
        view = state.slots.get(slot)
        return view is not None and view.source is SlotSource.TRIP

    def _confirmed_parts(self, state: _DialogState) -> list[str]:
        parts = []
        for slot in SLOT_ORDER:
            view = state.slots.get(slot)
            if view is not None and view.state is SlotState.CONFIRMED and view.value is not None:
                parts.append(f"{SLOT_LABELS[slot]} {_render(slot, view.value)}")
        return parts

    def _progress_text(self, state: _DialogState) -> str:
        parts = self._confirmed_parts(state)
        return f"当前约束：{'；'.join(parts)}。" if parts else "当前还没有已确认的约束。"

    def _propose(
        self,
        state: _DialogState,
        slot: str,
        value: Any,
        *,
        restore: SlotView | None = None,
    ) -> None:
        state.slots[slot] = SlotView(
            value=value, state=SlotState.INFERRED, source=SlotSource.USER_EXPLICIT,
        )
        if restore is not None:
            state.pending = _Pending(slot=slot, mode="confirm", restore_view=restore)

    def _handle_completed_text(self, state: _DialogState, text: str) -> bool:
        """Route free text that arrives after the wizard finished.

        Deterministic heuristics only: dates, budget, travelers, and
        place-like strings (→ must-visit add).  Returns False when nothing
        matched so the caller can fall back to guidance.  Trip-fact slots
        are never proposed here.
        """
        stripped = text.strip()
        if not stripped or stripped in _STOP_WORDS:
            return False

        # 人数/预算/节奏用正则扫描（_scan_free_text 能同时parse"2个人，预算5500元"；
        # _parse_free_value 会把"2位"的"2"误当成预算，故此处复用扫描）。
        scanned = _scan_free_text(text)
        noted: list[str] = []
        for slot in EXTERNAL_SLOTS + ("pace",):
            value = scanned.get(slot)
            if value is not None and not self._locked(state, slot):
                self._propose(state, slot, value)
                noted.append(f"{SLOT_LABELS.get(slot, slot)}：{_render(slot, value)}")
        if noted:
            self._reply(state, "我从你的描述里注意到：" + "；".join(noted) + "。逐项和你确认一下。")
            return True

        # Handle preference keywords (历史, 文化, 美食, etc.)
        _PREFERENCE_KEYWORDS = [
            "美食", "历史", "文化", "自然", "风景", "城市", "购物",
            "摄影", "亲子", "休闲", "遗迹", "古迹", "博物馆",
            "艺术", "建筑", "公园", "海滩", "夜景", "温泉",
        ]
        matched_prefs = [kw for kw in _PREFERENCE_KEYWORDS if kw in text]
        if matched_prefs and not self._locked(state, "preferences"):
            current = state.slots.get("preferences")
            existing = (
                list(current.value)
                if current is not None and isinstance(current.value, list)
                else []
            )
            new_prefs = [p for p in matched_prefs if p not in existing]
            if new_prefs:
                restore = (
                    current
                    if current is not None and current.state is SlotState.CONFIRMED
                    else None
                )
                self._propose(
                    state, "preferences",
                    [*existing, *new_prefs] if existing else new_prefs,
                    restore=restore,
                )
                return True

        if "住" in text or "酒店" in text or "民宿" in text:
            value = _parse_free_value("accommodation", text)
            if value is not _INVALID and not self._locked(state, "accommodation"):
                self._propose(state, "accommodation", value)
                return True
        if re.search(r"\d{1,2}[:：点]", text):
            anchor = _parse_anchor_text(text)
            if anchor is not None:
                slot = "departure" if re.search(r"走|出发|返", text) else "arrival"
                if not self._locked(state, slot):
                    self._propose(state, slot, anchor)
                    return True

        rng = _parse_date_range(text, today=date.today())
        if rng and not self._locked(state, "start_date") and not self._locked(state, "end_date"):
            self._propose(state, "start_date", rng[0])
            self._propose(state, "end_date", rng[1])
            return True

        if not re.search(r"\d", stripped):
            cleaned = _clean_destination(stripped)
            if cleaned not in _STOP_WORDS and 2 <= len(cleaned) <= 20:
                current = state.slots.get("must_visit")
                base = (
                    list(current.value)
                    if current is not None and isinstance(current.value, list)
                    else []
                )
                if cleaned in base:
                    self._reply(state, f"「{cleaned}」已经在必去地点里啦。")
                    return True
                restore = (
                    current
                    if current is not None and current.state is SlotState.CONFIRMED
                    else None
                )
                self._propose(state, "must_visit", [*base, cleaned], restore=restore)
                return True
        return False

    async def confirmed_creation(self, scope_key: str) -> ConfirmedSlotsResponse:
        """Confirmed-slot projection for agent-driven trip creation."""
        raw = await self._store.load(scope_key)
        if raw is None:
            raise KeyError(scope_key)
        state = _DialogState.model_validate(raw)
        confirmed: dict[str, Any] = {}
        for slot in SLOT_ORDER:
            view = state.slots.get(slot)
            if view is None or view.state is not SlotState.CONFIRMED or view.value is None:
                continue
            if slot == "destination" and isinstance(view.value, str):
                # 旅行约束板可能持有整句话（修复前的历史会话）；建行程必须
                # 使用城市名，否则行政区划与 place-token 校验都会失败。
                confirmed[slot] = _city_from_destination(view.value)
                continue
            confirmed[slot] = view.value
        ready = (
            all(name in confirmed for name in REQUIRED_FOR_CREATION)
            # 出行设置门槛：人数/预算任一缺失都不可开始规划（与目的地/日期同级）。
            and all(name in confirmed for name in EXTERNAL_SLOTS)
            and state.pending is None
            and state.current_question is None
            and not any(view.state is SlotState.INFERRED for view in state.slots.values())
        )
        return ConfirmedSlotsResponse(ready=ready, confirmed=confirmed)

    def _summary_text(self, state: _DialogState) -> str:
        parts = []
        for slot in SLOT_ORDER:
            view = state.slots.get(slot)
            if view is not None and view.state is SlotState.CONFIRMED and view.value is not None:
                parts.append(f"{SLOT_LABELS[slot]} {_render(slot, view.value)}")
        return "约束已确认：" + "；".join(parts) + "。"

    # ── helpers ──────────────────────────────────────────────────────

    def _reply(
        self,
        state: _DialogState,
        text: str,
        *,
        role: Literal["user", "agent"] = "agent",
        kind: Literal["TEXT", "CLARIFY", "SUMMARY"] = "TEXT",
        options: list[CardOption] | None = None,
    ) -> None:
        if role == "agent" and state.messages:
            last = state.messages[-1]
            if last.role == "agent" and last.text == text and last.kind == kind:
                # The same question is still on screen (re-asked after an
                # unanswered turn) — appending it again reads as a glitch.
                return
        state.messages.append(AgentMessage(role=role, text=text, kind=kind, options=options or []))
        if len(state.messages) > MAX_MESSAGES:
            del state.messages[:-MAX_MESSAGES]
