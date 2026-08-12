"""B5 — VISIT_DURATION canonical rule.

Duration is judged only against an eligible profile (PROVIDER / OFFICIAL_FACT
with high confidence).  Category and system-default profiles are planning
guidance: they can only produce UNKNOWN.  The rule never scores confidence
itself; eligibility comes from the profile's explicit flag.
"""

from __future__ import annotations

from datetime import date

from trip_agent.feasibility.context import ValidationContext
from trip_agent.feasibility.entity_refs import encode_activity_ref, encode_poi_ref
from trip_agent.feasibility.inputs import ActivityLocator
from trip_agent.feasibility.models import (
    EvidenceReference,
    EvidenceState,
    RuleOutcome,
    RuleResult,
)
from trip_agent.feasibility.rules.core import (
    MAX_AFFECTED_DATES,
    MAX_AFFECTED_ENTITY_REFS,
    RULE_VERSION,
    RuleAssessment,
    RuleFinding,
)
from trip_agent.planning.visit_duration import VisitDurationProfile

DURATION_RULE_ID = "VISIT_DURATION"
_APPLICABLE_KINDS = frozenset({"ATTRACTION", "EXPERIENCE"})


def _result(
    outcome: RuleOutcome,
    reason_code: str,
    message: str,
    *,
    affected_dates: tuple[date, ...] = (),
    affected_entity_refs: tuple[str, ...] = (),
    evidence_refs: tuple[EvidenceReference, ...] = (),
) -> RuleResult:
    return RuleResult(
        rule_id=DURATION_RULE_ID,
        rule_version=RULE_VERSION,
        outcome=outcome,
        reason_code=reason_code,
        message=message,
        affected_dates=affected_dates,
        affected_entity_refs=affected_entity_refs,
        evidence_refs=evidence_refs,
    )


def _profile_evidence(profile: VisitDurationProfile) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=profile.source_ref,
        evidence_type="VISIT_DURATION",
        state=(
            EvidenceState.VERIFIED if profile.hard_constraint_eligible else EvidenceState.UNKNOWN
        ),
        hard_constraint_eligible=profile.hard_constraint_eligible,
    )


def _activity_ref(activity: object) -> str | None:
    if activity.activity_id is not None:
        return encode_activity_ref(activity.activity_id)
    if activity.provider_poi_id is not None:
        return encode_poi_ref(activity.provider_poi_id)
    return None


def assess_visit_duration(ctx: ValidationContext) -> RuleAssessment:
    """Every applicable activity duration must fit its eligible profile."""
    applicable = tuple(
        (day_index, activity_index, day.date, activity)
        for day_index, day in enumerate(ctx.itinerary.days)
        for activity_index, activity in enumerate(day.activities)
        if activity.kind in _APPLICABLE_KINDS
    )
    if not applicable:
        return RuleAssessment(
            result=_result(
                RuleOutcome.NOT_APPLICABLE,
                "NO_DURATION_APPLICABLE_ACTIVITIES",
                "no visit-duration applicable activities",
            )
        )
    bindings: dict[tuple[int, int], VisitDurationProfile] = {}
    if ctx.validation_inputs is not None:
        for binding in ctx.validation_inputs.visit_duration_bindings:
            bindings[(binding.activity.day_index, binding.activity.activity_index)] = (
                binding.profile
            )

    findings: list[RuleFinding] = []
    fail_count = 0
    unknown_count = 0
    pass_count = 0
    affected_dates: set[date] = set()
    affected_refs: set[str] = set()
    evidence_by_id: dict[str, EvidenceReference] = {}

    for day_index, activity_index, day_date, activity in applicable:
        profile = bindings.get((day_index, activity_index))
        ref = _activity_ref(activity)
        if ref is not None:
            affected_refs.add(ref)
        if profile is None:
            unknown_count += 1
            affected_dates.add(day_date)
            findings.append(
                RuleFinding(
                    reason_code="VISIT_DURATION_PROFILE_MISSING",
                    message=f"activity {activity_index} has no duration profile",
                    affected_date=day_date,
                    activity=ActivityLocator(day_index, activity_index),
                )
            )
            continue
        evidence_by_id[profile.source_ref] = _profile_evidence(profile)
        if not profile.hard_constraint_eligible:
            unknown_count += 1
            affected_dates.add(day_date)
            findings.append(
                RuleFinding(
                    reason_code="VISIT_DURATION_UNVERIFIED",
                    message=f"activity {activity_index} profile is not hard-eligible",
                    affected_date=day_date,
                    activity=ActivityLocator(day_index, activity_index),
                )
            )
            continue
        start = activity.start_time
        end = activity.end_time
        if (
            start.tzinfo is None
            or end.tzinfo is None
            or start.utcoffset() is None
            or end.utcoffset() is None
        ):
            unknown_count += 1
            affected_dates.add(day_date)
            findings.append(
                RuleFinding(
                    reason_code="VISIT_DURATION_UNVERIFIED",
                    message=f"activity {activity_index} times are not timezone-aware",
                    affected_date=day_date,
                    activity=ActivityLocator(day_index, activity_index),
                )
            )
            continue
        duration_minutes = (end - start).total_seconds() / 60
        if duration_minutes < profile.min_minutes:
            fail_count += 1
            affected_dates.add(day_date)
            findings.append(
                RuleFinding(
                    reason_code="VISIT_TOO_SHORT",
                    message=f"activity {activity_index} visit is shorter than the minimum",
                    affected_date=day_date,
                    activity=ActivityLocator(day_index, activity_index),
                )
            )
        elif duration_minutes > profile.max_minutes:
            fail_count += 1
            affected_dates.add(day_date)
            findings.append(
                RuleFinding(
                    reason_code="VISIT_TOO_LONG",
                    message=f"activity {activity_index} visit is longer than the maximum",
                    affected_date=day_date,
                    activity=ActivityLocator(day_index, activity_index),
                )
            )
        else:
            pass_count += 1

    if fail_count > 0:
        outcome = RuleOutcome.FAIL
        reason_code = (
            "VISIT_TOO_LONG"
            if any(f.reason_code == "VISIT_TOO_LONG" for f in findings)
            else "VISIT_TOO_SHORT"
        )
        message = f"{fail_count} activity/activities violate their duration profile"
    elif unknown_count > 0:
        outcome = RuleOutcome.UNKNOWN
        reason_code = next(
            (
                finding.reason_code
                for finding in findings
                if finding.reason_code
                in {"VISIT_DURATION_PROFILE_MISSING", "VISIT_DURATION_UNVERIFIED"}
            ),
            "VISIT_DURATION_UNVERIFIED",
        )
        message = f"{unknown_count} activity/activities have unverifiable durations"
    else:
        outcome = RuleOutcome.PASS
        reason_code = "VISIT_DURATIONS_VERIFIED"
        message = "every applicable activity fits its duration profile"
    return RuleAssessment(
        result=_result(
            outcome,
            reason_code,
            message,
            affected_dates=tuple(sorted(affected_dates))[:MAX_AFFECTED_DATES],
            affected_entity_refs=tuple(sorted(affected_refs))[:MAX_AFFECTED_ENTITY_REFS],
            evidence_refs=tuple(evidence_by_id.values())[:64],
        ),
        findings=tuple(findings),
    )
