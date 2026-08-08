"""Run deterministic PlanEvaluation benchmark scenarios.

Usage: python benchmarks/run_plan_evaluation.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal, Self
from uuid import UUID

SERVICE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = SERVICE_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from pydantic import BaseModel, ConfigDict, Field, model_validator  # noqa: E402

from trip_agent.domain.planning.protocols import PlanningResult  # noqa: E402
from trip_agent.evaluation.evaluator import PlanEvaluator  # noqa: E402
from trip_agent.evaluation.models import PlanEvaluation  # noqa: E402
from trip_agent.worker.contracts import (  # noqa: E402
    ActivityCoordinates,
    FallbackOperation,
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
    PlanningCreateCommand,
    TransitLeg,
)

type Profile = Literal[
    "budget-near-limit",
    "clean-real",
    "combined-load-transfer",
    "estimated-transit",
    "fixed-appointment",
    "high-daily-load",
    "long-walking",
    "mixed-provider-fallback",
    "tight-transfer",
]

FROZEN_NOW = datetime(2026, 8, 2, 0, 0, tzinfo=UTC)
ACTIVITY_IDS = tuple(UUID(int=10_000 + index) for index in range(16))
TRANSIT_IDS = tuple(UUID(int=20_000 + index) for index in range(16))

# Benchmark expectation dimension name → PlanEvaluation dimension attribute.
DIMENSION_ATTRS: dict[str, str] = {
    "constraintSatisfaction": "constraint_satisfaction",
    "timeFeasibility": "time_feasibility",
    "budgetFit": "budget_fit",
    "routeEfficiency": "route_efficiency",
    "interestMatch": "interest_match",
}


class BenchmarkExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    minimum_score: int = Field(ge=0, le=100)
    maximum_score: int = Field(ge=0, le=100)
    required_warnings: tuple[str, ...] = ()
    forbidden_warnings: tuple[str, ...] = ()
    required_dimensions: dict[str, tuple[int, int]] | None = Field(
        default=None, alias="requiredDimensions"
    )

    @model_validator(mode="after")
    def validate_score_range(self) -> Self:
        if self.minimum_score > self.maximum_score:
            raise ValueError("minimumScore must not exceed maximumScore")
        return self


class BenchmarkScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    profile: Profile
    expect: BenchmarkExpectation

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.id != self.profile:
            raise ValueError("scenario id must match profile")
        return self


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    scenario_id: str
    overall_score: int
    warning_codes: tuple[str, ...]
    passed: bool
    failures: tuple[str, ...]


class FrozenClock:
    @classmethod
    def now(cls, tz: object | None = None) -> datetime:
        return FROZEN_NOW


def load_scenario(path: Path) -> BenchmarkScenario:
    return BenchmarkScenario.model_validate_json(path.read_text(encoding="utf-8"))


def run_scenario(scenario: BenchmarkScenario) -> BenchmarkResult:
    command, result = _build_case(scenario.profile)
    evaluation = PlanEvaluator(clock=FrozenClock).evaluate(command, result)
    warnings = tuple(warning.code for warning in evaluation.warnings)
    failures: list[str] = []
    expected = scenario.expect
    if not expected.minimum_score <= evaluation.overall_score <= expected.maximum_score:
        failures.append(
            f"score {evaluation.overall_score} outside "
            f"[{expected.minimum_score}, {expected.maximum_score}]"
        )
    missing = tuple(code for code in expected.required_warnings if code not in warnings)
    if missing:
        failures.append(f"missing warnings: {', '.join(missing)}")
    forbidden = tuple(code for code in expected.forbidden_warnings if code in warnings)
    if forbidden:
        failures.append(f"forbidden warnings: {', '.join(forbidden)}")
    failures.extend(_check_required_dimensions(expected, evaluation))
    return BenchmarkResult(
        scenario_id=scenario.id,
        overall_score=evaluation.overall_score,
        warning_codes=warnings,
        passed=not failures,
        failures=tuple(failures),
    )


def _check_required_dimensions(
    expected: BenchmarkExpectation,
    evaluation: PlanEvaluation,
) -> list[str]:
    """Assert per-dimension scores against declared bands.

    A dimension that is None (not applicable) fails any declared band —
    the scenario contract must never rely on N/A normalisation.
    """
    if not expected.required_dimensions:
        return []
    failures: list[str] = []
    for name, (lo, hi) in expected.required_dimensions.items():
        attr = DIMENSION_ATTRS.get(name)
        if attr is None:
            failures.append(f"unknown required dimension: {name}")
            continue
        actual = getattr(evaluation.dimensions, attr)
        if actual is None:
            failures.append(f"dimension {name} is N/A but required in [{lo}, {hi}]")
        elif not lo <= actual <= hi:
            failures.append(f"dimension {name} = {actual} outside [{lo}, {hi}]")
    return failures


def run_all(directory: Path | None = None) -> tuple[BenchmarkResult, ...]:
    scenario_directory = directory or Path(__file__).with_name("plan_evaluation")
    scenario_paths = sorted(scenario_directory.glob("*.json"))
    return tuple(run_scenario(load_scenario(path)) for path in scenario_paths)


def _build_case(profile: Profile) -> tuple[PlanningCreateCommand, PlanningResult]:
    if profile == "clean-real":
        return _command(), _result(real=True)
    if profile == "budget-near-limit":
        return _command(), _result(estimated_total_cost=Decimal("900.00"), real=True)
    if profile == "estimated-transit":
        return _command(), _result()
    if profile == "fixed-appointment":
        schedule = ({
            "placeName": "Activity 1",
            "startTime": "2026-08-01T09:15:00Z",
            "endTime": "2026-08-01T09:45:00Z",
        },)
        return _command(fixed_schedules=schedule), _result(real=True)
    if profile == "high-daily-load":
        activities = tuple(
            _activity(index, kind="ATTRACTION") for index in range(5)
        )
        return _command(), _result(activities=activities)
    if profile == "long-walking":
        legs = (_transit(0, duration_seconds=1_800, distance_meters=2_400),)
        return _command(), _result(transit_legs=legs)
    if profile == "mixed-provider-fallback":
        fallback = _fallback()
        legs = (_transit(0, fallback=fallback),)
        return _command(), _result(transit_legs=legs, fallback_operations=(fallback,), real=True)
    if profile == "tight-transfer":
        activities = (
            _activity(0),
            _activity(1, start=datetime(2026, 8, 1, 10, 4, tzinfo=UTC)),
        )
        legs = (_transit(0, duration_seconds=180),)
        return _command(), _result(activities=activities, transit_legs=legs)
    if profile == "combined-load-transfer":
        return _combined_case()
    raise ValueError(f"unsupported benchmark profile: {profile}")


def _combined_case() -> tuple[PlanningCreateCommand, PlanningResult]:
    """Two 5.5-workload days with exactly one tight leg (slack 9 min) each.

    Overall 84 is locked by requiredDimensions: timeFeasibility must be
    exactly 34 while the other four dimensions stay applicable at 100 —
    no N/A normalisation allowed.
    """
    command = _command(preferences=("美食",), end_date="2026-08-02")
    days = (
        _combined_day(date(2026, 8, 1), activity_offset=0, transit_offset=0),
        _combined_day(date(2026, 8, 2), activity_offset=8, transit_offset=7),
    )
    return command, PlanningResult(
        provider="DEMO",
        itinerary=Itinerary(
            title="Benchmark itinerary",
            days=days,
            estimated_total_cost=Decimal("500.00"),
        ),
        fallback_operations=(),
    )


def _combined_day(
    day_date: date,
    *,
    activity_offset: int,
    transit_offset: int,
) -> ItineraryDay:
    """One day: ARRIVAL + 5×ATTRACTION + MEAL + ACCOMMODATION (workload 5.5).

    Activities run hourly from 09:00 with a 15-minute gap between each;
    the last leg has a 12-minute gap with a 3-minute transit → slack 9.
    Span 09:00–18:42 (≤ 12 h), total transit 180 s (≤ 1 h).
    """
    kinds = (
        "ARRIVAL",
        "ATTRACTION",
        "ATTRACTION",
        "ATTRACTION",
        "ATTRACTION",
        "ATTRACTION",
        "MEAL",
        "ACCOMMODATION",
    )
    starts = (
        (9, 0), (10, 15), (11, 30), (12, 45), (14, 0), (15, 15), (16, 30), (17, 42),
    )
    activities = tuple(
        _activity(
            activity_offset + index,
            kind=kind,
            type_code="050000",
            start=datetime(2026, 8, day_date.day, hour, minute, tzinfo=UTC),
        )
        for index, (kind, (hour, minute)) in enumerate(zip(kinds, starts, strict=True))
    )
    legs = tuple(
        _transit(
            transit_offset + index,
            duration_seconds=0 if index < 6 else 180,
            distance_meters=0 if index < 6 else 300,
            from_activity_index=index,
            to_activity_index=index + 1,
        )
        for index in range(7)
    )
    return ItineraryDay(
        date=day_date,
        activities=activities,
        transit_legs=legs,
    )


def _command(
    *,
    fixed_schedules: tuple[dict[str, object], ...] = (),
    preferences: tuple[str, ...] = (),
    end_date: str | None = None,
) -> PlanningCreateCommand:
    return PlanningCreateCommand.model_validate(
        {
            "eventType": "PLANNING_CREATE_REQUESTED",
            "schemaVersion": 2,
            "eventId": "08db18af-3dfe-4e3f-9e3e-2900d43385b4",
            "traceId": "8f5ef9c2-c194-4292-b847-5b9dcfda978b",
            "taskId": "b0642d34-e24f-4b24-9ea7-82a68a4be781",
            "tripId": "08be9aca-fb30-4309-aa4b-93c240f19d75",
            "occurredAt": "2026-07-14T03:00:00Z",
            "payload": {
                "taskType": "CREATE",
                "baselineTripVersion": 0,
                "idempotencyKey": "00000000-0000-4000-8000-000000000001",
                "trip": {
                    "title": "Benchmark trip",
                    "destination": "Guangzhou",
                    "startDate": "2026-08-01",
                    "endDate": end_date or "2026-08-01",
                    "status": "DRAFT",
                    "version": 0,
                    "constraints": {
                        "budgetAmount": 1000,
                        "travelers": 1,
                        "travelerType": "SOLO",
                        "pace": "BALANCED",
                        "preferences": list(preferences),
                        "fixedSchedules": list(fixed_schedules),
                        "schemaVersion": 2,
                    },
                },
            },
        }
    )


def _activity(
    index: int,
    *,
    start: datetime | None = None,
    real: bool = False,
    kind: str | None = None,
    type_code: str | None = None,
) -> ItineraryActivity:
    resolved_start = start or datetime(2026, 8, 1, 9 + index * 2, tzinfo=UTC)
    common = {
        "activity_id": ACTIVITY_IDS[index],
        "title": f"Activity {index + 1}",
        "start_time": resolved_start,
        "end_time": resolved_start + timedelta(hours=1),
        "estimated_cost": Decimal("0.00"),
    }
    if real:
        return ItineraryActivity(
            **common,
            source="AMAP",
            provider_poi_id=f"POI-{index + 1}",
            coordinates=ActivityCoordinates(longitude=113, latitude=23),
            address=f"Address {index + 1}",
            kind=kind,
            type_code=type_code,
        )
    return ItineraryActivity(**common, source="DEMO", kind=kind, type_code=type_code)


def _transit(
    index: int,
    *,
    duration_seconds: int = 300,
    distance_meters: int = 300,
    real: bool = False,
    fallback: FallbackOperation | None = None,
    from_activity_index: int | None = None,
    to_activity_index: int | None = None,
) -> TransitLeg:
    resolved_from = index if from_activity_index is None else from_activity_index
    resolved_to = index + 1 if to_activity_index is None else to_activity_index
    return TransitLeg(
        transit_id=TRANSIT_IDS[index],
        from_activity_index=resolved_from,
        to_activity_index=resolved_to,
        mode="WALKING",
        distance_meters=distance_meters,
        duration_seconds=duration_seconds,
        provider="AMAP" if real else "DEMO",
        estimated=not real,
        polyline=(ActivityCoordinates(longitude=113, latitude=23),),
        estimated_cost=Decimal("0.00"),
        cost_source="RULE_ESTIMATE" if real else "DEMO",
        fallback_operation=fallback,
    )


def _fallback() -> FallbackOperation:
    return FallbackOperation(
        operation="ROUTE",
        transit_id=TRANSIT_IDS[0],
        from_activity_id=ACTIVITY_IDS[0],
        to_activity_id=ACTIVITY_IDS[1],
        requested_mode="REAL_WITH_EXPLICIT_FALLBACK",
        actual_provider="DEMO",
        error_category="TIMEOUT",
        error_code="PROVIDER_TIMEOUT",
        retry_count=2,
    )


def _result(
    *,
    activities: tuple[ItineraryActivity, ...] | None = None,
    transit_legs: tuple[TransitLeg, ...] | None = None,
    estimated_total_cost: Decimal = Decimal("500.00"),
    real: bool = False,
    fallback_operations: tuple[FallbackOperation, ...] = (),
) -> PlanningResult:
    resolved_activities = activities or (_activity(0, real=real), _activity(1, real=real))
    resolved_legs = transit_legs
    if resolved_legs is None:
        resolved_legs = tuple(
            _transit(index, real=real) for index in range(len(resolved_activities) - 1)
        )
    return PlanningResult(
        provider="AMAP" if real else "DEMO",
        itinerary=Itinerary(
            title="Benchmark itinerary",
            days=(ItineraryDay(
                date=date(2026, 8, 1),
                activities=resolved_activities,
                transit_legs=resolved_legs,
            ),),
            estimated_total_cost=estimated_total_cost,
        ),
        fallback_operations=fallback_operations,
    )


def main() -> int:
    results = run_all()
    print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
