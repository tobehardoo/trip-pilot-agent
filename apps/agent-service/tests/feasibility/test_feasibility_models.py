"""B1-A — feasibility domain model and aggregator (TDD RED/GREEN).

The aggregator is the single entry point; callers never supply ``status``,
``summary`` or ``missing_required_rule_ids`` — those are produced by the
builder from the rule outcomes and the required-rule set.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from trip_agent.feasibility.models import (
    EvidenceReference,
    EvidenceState,
    FeasibilityReport,
    FeasibilityStatus,
    RepairAttempt,
    RuleOutcome,
    RuleResult,
    build_feasibility_report,
)

REPORT_ID = "c9c467cc-65c4-8ff1-e175-4af42f2ed545"
_VALIDATOR = "feasibility-v1"


def _fingerprint(seed: str = "a") -> str:
    return seed * 64


def _ts() -> datetime:
    return datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _rule(
    rule_id: str = "R1",
    outcome: RuleOutcome = RuleOutcome.PASS,
    evidence_refs: tuple[EvidenceReference, ...] = (),
    repairable: bool = False,
) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        rule_version="1",
        outcome=outcome,
        reason_code="REASON_OK",
        message="ok",
        affected_dates=(),
        affected_entity_refs=(),
        evidence_refs=evidence_refs,
        repairable=repairable,
    )


def _build(
    *,
    rules: tuple[RuleResult, ...],
    required: tuple[str, ...] = ("R1",),
    attempts: tuple[RepairAttempt, ...] = (),
    fingerprint: str | None = None,
) -> FeasibilityReport:
    return build_feasibility_report(
        report_id=REPORT_ID,
        validator_version=_VALIDATOR,
        itinerary_fingerprint=fingerprint or _fingerprint(),
        validated_at=_ts(),
        required_rule_ids=required,
        rule_results=rules,
        repair_attempts=attempts,
    )


# ── enums ──────────────────────────────────────────────────────────────────


def test_enum_values_are_exact() -> None:
    assert [s.value for s in FeasibilityStatus] == ["VERIFIED", "NEEDS_REPAIR", "UNVERIFIED"]
    assert [o.value for o in RuleOutcome] == ["PASS", "FAIL", "UNKNOWN", "NOT_APPLICABLE"]
    assert [e.value for e in EvidenceState] == ["VERIFIED", "UNKNOWN", "STALE", "CONFLICTING"]


# ── aggregation truth table ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("outcomes", "expected"),
    [
        ((RuleOutcome.PASS, RuleOutcome.NOT_APPLICABLE), FeasibilityStatus.VERIFIED),
        ((RuleOutcome.PASS, RuleOutcome.FAIL), FeasibilityStatus.NEEDS_REPAIR),
        ((RuleOutcome.PASS, RuleOutcome.UNKNOWN), FeasibilityStatus.UNVERIFIED),
        ((RuleOutcome.FAIL, RuleOutcome.UNKNOWN), FeasibilityStatus.NEEDS_REPAIR),
        ((RuleOutcome.NOT_APPLICABLE, RuleOutcome.UNKNOWN), FeasibilityStatus.UNVERIFIED),
        ((RuleOutcome.FAIL,), FeasibilityStatus.NEEDS_REPAIR),
        ((RuleOutcome.UNKNOWN,), FeasibilityStatus.UNVERIFIED),
        ((RuleOutcome.NOT_APPLICABLE,), FeasibilityStatus.VERIFIED),
    ],
)
def test_aggregation_truth_table(outcomes, expected) -> None:
    ids = tuple(f"R{i}" for i in range(len(outcomes)))
    rules = tuple(_rule(rule_id, outcome) for rule_id, outcome in zip(ids, outcomes, strict=False))
    report = _build(rules=rules, required=ids)
    assert report.status == expected


# ── has_blocker / can_save (Information Missing != Planning Failed) ────────


@pytest.mark.parametrize(
    ("outcomes", "expected_has_blocker", "expected_can_save"),
    [
        ((RuleOutcome.PASS, RuleOutcome.NOT_APPLICABLE), False, True),
        ((RuleOutcome.PASS, RuleOutcome.FAIL), True, False),
        ((RuleOutcome.PASS, RuleOutcome.UNKNOWN), False, True),
        ((RuleOutcome.FAIL, RuleOutcome.UNKNOWN), True, False),
        ((RuleOutcome.NOT_APPLICABLE, RuleOutcome.UNKNOWN), False, True),
        ((RuleOutcome.FAIL,), True, False),
        ((RuleOutcome.UNKNOWN,), False, True),
        ((RuleOutcome.NOT_APPLICABLE,), False, True),
    ],
)
def test_has_blocker_and_can_save_truth_table(
    outcomes, expected_has_blocker, expected_can_save
) -> None:
    ids = tuple(f"R{i}" for i in range(len(outcomes)))
    rules = tuple(_rule(rule_id, outcome) for rule_id, outcome in zip(ids, outcomes, strict=False))
    report = _build(rules=rules, required=ids)
    assert report.has_blocker == expected_has_blocker
    assert report.can_save == expected_can_save


def test_unknown_only_report_can_save() -> None:
    """3 opening-hours unknowns + 4 duration unknowns must still be savable."""
    rules = (
        _rule("OPENING_HOURS", RuleOutcome.UNKNOWN),
        _rule("VISIT_DURATION", RuleOutcome.UNKNOWN),
    )
    report = _build(rules=rules, required=("OPENING_HOURS", "VISIT_DURATION"))
    assert report.status == FeasibilityStatus.UNVERIFIED
    assert report.has_blocker is False
    assert report.can_save is True


def test_fail_report_cannot_save() -> None:
    """A confirmed venue-closed conflict must remain a blocker."""
    verified_evidence = EvidenceReference(
        evidence_id="ev:opening",
        evidence_type="OPENING_HOURS",
        state=EvidenceState.VERIFIED,
        hard_constraint_eligible=True,
    )
    rules = (
        _rule(
            "OPENING_HOURS",
            RuleOutcome.FAIL,
            evidence_refs=(verified_evidence,),
        ),
    )
    report = _build(rules=rules, required=("OPENING_HOURS",))
    assert report.status == FeasibilityStatus.NEEDS_REPAIR
    assert report.has_blocker is True
    assert report.can_save is False


def test_missing_required_rule_keeps_can_save_false_when_unknown() -> None:
    """Missing required rule yields UNVERIFIED and is NOT savable (unknown blocker)."""
    report = _build(rules=(_rule("R1", RuleOutcome.PASS),), required=("R1", "R2"))
    assert report.status == FeasibilityStatus.UNVERIFIED
    assert report.has_blocker is True
    assert report.can_save is False


def test_fail_wins_over_unknown() -> None:
    report = _build(
        rules=(_rule("R1", RuleOutcome.UNKNOWN), _rule("R2", RuleOutcome.FAIL)),
        required=("R1", "R2"),
    )
    assert report.status == FeasibilityStatus.NEEDS_REPAIR


def test_caller_cannot_supply_status_or_summary() -> None:
    with pytest.raises(TypeError):
        build_feasibility_report(
            report_id=REPORT_ID,
            validator_version=_VALIDATOR,
            itinerary_fingerprint=_fingerprint(),
            validated_at=_ts(),
            required_rule_ids=("R1",),
            rule_results=(_rule(),),
            status=FeasibilityStatus.VERIFIED,  # type: ignore[call-arg]
        )


# ── missing required rules ─────────────────────────────────────────────────


def test_missing_required_rule_yields_unverified() -> None:
    report = _build(rules=(_rule("R1", RuleOutcome.PASS),), required=("R1", "R2", "R3"))
    assert report.status == FeasibilityStatus.UNVERIFIED
    assert report.missing_required_rule_ids == ("R2", "R3")


def test_missing_required_keeps_required_order() -> None:
    report = _build(rules=(_rule("R3", RuleOutcome.PASS),), required=("R1", "R2", "R3"))
    assert report.missing_required_rule_ids == ("R1", "R2")


def test_empty_required_rules_rejected() -> None:
    with pytest.raises(ValidationError):
        _build(rules=(), required=())


# ── summary ────────────────────────────────────────────────────────────────


def test_summary_counts() -> None:
    report = _build(
        rules=(
            _rule("R1", RuleOutcome.PASS),
            _rule("R2", RuleOutcome.FAIL),
            _rule("R3", RuleOutcome.UNKNOWN),
            _rule("R4", RuleOutcome.NOT_APPLICABLE),
        ),
        required=("R1", "R2", "R3", "R4", "R5"),
    )
    s = report.summary
    assert s.total_count == 4
    assert s.pass_count == 1
    assert s.fail_count == 1
    assert s.unknown_count == 1
    assert s.not_applicable_count == 1
    assert s.missing_required_count == 1


# ── ordering stability / duplicates ────────────────────────────────────────


def test_rule_results_keep_input_order() -> None:
    report = _build(
        rules=(_rule("R2"), _rule("R1"), _rule("R3")),
        required=("R1", "R2", "R3"),
    )
    assert [r.rule_id for r in report.rule_results] == ["R2", "R1", "R3"]
    assert report.required_rule_ids == ("R1", "R2", "R3")


def test_duplicate_rule_id_rejected() -> None:
    with pytest.raises(ValueError):
        _build(rules=(_rule("R1"), _rule("R1")), required=("R1",))


def test_duplicate_required_rule_id_rejected() -> None:
    with pytest.raises(ValidationError):
        _build(rules=(_rule("R1"),), required=("R1", "R1"))


# ── validated_at / fingerprint ─────────────────────────────────────────────


def test_naive_validated_at_rejected() -> None:
    with pytest.raises(ValidationError):
        _build_naive()


def _build_naive() -> FeasibilityReport:
    return build_feasibility_report(
        report_id=REPORT_ID,
        validator_version=_VALIDATOR,
        itinerary_fingerprint=_fingerprint(),
        validated_at=datetime(2026, 8, 9, 12, 0),  # naive
        required_rule_ids=("R1",),
        rule_results=(_rule(),),
    )


def test_bad_fingerprint_rejected() -> None:
    with pytest.raises(ValidationError):
        _build(rules=(_rule(),), fingerprint="not-a-64-hex")


def test_bad_fingerprint_in_rule_rejected() -> None:
    with pytest.raises(ValidationError):
        RepairAttempt(
            attempt_index=1,
            triggering_rule_ids=("R1",),
            action_codes=("MOVE_ACTIVITY",),
            affected_dates=(),
            affected_entity_refs=(),
            before_fingerprint="not-a-64-hex",
            after_fingerprint=_fingerprint("c"),
            resulting_status=FeasibilityStatus.VERIFIED,
        )


def test_schema_version_is_one() -> None:
    assert _build(rules=(_rule(),)).schema_version == 1


def test_schema_version_other_than_one_rejected_on_model_validate() -> None:
    report = _build(rules=(_rule(),))
    forged = report.model_dump(by_alias=True, mode="json")
    forged["schemaVersion"] = 2
    with pytest.raises(ValidationError):
        FeasibilityReport.model_validate(forged)


# ── immutability ───────────────────────────────────────────────────────────


def test_report_and_models_are_frozen() -> None:
    report = _build(rules=(_rule(),))
    with pytest.raises(ValidationError):
        report.rule_results = ()  # type: ignore[misc]
    rule = _rule()
    with pytest.raises(ValidationError):
        rule.outcome = RuleOutcome.FAIL  # type: ignore[misc]


# ── repair attempts ────────────────────────────────────────────────────────


def _attempt(index: int) -> RepairAttempt:
    return RepairAttempt(
        attempt_index=index,
        triggering_rule_ids=("R1",),
        action_codes=("MOVE_ACTIVITY",),
        affected_dates=(),
        affected_entity_refs=(),
        before_fingerprint=_fingerprint("b"),
        after_fingerprint=_fingerprint("c"),
        resulting_status=FeasibilityStatus.VERIFIED,
    )


def test_repair_attempt_index_contiguous_from_one() -> None:
    report = _build(
        rules=(_rule("R1", RuleOutcome.FAIL),),
        attempts=(_attempt(1), _attempt(2), _attempt(3)),
    )
    assert [a.attempt_index for a in report.repair_attempts] == [1, 2, 3]


def test_repair_attempt_index_must_start_at_one() -> None:
    with pytest.raises(ValidationError):
        _build(rules=(_rule("R1", RuleOutcome.FAIL),), attempts=(_attempt(2),))


def test_repair_attempt_index_gap_rejected() -> None:
    with pytest.raises(ValidationError):
        _build(rules=(_rule("R1", RuleOutcome.FAIL),), attempts=(_attempt(1), _attempt(3)))


def test_repair_attempt_max_three() -> None:
    with pytest.raises(ValidationError):
        _build(
            rules=(_rule("R1", RuleOutcome.FAIL),),
            attempts=(_attempt(1), _attempt(2), _attempt(3), _attempt(4)),
        )


# ── evidence eligibility safety ────────────────────────────────────────────


def test_eligible_evidence_must_be_verified() -> None:
    with pytest.raises(ValidationError):
        EvidenceReference(
            evidence_id="e1",
            evidence_type="OPENING_HOURS",
            state=EvidenceState.UNKNOWN,
            hard_constraint_eligible=True,
        )


def test_non_verified_evidence_cannot_be_eligible() -> None:
    for state in (EvidenceState.UNKNOWN, EvidenceState.STALE, EvidenceState.CONFLICTING):
        with pytest.raises(ValidationError):
            EvidenceReference(
                evidence_id="e1",
                evidence_type="OPENING_HOURS",
                state=state,
                hard_constraint_eligible=True,
            )


def test_verified_evidence_may_be_eligible() -> None:
    ref = EvidenceReference(
        evidence_id="e1",
        evidence_type="OPENING_HOURS",
        state=EvidenceState.VERIFIED,
        hard_constraint_eligible=True,
    )
    assert ref.hard_constraint_eligible is True


def _opening_evidence(state: EvidenceState, eligible: bool) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=f"ev-{state.value.lower()}",
        evidence_type="OPENING_HOURS",
        state=state,
        hard_constraint_eligible=eligible,
    )


def test_opening_pass_requires_verified_eligible_evidence() -> None:
    stale_evidence = _opening_evidence(EvidenceState.STALE, False)
    with pytest.raises(ValidationError):
        _build(rules=(_rule("OPENING_HOURS", RuleOutcome.PASS, (stale_evidence,)),))


def test_opening_fail_requires_verified_eligible_evidence() -> None:
    unknown_evidence = _opening_evidence(EvidenceState.UNKNOWN, False)
    with pytest.raises(ValidationError):
        _build(rules=(_rule("OPENING_HOURS", RuleOutcome.FAIL, (unknown_evidence,)),))


def test_opening_pass_with_verified_eligible_evidence_ok() -> None:
    verified_eligible = _opening_evidence(EvidenceState.VERIFIED, True)
    report = _build(
        rules=(_rule("OPENING_HOURS", RuleOutcome.PASS, (verified_eligible,)),),
        required=("OPENING_HOURS",),
    )
    assert report.status == FeasibilityStatus.VERIFIED


def test_opening_unknown_with_stale_evidence_ok_but_unverified() -> None:
    stale_evidence = _opening_evidence(EvidenceState.STALE, False)
    report = _build(rules=(_rule("OPENING_HOURS", RuleOutcome.UNKNOWN, (stale_evidence,)),))
    assert report.status == FeasibilityStatus.UNVERIFIED


def test_opening_unknown_with_conflicting_evidence_ok_but_unverified() -> None:
    conflicting_evidence = _opening_evidence(EvidenceState.CONFLICTING, False)
    report = _build(rules=(_rule("OPENING_HOURS", RuleOutcome.UNKNOWN, (conflicting_evidence,)),))
    assert report.status == FeasibilityStatus.UNVERIFIED


def test_opening_unknown_with_unknown_evidence_ok_but_unverified() -> None:
    unknown_evidence = _opening_evidence(EvidenceState.UNKNOWN, False)
    report = _build(rules=(_rule("OPENING_HOURS", RuleOutcome.UNKNOWN, (unknown_evidence,)),))
    assert report.status == FeasibilityStatus.UNVERIFIED


def test_opening_pass_requires_at_least_one_verified_eligible() -> None:
    # one verified non-eligible + one stale: still no eligible verified -> invalid
    with pytest.raises(ValidationError):
        _build(
            rules=(
                _rule(
                    "OPENING_HOURS",
                    RuleOutcome.PASS,
                    (
                        _opening_evidence(EvidenceState.VERIFIED, False),
                        _opening_evidence(EvidenceState.STALE, False),
                    ),
                ),
            )
        )


# ── B1.1 fix 2: opening-hours empty-evidence bypass ─────────────────────────


def test_opening_pass_with_no_evidence_rejected() -> None:
    with pytest.raises(ValidationError):
        _build(
            rules=(_rule("OPENING_HOURS", RuleOutcome.PASS, ()),),
            required=("OPENING_HOURS",),
        )


def test_opening_fail_with_no_evidence_rejected() -> None:
    with pytest.raises(ValidationError):
        _build(
            rules=(_rule("OPENING_HOURS", RuleOutcome.FAIL, ()),),
            required=("OPENING_HOURS",),
        )


def test_opening_pass_with_only_other_evidence_rejected() -> None:
    other = EvidenceReference(
        evidence_id="ev-other",
        evidence_type="OTHER",
        state=EvidenceState.VERIFIED,
        hard_constraint_eligible=True,
    )
    with pytest.raises(ValidationError):
        _build(
            rules=(_rule("OPENING_HOURS", RuleOutcome.PASS, (other,)),),
            required=("OPENING_HOURS",),
        )


def test_opening_fail_with_only_other_evidence_rejected() -> None:
    other = EvidenceReference(
        evidence_id="ev-other",
        evidence_type="OTHER",
        state=EvidenceState.VERIFIED,
        hard_constraint_eligible=True,
    )
    with pytest.raises(ValidationError):
        _build(
            rules=(_rule("OPENING_HOURS", RuleOutcome.FAIL, (other,)),),
            required=("OPENING_HOURS",),
        )


def test_opening_unknown_with_no_evidence_accepted_unverified() -> None:
    report = _build(
        rules=(_rule("OPENING_HOURS", RuleOutcome.UNKNOWN, ()),),
        required=("OPENING_HOURS",),
    )
    assert report.status == FeasibilityStatus.UNVERIFIED


def test_opening_not_applicable_with_no_evidence_accepted() -> None:
    report = _build(
        rules=(_rule("OPENING_HOURS", RuleOutcome.NOT_APPLICABLE, ()),),
        required=("OPENING_HOURS",),
    )
    assert report.status == FeasibilityStatus.VERIFIED


def test_transit_pass_with_no_evidence_accepted() -> None:
    report = _build(
        rules=(_rule("TRANSIT", RuleOutcome.PASS, ()),),
        required=("TRANSIT",),
    )
    assert report.status == FeasibilityStatus.VERIFIED


# B6J.2.1 F2: explicit validatorVersion policy (Java-aligned whitelist)


def _rule_with_refs(refs: tuple[str, ...]) -> RuleResult:
    return RuleResult(
        rule_id="R1",
        rule_version="1",
        outcome=RuleOutcome.PASS,
        reason_code="REASON_OK",
        message="ok",
        affected_dates=(),
        affected_entity_refs=refs,
        evidence_refs=(),
        repairable=False,
    )


def _report_with(validator_version: str, refs: tuple[str, ...] = ()) -> FeasibilityReport:
    return build_feasibility_report(
        report_id=REPORT_ID,
        validator_version=validator_version,
        itinerary_fingerprint=_fingerprint(),
        validated_at=_ts(),
        required_rule_ids=("R1",),
        rule_results=(_rule_with_refs(refs),),
        repair_attempts=(),
    )


def test_v4_accepts_valid_typed_refs() -> None:
    report = _report_with("hard-validator-v4", ("poi:POI-1",))
    assert report.status == FeasibilityStatus.VERIFIED


def test_v4_rejects_bare_ref() -> None:
    with pytest.raises(ValidationError):
        _report_with("hard-validator-v4", ("8f5ef9c2-c194-4292-b847-5b9dcfda978b",))


def test_legacy_versions_accept_bare_refs() -> None:
    for legacy in ("feasibility-v1", "hard-validator-v1", "hard-validator-v2", "hard-validator-v3"):
        report = _report_with(legacy, ("8f5ef9c2-c194-4292-b847-5b9dcfda978b",))
        assert report.status == FeasibilityStatus.VERIFIED


def test_v5_accepts_valid_typed_refs() -> None:
    report = _report_with("hard-validator-v5", ("poi:POI-1",))

    assert report.validator_version == "hard-validator-v5"


def test_v6_rejects_even_with_valid_typed_refs() -> None:
    with pytest.raises(ValidationError):
        _report_with("hard-validator-v6", ("poi:POI-1",))


def test_arbitrary_validator_rejects_with_empty_refs() -> None:
    with pytest.raises(ValidationError):
        _report_with("arbitrary-validator")


def test_repair_attempt_refs_are_strict_in_v4() -> None:
    with pytest.raises(ValidationError):
        build_feasibility_report(
            report_id=REPORT_ID,
            validator_version="hard-validator-v4",
            itinerary_fingerprint=_fingerprint(),
            validated_at=_ts(),
            required_rule_ids=("R1",),
            rule_results=(_rule_with_refs(()),),
            repair_attempts=(
                RepairAttempt(
                    attempt_index=1,
                    triggering_rule_ids=("R1",),
                    action_codes=("MOVE",),
                    affected_dates=(),
                    affected_entity_refs=("8f5ef9c2-c194-4292-b847-5b9dcfda978b",),
                    before_fingerprint=_fingerprint("b"),
                    after_fingerprint=_fingerprint("c"),
                    resulting_status=FeasibilityStatus.VERIFIED,
                ),
            ),
        )
