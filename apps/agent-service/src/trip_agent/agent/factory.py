"""Production wiring for the agent loop's decision maker.

P1.9: the decider reuses the shared ``STRUCTURED_MODEL_*`` credential surface
already configured for guide-intelligence and dialog extraction — no new
credential plane appears.  Without that configuration the deterministic
``AskingDecider`` keeps the loop runnable and reproducible (ADR-007).

This module is the single sanctioned production construction point; the
run-entry wiring (P2.1) must build its decider through
:func:`build_decision_maker` rather than instantiating deciders directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from trip_agent.agent.graph import (
    AskingDecider,
    DecisionMaker,
    StructuredOutputDecider,
)
from trip_agent.agent.tools import ToolRegistry
from trip_agent.providers.settings import structured_model_config

DEFAULT_TIMEOUT_SECONDS = 8.0
DEFAULT_MAX_INPUT_CHARACTERS = 30_000

DECISION_SCHEMA_NAME = "trip_pilot_agent_decision"

# AUDIT-03：decider 语义透明化 —— 运行环境的实际决策器必须可被
# health/metrics 观测，避免「未接模型却表现成完整 LLM Agent」。
DECIDER_KIND_STRUCTURED = "STRUCTURED"
DECIDER_KIND_DETERMINISTIC = "DETERMINISTIC"

_DECISION_SYSTEM_PROMPT = (
    "你是 TripPilot 的旅行规划决策器。"
    "只输出符合给定 JSON Schema 的 JSON，不要输出任何其他内容。"
)


@dataclass(frozen=True, slots=True)
class DecisionModelConfig:
    """The shared structured-model configuration, resolved for decisions.

    Bounds mirror the guide-intelligence extractor: a bounded timeout and a
    bounded prompt keep one bad deployment setting from hanging or flooding
    the model endpoint.
    """

    endpoint: str
    api_key: str
    model: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_input_characters: int = DEFAULT_MAX_INPUT_CHARACTERS

    def __post_init__(self) -> None:
        if not 0 < self.timeout_seconds <= 60:
            raise ValueError("timeout_seconds must be between zero and 60")
        if not 1_000 <= self.max_input_characters <= 100_000:
            raise ValueError("max_input_characters must be between 1000 and 100000")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> DecisionModelConfig | None:
        """Read the shared ``STRUCTURED_MODEL_*`` surface.

        All three identity fields are required — a partially configured
        endpoint must not half-start.  Returns ``None`` when unconfigured,
        which the factory maps to the deterministic fallback.
        """
        shared = structured_model_config(env)
        if shared is None:
            return None
        return cls(
            endpoint=shared.endpoint,
            api_key=shared.api_key,
            model=shared.model,
            timeout_seconds=shared.timeout_seconds,
            max_input_characters=shared.max_input_characters,
        )


class HttpDecisionTransport:
    """Call the shared OpenAI-compatible structured endpoint for decisions.

    Mirrors the guide-intelligence transport's hard edges (HTTPS-only,
    bearer auth, strict json_schema response format) with a decision-shaped
    system prompt.  Secrets are never logged.
    """

    def __init__(
        self,
        *,
        config: DecisionModelConfig,
        http_client: httpx.AsyncClient,
    ) -> None:
        if not config.endpoint.startswith("https://"):
            raise ValueError("structured model endpoint must use HTTPS")
        self._config = config
        self._http_client = http_client

    async def extract(
        self,
        *,
        content: str,
        json_schema: dict[str, Any],
        timeout_seconds: float,
    ) -> object:
        response = await self._http_client.post(
            self._config.endpoint,
            headers={"Authorization": f"Bearer {self._config.api_key}"},
            json={
                "model": self._config.model,
                "messages": [
                    {"role": "system", "content": _DECISION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": content[: self._config.max_input_characters],
                    },
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": DECISION_SCHEMA_NAME,
                        "strict": True,
                        "schema": json_schema,
                    },
                },
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        return body["choices"][0]["message"]["content"]


def resolve_decider_kind(*, env: Mapping[str, str] | None = None) -> str:
    """报告当前部署实际使用的决策器（AUDIT-03）。

    ``STRUCTURED`` = 已配置共享模型，决策由 LLM 基于 State 产生；
    ``DETERMINISTIC`` = 无模型配置，决策退回确定性 AskingDecider（仅 Level 2
    Workflow 行为）。生产 Agent 闭环要求 STRUCTURED。
    """
    return (
        DECIDER_KIND_STRUCTURED
        if DecisionModelConfig.from_env(env) is not None
        else DECIDER_KIND_DETERMINISTIC
    )


def build_decision_maker(
    *,
    tools: ToolRegistry,
    env: Mapping[str, str] | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> DecisionMaker:
    """Construct the production decision maker from shared configuration.

    With ``STRUCTURED_MODEL_*`` configured this is a model-backed
    :class:`StructuredOutputDecider`; without it the deterministic
    :class:`AskingDecider` keeps the loop runnable with no provider keys.
    A malformed numeric setting or a plaintext endpoint raises — a
    misconfigured deployment must fail loudly rather than silently change
    behaviour.
    """
    config = DecisionModelConfig.from_env(env)
    if config is None:
        return AskingDecider()
    client = http_client or httpx.AsyncClient()
    return StructuredOutputDecider(
        transport=HttpDecisionTransport(config=config, http_client=client),
        tools=tools,
        timeout_seconds=config.timeout_seconds,
    )
