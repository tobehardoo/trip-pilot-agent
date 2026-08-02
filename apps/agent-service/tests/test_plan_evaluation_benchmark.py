from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = SERVICE_ROOT / "benchmarks" / "run_plan_evaluation.py"
SCENARIO_DIRECTORY = SERVICE_ROOT / "benchmarks" / "plan_evaluation"


def _load_runner():
    spec = importlib.util.spec_from_file_location("plan_evaluation_benchmark", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_benchmark_contains_eight_named_scenarios() -> None:
    scenarios = sorted(SCENARIO_DIRECTORY.glob("*.json"))

    assert [scenario.stem for scenario in scenarios] == [
        "budget-near-limit",
        "clean-real",
        "estimated-transit",
        "fixed-appointment",
        "high-daily-load",
        "long-walking",
        "mixed-provider-fallback",
        "tight-transfer",
    ]


def test_benchmark_runner_is_deterministic_and_meets_all_expectations() -> None:
    runner = _load_runner()

    first = runner.run_all(SCENARIO_DIRECTORY)
    repeated = runner.run_all(SCENARIO_DIRECTORY)

    assert first == repeated
    assert len(first) == 8
    assert all(result.passed for result in first)
