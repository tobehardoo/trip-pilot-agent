from datetime import UTC, datetime

from plan_evaluation_support import make_activity, make_command, make_result, make_transit

from trip_agent.evaluation.evaluator import PlanEvaluator
from trip_agent.worker.contracts import FallbackOperation


class FrozenClock:
    @classmethod
    def now(cls, tz: object | None = None) -> datetime:
        return datetime(2026, 8, 2, tzinfo=UTC)


def test_fixed_appointment_decision_references_the_activity_and_evidence() -> None:
    schedule = ({
        "placeName": "Activity 1",
        "startTime": datetime(2026, 8, 1, 9, 15, tzinfo=UTC),
        "endTime": datetime(2026, 8, 1, 9, 45, tzinfo=UTC),
    },)

    evaluation = PlanEvaluator(clock=FrozenClock).evaluate(
        make_command(fixed_schedules=schedule),
        make_result(),
    )

    decision = next(
        item for item in evaluation.decisions if "FIXED_APPOINTMENT" in item.reason_codes
        and item.subject_type == "ACTIVITY"
    )
    assert decision.subject_id == make_result().itinerary.days[0].activities[0].activity_id
    assert decision.evidence[0].value == "Activity 1"


def test_fallback_decision_and_warning_share_the_same_transit_identity() -> None:
    activities = (make_activity(0, source="AMAP"), make_activity(1, source="AMAP"))
    transit_id = make_transit(0).transit_id
    fallback = FallbackOperation(
        operation="ROUTE",
        transit_id=transit_id,
        from_activity_id=activities[0].activity_id,
        to_activity_id=activities[1].activity_id,
        requested_mode="REAL_WITH_EXPLICIT_FALLBACK",
        actual_provider="DEMO",
        error_category="TIMEOUT",
        error_code="PROVIDER_TIMEOUT",
        retry_count=2,
    )
    result = make_result(
        activities=activities,
        transit_legs=(make_transit(0, fallback=fallback),),
        provider="AMAP",
        fallback_operations=(fallback,),
    )

    evaluation = PlanEvaluator(clock=FrozenClock).evaluate(make_command(), result)

    warning = next(item for item in evaluation.warnings if item.code == "PROVIDER_FALLBACK_USED")
    decision = next(
        item for item in evaluation.decisions if "PROVIDER_CONSTRAINT" in item.reason_codes
        and item.subject_type == "TRANSIT"
    )
    assert warning.entity_id == decision.subject_id == transit_id
