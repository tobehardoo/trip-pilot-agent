"""Feasibility domain model — deterministic, immutable, standalone.

B1 scope: contract foundation only.  This module defines the report shape
and the aggregation semantics for a future hard validator.  It does NOT run
any real rules, is NOT embedded in any runtime envelope, and must never be
described as "Hard Validation complete".
"""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_UPPER_BOUND = 64
_OPENING_RULE_ID = "OPENING_HOURS"
_OPENING_EVIDENCE_TYPE = "OPENING_HOURS"


class FeasibilityStatus(str, Enum):
    VERIFIED = "VERIFIED"
    NEEDS_REPAIR = "NEEDS_REPAIR"
    UNVERIFIED = "UNVERIFIED"


class RuleOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class EvidenceState(str, Enum):
    VERIFIED = "VERIFIED"
    UNKNOWN = "UNKNOWN"
    STALE = "STALE"
    CONFLICTING = "CONFLICTING"


def _config() -> ConfigDict:
    return ConfigDict(
        frozen=True,
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class EvidenceReference(BaseModel):
    """A reference to one piece of evidence used by a rule result.

    Safety invariant: ``hard_constraint_eligible=True`` requires
    ``state == VERIFIED``; UNKNOWN/STALE/CONFLICTING evidence is never
    hard-constraint eligible.
    """

    model_config = _config()

    evidence_id: str = Field(min_length=1, max_length=200)
    evidence_type: str = Field(min_length=1, max_length=60)
    state: EvidenceState
    hard_constraint_eligible: bool = False

    @model_validator(mode="after")
    def evidence_eligibility_safety(self) -> EvidenceReference:
        if self.hard_constraint_eligible and self.state is not EvidenceState.VERIFIED:
            raise ValueError("hard-constraint-eligible evidence must be in VERIFIED state")
        return self


class RuleResult(BaseModel):
    """One deterministic rule evaluation inside a feasibility report."""

    model_config = _config()

    rule_id: str = Field(min_length=1, max_length=64)
    rule_version: str = Field(min_length=1, max_length=32)
    outcome: RuleOutcome
    reason_code: str = Field(min_length=1, max_length=60)
    message: str = Field(min_length=1, max_length=500)
    affected_dates: tuple[date, ...] = Field(default=(), max_length=16)
    affected_entity_refs: tuple[str, ...] = Field(default=(), max_length=64)
    evidence_refs: tuple[EvidenceReference, ...] = Field(default=(), max_length=64)
    repairable: bool = False


class RepairAttempt(BaseModel):
    """A recorded, bounded repair attempt (max 3, contiguous indices from 1)."""

    model_config = _config()

    attempt_index: int = Field(ge=1)
    triggering_rule_ids: tuple[str, ...] = Field(min_length=1, max_length=16)
    action_codes: tuple[str, ...] = Field(min_length=1, max_length=16)
    affected_dates: tuple[date, ...] = Field(default=(), max_length=16)
    affected_entity_refs: tuple[str, ...] = Field(default=(), max_length=64)
    before_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    after_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    resulting_status: FeasibilityStatus


class FeasibilitySummary(BaseModel):
    model_config = _config()

    total_count: int = Field(ge=0)
    pass_count: int = Field(ge=0)
    fail_count: int = Field(ge=0)
    unknown_count: int = Field(ge=0)
    not_applicable_count: int = Field(ge=0)
    missing_required_count: int = Field(ge=0)


class FeasibilityReport(BaseModel):
    """Standalone feasibility report (schemaVersion 1).

    ``status``, ``summary`` and ``missing_required_rule_ids`` are validated
    for consistency with the rule results and required-rule set; callers of
    :func:`build_feasibility_report` never supply them directly.
    """

    model_config = _config()

    schema_version: Literal[1] = 1
    report_id: UUID
    validator_version: str = Field(min_length=1, max_length=32)
    itinerary_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: FeasibilityStatus
    validated_at: datetime
    required_rule_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    missing_required_rule_ids: tuple[str, ...] = Field(default=(), max_length=64)
    summary: FeasibilitySummary
    rule_results: tuple[RuleResult, ...] = Field(default=(), max_length=64)
    repair_attempts: tuple[RepairAttempt, ...] = Field(default=(), max_length=3)

    @field_validator("validated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("validatedAt must include a timezone")
        return value

    @field_validator("required_rule_ids")
    @classmethod
    def unique_required(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("required_rule_ids must be unique")
        return value

    @field_validator("repair_attempts")
    @classmethod
    def contiguous_attempts(cls, value: tuple[RepairAttempt, ...]) -> tuple[RepairAttempt, ...]:
        expected = list(range(1, len(value) + 1))
        actual = [attempt.attempt_index for attempt in value]
        if actual != expected:
            raise ValueError("repair attempt indices must be contiguous starting from 1")
        return value

    @model_validator(mode="after")
    def cross_field_consistency(self) -> FeasibilityReport:
        _validate_semantics(
            rule_results=self.rule_results,
            required_rule_ids=self.required_rule_ids,
            status=self.status,
            missing_required=self.missing_required_rule_ids,
            summary=self.summary,
            validator_version=self.validator_version,
        )
        _validate_repair_entity_refs(self.repair_attempts, self.validator_version)
        return self


def build_feasibility_report(
    *,
    report_id: str | UUID,
    validator_version: str,
    itinerary_fingerprint: str,
    validated_at: datetime,
    required_rule_ids: tuple[str, ...],
    rule_results: tuple[RuleResult, ...],
    repair_attempts: tuple[RepairAttempt, ...] = (),
) -> FeasibilityReport:
    """The single aggregation entry point for a feasibility report.

    ``status``, ``summary`` and ``missing_required_rule_ids`` are derived
    here; callers must not pass them.  The report model re-validates all
    cross-field consistency invariants.
    """
    rule_ids = tuple(result.rule_id for result in rule_results)
    if len(set(rule_ids)) != len(rule_ids):
        raise ValueError("rule_results must contain unique rule_ids")

    required_ids = tuple(dict.fromkeys(required_rule_ids))
    present = set(rule_ids)
    missing_required = tuple(rule_id for rule_id in required_ids if rule_id not in present)

    pass_count = sum(1 for r in rule_results if r.outcome is RuleOutcome.PASS)
    fail_count = sum(1 for r in rule_results if r.outcome is RuleOutcome.FAIL)
    unknown_count = sum(1 for r in rule_results if r.outcome is RuleOutcome.UNKNOWN)
    na_count = sum(1 for r in rule_results if r.outcome is RuleOutcome.NOT_APPLICABLE)

    if fail_count > 0:
        status = FeasibilityStatus.NEEDS_REPAIR
    elif unknown_count > 0 or missing_required:
        status = FeasibilityStatus.UNVERIFIED
    else:
        status = FeasibilityStatus.VERIFIED

    summary = FeasibilitySummary(
        total_count=len(rule_results),
        pass_count=pass_count,
        fail_count=fail_count,
        unknown_count=unknown_count,
        not_applicable_count=na_count,
        missing_required_count=len(missing_required),
    )

    return FeasibilityReport(
        schema_version=1,
        report_id=UUID(str(report_id)),
        validator_version=validator_version,
        itinerary_fingerprint=itinerary_fingerprint,
        status=status,
        validated_at=validated_at,
        required_rule_ids=required_rule_ids,
        missing_required_rule_ids=missing_required,
        summary=summary,
        rule_results=rule_results,
        repair_attempts=repair_attempts,
    )


def validate_feasibility_report(report: FeasibilityReport) -> None:
    """Re-validate an already-constructed report (e.g. parsed from JSON).

    Raises ValueError on any cross-field semantic violation.  Used by the
    semantic checker so forged reports are rejected on read.
    """
    _validate_semantics(
        rule_results=report.rule_results,
        required_rule_ids=report.required_rule_ids,
        status=report.status,
        missing_required=report.missing_required_rule_ids,
        summary=report.summary,
        validator_version=report.validator_version,
    )


def _validate_semantics(
    *,
    rule_results: tuple[RuleResult, ...],
    required_rule_ids: tuple[str, ...],
    status: FeasibilityStatus,
    missing_required: tuple[str, ...],
    summary: FeasibilitySummary,
    validator_version: str,
) -> None:
    rule_ids = tuple(result.rule_id for result in rule_results)
    if len(set(rule_ids)) != len(rule_ids):
        raise ValueError("rule_results must contain unique rule_ids")

    present = set(rule_ids)
    expected_missing = tuple(rule_id for rule_id in required_rule_ids if rule_id not in present)
    if tuple(missing_required) != expected_missing:
        raise ValueError("missing_required_rule_ids must list required rules absent from results")

    if (
        summary.total_count,
        summary.pass_count,
        summary.fail_count,
        summary.unknown_count,
        summary.not_applicable_count,
        summary.missing_required_count,
    ) != (
        len(rule_results),
        sum(1 for r in rule_results if r.outcome is RuleOutcome.PASS),
        sum(1 for r in rule_results if r.outcome is RuleOutcome.FAIL),
        sum(1 for r in rule_results if r.outcome is RuleOutcome.UNKNOWN),
        sum(1 for r in rule_results if r.outcome is RuleOutcome.NOT_APPLICABLE),
        len(expected_missing),
    ):
        raise ValueError("summary counts must match rule results and missing rules")

    expected_status = _aggregate_status(rule_results, expected_missing)
    if status is not expected_status:
        raise ValueError(f"status must be {expected_status.value} for the given rule results")

    _validate_opening_evidence_safety(rule_results)
    _validate_entity_refs(rule_results, validator_version)


def _aggregate_status(
    rule_results: tuple[RuleResult, ...], missing_required: tuple[str, ...]
) -> FeasibilityStatus:
    if any(result.outcome is RuleOutcome.FAIL for result in rule_results):
        return FeasibilityStatus.NEEDS_REPAIR
    if any(result.outcome is RuleOutcome.UNKNOWN for result in rule_results):
        return FeasibilityStatus.UNVERIFIED
    if missing_required:
        return FeasibilityStatus.UNVERIFIED
    return FeasibilityStatus.VERIFIED


def _validate_opening_evidence_safety(rule_results: tuple[RuleResult, ...]) -> None:
    for result in rule_results:
        if result.rule_id != _OPENING_RULE_ID:
            continue
        opening_refs = tuple(
            ref for ref in result.evidence_refs if ref.evidence_type == _OPENING_EVIDENCE_TYPE
        )
        has_verified_eligible = any(
            ref.state is EvidenceState.VERIFIED and ref.hard_constraint_eligible
            for ref in opening_refs
        )
        if result.outcome in (RuleOutcome.PASS, RuleOutcome.FAIL) and not has_verified_eligible:
            raise ValueError(
                f"rule {result.rule_id} outcome {result.outcome.value} requires "
                "at least one VERIFIED hard-constraint-eligible OPENING_HOURS "
                "evidence"
            )
        if opening_refs and not has_verified_eligible and result.outcome is not RuleOutcome.UNKNOWN:
            raise ValueError(
                f"rule {result.rule_id} with only non-verified opening evidence must be UNKNOWN"
            )


_LEGACY_VALIDATOR_VERSIONS = frozenset(
    {"feasibility-v1", "hard-validator-v1", "hard-validator-v2", "hard-validator-v3"}
)
_TYPED_REF_VALIDATOR_VERSIONS = frozenset(
    {"hard-validator-v4", "hard-validator-v5"}
)


def _validate_entity_refs(rule_results: tuple[RuleResult, ...], validator_version: str) -> None:
    """Validate affected_entity_refs per validator generation.

    v4 reports must use typed refs (activity:/transit:/poi:/text:); v1-v3 and
    the historical feasibility-v1 keep the legacy raw-id heuristic.  Any
    other validatorVersion fails closed: an unknown generation must never be
    treated as v4 or silently accept untyped refs.
    """
    if validator_version in _TYPED_REF_VALIDATOR_VERSIONS:
        _validate_v4_rule_refs(rule_results)
        return
    if validator_version in _LEGACY_VALIDATOR_VERSIONS:
        return
    raise ValueError(f"unknown validatorVersion: {validator_version!r}")


def _validate_v4_rule_refs(rule_results: tuple[RuleResult, ...]) -> None:
    from trip_agent.feasibility.entity_refs import validate_entity_ref

    for result in rule_results:
        for ref in result.affected_entity_refs:
            if not validate_entity_ref(ref):
                raise ValueError(
                    f"rule {result.rule_id} contains an invalid entity reference {ref!r}"
                )


def _validate_repair_entity_refs(
    repair_attempts: tuple[RepairAttempt, ...], validator_version: str
) -> None:
    if validator_version in _TYPED_REF_VALIDATOR_VERSIONS:
        _validate_v4_repair_refs(repair_attempts)
        return
    if validator_version in _LEGACY_VALIDATOR_VERSIONS:
        return
    raise ValueError(f"unknown validatorVersion: {validator_version!r}")


def _validate_v4_repair_refs(repair_attempts: tuple[RepairAttempt, ...]) -> None:
    from trip_agent.feasibility.entity_refs import validate_entity_ref

    for attempt in repair_attempts:
        for ref in attempt.affected_entity_refs:
            if not validate_entity_ref(ref):
                raise ValueError(
                    f"repair attempt {attempt.attempt_index} contains an invalid "
                    f"entity reference {ref!r}"
                )
