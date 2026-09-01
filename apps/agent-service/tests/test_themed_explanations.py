"""V3 P2-3 — themed user explanations assemble existing decisions only.

The product goal: the user sees "为什么这份方案适合你", not policy names.
``themed_user_explanations`` is pure read-side assembly over the already
emitted DecisionExplanation records — it invents nothing, computes nothing
and drops nothing from the underlying decisions.

Counterfactual discipline: a theme appears only when its decisions exist.
"""

from trip_agent.evaluation.explanations import (
    themed_user_explanations,
)
from trip_agent.evaluation.models import (
    DecisionExplanation,
    EvaluationEvidence,
)


def _decision(summary: str, *codes: str, reasons: tuple[str, ...] | None = None) -> DecisionExplanation:
    return DecisionExplanation(
        subject_type="PLAN",
        subject_id=None,
        summary=summary,
        reason_codes=codes,  # type: ignore[arg-type]
        reasons=reasons or tuple(f"{code}：{summary}" for code in codes),
        constraint_refs=(),
    )


def test_weather_budget_and_pace_group_into_themes() -> None:
    decisions = (
        _decision("第 2 天有暴雨，长距离步行已改为公交。", "TRANSIT_MODE"),
        _decision("预算紧张：超出门票上限的候选已降权。", "BUDGET_CONSTRAINT"),
        _decision("节奏为 RELAXED：每个观光时段预留休整余量。", "PACE_POLICY"),
    )

    themes = themed_user_explanations(decisions)

    topics = [theme.topic for theme in themes]
    assert topics == ["WEATHER", "BUDGET", "PACE"]
    by_topic = {theme.topic: theme for theme in themes}
    assert by_topic["WEATHER"].title == "天气调整"
    assert by_topic["BUDGET"].title == "预算控制"
    assert by_topic["PACE"].title == "旅行节奏"
    assert by_topic["PACE"].lines == ("节奏为 RELAXED：每个观光时段预留休整余量。",)


def test_removing_the_signal_removes_the_theme() -> None:
    """Counterfactual: no weather decision → no weather theme."""
    decisions = (_decision("预算紧张：候选已降权。", "BUDGET_CONSTRAINT"),)

    themes = themed_user_explanations(decisions)

    assert [theme.topic for theme in themes] == ["BUDGET"]


def test_semantic_governance_and_fixed_schedule_map_to_their_themes() -> None:
    decisions = (
        _decision("3 个召回候选不是可游览地点，未进入景点池。", "PROVIDER_CONSTRAINT"),
        _decision(
            "固定预约前一段改为驾车，保证准时到达。",
            "TRANSIT_MODE",
            "FIXED_APPOINTMENT",
            reasons=("到达确定性优先于预算舒适性。", "固定安排时间不可移动。"),
        ),
    )

    themes = themed_user_explanations(decisions)

    topics = [theme.topic for theme in themes]
    assert topics == ["FIXED_SCHEDULE", "POI_GOVERNANCE"]
    governance = themes[1]
    assert governance.title == "景点甄选"
    assert governance.lines == ("3 个召回候选不是可游览地点，未进入景点池。",)


def test_duplicate_summaries_deduplicate_within_a_theme() -> None:
    decisions = (
        _decision("同一段决策被记录两次。", "TRANSIT_MODE"),
        _decision("同一段决策被记录两次。", "TRANSIT_MODE"),
    )

    themes = themed_user_explanations(decisions)

    assert len(themes) == 1
    assert themes[0].lines == ("同一段决策被记录两次。",)


def test_decisions_carry_evidence_through() -> None:
    """Evidence stays attached to the underlying decisions — the theme is a
    view, not a flattening: the envelope numbers remain inspectable."""
    decision = DecisionExplanation(
        subject_type="PLAN",
        subject_id=None,
        summary="餐厅「贵餐厅」人均超包络：仍安排用餐。",
        reason_codes=("BUDGET_CONSTRAINT",),
        reasons=("餐厅人均消费超过当日餐费软包络。",),
        constraint_refs=(),
        evidence=(
            EvaluationEvidence(
                key="meal_envelope_per_person", label="单餐人均包络", value="37.50"
            ),
        ),
    )

    themes = themed_user_explanations((decision,))

    assert len(themes) == 1
    assert themes[0].topic == "BUDGET"
    # the underlying decision keeps its evidence for UI drill-down
    assert decision.evidence[0].value == "37.50"
