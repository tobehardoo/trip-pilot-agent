"""P1.9: the production decision-maker factory and its HTTP transport.

The factory is the single sanctioned construction point: configured
``STRUCTURED_MODEL_*`` yields a model-backed decider over the shared
credential surface; missing or partial configuration yields the
deterministic ``AskingDecider``.  HTTP fakes use ``httpx.MockTransport`` —
the project runs no pytest-asyncio plugin, so async paths go through
``run_async``.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from trip_agent.agent import (
    AgentLoop,
    AgentState,
    AskingDecider,
    StructuredOutputDecider,
    ToolRegistry,
    ToolRuntime,
    build_decision_maker,
    run_agent,
)
from trip_agent.agent.factory import DecisionModelConfig, HttpDecisionTransport
from trip_agent.platform_util import run_async

ENV: dict[str, str] = {
    "STRUCTURED_MODEL_ENDPOINT": "https://llm.example.com/v1/chat/completions",
    "STRUCTURED_MODEL_API_KEY": "secret-key",
    "STRUCTURED_MODEL_NAME": "decision-model",
}


def _registry() -> ToolRegistry:
    return ToolRegistry.with_runtime(ToolRuntime())


def _decision_body(payload: dict[str, Any]) -> httpx.Response:
    content = json.dumps(payload, ensure_ascii=False)
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


# ── configuration resolution ────────────────────────────────────────


def test_without_configuration_the_factory_returns_the_asking_decider() -> None:
    assert isinstance(build_decision_maker(tools=_registry(), env={}), AskingDecider)


def test_incomplete_environment_yields_no_config() -> None:
    assert DecisionModelConfig.from_env({}) is None
    assert (
        DecisionModelConfig.from_env(
            {"STRUCTURED_MODEL_ENDPOINT": "https://x", "STRUCTURED_MODEL_API_KEY": "k"}
        )
        is None
    )


def test_config_reads_the_shared_environment_surface() -> None:
    config = DecisionModelConfig.from_env(
        {
            **ENV,
            "STRUCTURED_MODEL_TIMEOUT_SECONDS": "12",
            "STRUCTURED_MODEL_MAX_INPUT_CHARACTERS": "5000",
        }
    )
    assert config is not None
    assert config.endpoint == ENV["STRUCTURED_MODEL_ENDPOINT"]
    assert config.model == "decision-model"
    assert config.timeout_seconds == 12.0
    assert config.max_input_characters == 5000


def test_out_of_band_config_is_refused() -> None:
    with pytest.raises(ValueError):
        DecisionModelConfig(
            endpoint="https://llm.example.com", api_key="k", model="m", timeout_seconds=0
        )
    with pytest.raises(ValueError):
        DecisionModelConfig(
            endpoint="https://llm.example.com",
            api_key="k",
            model="m",
            max_input_characters=200,
        )


def test_non_https_endpoint_is_refused() -> None:
    config = DecisionModelConfig(endpoint="http://llm.example.com", api_key="k", model="m")
    with pytest.raises(ValueError):
        HttpDecisionTransport(config=config, http_client=httpx.AsyncClient())


# ── the wired model-backed path ─────────────────────────────────────


def test_the_wired_decider_reaches_the_model_and_decides() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _decision_body(
            {
                "thought": "需要先确认城市",
                "tool": "ask_user",
                "args": {"question": "你想去哪个城市？"},
                "answer": None,
            }
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    decider = build_decision_maker(tools=_registry(), env=ENV, http_client=client)
    assert isinstance(decider, StructuredOutputDecider)

    decision = run_async(decider.decide(AgentState()))
    assert decision.call is not None and decision.call.tool == "ask_user"
    assert decision.call.args["question"] == "你想去哪个城市？"

    [request] = requests
    assert request.headers["Authorization"] == "Bearer secret-key"
    body = json.loads(request.content)
    assert body["model"] == "decision-model"
    schema = body["response_format"]["json_schema"]
    assert schema["name"] == "trip_pilot_agent_decision"
    assert schema["schema"]["required"] == ["thought", "tool", "args", "answer"]


def test_transport_http_error_degrades_instead_of_raising() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500, text="boom"))
    )
    decider = build_decision_maker(tools=_registry(), env=ENV, http_client=client)
    decision = run_async(decider.decide(AgentState()))
    assert decision.call is not None and decision.call.tool == "ask_user"
    assert decision.call.args["question"] == "你想去哪个城市？"


def test_transport_truncates_the_prompt_to_the_configured_bound() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["content"] = json.loads(request.content)["messages"][1]["content"]
        return _decision_body({"thought": "t", "tool": None, "args": {}, "answer": "好"})

    config = DecisionModelConfig(
        endpoint="https://llm.example.com",
        api_key="k",
        model="m",
        max_input_characters=1_000,
    )
    transport = HttpDecisionTransport(
        config=config, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    run_async(
        transport.extract(content="成都" * 800, json_schema={}, timeout_seconds=8.0)
    )
    assert len(captured["content"]) == 1_000
    assert captured["content"].startswith("成都成都")


def test_no_key_factory_feeds_a_converging_agent_loop() -> None:
    loop = AgentLoop(
        decider=build_decision_maker(tools=_registry(), env={}),
        tools=_registry(),
    )
    result = run_async(run_agent(loop))
    assert result.stop_reason == "WAITING_USER"
    assert result.pending_question == "你想去哪个城市？"
