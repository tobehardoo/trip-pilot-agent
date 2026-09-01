"""P3.4: the agent trajectory benchmark — Gate 2's measurability harness.

Every scenario replays a scripted conversation through the production
processor stack (real demo builder, real structural gate) and asserts the
bounded-loop invariants.  Runs offline: no keys, no database.
"""

import sys
from pathlib import Path

BENCHMARK_DIRECTORY = Path(__file__).resolve().parents[1] / "benchmarks" / "agent_trajectory"
sys.path.insert(0, str(BENCHMARK_DIRECTORY))

from run_agent_trajectory import SCENARIOS, run_all, run_scenario  # noqa: E402


def test_every_scenario_replays_within_the_invariants() -> None:
    reports = run_all()
    assert len(reports) == len(SCENARIOS)
    for report in reports:
        assert report["ok"], f"{report['name']}: {report['violations']}"


def test_happy_path_emits_a_gated_itinerary() -> None:
    scenario = next(s for s in SCENARIOS if s.name == "happy-path-emit")
    report = run_scenario(scenario)
    assert report["stop_reason"] == "EMITTED"


def test_scenarios_are_registered_for_replay() -> None:
    names = {scenario.name for scenario in SCENARIOS}
    assert {
        "happy-path-emit",
        "clarification-loop",
        "rejected-value",
        "infeasible-must-visit",
        "boundary-dates",
    } <= names
