"""Greedy vs CP-SAT day-scheduler benchmark.

Runs every scenario in ``scenarios/*.json`` through both day schedulers —
the historical score-ordered greedy filler (``_fill_slots``) and the CP-SAT
exact selection (``cpsat_schedule.choose_activities_cpsat``) — over the
identical feasible space (slots split by meal demands, pace/mobility
capacity discounts) and reports:

* selected score and item count,
* packed minutes and utilization against the packable capacity,
* CP-SAT wall-clock solve time,
* per-scenario verdict (CPSAT better / tie / worse on score).

Deterministic by construction: scenarios are static JSON, the CP-SAT solver
is pinned to seed 0 / single worker.  No provider, database, or network.

Usage (repo-root relative):

    cd apps/agent-service
    .venv/Scripts/python.exe benchmarks/scheduler/run_scheduler_benchmark.py

Output: a markdown table on stdout plus ``results/latest.json`` for diffing
across runs.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

BENCHMARK_DIR = Path(__file__).resolve().parent
SCENARIO_DIR = BENCHMARK_DIR / "scenarios"
RESULTS_DIR = BENCHMARK_DIR / "results"

# Make the planning package importable when run as a script.
sys.path.insert(0, str(BENCHMARK_DIR.parent.parent / "src"))

from trip_agent.planning.cpsat_schedule import (  # noqa: E402
    _slot_capacity,
    choose_activities_cpsat,
)
from trip_agent.planning.daily_schedule import (  # noqa: E402
    BUFFER_BETWEEN_MINUTES,
    MealDemand,
    _fill_slots,
    _split_windows_by_meals,
)
from trip_agent.planning.visit_duration import (  # noqa: E402
    DurationProfileSource,
    VisitDurationProfile,
)


def _profile(minutes: int) -> VisitDurationProfile:
    return VisitDurationProfile(
        max(30, minutes - 60),
        minutes,
        minutes + 30,
        DurationProfileSource.CATEGORY_PROFILE,
        source_ref="benchmark:scenario",
        confidence=0.5,
        profile_version="benchmark-v1",
    )


def _build_candidate(raw: dict[str, Any]) -> Any:
    from trip_agent.planning.daily_schedule import CandidateActivity

    opening = None
    if raw_opening := raw.get("opening"):
        from trip_agent.planning.daily_schedule import OpeningAvailability

        opening = OpeningAvailability(
            kind=raw_opening["kind"],
            windows=tuple((w[0], w[1]) for w in raw_opening.get("windows", ())),
            last_entry_minute=raw_opening.get("lastEntryMinute"),
        )
    return CandidateActivity(
        poi_id=raw["poiId"],
        title=raw.get("title", raw["poiId"]),
        magnitude=raw.get("magnitude", "LIGHT"),
        region=raw.get("region"),
        must_include=bool(raw.get("mustInclude", False)),
        kind=raw.get("kind", "ATTRACTION"),
        score=int(raw.get("score", 0)),
        visit_duration_profile=_profile(int(raw["minutes"])),
        opening=opening,
    )


def _build_slots(scenario: dict[str, Any]) -> tuple[tuple[int, int], ...]:
    free_windows = tuple((w[0], w[1]) for w in scenario["freeWindows"])
    meals = tuple(
        MealDemand(
            meal_type=meal["mealType"],
            start_minute=int(meal["startMinute"]),
            end_minute=int(meal["endMinute"]),
        )
        for meal in scenario.get("meals", ())
    )
    buffer = BUFFER_BETWEEN_MINUTES[scenario.get("pace", "BALANCED")]
    return _split_windows_by_meals(free_windows, meals, buffer)


def _packable_minutes(
    slots: tuple[tuple[int, int], ...], *, pace: str, mobility_reduced: bool
) -> int:
    return sum(
        _slot_capacity(high - low, pace=pace, mobility_reduced=mobility_reduced)
        for low, high in slots
    )


def _packed_minutes(placed: tuple[Any, ...]) -> int:
    return sum(item.end_minute - item.start_minute for item in placed)


def _score(placed: tuple[Any, ...]) -> int:
    return sum(item.candidate.score for item in placed)


def _run_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    pace = scenario.get("pace", "BALANCED")
    mobility_reduced = bool(scenario.get("mobilityReduced", False))
    primary_region = scenario.get("primaryRegion")
    candidates = tuple(_build_candidate(raw) for raw in scenario["candidates"])
    slots = _build_slots(scenario)
    day_args = dict(
        day_type="FULL_DAY",
        pace=pace,
        mobility_reduced=mobility_reduced,
        primary_region=primary_region,
    )
    fill_args = dict(
        pace=pace,
        mobility_reduced=mobility_reduced,
        primary_region=primary_region,
    )

    greedy = _fill_slots(candidates, slots, **fill_args)
    started = time.perf_counter()
    cpsat = choose_activities_cpsat(candidates, slots, **day_args)
    solve_ms = (time.perf_counter() - started) * 1000

    packable = _packable_minutes(slots, pace=pace, mobility_reduced=mobility_reduced)
    return {
        "id": scenario["id"],
        "description": scenario.get("description", ""),
        "greedy": {
            "score": _score(greedy),
            "items": len(greedy),
            "packedMinutes": _packed_minutes(greedy),
            "utilization": round(_packed_minutes(greedy) / packable, 3) if packable else 0.0,
        },
        "cpsat": {
            "score": _score(cpsat),
            "items": len(cpsat),
            "packedMinutes": _packed_minutes(cpsat),
            "utilization": round(_packed_minutes(cpsat) / packable, 3) if packable else 0.0,
            "solveMs": round(solve_ms, 1),
        },
        "verdict": (
            "CPSAT_BETTER"
            if _score(cpsat) > _score(greedy)
            else "TIE"
            if _score(cpsat) == _score(greedy)
            else "CPSAT_WORSE"
        ),
    }


def _format_table(results: list[dict[str, Any]]) -> str:
    header = (
        "| scenario | greedy score/items/util | cpsat score/items/util"
        " | cpsat solve ms | verdict |"
    )
    separator = "| --- | --- | --- | --- | --- |"
    rows = []
    for result in results:
        greedy = result["greedy"]
        cpsat = result["cpsat"]
        rows.append(
            f"| {result['id']} "
            f"| {greedy['score']} / {greedy['items']} / {greedy['utilization']:.0%} "
            f"| {cpsat['score']} / {cpsat['items']} / {cpsat['utilization']:.0%} "
            f"| {cpsat['solveMs']} "
            f"| {result['verdict']} |"
        )
    return "\n".join((header, separator, *rows))


def main() -> int:
    scenario_files = sorted(SCENARIO_DIR.glob("*.json"))
    if not scenario_files:
        print(f"no scenarios found in {SCENARIO_DIR}", file=sys.stderr)
        return 1
    results = []
    for path in scenario_files:
        scenario = json.loads(path.read_text(encoding="utf-8"))
        results.append(_run_scenario(scenario))

    better = sum(1 for r in results if r["verdict"] == "CPSAT_BETTER")
    ties = sum(1 for r in results if r["verdict"] == "TIE")
    worse = sum(1 for r in results if r["verdict"] == "CPSAT_WORSE")
    max_solve = max((r["cpsat"]["solveMs"] for r in results), default=0.0)

    print(_format_table(results))
    print()
    print(
        f"total: {len(results)} scenarios — CPSAT_BETTER {better} / TIE {ties}"
        f" / CPSAT_WORSE {worse}; max cpsat solve {max_solve} ms"
    )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output = {
        "summary": {"better": better, "tie": ties, "worse": worse, "maxSolveMs": max_solve},
        "results": results,
    }
    (RESULTS_DIR / "latest.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
