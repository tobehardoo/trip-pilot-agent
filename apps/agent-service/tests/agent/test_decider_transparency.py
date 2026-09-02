"""AUDIT-03 防回归：decider 语义透明化。

health/metrics 必须能如实报告实际决策器，未配置模型时不得宣称完整 LLM Agent。
"""
from __future__ import annotations

from trip_agent.agent.factory import (
    DECIDER_KIND_DETERMINISTIC,
    DECIDER_KIND_STRUCTURED,
    resolve_decider_kind,
)


def test_no_model_config_reports_deterministic() -> None:
    assert resolve_decider_kind(env={}) == DECIDER_KIND_DETERMINISTIC
    assert resolve_decider_kind(env=None) == DECIDER_KIND_DETERMINISTIC


def test_partial_model_config_still_reports_deterministic() -> None:
    # 三个身份字段缺一即视为未配置（半配置不得 half-start）。
    assert resolve_decider_kind(env={"STRUCTURED_MODEL_ENDPOINT": "https://x.example"}) == (
        DECIDER_KIND_DETERMINISTIC
    )


def test_full_model_config_reports_structured() -> None:
    assert resolve_decider_kind(
        env={
            "STRUCTURED_MODEL_ENDPOINT": "https://x.example",
            "STRUCTURED_MODEL_API_KEY": "k",
            "STRUCTURED_MODEL_NAME": "m",
        }
    ) == DECIDER_KIND_STRUCTURED