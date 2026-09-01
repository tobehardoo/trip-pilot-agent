"""Bounded agent loop built on LangGraph.

Shape::

    START → decide → (tool pending) → act → decide
                  → (answered / waiting / emitted / ceiling) → finish → END

The loop is bounded by three ceilings — steps, tool calls and model calls.
Hitting a ceiling is a stop condition, never a reason to loop forever.  This
mirrors the planner's ``MAX_REPAIR_ATTEMPTS`` philosophy: the agent may try,
but it may not spin.

Emission is deterministic (P2.4): a passing ``validate_itinerary``
observation auto-emits the candidate — the model has no emit tool.

Model-backed decision making is optional.  With no model configured the loop
falls back to a deterministic policy that fills required slots by asking the
user, which keeps the run reproducible and Demo-mode runnable.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, fields, replace
from typing import Any, Protocol

import httpx
from langgraph.graph import END, START, StateGraph

from trip_agent.agent.failure_policy import (
    USER_OWNED_KINDS,
    advance_failure_memory,
    classify_failure,
    escalate_duplicate,
)
from trip_agent.agent.reflection import (
    REFLECTION_EXHAUSTED_ANSWER,
    REFLECTION_MAX_ATTEMPTS,
    reflect_on_evaluation,
    reflection_budget_exhausted,
)
from trip_agent.agent.state import AgentState, ToolObservation
from trip_agent.agent.tools import ToolCall, ToolRegistry

logger = logging.getLogger(__name__)

MAX_STEPS = 8
MAX_TOOL_CALLS = 16
MAX_LLM_CALLS = 8

STOP_CEILING = "CEILING_REACHED"
STOP_BUDGET = "LLM_BUDGET_EXHAUSTED"


@dataclass(frozen=True, slots=True)
class Decision:
    """The model's next move.

    Either a tool call, or a final answer (which ends the run).  The
    declared strategy (P3.3) is optional and only recorded when valid.
    """

    thought: str
    call: ToolCall | None = None
    answer: str | None = None
    strategy: str | None = None


class DecisionMaker(Protocol):
    """Produces the next decision from the current state."""

    async def decide(self, state: AgentState) -> Decision: ...


class DecisionTransport(Protocol):
    """Minimal structured-output transport contract."""

    async def extract(
        self,
        *,
        content: str,
        json_schema: dict[str, Any],
        timeout_seconds: float,
    ) -> object: ...


QUESTION_FOR_SLOT: dict[str, str] = {
    "destination": "你想去哪个城市？",
    "start_date": "行程从哪天开始？",
    "end_date": "行程到哪天结束？",
}


_SLOT_QUESTION: dict[str, str] = {question: slot for slot, question in QUESTION_FOR_SLOT.items()}

# 确定性回答提取（无 Key 演示路径）：只把用户原话里的词提取为候选值，
# 提取器从不发明值——确认与否仍由 evidence-match 规则裁决。
_DESTINATION_PATTERN = re.compile(
    r"(?:想去|就去|去|前往)([\u4e00-\u9fa5]{2,8}?)(?:玩|旅游|旅行|，|,|。|！|$)"
)
# V3 D-3: the infeasibility question asks the user to adjust constraints —
# "预算可以提高到 4000" / "预算降到 3000" must both parse.
_BUDGET_PATTERN = re.compile(r"预算\s*(?:可以)?(?:提高|降低|升|降|调|改)?到?\s*(\d{3,})")
_TRAVELERS_PATTERN = re.compile(r"(\d+)\s*(?:个?人|位)")
_DATE_PATTERN = re.compile(r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}月\d{1,2}日")


# V3 D-3: removal cues for the infeasible-resume parser — the user's own
# words that indicate a must-visit entry should be dropped.
_REMOVAL_CUES: tuple[str, ...] = ("删除", "去掉", "移除", "取消", "不要", "别去", "不想去")
# E-1/T4: clause separators that bound a removal clause ("去掉不存在的景点，"
# ends at the comma).  A removal clause must be stripped BEFORE slot-value
# extraction, otherwise "去掉X" is misread by the destination pattern as
# "去" + destination "掉X" — a fabricated destination change.
_REMOVAL_CLAUSE_SEPARATORS: tuple[str, ...] = ("，", ",", "。", "！", "？", "；", ";", "\n")


def _extract_slot_values(message: str) -> dict[str, Any]:
    """Deterministically extract slot candidates from the user's message.

    Demo-grade heuristics for the no-key path: only verbatim user words are
    ever proposed — the extractor never invents a value.
    """
    values: dict[str, Any] = {}
    destination = _DESTINATION_PATTERN.search(message)
    if destination:
        values["destination"] = destination.group(1)
    budget = _BUDGET_PATTERN.search(message)
    if budget:
        values["budget"] = budget.group(1)
    travelers = _TRAVELERS_PATTERN.search(message)
    if travelers:
        values["travelers"] = travelers.group(1)
    dates = _DATE_PATTERN.findall(message)
    if dates:
        values["start_date"] = dates[0]
        if len(dates) > 1:
            values["end_date"] = dates[1]
    return values


def _question_for(slot: str) -> str:
    return QUESTION_FOR_SLOT.get(slot, f"请补充约束：{slot}")


# V3 D-4: what to ask INSTEAD of repeating a failing action.  Every template
# names the concrete conflict the tool reported ({detail}) and the change only
# the user can supply — the guard must never invent a constraint to escape.
_DUPLICATE_QUESTIONS: dict[str, str] = {
    "USER_CONSTRAINT": (
        "按当前约束我试过了，结果不变：{detail}。"
        "请调整必去地点、日期或预算，我再重新规划。"
    ),
    "FEASIBILITY": (
        "这几次规划都卡在同一个冲突上：{detail}。"
        "重复尝试不会有新结果，请放宽日期、减少必去地点或提高预算。"
    ),
    "VALIDATION": (
        "草稿反复未通过硬校验：{detail}。"
        "请调整行程条件（日期、必去地点、预算），我再重新规划。"
    ),
    "CANDIDATE_EMPTY": (
        "同样的检索反复返回空结果：{detail}。"
        "换一个目的地、放宽条件或改一下关键词，我再试一次。"
    ),
}

_DUPLICATE_QUESTION_FALLBACK = "同一个操作我重复了几次都失败：{detail}。请换个条件再试。"

# ask_user questions are bounded by the wire contract (300 characters); the
# quoted conflict gets the shorter half of the budget.
_MAX_DUPLICATE_DETAIL_CHARACTERS = 140


class AskingDecider:
    """Deterministic fallback policy: fill required slots by asking.

    Used when no model is configured.  It never guesses a constraint — the
    first missing required slot becomes a question and the run stops to wait
    for the human answer.  When the user answers, their verbatim words are
    proposed back through ``update_constraints`` (the evidence-match rule
    decides what counts as confirmed).
    """

    async def decide(self, state: AgentState) -> Decision:
        required_hard = all(
            state.slots.get(name).hard for name in QUESTION_FOR_SLOT
        )
        if required_hard:
            # 约束齐了：build → 守门 → 自动发射（P2.2–P2.4 编排语义）。
            builds = [obs for obs in state.observations if obs.tool == "build_itinerary"]
            if builds and not builds[-1].ok and builds[-1].error_code == "CAPABILITY_MISSING":
                return Decision(
                    thought="no builder wired; hand off to the planning pipeline",
                    answer="约束已收集完整，可以交给确定性规划链路。",
                    strategy="DIRECT",
                )
            if (
                state.observations
                and state.observations[-1].tool == "ask_user"
                and state.failure_kind in USER_OWNED_KINDS
                and state.failure_attempts > 0
            ):
                # V3 D-4: an escalation question is only honest if the reply
                # can act on it.  Every kind the user owns gets its reply
                # parsed for a constraint adjustment BEFORE the decider
                # considers repeating the failing action, so a real change
                # always reaches the update_constraints reset that releases the
                # duplicate guard — otherwise the resumed turn would re-meet
                # the guard and re-ask the same question forever.
                adjustment = self._extract_adjustment(state)
                if adjustment is not None:
                    return Decision(
                        thought="the user adjusted the constraints; replan",
                        call=ToolCall("update_constraints", adjustment),
                        strategy="REPLAN",
                    )
            if (
                builds
                and not builds[-1].ok
                and builds[-1].error_code == "PLANNING_INFEASIBLE"
                # V3 D-3: the branch is gated on the failure memory being
                # unresolved — once a constraint update clears it, the loop
                # rebuilds instead of re-asking the old question.
                and state.failure_kind == "USER_CONSTRAINT"
            ):
                # V3 D-3: the reply that carries the adjustment is handled by
                # the parse above; only an unresolvable reply reaches here.
                conflict = builds[-1].summary
                return Decision(
                    thought="planning reported an infeasible constraint; the user must adjust it",
                    call=ToolCall(
                        "ask_user",
                        {
                            "question": (
                                f"行程无法在当前约束下生成：{conflict}。"
                                "请调整必去地点或日期，我再重新规划。"
                            )
                        },
                    ),
                    strategy="REPLAN",
                )
            if builds and not builds[-1].ok and state.failure_kind == "TRANSIENT":
                # V3 D-2: a transient provider failure is the one failure the
                # agent may answer by acting again — ONE bounded retry of the
                # same build under the SAME confirmed constraints.  The
                # provider has usually exhausted its own retries by the time
                # the error arrives; the agent-level retry is a single second
                # chance, never a loop.  A second consecutive transient
                # failure exits to the user via the existing WAITING_USER
                # semantics; a reply to that notice is the user's consent to
                # try again right now — every rebuild past the bound is
                # user-initiated.  V3 D-4 bounds those user-initiated cycles:
                # past the transient repeat budget the run stops instead of
                # asking the same thing again.
                guarded = self._duplicate_guard(
                    state, action_tool="build_itinerary", detail=builds[-1].summary
                )
                if guarded is not None:
                    return guarded
                if state.failure_attempts <= 1:
                    return Decision(
                        thought="transient provider failure; retry the same build once",
                        call=ToolCall("build_itinerary"),
                        strategy="RETRY",
                    )
                if state.observations and state.observations[-1].tool == "ask_user":
                    return Decision(
                        thought="the user replied to the transient-failure notice; try again",
                        call=ToolCall("build_itinerary"),
                        strategy="RETRY",
                    )
                return Decision(
                    thought="the bounded retry failed too; hand the outage to the user",
                    call=ToolCall(
                        "ask_user",
                        {
                            "question": (
                                f"规划服务暂时不可用（{builds[-1].error_code}）。"
                                "已自动重试仍未恢复，你可以回复任意消息让我"
                                "立即再试一次，或稍后再来。"
                            )
                        },
                    ),
                    strategy="CLARIFY",
                )
            if (
                builds
                and builds[-1].ok
                and state.failure_kind in USER_OWNED_KINDS
                and state.failure_attempts > 0
                and reflect_on_evaluation(state.plan_evaluation) == "REJECT_HARD"
            ):
                # E-1 Case B: a build whose Evaluation verdict is REJECT_HARD
                # (unresolved hard-validation FAIL) must not ride to EMITTED
                # on a structural-gate pass (S2).  The failure memory is
                # already populated from the build's reason codes, so the
                # existing D-4 escalation asks the user to adjust — and a
                # doomed structural pass is skipped entirely.
                if state.observations and state.observations[-1].tool == "ask_user":
                    # The user just replied to the reflection question without
                    # an actionable adjustment — repeating the same question is
                    # a dialog loop; end the turn honestly instead.
                    return Decision(
                        thought=(
                            "user reply carried no constraint adjustment; "
                            "the evaluation-rejected candidate is not emitted"
                        ),
                        answer=(
                            "当前约束下无法生成可接受的行程，"
                            "请调整必去地点、日期或预算后再试。"
                        ),
                        strategy="CLARIFY",
                    )
                guarded = self._duplicate_guard(
                    state,
                    action_tool="build_itinerary",
                    detail=self._failure_detail(state, "build_itinerary"),
                )
                if guarded is not None:
                    return guarded
                return Decision(
                    thought="evaluation rejected the draft; ask the user to adjust",
                    call=ToolCall(
                        "ask_user",
                        {
                            "question": (
                                "行程未通过规划评估："
                                f"{self._failure_detail(state, 'build_itinerary')}。"
                                "请调整必去地点、日期或预算，我再重新规划。"
                            )
                        },
                    ),
                    strategy="REPLAN",
                )
            if state.candidate_itinerary is None:
                # V3 D-4: reaching this branch with the failure memory still
                # holding a build_itinerary failure means the SAME build under
                # the SAME constraints already refused — for a deterministic
                # refusal a second attempt is a policy loop, not recovery.
                guarded = self._duplicate_guard(
                    state,
                    action_tool="build_itinerary",
                    detail=self._failure_detail(state, "build_itinerary"),
                )
                if guarded is not None:
                    return guarded
                return Decision(
                    thought="build the draft",
                    call=ToolCall("build_itinerary"),
                    strategy="DIRECT",
                )
            if not any(
                obs.tool == "validate_itinerary" and obs.ok for obs in state.observations
            ):
                # V3 D-4: same for the structural gate — a blocked candidate
                # only becomes unblocked when the user changes the constraints.
                guarded = self._duplicate_guard(
                    state,
                    action_tool="validate_itinerary",
                    detail=self._failure_detail(state, "validate_itinerary"),
                )
                if guarded is not None:
                    return guarded
                return Decision(
                    thought="gate the draft",
                    call=ToolCall("validate_itinerary"),
                    strategy="DIRECT",
                )
            return Decision(
                thought="draft emitted",
                answer="行程草稿已生成，请在卡片中确认。",
                strategy="DIRECT",
            )

        message = (state.user_message or "").strip()
        if message:
            values = _extract_slot_values(message)
            fresh = {
                name: value
                for name, value in values.items()
                if not state.slots.get(name).hard
            }
            if fresh:
                return Decision(
                    thought="the user message answers pending constraints",
                    call=ToolCall(
                        "update_constraints",
                        {"values": fresh, "evidence": message},
                    ),
                    strategy="DIRECT",
                )
            pending = self._pending_question_slot(state)
            if pending:
                # The user replied to the pending question, but the reply did
                # not contain a recognizable value — ask once more with the
                # reply echoed, instead of silently looping the identical one.
                return Decision(
                    thought="the answer was not recognizable; ask once more",
                    call=ToolCall(
                        "ask_user",
                        {"question": f"没太理解「{message}」——{_question_for(pending)}"},
                    ),
                    strategy="CLARIFY",
                )
        missing = state.slots.missing_required()
        if missing:
            name = missing[0]
            return Decision(
                thought=f"required slot '{name}' is not confirmed yet",
                call=ToolCall("ask_user", {"question": _question_for(name)}),
                strategy="CLARIFY",
            )
        return Decision(
            thought="all required slots are confirmed",
            answer="约束已收集完整，可以交给确定性规划链路。",
            strategy="DIRECT",
        )

    def _duplicate_guard(
        self,
        state: AgentState,
        *,
        action_tool: str,
        detail: str,
    ) -> Decision | None:
        """V3 D-4: veto an action that would repeat the action that just failed.

        Returns the Decision to issue INSTEAD of ``action_tool`` — a question
        when the user is the one who can change the outcome, a bare stop
        decision (the loop's existing ``"STOPPED"`` exit) when they cannot —
        or ``None`` when the action is still policy-approved.

        The guard writes nothing: it never resets the failure memory, never
        touches a slot, and never vetoes ``ask_user`` or
        ``update_constraints``, so D-2's bounded retry and D-3's repair path
        keep their existing behaviour.
        """
        escalation = escalate_duplicate(
            kind=state.failure_kind,
            signature=state.failure_signature,
            attempts=state.failure_attempts,
            action_tool=action_tool,
        )
        if escalation is None:
            return None
        kind = state.failure_kind or "INTERNAL"
        thought = (
            f"{kind} failure #{state.failure_attempts} of {action_tool}: "
            "repeating it is a policy loop, escalate instead"
        )
        if escalation == "STOPPED":
            return Decision(thought=thought)
        template = _DUPLICATE_QUESTIONS.get(kind, _DUPLICATE_QUESTION_FALLBACK)
        return Decision(
            thought=thought,
            call=ToolCall("ask_user", {"question": template.format(detail=detail)}),
            strategy="CLARIFY",
        )

    @staticmethod
    def _failure_detail(state: AgentState, tool: str) -> str:
        """The most specific conflict text the failing tool reported.

        An escalation question must say WHY repeating the action is useless,
        not just that something failed: the structural gate's report carries
        per-rule messages, every tool carries a summary.  Bounded so the
        question stays inside the wire contract's length limit.
        """
        if tool == "validate_itinerary":
            messages = [
                str(failure["message"])
                for failure in ((state.plan_evaluation or {}).get("failures") or [])
                if isinstance(failure, dict) and failure.get("message")
            ]
            if messages:
                return "；".join(messages)[:_MAX_DUPLICATE_DETAIL_CHARACTERS]
        for observation in reversed(state.observations):
            if observation.tool == tool:
                return observation.summary[:_MAX_DUPLICATE_DETAIL_CHARACTERS]
        return (state.failure_signature or "未知失败")[:_MAX_DUPLICATE_DETAIL_CHARACTERS]

    def _extract_adjustment(self, state: AgentState) -> dict[str, Any] | None:
        """V3 D-3: parse the user's reply to an infeasibility question into an
        ``update_constraints`` proposal (values/rejections/evidence).

        Deterministic and conservative: only the user's own words are ever
        proposed (the evidence gate still decides confirmation downstream);
        a reply with no recognizable adjustment returns None so the question
        repeats instead of the constraints being guessed.
        """
        message = (state.user_message or "").strip()
        if not message:
            return None
        # E-1/T4: strip removal clauses BEFORE slot-value extraction.  A
        # conflict reply like "预算提高到 9000，去掉不存在的景点" must only
        # contribute budget=9000 and a must_visit rejection — "去掉X" must
        # never be re-read by the destination pattern as "去" + "掉X".
        parse_message = message
        for cue in _REMOVAL_CUES:
            while True:
                cue_at = parse_message.find(cue)
                if cue_at < 0:
                    break
                # The clause runs from the cue to the next separator (or end).
                tail = parse_message[cue_at + len(cue):]
                cut = len(tail)
                for sep in _REMOVAL_CLAUSE_SEPARATORS:
                    sep_at = tail.find(sep)
                    if sep_at >= 0 and sep_at < cut:
                        cut = sep_at
                parse_message = (
                    parse_message[:cue_at] + parse_message[cue_at + len(cue) + cut:]
                )
        # a constraint adjustment may legitimately OVERRIDE a confirmed slot
        # (the user is answering the conflict question), so the collection
        # phase's "skip hard slots" filter does not apply here — the handler's
        # override/evidence rules stay the only confirmation path.
        values = {
            name: value
            for name, value in _extract_slot_values(parse_message).items()
            if str(state.slots.get(name).value) != str(value)
        }
        rejections: dict[str, str] = {}
        try:
            must_visit = state.slots.get("must_visit").value
        except KeyError:
            must_visit = None
        entries = (
            [str(item).strip() for item in must_visit]
            if isinstance(must_visit, list | tuple)
            else ([str(must_visit).strip()] if must_visit else [])
        )
        if entries and any(cue in message for cue in _REMOVAL_CUES):
            # An entry counts as REMOVED only when a removal cue is directly
            # adjacent to it ("不要武侯祠") — a mere mention ("宽窄巷子还是
            # 可以去") means the user wants to KEEP it.
            removed = [
                entry
                for entry in entries
                if any(f"{cue}{entry}" in message for cue in _REMOVAL_CUES)
            ]
            if len(removed) == 1:
                rejections["must_visit"] = removed[0]
                remaining = [entry for entry in entries if entry != removed[0]]
                if remaining and all(entry in message for entry in remaining):
                    values["must_visit"] = remaining
            elif not removed and "必去" in message and len(entries) == 1:
                # anaphoric removal ("删除这个必去点") is only resolvable when
                # exactly one entry exists — otherwise re-ask, never guess
                rejections["must_visit"] = entries[0]
        if not values and not rejections:
            return None
        return {"values": values, "rejections": rejections, "evidence": message}

    @staticmethod
    def _pending_question_slot(state: AgentState) -> str | None:
        for observation in reversed(state.observations):
            if observation.tool != "ask_user":
                continue
            return _SLOT_QUESTION.get(observation.summary)
        return None


DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "thought": {"type": "string", "description": "One sentence of reasoning."},
        "strategy": {
            "type": ["string", "null"],
            "enum": ["DIRECT", "RETRIEVE", "CLARIFY", "REPLAN", "RETRY", None],
            "description": "The declared strategy for this decision.",
        },
        "tool": {
            "type": ["string", "null"],
            "description": "Name of the tool to call, or null to answer.",
        },
        "args": {"type": "object", "description": "Arguments for the chosen tool."},
        "answer": {
            "type": ["string", "null"],
            "description": "Final answer to the user when no tool is needed.",
        },
    },
    "required": ["thought", "tool", "args", "answer"],
    "additionalProperties": False,
}

# V3 D-2: RETRY names the bounded second attempt of the same action after a
# transient provider failure — a normal agent action, visible in the state.
DECISION_STRATEGIES: frozenset[str] = frozenset(
    {"DIRECT", "RETRIEVE", "CLARIFY", "REPLAN", "RETRY"}
)


class StructuredOutputDecider:
    """Model-backed decision via an OpenAI-compatible structured endpoint.

    Reuses the same structured-output configuration style as
    guide-intelligence extraction, so no new credential surface appears.  A
    model response that cannot be parsed, or a transport failure (timeout,
    connection, HTTP error), never breaks the run: the decider degrades to
    the deterministic fallback policy instead of raising.
    """

    def __init__(
        self,
        *,
        transport: DecisionTransport,
        tools: ToolRegistry,
        timeout_seconds: float = 8.0,
        max_calls: int = MAX_LLM_CALLS,
        fallback: DecisionMaker | None = None,
    ) -> None:
        self._transport = transport
        self._tools = tools
        self._timeout = timeout_seconds
        self._max_calls = max_calls
        self._calls = 0
        self._fallback = fallback or AskingDecider()

    @property
    def calls(self) -> int:
        return self._calls

    async def decide(self, state: AgentState) -> Decision:
        if self._calls >= self._max_calls:
            return Decision(
                thought="model call budget exhausted",
                answer="已达到模型调用上限，停止本次会话。",
            )
        self._calls += 1
        try:
            raw = await self._transport.extract(
                content=self._prompt(state),
                json_schema=DECISION_SCHEMA,
                timeout_seconds=self._timeout,
            )
            payload = json.loads(str(raw))
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.warning("agent_decision_unparsable")
            return await self._fallback.decide(state)
        except (httpx.HTTPError, TimeoutError, ConnectionError, OSError) as exc:
            logger.warning(
                "agent_decision_transport_failure error=%s", type(exc).__name__
            )
            return await self._fallback.decide(state)
        return self._to_decision(payload)

    def _to_decision(self, payload: Any) -> Decision:
        if not isinstance(payload, dict):
            return Decision(thought="unexpected payload", answer=None)
        thought = str(payload.get("thought", ""))
        tool = payload.get("tool")
        answer = payload.get("answer")
        strategy = payload.get("strategy")
        args = payload.get("args") or {}
        if not isinstance(args, dict):
            args = {}
        if strategy is not None and strategy not in DECISION_STRATEGIES:
            strategy = None
        if isinstance(tool, str) and tool:
            if not self._tools.has(tool):
                return Decision(
                    thought=f"model requested unknown tool '{tool}'",
                    call=ToolCall("ask_user", {"question": "这个操作我暂时做不到，换个说法？"}),
                    strategy=strategy,
                )
            return Decision(thought=thought, call=ToolCall(tool, args), strategy=strategy)
        if isinstance(answer, str) and answer:
            return Decision(thought=thought, answer=answer, strategy=strategy)
        return Decision(
            thought=thought or "no actionable output",
            call=ToolCall("ask_user", {"question": "能补充一下你的需求吗？"}),
            strategy=strategy,
        )

    def _prompt(self, state: AgentState) -> str:
        tools = json.dumps(list(self._tools.declarations()), ensure_ascii=False)
        slots = json.dumps(state.slots.confirmed_values(), ensure_ascii=False, default=str)
        missing = ", ".join(state.slots.missing_required()) or "none"
        preferences = (
            "; ".join(f"{category}={value}" for category, value in state.confirmed_preferences)
            or "none"
        )
        return (
            "你是 TripPilot 的旅行规划助手。\n"
            "只使用给定工具获取事实，不得编造营业时间、路程耗时等硬事实。\n"
            "回答处理规则：若最近的用户消息包含了待确认约束的答案，必须立即调用 "
            "update_constraints 提交（values 填结构化值、evidence 原样引用用户原话），"
            "严禁原样重复已经问过的问题。提交后再决定下一步。\n"
            "每次决策请声明策略 strategy：DIRECT（信息足够直接构建）/\n"
            "RETRIEVE（先检索攻略）/ CLARIFY（向用户澄清）/ REPLAN（修改既有行程）。\n"
            f"用户长期偏好（已确认）: {preferences}\n"
            f"待确认的必填约束: {missing}\n"
            f"已确认约束: {slots}\n"
            f"最近的用户消息: {state.user_message or '(无)'}\n"
            f"可用工具: {tools}\n"
            f"最近的观测:\n{state.recent_observations()}\n"
            f"当前行程评估 (PLAN EVALUATION):\n{self._render_evaluation(state)}\n"
            f"反思预算 (REFLECTION BUDGET): {state.reflection_attempts}/"
            f"{REFLECTION_MAX_ATTEMPTS}\n"
            "反射规则：若当前行程评估存在未解决硬校验失败（status=NEEDS_REPAIR "
            "且 failures 非空），不得以完成姿态结束会话——必须调用 ask_user 请用户"
            "调整约束（必去地点/日期/预算）或调用 build_itinerary 重新规划；"
            "反复失败时不得无限重试（达到反思预算上限将强制停止）。\n"
        )

    @staticmethod
    def _render_evaluation(state: AgentState) -> str:
        """The E-1 decision context: the stored evaluation rendered as a
        stable CURRENT STATE section.  Quality is feedback — rendered, never
        a gate; the hard-validation FAIL verdict is what the model must act
        on (Case B)."""
        evaluation = state.plan_evaluation
        if not isinstance(evaluation, dict):
            return "(无)"
        lines = [f"- status: {evaluation.get('status', 'UNKNOWN')}"]
        failures = evaluation.get("failures") or []
        if failures:
            lines.append("- failures:")
            for failure in failures:
                if isinstance(failure, dict):
                    lines.append(
                        f"  - {failure.get('rule_id')} / {failure.get('reason_code')}: "
                        f"{failure.get('message')}"
                    )
        quality = evaluation.get("quality")
        if isinstance(quality, dict) and quality.get("verdict"):
            lines.append(
                f"- quality: {quality.get('verdict')} (score {quality.get('score')})"
            )
            reasons = quality.get("reasons") or []
            if reasons:
                lines.append(f"  - {'; '.join(str(reason) for reason in reasons)}")
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class AgentLoop:
    """Wires a decision maker and a tool registry into one bounded graph."""

    decider: DecisionMaker
    tools: ToolRegistry
    max_steps: int = MAX_STEPS
    max_tool_calls: int = MAX_TOOL_CALLS

    def build(self) -> StateGraph:
        graph = StateGraph(AgentState)
        graph.add_node("decide", self._decide_node)
        graph.add_node("act", self._act_node)
        graph.add_node("finish", self._finish_node)
        graph.add_edge(START, "decide")
        graph.add_conditional_edges(
            "decide",
            self._route,
            {"act": "act", "finish": "finish"},
        )
        graph.add_edge("act", "decide")
        graph.add_edge("finish", END)
        return graph

    def compile(self):
        return self.build().compile()

    async def _decide_node(self, state: AgentState) -> dict[str, Any]:
        if state.stop_reason is not None:
            return {}
        if state.steps >= self.max_steps:
            return {"stop_reason": STOP_CEILING}
        if reflection_budget_exhausted(state):
            # E-1 Case D: the reflection budget is spent while the latest
            # candidate is still evaluation-rejected.  Bounded by design —
            # neither decider may REPLAN without end; the run hands the
            # outcome to the user with a final answer instead.
            return {
                "steps": state.steps + 1,
                "pending_call": None,
                "answer": REFLECTION_EXHAUSTED_ANSWER,
                "strategy": None,
            }
        decision = await self.decider.decide(state)
        update: dict[str, Any] = {
            "steps": state.steps + 1,
            "pending_call": decision.call,
            "answer": decision.answer,
            "strategy": decision.strategy,
        }
        return update

    async def _act_node(self, state: AgentState) -> dict[str, Any]:
        call = state.pending_call
        update: dict[str, Any] = {"pending_call": None}
        if call is None:
            return update
        if (
            len(state.observations) - state.turn_baseline_observations
            >= self.max_tool_calls
        ):
            return {**update, "stop_reason": STOP_CEILING}
        result, extra = await self.tools.invoke(call, state)
        observation = ToolObservation(
            tool=call.tool,
            ok=result.ok,
            summary=result.summary,
            data=result.data,
            error_code=result.error_code,
        )
        update.update(state.with_observation(observation))
        update.update(extra)
        # V3 D-1: classify every observation into the failure memory (pure;
        # the decider reads it from D-2/D-3/D-4 onward — this wiring only
        # records, it never changes the exit decision).
        # V3 D-3 exception: an ask_user observation is PART of handling the
        # failure, not a resolution of it — the memory must survive the ask
        # so the resume can act on it.
        evaluation = update.get("plan_evaluation", state.plan_evaluation)
        if observation.tool == "ask_user":
            return update
        reason_codes = tuple(
            failure["reason_code"]
            for failure in ((evaluation or {}).get("failures") or [])
            if isinstance(failure, dict) and failure.get("reason_code")
        )
        kind, signature = classify_failure(
            tool=observation.tool,
            ok=observation.ok,
            error_code=observation.error_code,
            data=observation.data,
            validation_reason_codes=reason_codes,
        )
        (
            update["failure_kind"],
            update["failure_signature"],
            update["failure_attempts"],
        ) = advance_failure_memory(
            kind=kind,
            signature=signature,
            current_kind=state.failure_kind,
            current_signature=state.failure_signature,
            current_attempts=state.failure_attempts,
        )
        # E-1 reflection accounting: a build whose evaluation is REJECT_HARD
        # consumes one reflection-budget slot under the current constraint
        # context (validate does not change the evaluation, so it does not
        # count).  The budget is reset by a user-applied constraint change.
        if (
            observation.tool == "build_itinerary"
            and observation.ok
            and reflect_on_evaluation(evaluation) == "REJECT_HARD"
        ):
            update["reflection_attempts"] = state.reflection_attempts + 1
        # P2.4 + E-1 P0: a passing gate emits the candidate deterministically —
        # the model never decides when to emit — but only when the evaluation
        # verdict is ACCEPT.  An unresolved hard validation FAIL (NEEDS_REPAIR
        # with failures, S2) must not ride to EMITTED on a structural-gate
        # pass.
        if (
            observation.tool == "validate_itinerary"
            and observation.ok
            and reflect_on_evaluation(
                update.get("plan_evaluation", state.plan_evaluation)
            )
            == "ACCEPT"
        ):
            update["stop_reason"] = "EMITTED"
        return update

    def _route(self, state: AgentState) -> str:
        if state.stop_reason is not None:
            return "finish"
        if state.answer is not None:
            return "finish"
        if state.pending_call is None:
            return "finish"
        return "act"

    async def _finish_node(self, state: AgentState) -> dict[str, Any]:
        if state.stop_reason is None:
            return {"stop_reason": "ANSWERED" if state.answer else "STOPPED"}
        return {}


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    """What the caller needs after a run."""

    slots: Any
    observations: tuple[Any, ...]
    pending_question: str | None
    pending_options: tuple[str, ...] | None
    pending_expected_type: str | None
    answer: str | None
    stop_reason: str | None
    steps: int
    itinerary: dict[str, Any] | None = None


async def run_agent(
    loop: AgentLoop,
    state: AgentState | None = None,
    *,
    checkpoint_sink: Callable[[AgentState], Awaitable[None]] | None = None,
) -> AgentRunResult:
    """Execute one bounded agent run and summarise the outcome.

    With ``checkpoint_sink`` the run streams node-by-node and hands the
    accumulated state to the sink after every node — the P1.7 persistence
    hook; without one, the plain invoke path is unchanged.
    """
    app = loop.compile()
    initial = state or AgentState()
    if checkpoint_sink is None:
        final = await app.ainvoke(initial)
        if isinstance(final, dict):
            final = AgentState(**final)
    else:
        field_names = {field.name for field in fields(AgentState)}
        current = initial
        async for snapshot in app.astream(initial, stream_mode="values"):
            current = AgentState(
                **{
                    key: value
                    for key, value in dict(snapshot).items()
                    if key in field_names
                }
            )
            await checkpoint_sink(current)
        final = current
    return AgentRunResult(
        slots=final.slots,
        observations=final.observations,
        pending_question=final.pending_question,
        pending_options=final.pending_options,
        pending_expected_type=final.pending_expected_type,
        answer=final.answer,
        stop_reason=final.stop_reason,
        steps=final.steps,
        itinerary=final.candidate_itinerary,
    )


def with_answer(state: AgentState, answer: str) -> AgentState:
    """Resume helper: clear the pending question and record the answer."""
    return replace(state, pending_question=None, answer=answer)
