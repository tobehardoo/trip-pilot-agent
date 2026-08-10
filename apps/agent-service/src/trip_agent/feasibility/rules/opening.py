"""B5 — OPENING_HOURS canonical rule.

Reuses ``resolve_opening_hours`` / ``OpeningHoursEvidence`` verbatim; this
rule only decides how a resolved verdict applies to an itinerary activity.
Unverifiable states (UNKNOWN / STALE / CONFLICTING) and non-eligible
evidence never produce hard conclusions — they are UNKNOWN.  Only an
eligible VERIFIED verdict can PASS or FAIL an activity, and every PASS/FAIL
activity must carry its own eligible evidence.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from trip_agent.domain.shared import CHINA_TIME_ZONE
from trip_agent.feasibility.context import ValidationContext
from trip_agent.feasibility.inputs import OpeningHoursBinding
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
from trip_agent.guide_intelligence.opening_evidence import OpeningHoursEvidence
from trip_agent.guide_intelligence.opening_resolver import (
    ResolvedOpeningHours,
    resolve_opening_hours,
)

OPENING_RULE_ID = "OPENING_HOURS"
_APPLICABLE_KINDS = frozenset({"ATTRACTION", "EXPERIENCE", "MEAL"})

_MAX_EVIDENCE_REFS = 64


def _seconds(value: time) -> float:
    """Exact local seconds-of-day (includes seconds and microseconds)."""
    return value.hour * 3600 + value.minute * 60 + value.second + value.microsecond / 1_000_000


def _evidence_refs_for_binding(
    evidences: tuple[OpeningHoursEvidence, ...],
    resolved: ResolvedOpeningHours,
    validation_time: datetime,
) -> tuple[EvidenceReference, ...]:
    """Map a binding's evidence to report refs from its resolved verdict.

    Only the evidence selected for a hard VERIFIED_WINDOW / VERIFIED_CLOSED
    verdict may be VERIFIED and eligible — and only when that evidence is
    itself hard-constraint eligible (an ineligible evidence is never
    upgraded).  CONFLICTING / STALE / UNKNOWN verdicts downgrade every
    evidence of the binding.
    """
    refs = []
    for evidence in evidences:
        state: EvidenceState
        eligible = False
        if (
            resolved.state in {"VERIFIED_WINDOW", "VERIFIED_CLOSED"}
            and resolved.hard_constraint_eligible
            and evidence is resolved.selected_evidence
            and evidence.hard_constraint_eligible
        ):
            state, eligible = EvidenceState.VERIFIED, True
        elif resolved.state == "STALE":
            state = EvidenceState.STALE
        elif resolved.state == "CONFLICTING":
            state = EvidenceState.CONFLICTING
        else:
            state = EvidenceState.UNKNOWN
        refs.append(
            EvidenceReference(
                evidence_id=f"{evidence.kind}:{evidence.source_ref}",
                evidence_type="OPENING_HOURS",
                state=state,
                hard_constraint_eligible=eligible,
            )
        )
    return tuple(refs)


def _merge_evidence_refs(
    refs: list[EvidenceReference],
) -> tuple[EvidenceReference, ...]:
    # eligible evidence first so truncation never drops a PASS/FAIL basis.
    refs.sort(key=lambda ref: (not ref.hard_constraint_eligible, ref.evidence_id))
    deduped: list[EvidenceReference] = []
    seen: set[str] = set()
    for ref in refs:
        if ref.evidence_id not in seen:
            seen.add(ref.evidence_id)
            deduped.append(ref)
    return tuple(deduped[:_MAX_EVIDENCE_REFS])


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
        rule_id=OPENING_RULE_ID,
        rule_version=RULE_VERSION,
        outcome=outcome,
        reason_code=reason_code,
        message=message,
        affected_dates=affected_dates,
        affected_entity_refs=affected_entity_refs,
        evidence_refs=evidence_refs,
    )


def _activity_local_window(
    activity_start: datetime,
    activity_end: datetime,
    day_date: date,
) -> tuple[float, float] | None:
    """Return (start_seconds, end_seconds) in the day's local scale.

    Returns None when times are naive or the activity does not start on the
    itinerary day (unverifiable -> caller reports UNKNOWN).
    """
    if activity_start.tzinfo is None or activity_end.tzinfo is None:
        return None
    if activity_start.utcoffset() is None or activity_end.utcoffset() is None:
        return None
    local_start = activity_start.astimezone(CHINA_TIME_ZONE)
    local_end = activity_end.astimezone(CHINA_TIME_ZONE)
    if local_start.date() != day_date:
        return None
    start_seconds = _seconds(local_start.time())
    next_day = day_date + timedelta(days=1)
    if local_end.date() == day_date:
        end_seconds = _seconds(local_end.time())
    elif local_end.date() == next_day:
        end_seconds = _seconds(local_end.time()) + 1440 * 60
    else:
        return None
    return start_seconds, end_seconds


def assess_opening_hours(ctx: ValidationContext) -> RuleAssessment:
    """Every applicable activity must fit its resolved opening window."""
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
                "NO_OPENING_HOURS_APPLICABLE_ACTIVITIES",
                "no opening-hours applicable activities",
            )
        )
    if ctx.validation_time is None:
        return RuleAssessment(
            result=_result(
                RuleOutcome.UNKNOWN,
                "OPENING_HOURS_UNVERIFIED",
                "validation time is required to resolve opening hours",
            )
        )
    bindings: dict[tuple[int, int], OpeningHoursBinding] = {}
    if ctx.validation_inputs is not None:
        for binding in ctx.validation_inputs.opening_hours_bindings:
            bindings[(binding.activity.day_index, binding.activity.activity_index)] = binding

    findings: list[RuleFinding] = []
    fail_count = 0
    unknown_count = 0
    pass_count = 0
    affected_dates: set[date] = set()
    affected_refs: set[str] = set()
    collected_refs: list[EvidenceReference] = []

    for day_index, activity_index, day_date, activity in applicable:
        binding = bindings.get((day_index, activity_index))
        if binding is None or not binding.evidences:
            unknown_count += 1
            affected_dates.add(day_date)
            ref = (
                f"{activity.activity_id}"
                if activity.activity_id is not None
                else (activity.provider_poi_id if activity.provider_poi_id is not None else None)
            )
            if ref is not None:
                affected_refs.add(ref)
            findings.append(
                RuleFinding(
                    reason_code="OPENING_BINDING_MISSING",
                    message=f"no opening-hours evidence for activity {activity_index}",
                    affected_date=day_date,
                )
            )
            continue
        local_window = _activity_local_window(activity.start_time, activity.end_time, day_date)
        if local_window is None:
            unknown_count += 1
            affected_dates.add(day_date)
            findings.append(
                RuleFinding(
                    reason_code="OPENING_HOURS_UNVERIFIED",
                    message=f"activity {activity_index} time is not verifiable on its day",
                    affected_date=day_date,
                )
            )
            continue
        resolved = resolve_opening_hours(
            binding.evidences,
            poi_key=binding.poi_key,
            trip_date=day_date,
            resolver_as_of=ctx.validation_time,
        )
        collected_refs.extend(
            _evidence_refs_for_binding(binding.evidences, resolved, ctx.validation_time)
        )
        if resolved.state in {"UNKNOWN", "STALE", "CONFLICTING"}:
            unknown_count += 1
            affected_dates.add(day_date)
            findings.append(
                RuleFinding(
                    reason_code="OPENING_HOURS_UNVERIFIED",
                    message=f"activity {activity_index} opening hours are {resolved.state.lower()}",
                    affected_date=day_date,
                )
            )
            continue
        if not resolved.hard_constraint_eligible:
            unknown_count += 1
            affected_dates.add(day_date)
            findings.append(
                RuleFinding(
                    reason_code="OPENING_HOURS_UNVERIFIED",
                    message=f"activity {activity_index} opening evidence is not hard-eligible",
                    affected_date=day_date,
                )
            )
            continue
        start_seconds, end_seconds = local_window
        if resolved.closed:
            fail_count += 1
            affected_dates.add(day_date)
            findings.append(
                RuleFinding(
                    reason_code="VENUE_CLOSED",
                    message=f"activity {activity_index} venue is closed",
                    affected_date=day_date,
                )
            )
            continue
        if resolved.all_day:
            pass_count += 1
            continue
        if not resolved.windows:
            unknown_count += 1
            affected_dates.add(day_date)
            findings.append(
                RuleFinding(
                    reason_code="OPENING_HOURS_UNVERIFIED",
                    message=f"activity {activity_index} has no usable opening window",
                    affected_date=day_date,
                )
            )
            continue
        inside = any(
            start_seconds >= _seconds(window.open)
            and end_seconds <= _seconds(window.close) + window.close_day_offset * 1440 * 60
            for window in resolved.windows
        )
        if not inside:
            fail_count += 1
            affected_dates.add(day_date)
            findings.append(
                RuleFinding(
                    reason_code="ACTIVITY_OUTSIDE_OPENING_WINDOW",
                    message=f"activity {activity_index} is outside the opening window",
                    affected_date=day_date,
                )
            )
            continue
        if resolved.last_entry is not None and start_seconds > _seconds(resolved.last_entry):
            fail_count += 1
            affected_dates.add(day_date)
            findings.append(
                RuleFinding(
                    reason_code="ACTIVITY_AFTER_LAST_ENTRY",
                    message=f"activity {activity_index} starts after last entry",
                    affected_date=day_date,
                )
            )
            continue
        pass_count += 1

    if fail_count > 0:
        outcome = RuleOutcome.FAIL
        reason_code = (
            "VENUE_CLOSED"
            if any(f.reason_code == "VENUE_CLOSED" for f in findings)
            else (
                "ACTIVITY_AFTER_LAST_ENTRY"
                if any(f.reason_code == "ACTIVITY_AFTER_LAST_ENTRY" for f in findings)
                else "ACTIVITY_OUTSIDE_OPENING_WINDOW"
            )
        )
        message = f"{fail_count} activity/activities violate verified opening hours"
    elif unknown_count > 0:
        outcome = RuleOutcome.UNKNOWN
        reason_code = next(
            (
                finding.reason_code
                for finding in findings
                if finding.reason_code
                in {
                    "OPENING_BINDING_MISSING",
                    "OPENING_HOURS_UNVERIFIED",
                }
            ),
            "OPENING_HOURS_UNVERIFIED",
        )
        message = f"{unknown_count} activity/activities have unverifiable opening hours"
    else:
        outcome = RuleOutcome.PASS
        reason_code = "OPENING_HOURS_VERIFIED"
        message = "every applicable activity fits its verified opening window"
    return RuleAssessment(
        result=_result(
            outcome,
            reason_code,
            message,
            affected_dates=tuple(sorted(affected_dates))[:MAX_AFFECTED_DATES],
            affected_entity_refs=tuple(sorted(affected_refs))[:MAX_AFFECTED_ENTITY_REFS],
            evidence_refs=_merge_evidence_refs(collected_refs),
        ),
        findings=tuple(findings),
    )
