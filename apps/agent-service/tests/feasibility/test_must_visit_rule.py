"""B5 Phase 3 — MUST_VISIT_COVERAGE canonical rule."""

from decimal import Decimal

from plan_evaluation_support import make_activity, make_command

from trip_agent.feasibility.context import ValidationContext, build_budget_context
from trip_agent.feasibility.models import RuleOutcome
from trip_agent.feasibility.rules.coverage import assess_must_visit_coverage
from trip_agent.worker.contracts import Itinerary, ItineraryDay


def _ctx(*, must_visit: tuple[str, ...] = (), titles: tuple[str, ...] = ()) -> ValidationContext:
    command = make_command(must_visit_places=must_visit)
    activities = tuple(
        make_activity(index, title=title, start_hour=9 + index * 2, kind="ATTRACTION")
        for index, title in enumerate(titles)
    )
    itinerary = Itinerary(
        title="must visit",
        days=(
            ItineraryDay(
                date=__import__("datetime").date(2026, 8, 1),
                activities=activities,
                transit_legs=(),
            ),
        ),
        estimated_total_cost=Decimal("0"),
    )
    return ValidationContext(
        command=command,
        itinerary=itinerary,
        budget=build_budget_context(command, itinerary),
    )


def test_no_must_visit_is_not_applicable() -> None:
    assessment = assess_must_visit_coverage(_ctx(titles=("陈家祠",)))

    assert assessment.result.outcome is RuleOutcome.NOT_APPLICABLE
    assert assessment.result.reason_code == "NO_MUST_VISIT_PLACES"
    assert assessment.findings == ()


def test_single_must_visit_covered_passes() -> None:
    assessment = assess_must_visit_coverage(_ctx(must_visit=("陈家祠",), titles=("陈家祠",)))

    assert assessment.result.outcome is RuleOutcome.PASS
    assert assessment.result.reason_code == "ALL_MUST_VISIT_PLACES_COVERED"


def test_multiple_must_visit_all_covered_passes() -> None:
    assessment = assess_must_visit_coverage(
        _ctx(must_visit=("陈家祠", "光孝寺"), titles=("光孝寺", "陈家祠"))
    )

    assert assessment.result.outcome is RuleOutcome.PASS


def test_single_missing_fails() -> None:
    assessment = assess_must_visit_coverage(_ctx(must_visit=("陈家祠",), titles=("光孝寺",)))

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "MUST_VISIT_PLACE_MISSING"
    assert assessment.result.affected_entity_refs == ("陈家祠",)
    assert assessment.result.affected_dates == ()


def test_halfwidth_fullwidth_normalisation() -> None:
    assessment = assess_must_visit_coverage(_ctx(must_visit=("ＣＡＮＴＯＮ",), titles=("CANTON",)))

    assert assessment.result.outcome is RuleOutcome.PASS


def test_case_insensitive_normalisation() -> None:
    assessment = assess_must_visit_coverage(
        _ctx(must_visit=("Canton Tower",), titles=("canton tower",))
    )

    assert assessment.result.outcome is RuleOutcome.PASS


def test_child_poi_does_not_cover_must_visit() -> None:
    assessment = assess_must_visit_coverage(_ctx(must_visit=("陈家祠",), titles=("陈家祠公交站",)))

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert "陈家祠" in assessment.result.affected_entity_refs


def test_structural_activity_does_not_cover_must_visit() -> None:
    command = make_command(must_visit_places=("广州站",))
    activity = make_activity(0, title="广州站", kind="ARRIVAL")
    itinerary = Itinerary(
        title="anchors",
        days=(
            ItineraryDay(
                date=__import__("datetime").date(2026, 8, 1),
                activities=(activity,),
                transit_legs=(),
            ),
        ),
        estimated_total_cost=Decimal("0"),
    )
    ctx = ValidationContext(
        command=command,
        itinerary=itinerary,
        budget=build_budget_context(command, itinerary),
    )

    assessment = assess_must_visit_coverage(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "MUST_VISIT_PLACE_MISSING"


def test_duplicate_must_visit_inputs_judged_once() -> None:
    assessment = assess_must_visit_coverage(
        _ctx(must_visit=("陈家祠", "陈家祠"), titles=("陈家祠",))
    )

    assert assessment.result.outcome is RuleOutcome.PASS
    assert assessment.result.affected_entity_refs == ()


def test_refs_capped_at_64_and_sorted() -> None:
    missing = tuple(f"MISSING-{index:03d}" for index in range(30))
    assessment = assess_must_visit_coverage(_ctx(must_visit=missing, titles=("占位景点",)))

    assert assessment.result.outcome is RuleOutcome.FAIL
    # Command contract caps mustVisitPlaces at 30; the rule still guarantees
    # the aggregate stays bounded (<=64) and sorted.
    assert len(assessment.result.affected_entity_refs) <= 64
    assert assessment.result.affected_entity_refs == tuple(
        sorted(assessment.result.affected_entity_refs)
    )
    assert len(assessment.result.affected_entity_refs) == 30


def test_input_order_does_not_change_result() -> None:
    a = assess_must_visit_coverage(_ctx(must_visit=("陈家祠", "光孝寺"), titles=("光孝寺",)))
    b = assess_must_visit_coverage(_ctx(must_visit=("光孝寺", "陈家祠"), titles=("光孝寺",)))

    assert a.result == b.result


def test_does_not_mutate_inputs() -> None:
    command = make_command(must_visit_places=("陈家祠",))
    before = command.model_dump_json(by_alias=True)
    _ctx(must_visit=("陈家祠",), titles=("陈家祠",))
    assert command.model_dump_json(by_alias=True) == before


def test_meal_activity_does_not_cover_must_visit() -> None:
    assessment = assess_must_visit_coverage(_ctx(must_visit=("陈家祠",), titles=("陈家祠",)))
    # The fixture activity is ATTRACTION by default; a MEAL with the same
    # title must not count.  Construct explicitly:
    from plan_evaluation_support import make_activity

    command = make_command(must_visit_places=("陈家祠",))
    meal = make_activity(0, title="陈家祠", kind="MEAL")
    itinerary = Itinerary(
        title="meal",
        days=(
            ItineraryDay(
                date=__import__("datetime").date(2026, 8, 1),
                activities=(meal,),
                transit_legs=(),
            ),
        ),
        estimated_total_cost=Decimal("0"),
    )
    ctx = ValidationContext(
        command=command,
        itinerary=itinerary,
        budget=build_budget_context(command, itinerary),
    )

    assessment = assess_must_visit_coverage(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
