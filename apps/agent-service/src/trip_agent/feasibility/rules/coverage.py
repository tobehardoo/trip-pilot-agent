"""B5 — MUST_VISIT_COVERAGE canonical rule.

A must-visit place is covered only by an ATTRACTION / EXPERIENCE activity
whose normalised name equals the normalised request exactly (NFKC +
casefold + alphanumeric-only).  Sub-POIs and structural nodes never count;
missing places become FAIL with a bounded, sorted ref list.
"""

from __future__ import annotations

from unicodedata import normalize

from trip_agent.feasibility.context import ValidationContext
from trip_agent.feasibility.entity_refs import encode_text_ref
from trip_agent.feasibility.models import RuleOutcome, RuleResult
from trip_agent.feasibility.rules.core import (
    MAX_AFFECTED_ENTITY_REFS,
    RULE_VERSION,
    RuleAssessment,
    RuleFinding,
)

MUST_VISIT_RULE_ID = "MUST_VISIT_COVERAGE"
_COVERING_KINDS = frozenset({"ATTRACTION", "EXPERIENCE"})


def _normalise_place_name(value: str) -> str:
    return "".join(
        character for character in normalize("NFKC", value).casefold() if character.isalnum()
    )


def _result(
    outcome: RuleOutcome,
    reason_code: str,
    message: str,
    *,
    affected_entity_refs: tuple[str, ...] = (),
) -> RuleResult:
    return RuleResult(
        rule_id=MUST_VISIT_RULE_ID,
        rule_version=RULE_VERSION,
        outcome=outcome,
        reason_code=reason_code,
        message=message,
        affected_entity_refs=affected_entity_refs,
    )


def assess_must_visit_coverage(ctx: ValidationContext) -> RuleAssessment:
    """Every must-visit place must be covered by a matching attraction."""
    raw_requests = tuple(ctx.command.payload.trip.constraints.must_visit_places)
    requests: list[str] = []
    seen: set[str] = set()
    for request in raw_requests:
        normalised = _normalise_place_name(request)
        if normalised and normalised not in seen:
            seen.add(normalised)
            requests.append(normalised)
    if not requests:
        return RuleAssessment(
            result=_result(
                RuleOutcome.NOT_APPLICABLE,
                "NO_MUST_VISIT_PLACES",
                "no must-visit places requested",
            )
        )

    covered: set[str] = set()
    for day in ctx.itinerary.days:
        for activity in day.activities:
            if activity.kind not in _COVERING_KINDS:
                continue
            normalised = _normalise_place_name(activity.title)
            if normalised in seen:
                covered.add(normalised)

    missing = tuple(sorted(request for request in requests if request not in covered))
    if not missing:
        return RuleAssessment(
            result=_result(
                RuleOutcome.PASS,
                "ALL_MUST_VISIT_PLACES_COVERED",
                "every must-visit place is covered",
            )
        )
    bounded = missing[:MAX_AFFECTED_ENTITY_REFS]
    typed_bounded = tuple(encode_text_ref(place) for place in bounded)
    return RuleAssessment(
        result=_result(
            RuleOutcome.FAIL,
            "MUST_VISIT_PLACE_MISSING",
            f"{len(missing)} must-visit place(s) are not covered",
            affected_entity_refs=typed_bounded,
        ),
        findings=tuple(
            RuleFinding(
                reason_code="MUST_VISIT_PLACE_MISSING",
                message=f"must-visit place {place} is not covered",
                affected_entity_refs=(encode_text_ref(place),),
            )
            for place in bounded
        ),
    )
