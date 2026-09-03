"""CP-SAT day-schedule optimizer — an exact alternative to the greedy filler.

The greedy ``_fill_slots`` places candidates in score order with a first-fit
cursor walk.  That is deterministic and fast, but it can strand capacity: one
long high-score activity can block two shorter ones whose combined score is
higher.  This module models the *same* feasible space — slot capacity
including pace/mobility discounts, inter-item buffer, VERIFIED opening
windows and closures, must-include obligations — and lets CP-SAT choose the
selection and ordering exactly, so the best feasible combination is found.

Feasible-space mirror, item by item against the greedy path:

* a slot whose raw length is below ``MIN_SLOT_MINUTES`` is skipped; the
  RELAXED / mobility-reduced capacity discount then shrinks the *packable*
  end of the slot (deliberate slack stays empty), exactly like the greedy
  cursor walk which never packs past ``low + capacity``;
* unconstrained candidates must end by the discounted packable end;
  VERIFIED_WINDOW candidates may run to the slot's raw end (the greedy
  opening placement checks against ``slot_high``, not the discounted
  capacity) — in both paths a must-include-style opening item still
  partitions the slot through the pairwise buffer disjunction;
* VERIFIED_CLOSED candidates are excluded for the day;
* a USER-required ``must_include`` candidate is forced selected; if that
  makes the model infeasible the dispatcher falls back to greedy so the
  upstream capacity-repair machinery sees exactly the situation it knows.

Determinism and fail-safety:

* fixed random seed, single worker, bounded solve time — same input, same plan;
* any solver failure falls back to the greedy result.  Planning can get
  slower, never broken, because a plan that fails here fails identically
  under the greedy path the pipeline already knows how to repair.

Scheduler selection (``PLANNING_DAY_SCHEDULER``, resolved per dispatch):

* ``GREEDY`` (default) — the historical behavior, zero solver involvement;
* ``CPSAT``            — CP-SAT selection with greedy fallback;
* ``SHADOW``           — greedy result is authoritative and returned; CP-SAT
  runs alongside and the comparison is logged, so the benchmark and production
  traffic both gather evidence before the main path switches.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any, Literal

# ortools is an OPTIONAL dependency: the default GREEDY scheduler must run on
# installs without it, so the import is guarded and only CPSAT/SHADOW require
# the package (fail-loud with a clear message — never a raw ModuleNotFoundError).
try:
    from ortools.sat.python import cp_model
except ImportError:  # pragma: no cover - exercised only on ortools-less installs
    cp_model = None  # type: ignore[assignment]

from trip_agent.planning.daily_schedule import (
    BUFFER_BETWEEN_MINUTES,
    MIN_SLOT_MINUTES,
    RELAXED_SLOT_CAPACITY_DISCOUNT_MINUTES,
    CandidateActivity,
    OpeningAvailability,
    PlacedActivity,
    _activity_duration_minutes,
    _fill_slots,
)

logger = logging.getLogger(__name__)


def _require_cp_model() -> None:
    """Fail loudly when CPSAT/SHADOW is selected but ortools is not installed.

    The caller's generic solver-failure fallback must not silently swallow a
    missing package: an operator who explicitly chose CPSAT gets a clear
    config error, never a quiet greedy plan.
    """
    if cp_model is None:
        raise ValueError(
            "PLANNING_DAY_SCHEDULER=CPSAT/SHADOW requires the optional "
            "'ortools' package; install it or keep GREEDY"
        )

DayScheduler = Literal["GREEDY", "CPSAT", "SHADOW"]

SCHEDULER_ENV_VAR = "PLANNING_DAY_SCHEDULER"
CPSAT_TIME_LIMIT_ENV_VAR = "PLANNING_CPSAT_TIME_LIMIT_SECONDS"
DEFAULT_CPSAT_TIME_LIMIT_SECONDS = 5.0

# Objective bonus for a candidate whose region matches the day's primary
# region.  The greedy path *prefers* primary-region candidates ahead of the
# score sort; as a soft bonus this keeps coherence without overriding the
# capacity-optimal selection.
REGION_COHERENCE_BONUS = 40

# Per-selected-item reward.  Mirrors the greedy path's capacity-driven fill:
# candidates with score 0 are still placed when they fit (the evaluator scores
# them downstream), so an empty selection must never beat a filled slot.
PLACEMENT_REWARD = 1

# Objective layering: score terms are scaled so that any 1-point score
# difference outweighs the entire earliest-first tie-break spread (a full
# day of minutes is <= 1440 << _SCORE_WEIGHT), and the tie-break in turn
# never affects which candidates are selected.  This keeps the exact
# scheduler's "don't idle the morning, cram the afternoon" habit aligned
# with the greedy earliest-first placement without touching optimality.
_SCORE_WEIGHT = 100_000


def resolve_day_scheduler(env: Mapping[str, str] | None = None) -> DayScheduler:
    """Resolve the day-scheduler selection from the environment.

    Unset means ``GREEDY`` — the historical behavior.  An explicitly invalid
    value raises: a typo silently degrading to greedy would make the benchmark
    and the shadow evidence lie about which scheduler ran (fail-loud, mirroring
    ``resolve_provider_mode``).
    """
    source = os.environ if env is None else env
    raw = (source.get(SCHEDULER_ENV_VAR) or "").strip().upper()
    if not raw:
        return "GREEDY"
    if raw in ("GREEDY", "CPSAT", "SHADOW"):
        return raw  # type: ignore[return-value]
    raise ValueError(f"Invalid {SCHEDULER_ENV_VAR}: {raw!r} (expected GREEDY/CPSAT/SHADOW)")


def _cpsat_time_limit_seconds(env: Mapping[str, str] | None = None) -> float:
    source = os.environ if env is None else env
    raw = (source.get(CPSAT_TIME_LIMIT_ENV_VAR) or "").strip()
    if not raw:
        return DEFAULT_CPSAT_TIME_LIMIT_SECONDS
    value = float(raw)
    if value <= 0:
        raise ValueError(f"{CPSAT_TIME_LIMIT_ENV_VAR} must be positive, got {raw!r}")
    return value


def choose_activities_cpsat(
    candidates: tuple[CandidateActivity, ...],
    slots: tuple[tuple[int, int], ...],
    *,
    day_type: str,
    pace: str,
    mobility_reduced: bool,
    primary_region: str | None,
) -> tuple[PlacedActivity, ...]:
    """Select and place candidates with CP-SAT; fall back to greedy on failure.

    ``day_type`` is accepted for signature parity with ``choose_activities``;
    the SPECIAL_ACTIVITY_DAY main-slot placement is owned by the caller, so
    only the remaining-slot fill arrives here.
    """
    _require_cp_model()
    try:
        solved = _solve(
            candidates,
            slots,
            pace=pace,
            mobility_reduced=mobility_reduced,
            primary_region=primary_region,
        )
    except Exception:
        logger.exception("cpsat scheduler failed unexpectedly; falling back to greedy")
        return _greedy(
            candidates,
            slots,
            pace=pace,
            mobility_reduced=mobility_reduced,
            primary_region=primary_region,
        )
    if solved is None:
        logger.info(
            "cpsat scheduler returned no solution (infeasible or time limit);"
            " falling back to greedy"
        )
        return _greedy(
            candidates,
            slots,
            pace=pace,
            mobility_reduced=mobility_reduced,
            primary_region=primary_region,
        )
    return solved


def choose_activities_shadow(
    candidates: tuple[CandidateActivity, ...],
    slots: tuple[tuple[int, int], ...],
    *,
    day_type: str,
    pace: str,
    mobility_reduced: bool,
    primary_region: str | None,
) -> tuple[PlacedActivity, ...]:
    """Run both schedulers; return the greedy result and log the comparison.

    Shadow is the evidence-gathering mode: production behavior cannot change,
    but every dispatched day contributes a greedy-vs-CP-SAT data point to the
    logs, feeding the switch decision with real traffic instead of only the
    offline benchmark.
    """
    _require_cp_model()
    greedy = _greedy(
        candidates,
        slots,
        pace=pace,
        mobility_reduced=mobility_reduced,
        primary_region=primary_region,
    )
    try:
        cpsat = _solve(
            candidates,
            slots,
            pace=pace,
            mobility_reduced=mobility_reduced,
            primary_region=primary_region,
        )
    except Exception:
        logger.exception("cpsat shadow run failed; greedy result unaffected")
        return greedy
    cpsat_summary = "no-solution" if cpsat is None else _summary(cpsat)
    logger.info(
        "day scheduler shadow: greedy=%s cpsat=%s slots=%d candidates=%d",
        _summary(greedy),
        cpsat_summary,
        len(slots),
        len(candidates),
    )
    return greedy


def _summary(placed: tuple[PlacedActivity, ...]) -> str:
    score = sum(item.candidate.score for item in placed)
    minutes = sum(item.end_minute - item.start_minute for item in placed)
    return f"score={score} items={len(placed)} minutes={minutes}"


def _greedy(
    candidates: tuple[CandidateActivity, ...],
    slots: tuple[tuple[int, int], ...],
    *,
    pace: str,
    mobility_reduced: bool,
    primary_region: str | None,
) -> tuple[PlacedActivity, ...]:
    return _fill_slots(
        candidates,
        slots,
        pace=pace,  # type: ignore[arg-type]
        mobility_reduced=mobility_reduced,
        primary_region=primary_region,
    )


def _slot_capacity(raw_capacity: int, *, pace: str, mobility_reduced: bool) -> int:
    """Mirror the greedy capacity accounting: filter first, then discount."""
    if raw_capacity < MIN_SLOT_MINUTES:
        return 0
    capacity = raw_capacity
    if mobility_reduced:
        capacity = max(MIN_SLOT_MINUTES, capacity - 30)
    if pace == "RELAXED":
        capacity = max(MIN_SLOT_MINUTES, capacity - RELAXED_SLOT_CAPACITY_DISCOUNT_MINUTES)
    return capacity


def _solve(
    candidates: tuple[CandidateActivity, ...],
    slots: tuple[tuple[int, int], ...],
    *,
    pace: str,
    mobility_reduced: bool,
    primary_region: str | None,
) -> tuple[PlacedActivity, ...] | None:
    """Build and solve the selection model; ``None`` means fall back to greedy."""
    buffer = BUFFER_BETWEEN_MINUTES[pace]  # type: ignore[index]
    durations = [_activity_duration_minutes(candidate) for candidate in candidates]

    # Packable slots: raw capacity filter first (greedy skips short slots
    # before any discount), then the pace/mobility discount shrinks the
    # packable end while the raw end stays available to VERIFIED_WINDOW items.
    packable: dict[int, tuple[int, int]] = {}
    for low, high in slots:
        capacity = _slot_capacity(high - low, pace=pace, mobility_reduced=mobility_reduced)
        if capacity == 0:
            continue
        packable[low] = (low + capacity, high)

    model = cp_model.CpModel()
    booleans: dict[tuple[int, int], cp_model.IntVar] = {}
    starts: dict[tuple[int, int], cp_model.IntVar] = {}

    for index, candidate in enumerate(candidates):
        opening: OpeningAvailability | None = candidate.opening
        if opening is not None and opening.kind == "VERIFIED_CLOSED":
            continue  # verified closure: excluded from this day entirely
        for low, (packable_end, raw_end) in packable.items():
            if raw_end - low < durations[index]:
                continue
            if opening is not None and opening.constrains_placement:
                has_legal_window = any(
                    min(window_high, raw_end) - max(window_low, low) >= durations[index]
                    for window_low, window_high in sorted(opening.windows)
                )
                if not has_legal_window:
                    continue  # no legal window inside this slot
            x = model.NewBoolVar(f"x_{index}_{low}")
            start = model.NewIntVar(low, raw_end, f"start_{index}_{low}")
            booleans[(index, low)] = x
            starts[(index, low)] = start
            windowed = opening is not None and opening.constrains_placement
            end_bound = raw_end if windowed else packable_end
            model.Add(start + durations[index] <= end_bound).OnlyEnforceIf(x)

    if not booleans:
        return None

    # A candidate runs at most once across all slots; must-include runs exactly
    # once (infeasibility here is the documented greedy-fallback trigger).
    for index in range(len(candidates)):
        vars_for_candidate = [x for (i, _), x in booleans.items() if i == index]
        if not vars_for_candidate:
            continue
        if candidates[index].must_include:
            model.Add(sum(vars_for_candidate) == 1)
        else:
            model.Add(sum(vars_for_candidate) <= 1)

    # VERIFIED_WINDOW: the placement must sit inside one verified window and
    # respect the last-entry bound (mirrors `_earliest_opening_placement`).
    for (index, low), x in booleans.items():
        opening = candidates[index].opening
        if opening is None or not opening.constrains_placement:
            continue
        raw_end = packable[low][1]
        start = starts[(index, low)]
        window_vars: list[cp_model.IntVar] = []
        for window_index, (window_low, window_high) in enumerate(sorted(opening.windows)):
            start_bound = max(window_low, low)
            end_bound = min(window_high, raw_end)
            if end_bound - start_bound < durations[index]:
                continue
            y = model.NewBoolVar(f"w_{index}_{low}_{window_index}")
            window_vars.append(y)
            model.Add(start >= start_bound).OnlyEnforceIf(y)
            last_entry_cap = (
                min(opening.last_entry_minute, end_bound - durations[index])
                if opening.last_entry_minute is not None
                else end_bound - durations[index]
            )
            model.Add(start <= last_entry_cap).OnlyEnforceIf(y)
        if not window_vars:
            model.Add(x == 0)
        else:
            model.Add(sum(window_vars) == x)

    # Pairwise disjunction with the pace buffer between consecutive items —
    # the mirror of the greedy cursor's `needed = duration + buffer`.
    by_slot: dict[int, list[int]] = {}
    for index, low in booleans:
        by_slot.setdefault(low, []).append(index)
    for low, indexes in by_slot.items():
        for position, i in enumerate(indexes):
            for j in indexes[position + 1 :]:
                xi = booleans[(i, low)]
                xj = booleans[(j, low)]
                before = model.NewBoolVar(f"ord_{i}_{j}_{low}")
                model.Add(
                    starts[(j, low)] >= starts[(i, low)] + durations[i] + buffer
                ).OnlyEnforceIf([xi, xj, before])
                model.Add(
                    starts[(i, low)] >= starts[(j, low)] + durations[j] + buffer
                ).OnlyEnforceIf([xi, xj, before.Not()])

    # Objective, layered: (1) selection — score + region bonus + placement
    # reward, scaled by _SCORE_WEIGHT; (2) earliest-first tie-break — later
    # start minutes subtract a tiny amount so equal-score selections prefer
    # morning placements, mirroring the greedy cursor's earliest-first habit.
    def weight(index: int) -> int:
        bonus = (
            REGION_COHERENCE_BONUS
            if primary_region is not None and candidates[index].region == primary_region
            else 0
        )
        return candidates[index].score + bonus + PLACEMENT_REWARD

    objective_terms: list[Any] = []
    for (index, low), x in booleans.items():
        objective_terms.append(_SCORE_WEIGHT * weight(index) * x)
        effective_start = model.NewIntVar(0, 1440, f"estart_{index}_{low}")
        model.Add(effective_start == starts[(index, low)]).OnlyEnforceIf(x)
        model.Add(effective_start == 0).OnlyEnforceIf(x.Not())
        objective_terms.append(-effective_start)
    model.Maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = _cpsat_time_limit_seconds()
    solver.parameters.random_seed = 0
    solver.parameters.num_workers = 1
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    placed: list[PlacedActivity] = []
    for (index, low), x in booleans.items():
        if solver.Value(x):
            start = solver.Value(starts[(index, low)])
            placed.append(
                PlacedActivity(
                    candidate=candidates[index],
                    start_minute=start,
                    end_minute=start + durations[index],
                )
            )
    placed.sort(
        key=lambda item: (
            item.start_minute,
            item.end_minute,
            item.candidate.title,
            item.candidate.poi_id,
        )
    )
    return tuple(placed)
