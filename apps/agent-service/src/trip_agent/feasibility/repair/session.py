"""Pure state machine for the fixed three-attempt repair budget."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from trip_agent.feasibility.models import (
    FeasibilityStatus,
    RepairAttempt,
    RuleOutcome,
    RuleResult,
)
from trip_agent.feasibility.repair.engine import (
    MAX_REPAIR_ATTEMPTS,
    RepairPlan,
    plan_repairs,
)
from trip_agent.feasibility.rules.core import RuleFinding
from trip_agent.feasibility.validator import ValidationRun, run_validation


class RepairStopReason(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    NO_LEGAL_ACTION = "NO_LEGAL_ACTION"
    NO_PROGRESS = "NO_PROGRESS"
    REPEATED_FAILURE = "REPEATED_FAILURE"
    ATTEMPT_LIMIT = "ATTEMPT_LIMIT"


@dataclass(frozen=True, slots=True)
class RepairSession:
    current: ValidationRun
    attempts: tuple[RepairAttempt, ...]
    seen_failure_signatures: frozenset[
        tuple[tuple[str, str, date | None, tuple[int, int] | None, tuple[str, ...]], ...]
    ]
    stop_reason: RepairStopReason | None = None


def start_repair_session(initial: ValidationRun) -> RepairSession:
    status = initial.report.status
    if status is FeasibilityStatus.VERIFIED:
        stop = RepairStopReason.VERIFIED
    elif status is FeasibilityStatus.UNVERIFIED:
        stop = RepairStopReason.UNVERIFIED
    elif plan_repairs(initial, attempt_index=1) is None:
        stop = RepairStopReason.NO_LEGAL_ACTION
    else:
        stop = None
    return RepairSession(
        current=initial,
        attempts=(),
        seen_failure_signatures=frozenset({_failure_signature(initial)}),
        stop_reason=stop,
    )


def advance_repair_session(
    session: RepairSession,
    *,
    plan: RepairPlan,
    after: ValidationRun,
) -> RepairSession:
    """Record one transition and apply deterministic stop conditions."""
    if session.stop_reason is not None:
        raise ValueError("cannot advance a stopped repair session")
    expected_index = len(session.attempts) + 1
    if plan.attempt_index != expected_index:
        raise ValueError("repair attempt index must be contiguous")
    before_fingerprint = session.current.report.itinerary_fingerprint
    after_fingerprint = after.report.itinerary_fingerprint
    actions = tuple(action.code.value for action in plan.actions)
    rule_ids = tuple(dict.fromkeys(action.rule_id for action in plan.actions))
    dates = tuple(sorted({action.affected_date for action in plan.actions}))[:16]
    refs = tuple(sorted({ref for action in plan.actions for ref in action.affected_entity_refs}))[
        :64
    ]
    attempt = RepairAttempt(
        attempt_index=expected_index,
        triggering_rule_ids=rule_ids,
        action_codes=actions,
        affected_dates=dates,
        affected_entity_refs=refs,
        before_fingerprint=before_fingerprint,
        after_fingerprint=after_fingerprint,
        resulting_status=after.report.status,
    )
    attempts = (*session.attempts, attempt)
    current = _with_attempts(after, attempts)
    signature = _failure_signature(current)
    if before_fingerprint == after_fingerprint:
        stop = RepairStopReason.NO_PROGRESS
    elif current.report.status is FeasibilityStatus.VERIFIED:
        stop = RepairStopReason.VERIFIED
    elif current.report.status is FeasibilityStatus.UNVERIFIED:
        stop = RepairStopReason.UNVERIFIED
    elif signature in session.seen_failure_signatures:
        stop = RepairStopReason.REPEATED_FAILURE
    elif len(attempts) >= MAX_REPAIR_ATTEMPTS:
        stop = RepairStopReason.ATTEMPT_LIMIT
    elif plan_repairs(current, attempt_index=len(attempts) + 1) is None:
        stop = RepairStopReason.NO_LEGAL_ACTION
    else:
        stop = None
    return RepairSession(
        current=current,
        attempts=attempts,
        seen_failure_signatures=session.seen_failure_signatures | {signature},
        stop_reason=stop,
    )


def _with_attempts(run: ValidationRun, attempts: tuple[RepairAttempt, ...]) -> ValidationRun:
    ctx = run.context
    return run_validation(
        command=ctx.command,
        itinerary=ctx.itinerary,
        report_id=run.report.report_id,
        validated_at=run.report.validated_at,
        trip_skeleton=ctx.trip_skeleton,
        validation_inputs=ctx.validation_inputs,
        repair_attempts=attempts,
    )


def _failure_signature(
    run: ValidationRun,
) -> tuple[tuple[str, str, date | None, tuple[int, int] | None, tuple[str, ...]], ...]:
    return tuple(
        (
            assessment.result.rule_id,
            finding.reason_code,
            finding.affected_date,
            (
                (finding.activity.day_index, finding.activity.activity_index)
                if finding.activity is not None
                else None
            ),
            _finding_entity_refs(run, finding),
        )
        for assessment in run.assessments
        if assessment.result.outcome is RuleOutcome.FAIL
        for finding in (assessment.findings or (_aggregate_finding(assessment.result),))
    )


def _finding_entity_refs(
    run: ValidationRun,
    finding: RuleFinding,
) -> tuple[str, ...]:
    if finding.affected_entity_refs:
        return finding.affected_entity_refs
    if finding.activity is None:
        return ()
    activity = run.itinerary.days[finding.activity.day_index].activities[
        finding.activity.activity_index
    ]
    if activity.activity_id is not None:
        return (f"activity:{activity.activity_id}",)
    if activity.provider_poi_id is not None:
        return (f"poi:{activity.provider_poi_id}",)
    return (f"text:{activity.title}",)


def _aggregate_finding(result: RuleResult) -> RuleFinding:
    return RuleFinding(
        reason_code=result.reason_code,
        message=result.message,
        affected_date=result.affected_dates[0] if len(result.affected_dates) == 1 else None,
        affected_entity_refs=result.affected_entity_refs,
    )
