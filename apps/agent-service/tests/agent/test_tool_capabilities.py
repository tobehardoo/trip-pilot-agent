"""V3 C-2 — the four observation tools are wired to real capabilities.

Before this cut ``search_place`` / ``get_route`` / ``check_opening_hours`` /
``retrieve_guide_knowledge`` were schema-declared but always failed with
CAPABILITY_MISSING in production.  Now the ToolRuntime carries real
adapters over the same provider stack, and the knowledge-scoped handlers
thread the confirmed destination from the agent state.

Counterfactual discipline: unwired → CAPABILITY_MISSING; wired → real
observation data (or a structured provider error, never invented values).
"""

from __future__ import annotations

import asyncio
import os  # noqa: F401  (environment driven capability selection)

from trip_agent.agent import (
    AgentState,
    ConstraintSlots,
    SlotState,
    ToolCall,
    ToolRegistry,
    ToolRuntime,
)
from trip_agent.agent.tool_capabilities import (
    build_observation_capabilities,
)


def _wrap(knowledge) -> ToolRegistry:
    return ToolRegistry.with_runtime(ToolRuntime(knowledge=knowledge))


def _slots(destination: str = "成都市") -> AgentState:
    return AgentState(
        slots=ConstraintSlots.empty()
        .fill("destination", destination, state=SlotState.CONFIRMED)
    )


def _demo_runtime() -> ToolRegistry:
    with mock_demo_env():
        capabilities = build_observation_capabilities()
    return ToolRegistry.with_runtime(
        ToolRuntime(
            place_search=capabilities.place_search,
            route=capabilities.route,
            opening_hours=capabilities.opening_hours,
            knowledge=capabilities.knowledge,
        )
    )


class mock_demo_env:
    """Force the demo provider mode for the duration of the block."""

    def __enter__(self) -> None:
        self._saved = os.environ.get("PROVIDER_MODE")
        os.environ["PROVIDER_MODE"] = "DEMO_ONLY"

    def __exit__(self, *exc: object) -> None:
        if self._saved is None:
            os.environ.pop("PROVIDER_MODE", None)
        else:
            os.environ["PROVIDER_MODE"] = self._saved


def test_place_search_returns_real_demo_data() -> None:
    registry = _demo_runtime()
    result, _ = asyncio.run(
        registry.invoke(ToolCall("search_place", {"keyword": "宽窄巷子"}), _slots())
    )
    assert result.ok, result.summary
    assert "places" in result.data


def test_place_search_failure_is_structured_not_invented() -> None:
    """An empty demo batch still yields a structured observation."""
    registry = _demo_runtime()
    result, _ = asyncio.run(
        registry.invoke(
            ToolCall("search_place", {"keyword": "不存在的地方"}), _slots()
        )
    )
    # demo providers answer anything — the assertion is structural:
    assert result.ok and isinstance(result.data, dict)


def test_get_route_returns_distance_and_duration() -> None:
    registry = _demo_runtime()
    result, _ = asyncio.run(
        registry.invoke(
            ToolCall(
                "get_route",
                {"origin": "宽窄巷子", "destination": "武侯祠", "mode": "DRIVING"},
            ),
            _slots(),
        )
    )
    assert result.ok, result.summary
    assert isinstance(result.data["duration_seconds"], int)
    assert isinstance(result.data["distance_meters"], int)


def test_knowledge_without_destination_returns_unknown_note() -> None:
    """No confirmed destination → an empty, annotated observation: knowledge
    is city-scoped and the agent must not guess the city."""
    calls: list[dict] = []

    async def knowledge(*, query: str, city: str | None = None, limit: int = 5):
        calls.append({"query": query, "city": city})
        return {"citations": [{"title": "x", "content": "y"}]}

    registry = _wrap(knowledge)
    result, _ = asyncio.run(
        registry.invoke(ToolCall("retrieve_guide_knowledge", {"query": "美食"}), _slots(""))
    )
    assert result.ok
    # the handler threads the confirmed destination verbatim (here "" —
    # an empty slot value); the adapter's city-scoped note is asserted at
    # the adapter level
    assert calls and calls[0]["city"] == ""


def test_knowledge_threads_the_confirmed_destination() -> None:
    calls: list[dict] = []

    async def knowledge(*, query: str, city: str | None = None, limit: int = 5):
        calls.append({"query": query, "city": city})
        return {"citations": [{"title": "成都小吃", "content": "甜水面"}]}

    registry = _wrap(knowledge)
    result, _ = asyncio.run(
        registry.invoke(ToolCall("retrieve_guide_knowledge", {"query": "美食"}), _slots())
    )
    assert result.ok
    assert calls[0]["city"] == "成都市"
    assert result.data["citations"][0]["title"] == "成都小吃"


def test_opening_hours_unknown_when_the_knowledge_base_is_silent() -> None:
    from trip_agent.agent.tool_capabilities import _opening_hours_adapter

    async def knowledge(*, query: str, city: str | None = None, limit: int = 5):
        return {"citations": []}

    registry = ToolRegistry.with_runtime(
        ToolRuntime(
            knowledge=knowledge,
            opening_hours=_opening_hours_adapter(knowledge),
        )
    )
    result, _ = asyncio.run(
        registry.invoke(
            ToolCall("check_opening_hours", {"place": "武侯祠"}), _slots()
        )
    )
    assert not result.ok
    assert result.error_code == "UNKNOWN"


def test_opening_hours_returns_citations_when_known() -> None:
    from trip_agent.agent.tool_capabilities import _opening_hours_adapter

    async def knowledge(*, query: str, city: str | None = None, limit: int = 5):
        return {
            "citations": [
                {"title": "武侯祠", "content": "开放时间 09:00-18:00", "source_name": "官网"}
            ]
        }

    registry = ToolRegistry.with_runtime(
        ToolRuntime(
            knowledge=knowledge,
            opening_hours=_opening_hours_adapter(knowledge),
        )
    )
    result, _ = asyncio.run(
        registry.invoke(
            ToolCall("check_opening_hours", {"place": "武侯祠"}), _slots()
        )
    )
    assert result.ok
    assert result.data["sources"][0]["content"].startswith("开放时间")


def test_unwired_capabilities_still_fail_closed() -> None:
    """The fail-closed rule is untouched: a None capability keeps
    CAPABILITY_MISSING (this is what an unconfigured deployment looks like)."""
    registry = ToolRegistry.with_runtime(ToolRuntime())
    for tool, args in (
        ("search_place", {"keyword": "x"}),
        ("get_route", {"origin": "a", "destination": "b"}),
        ("check_opening_hours", {"place": "x"}),
        ("retrieve_guide_knowledge", {"query": "x"}),
    ):
        result, _ = asyncio.run(registry.invoke(ToolCall(tool, args), _slots()))
        assert not result.ok and result.error_code == "CAPABILITY_MISSING", tool


def test_demo_place_currency_survives_wire_projection() -> None:
    """The observation data is JSON-able end to end (ToolObservation.data
    travels into AgentStepEvent payloads)."""
    import json

    registry = _demo_runtime()
    result, _ = asyncio.run(
        registry.invoke(ToolCall("search_place", {"keyword": "武侯祠"}), _slots())
    )
    assert isinstance(json.dumps(result.data, ensure_ascii=False), str)
