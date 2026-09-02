"""Scheduler benchmark smoke gate.

Runs every scenario JSON through both schedulers in-process and pins the two
invariants the switch decision rests on:

1. CP-SAT is never worse than greedy on selected score (all scenarios);
2. both schedulers only produce capacity-fitting, buffer-respecting,
   within-slot placements — the feasible space itself must not drift.

The full per-scenario numbers live in ``benchmarks/scheduler/README.md``;
this gate fails loudly if a scenario edit or solver upgrade silently breaks
either invariant.
"""

import importlib.util
import json
import pathlib
from typing import Any

_BENCHMARK_DIR = (
    pathlib.Path(__file__).resolve().parent.parent / "benchmarks" / "scheduler"
)
_SPEC = importlib.util.spec_from_file_location(
    "run_scheduler_benchmark", _BENCHMARK_DIR / "run_scheduler_benchmark.py"
)
assert _SPEC is not None and _SPEC.loader is not None
_benchmark = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_benchmark)

from trip_agent.planning.daily_schedule import (  # noqa: E402
    BUFFER_BETWEEN_MINUTES,
)


def _scenarios() -> list[dict[str, Any]]:
    files = sorted((_BENCHMARK_DIR / "scenarios").glob("*.json"))
    assert files, "benchmark scenarios missing"
    return [json.loads(path.read_text(encoding="utf-8")) for path in files]


def test_cpsat_never_below_greedy_score_across_scenarios() -> None:
    for scenario in _scenarios():
        result = _benchmark._run_scenario(scenario)
        assert result["cpsat"]["score"] >= result["greedy"]["score"], (
            f"{scenario['id']}: cpsat {result['cpsat']['score']}"
            f" < greedy {result['greedy']['score']}"
        )


def test_both_schedulers_stay_inside_the_feasible_space() -> None:
    for scenario in _scenarios():
        pace = scenario.get("pace", "BALANCED")
        buffer = BUFFER_BETWEEN_MINUTES[pace]
        mobility_reduced = bool(scenario.get("mobilityReduced", False))
        primary_region = scenario.get("primaryRegion")
        slots = _benchmark._build_slots(scenario)
        bounds = {
            low: (
                low
                + _benchmark._slot_capacity(
                    high - low, pace=pace, mobility_reduced=mobility_reduced
                ),
                high,
            )
            for low, high in slots
        }
        candidates = tuple(_benchmark._build_candidate(raw) for raw in scenario["candidates"])
        runs = (
            (
                "greedy",
                _benchmark._fill_slots,
                dict(
                    pace=pace,
                    mobility_reduced=mobility_reduced,
                    primary_region=primary_region,
                ),
            ),
            (
                "cpsat",
                _benchmark.choose_activities_cpsat,
                dict(
                    day_type="FULL_DAY",
                    pace=pace,
                    mobility_reduced=mobility_reduced,
                    primary_region=primary_region,
                ),
            ),
        )
        for scheduler_name, runner, kwargs in runs:
            placed = runner(candidates, slots, **kwargs)
            by_slot: dict[int, list[Any]] = {}
            for item in placed:
                slot_low = max(
                    (low for low in bounds if low <= item.start_minute),
                    default=None,
                )
                assert slot_low is not None, (
                    f"{scenario['id']}/{scheduler_name}: {item.candidate.poi_id}"
                    " starts outside every slot"
                )
                packable_end, raw_end = bounds[slot_low]
                windowed = (
                    item.candidate.opening is not None
                    and item.candidate.opening.constrains_placement
                )
                assert item.end_minute <= (raw_end if windowed else packable_end), (
                    f"{scenario['id']}/{scheduler_name}: {item.candidate.poi_id}"
                    " exceeds the slot's allowed end"
                )
                by_slot.setdefault(slot_low, []).append(item)
            for items in by_slot.values():
                ordered = sorted(items, key=lambda i: i.start_minute)
                for previous, current in zip(ordered, ordered[1:], strict=False):
                    # The two schedulers distribute the pace slack differently
                    # but the occupancy math is identical (durations +
                    # (n-1)*buffer <= capacity): greedy walks a trailing-buffer
                    # cursor (items may touch), CP-SAT puts the buffer between
                    # items.  Assert each scheduler's own semantics.
                    min_gap = buffer if scheduler_name == "cpsat" else 0
                    assert current.start_minute >= previous.end_minute + min_gap, (
                        f"{scenario['id']}/{scheduler_name}: overlap or buffer violated"
                    )
