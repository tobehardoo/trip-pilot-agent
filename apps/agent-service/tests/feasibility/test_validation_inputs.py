"""B5 Phase 2 — transient ValidationInputs model and ValidationContext wiring."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from plan_evaluation_support import make_activity, make_command, make_result

from trip_agent.feasibility.context import ValidationContext, build_budget_context
from trip_agent.feasibility.inputs import (
    ActivityLocator,
    MealPlacementBinding,
    MealProjectionState,
    MealWindowType,
    OpeningHoursBinding,
    ValidationInputs,
    VisitDurationBinding,
)
from trip_agent.guide_intelligence.opening_evidence import OpeningHoursEvidence
from trip_agent.planning.visit_duration import (
    DurationProfileSource,
    VisitDurationProfile,
)
from trip_agent.worker.contracts import Itinerary, ItineraryDay

_TS = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _evidence(poi_key: str = "POI-1") -> OpeningHoursEvidence:
    return OpeningHoursEvidence(
        kind="OPENING_HOURS",
        poi_key=poi_key,
        parsed_hours=None,
        raw="09:00-18:00",
        effective_date=None,
        source_ref="amap:1",
        reliability_level="PROVIDER",
        source_reviewed=False,
        hard_constraint_eligible=False,
        confidence=0.8,
        checked_at=datetime(2026, 8, 1, tzinfo=UTC),
        expires_at=datetime(2026, 8, 15, tzinfo=UTC),
    )


def _profile(*, eligible: bool = False) -> VisitDurationProfile:
    return VisitDurationProfile(
        min_minutes=90,
        recommended_minutes=150,
        max_minutes=180,
        source=(
            DurationProfileSource.OFFICIAL_FACT
            if eligible
            else DurationProfileSource.CATEGORY_PROFILE
        ),
        source_ref="official:1" if eligible else "category:normal",
        confidence=0.9 if eligible else 0.5,
        profile_version="category-profile-v1",
        hard_constraint_eligible=eligible,
    )


def _opening_binding(
    day: int = 0,
    activity: int = 0,
    poi_key: str = "POI-1",
) -> OpeningHoursBinding:
    return OpeningHoursBinding(
        activity=ActivityLocator(day_index=day, activity_index=activity),
        poi_key=poi_key,
        evidences=(_evidence(poi_key),),
    )


def _duration_binding(day: int = 0, activity: int = 0) -> VisitDurationBinding:
    return VisitDurationBinding(
        activity=ActivityLocator(day_index=day, activity_index=activity),
        profile=_profile(),
    )


def _meal_binding(
    day: int = 0,
    activity: int = 0,
    meal_type: MealWindowType = MealWindowType.LUNCH,
) -> MealPlacementBinding:
    return MealPlacementBinding(
        activity=ActivityLocator(day_index=day, activity_index=activity),
        meal_type=meal_type,
    )


# ── ActivityLocator ────────────────────────────────────────────────────────


def test_locator_rejects_bool_and_negative_indices() -> None:
    with pytest.raises((TypeError, ValueError)):
        ActivityLocator(day_index=True, activity_index=0)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ActivityLocator(day_index=-1, activity_index=0)
    with pytest.raises(ValueError):
        ActivityLocator(day_index=0, activity_index=-2)


def test_locator_is_frozen() -> None:
    locator = ActivityLocator(day_index=0, activity_index=1)
    with pytest.raises(AttributeError):
        locator.day_index = 1  # type: ignore[misc]


# ── bindings ───────────────────────────────────────────────────────────────


def test_opening_binding_snapshots_list_input() -> None:
    binding = OpeningHoursBinding(
        activity=ActivityLocator(day_index=0, activity_index=0),
        poi_key="POI-1",
        evidences=[_evidence()],
    )
    assert isinstance(binding.evidences, tuple)


def test_opening_binding_rejects_evidence_with_different_poi_key() -> None:
    with pytest.raises(ValueError):
        OpeningHoursBinding(
            activity=ActivityLocator(day_index=0, activity_index=0),
            poi_key="POI-1",
            evidences=(_evidence("OTHER-POI"),),
        )


def test_meal_window_type_is_real_enum() -> None:
    assert tuple(MealWindowType) == (
        MealWindowType.BREAKFAST,
        MealWindowType.LUNCH,
        MealWindowType.DINNER,
    )
    with pytest.raises((TypeError, ValueError)):
        _meal_binding(meal_type="LUNCH")  # type: ignore[arg-type]


def test_meal_projection_state_is_real_enum() -> None:
    assert tuple(MealProjectionState) == (
        MealProjectionState.UNAVAILABLE,
        MealProjectionState.COMPLETE,
    )


# ── ValidationInputs aggregates ────────────────────────────────────────────


def test_inputs_snapshot_all_lists() -> None:
    inputs = ValidationInputs(
        opening_hours_bindings=[_opening_binding()],
        visit_duration_bindings=[_duration_binding()],
        meal_placement_bindings=[_meal_binding()],
        meal_projection_state=MealProjectionState.UNAVAILABLE,
    )
    assert isinstance(inputs.opening_hours_bindings, tuple)
    assert isinstance(inputs.visit_duration_bindings, tuple)
    assert isinstance(inputs.meal_placement_bindings, tuple)


def test_inputs_reject_duplicate_locator_within_category() -> None:
    with pytest.raises(ValueError):
        ValidationInputs(
            opening_hours_bindings=(_opening_binding(), _opening_binding()),
            meal_projection_state=MealProjectionState.UNAVAILABLE,
        )
    with pytest.raises(ValueError):
        ValidationInputs(
            visit_duration_bindings=(_duration_binding(), _duration_binding()),
            meal_projection_state=MealProjectionState.UNAVAILABLE,
        )
    with pytest.raises(ValueError):
        ValidationInputs(
            meal_placement_bindings=(_meal_binding(), _meal_binding()),
            meal_projection_state=MealProjectionState.UNAVAILABLE,
        )


def test_inputs_reject_duplicate_meal_day_and_type() -> None:
    with pytest.raises(ValueError):
        ValidationInputs(
            meal_placement_bindings=(
                _meal_binding(day=0, activity=1),
                _meal_binding(day=0, activity=2),
            ),
            meal_projection_state=MealProjectionState.UNAVAILABLE,
        )


def test_inputs_cap_each_category_at_512() -> None:
    many = tuple(
        _opening_binding(day=0, activity=index, poi_key=f"POI-{index}") for index in range(513)
    )
    with pytest.raises(ValueError):
        ValidationInputs(
            opening_hours_bindings=many,
            meal_projection_state=MealProjectionState.UNAVAILABLE,
        )


def test_inputs_is_frozen() -> None:
    inputs = ValidationInputs(meal_projection_state=MealProjectionState.UNAVAILABLE)
    with pytest.raises(AttributeError):
        inputs.meal_projection_state = MealProjectionState.COMPLETE  # type: ignore[misc]


# ── ValidationContext wiring ───────────────────────────────────────────────


def _ctx(itinerary: Itinerary, inputs: ValidationInputs) -> ValidationContext:
    command = make_command()
    return ValidationContext(
        command=command,
        itinerary=itinerary,
        budget=build_budget_context(command, itinerary),
        validation_inputs=inputs,
        validation_time=_TS,
    )


def _itinerary_with_activities(*kinds: str) -> Itinerary:
    activities = tuple(
        make_activity(
            index,
            source="AMAP" if kind != "MEAL" else "DEMO",
            start_hour=9 + index * 2,
            kind=kind,
        )
        for index, kind in enumerate(kinds)
    )
    return Itinerary(
        title="inputs",
        days=(ItineraryDay(date=date(2026, 8, 1), activities=activities, transit_legs=()),),
        estimated_total_cost=Decimal("0"),
    )


def test_context_defaults_empty_inputs_and_none_time() -> None:
    command = make_command()
    itinerary = make_result().itinerary
    ctx = ValidationContext(
        command=command,
        itinerary=itinerary,
        budget=build_budget_context(command, itinerary),
    )
    assert ctx.validation_inputs is None
    assert ctx.validation_time is None


def test_context_rejects_unknown_day_index() -> None:
    itinerary = _itinerary_with_activities("ATTRACTION", "ATTRACTION")
    with pytest.raises(ValueError):
        _ctx(
            itinerary,
            ValidationInputs(
                opening_hours_bindings=(_opening_binding(day=5, activity=0),),
                meal_projection_state=MealProjectionState.UNAVAILABLE,
            ),
        )


def test_context_rejects_unknown_activity_index() -> None:
    itinerary = _itinerary_with_activities("ATTRACTION", "ATTRACTION")
    with pytest.raises(ValueError):
        _ctx(
            itinerary,
            ValidationInputs(
                opening_hours_bindings=(_opening_binding(day=0, activity=9),),
                meal_projection_state=MealProjectionState.UNAVAILABLE,
            ),
        )


def test_context_rejects_opening_poi_key_mismatch() -> None:
    itinerary = _itinerary_with_activities("ATTRACTION", "ATTRACTION")
    with pytest.raises(ValueError):
        _ctx(
            itinerary,
            ValidationInputs(
                opening_hours_bindings=(_opening_binding(poi_key="WRONG-POI"),),
                meal_projection_state=MealProjectionState.UNAVAILABLE,
            ),
        )


def test_context_rejects_duration_binding_on_structural_node() -> None:
    itinerary = _itinerary_with_activities("ACCOMMODATION", "ATTRACTION")
    with pytest.raises(ValueError):
        _ctx(
            itinerary,
            ValidationInputs(
                visit_duration_bindings=(_duration_binding(day=0, activity=0),),
                meal_projection_state=MealProjectionState.UNAVAILABLE,
            ),
        )


def test_context_rejects_meal_binding_on_non_meal_activity() -> None:
    itinerary = _itinerary_with_activities("ATTRACTION", "ATTRACTION")
    with pytest.raises(ValueError):
        _ctx(
            itinerary,
            ValidationInputs(
                meal_placement_bindings=(_meal_binding(day=0, activity=0),),
                meal_projection_state=MealProjectionState.COMPLETE,
            ),
        )


def test_context_accepts_well_formed_inputs_without_mutation() -> None:
    itinerary = _itinerary_with_activities("ATTRACTION", "MEAL")
    inputs = ValidationInputs(
        opening_hours_bindings=(_opening_binding(day=0, activity=0),),
        visit_duration_bindings=(_duration_binding(day=0, activity=0),),
        meal_placement_bindings=(_meal_binding(day=0, activity=1),),
        meal_projection_state=MealProjectionState.COMPLETE,
    )
    before = itinerary.model_dump_json(by_alias=True)
    _ctx(itinerary, inputs)
    assert itinerary.model_dump_json(by_alias=True) == before
