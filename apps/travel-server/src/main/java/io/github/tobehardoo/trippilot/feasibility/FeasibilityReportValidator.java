package io.github.tobehardoo.trippilot.feasibility;

import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.format.DateTimeParseException;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * Semantic validator for the standalone feasibility report.
 *
 * Enforces the aggregation semantics that the JSON Schema cannot express:
 * status aggregation, summary consistency, missing-required derivation,
 * duplicate rule ids, repair-attempt bounds, timezone-aware timestamp,
 * fingerprint format, and evidence eligibility / opening-hours safety.
 *
 * Fail-closed: every required / null / enum field that can affect status
 * aggregation or safety decisions is rejected with
 * {@link IllegalArgumentException} — never an NPE.
 *
 * Referenced by the v9 completion and review-required event parsers after
 * wire deserialisation; parser adapters convert {@link IllegalArgumentException}
 * into the fail-closed contract rejection.
 */
public final class FeasibilityReportValidator {

    private static final Pattern FINGERPRINT = Pattern.compile("^[0-9a-f]{64}$");
    private static final String OPENING_RULE_ID = "OPENING_HOURS";
    private static final String OPENING_EVIDENCE_TYPE = "OPENING_HOURS";
    private static final int MAX_REPAIR_ATTEMPTS = 3;
    private static final int MAX_REPAIR_VALUES = 16;
    private static final int MAX_REPAIR_ENTITY_REFS = 64;
    private static final Set<String> LEGACY_VALIDATOR_VERSIONS = Set.of(
            "feasibility-v1", "hard-validator-v1", "hard-validator-v2", "hard-validator-v3"
    );
    private static final Set<String> TYPED_REF_VALIDATOR_VERSIONS = Set.of(
            "hard-validator-v4", "hard-validator-v5"
    );

    private FeasibilityReportValidator() {
    }

    public static void validate(FeasibilityReport report) {
        if (report == null) {
            throw new IllegalArgumentException("report must not be null");
        }
        if (report.schemaVersion() != 1) {
            throw new IllegalArgumentException("schemaVersion must be 1");
        }
        if (report.reportId() == null) {
            throw new IllegalArgumentException("reportId must not be null");
        }
        if (isBlank(report.validatorVersion())) {
            throw new IllegalArgumentException("validatorVersion must not be blank");
        }
        if (!LEGACY_VALIDATOR_VERSIONS.contains(report.validatorVersion())
                && !TYPED_REF_VALIDATOR_VERSIONS.contains(report.validatorVersion())) {
            throw new IllegalArgumentException(
                    "unknown validatorVersion: " + report.validatorVersion());
        }
        if (report.itineraryFingerprint() == null
                || !FINGERPRINT.matcher(report.itineraryFingerprint()).matches()) {
            throw new IllegalArgumentException("itineraryFingerprint must be 64 lowercase hex");
        }
        if (report.status() == null) {
            throw new IllegalArgumentException("status must not be null");
        }
        if (report.validatedAt() == null) {
            throw new IllegalArgumentException("validatedAt must be present and offset-aware");
        }
        if (report.requiredRuleIds() == null || report.requiredRuleIds().isEmpty()) {
            throw new IllegalArgumentException("requiredRuleIds must not be null or empty");
        }
        if (report.missingRequiredRuleIds() == null) {
            throw new IllegalArgumentException("missingRequiredRuleIds must not be null");
        }
        if (report.summary() == null) {
            throw new IllegalArgumentException("summary must not be null");
        }
        if (report.ruleResults() == null) {
            throw new IllegalArgumentException("ruleResults must not be null");
        }
        if (report.repairAttempts() == null) {
            throw new IllegalArgumentException("repairAttempts must not be null");
        }

        List<String> required = report.requiredRuleIds();
        if (required.stream().anyMatch(FeasibilityReportValidator::isBlank)) {
            throw new IllegalArgumentException("requiredRuleIds elements must not be blank");
        }
        if (new LinkedHashSet<>(required).size() != required.size()) {
            throw new IllegalArgumentException("requiredRuleIds must be unique");
        }

        List<FeasibilityReport.RuleResult> results = report.ruleResults();
        Set<String> ruleIds = new LinkedHashSet<>();
        for (FeasibilityReport.RuleResult result : results) {
            if (result == null) {
                throw new IllegalArgumentException("ruleResults must not contain null elements");
            }
            if (isBlank(result.ruleId()) || isBlank(result.ruleVersion())
                    || isBlank(result.reasonCode()) || isBlank(result.message())) {
                throw new IllegalArgumentException(
                        "ruleId, ruleVersion, reasonCode and message must not be blank");
            }
            if (result.outcome() == null) {
                throw new IllegalArgumentException("rule outcome must not be null");
            }
            if (result.evidenceRefs() == null) {
                throw new IllegalArgumentException("evidenceRefs must not be null");
            }
            for (FeasibilityReport.EvidenceReference ref : result.evidenceRefs()) {
                if (ref == null) {
                    throw new IllegalArgumentException(
                            "evidenceRefs must not contain null elements");
                }
                if (isBlank(ref.evidenceId()) || isBlank(ref.evidenceType())) {
                    throw new IllegalArgumentException(
                            "evidenceId and evidenceType must not be blank");
                }
                if (ref.state() == null) {
                    throw new IllegalArgumentException("evidence state must not be null");
                }
            }
            if (!ruleIds.add(result.ruleId())) {
                throw new IllegalArgumentException("ruleResults must contain unique ruleIds");
            }
        }
        for (FeasibilityReport.RepairAttempt attempt : report.repairAttempts()) {
            if (attempt == null) {
                throw new IllegalArgumentException(
                        "repairAttempts must not contain null elements");
            }
        }

        List<String> expectedMissing = required.stream()
                .filter(id -> !ruleIds.contains(id))
                .toList();
        if (!expectedMissing.equals(report.missingRequiredRuleIds())) {
            throw new IllegalArgumentException(
                    "missingRequiredRuleIds must list required rules absent from results in order");
        }

        validateSummary(report, expectedMissing.size());
        validateStatus(report, expectedMissing);
        validateRepairAttempts(report);
        validateEvidenceSafety(results);
        if (TYPED_REF_VALIDATOR_VERSIONS.contains(report.validatorVersion())) {
            validateV4EntityRefs(results, report.repairAttempts());
        }
    }

    /**
     * hard-validator-v4+ entity references must be typed strings
     * (activity:/transit:/poi:/text:).  Bare UUIDs, unknown kinds,
     * non-canonical UUIDs, empty values and any other grammar violation
     * fail closed.  RuleResult refs and RepairAttempt refs share the same
     * grammar, so both are checked here (the review path never reaches
     * FeasibilityEntityRefMapper, so this is the only review-side gate).
     */
    private static void validateV4EntityRefs(
            List<FeasibilityReport.RuleResult> results,
            List<FeasibilityReport.RepairAttempt> repairAttempts
    ) {
        for (FeasibilityReport.RuleResult result : results) {
            validateV4RefList(result.affectedEntityRefs(), "rule " + result.ruleId());
        }
        for (FeasibilityReport.RepairAttempt attempt : repairAttempts) {
            validateV4RefList(attempt.affectedEntityRefs(),
                    "repair attempt " + attempt.attemptIndex());
        }
    }

    private static void validateV4RefList(List<String> refs, String owner) {
        if (refs == null) {
            throw new IllegalArgumentException(owner + " affectedEntityRefs must not be null");
        }
        for (String ref : refs) {
            try {
                FeasibilityEntityReferenceCodec.parse(ref);
            } catch (IllegalArgumentException exception) {
                throw new IllegalArgumentException(
                        owner + " contains an invalid entity reference: " + ref, exception);
            }
        }
    }

    private static boolean isBlank(String value) {
        return value == null || value.trim().isEmpty();
    }

    private static void validateSummary(FeasibilityReport report, int missingCount) {
        FeasibilityReport.Summary s = report.summary();
        List<FeasibilityReport.RuleResult> results = report.ruleResults();
        long pass = results.stream().filter(r -> r.outcome() == RuleOutcome.PASS).count();
        long fail = results.stream().filter(r -> r.outcome() == RuleOutcome.FAIL).count();
        long unknown = results.stream().filter(r -> r.outcome() == RuleOutcome.UNKNOWN).count();
        long na = results.stream().filter(r -> r.outcome() == RuleOutcome.NOT_APPLICABLE).count();
        if (s.totalCount() != results.size()
                || s.passCount() != pass
                || s.failCount() != fail
                || s.unknownCount() != unknown
                || s.notApplicableCount() != na
                || s.missingRequiredCount() != missingCount) {
            throw new IllegalArgumentException("summary counts must match rule results and missing rules");
        }
    }

    private static void validateStatus(
            FeasibilityReport report, List<String> missingRequired
    ) {
        List<FeasibilityReport.RuleResult> results = report.ruleResults();
        FeasibilityStatus expected;
        if (results.stream().anyMatch(r -> r.outcome() == RuleOutcome.FAIL)) {
            expected = FeasibilityStatus.NEEDS_REPAIR;
        } else if (results.stream().anyMatch(r -> r.outcome() == RuleOutcome.UNKNOWN)) {
            expected = FeasibilityStatus.UNVERIFIED;
        } else if (!missingRequired.isEmpty()) {
            expected = FeasibilityStatus.UNVERIFIED;
        } else {
            expected = FeasibilityStatus.VERIFIED;
        }
        if (report.status() != expected) {
            throw new IllegalArgumentException(
                    "status must be " + expected + " for the given rule results");
        }
    }

    private static void validateRepairAttempts(FeasibilityReport report) {
        List<FeasibilityReport.RepairAttempt> attempts = report.repairAttempts();
        if (attempts.size() > MAX_REPAIR_ATTEMPTS) {
            throw new IllegalArgumentException("repairAttempts must not exceed 3");
        }
        for (int index = 0; index < attempts.size(); index++) {
            FeasibilityReport.RepairAttempt attempt = attempts.get(index);
            if (attempt == null) {
                throw new IllegalArgumentException("repairAttempts elements must not be null");
            }
            if (attempt.attemptIndex() != index + 1) {
                throw new IllegalArgumentException(
                        "repair attempt indices must be contiguous starting from 1");
            }
            validateRepairStringList(
                    attempt.triggeringRuleIds(), "triggeringRuleIds",
                    1, MAX_REPAIR_VALUES, 64, true);
            validateRepairStringList(
                    attempt.actionCodes(), "actionCodes",
                    1, MAX_REPAIR_VALUES, 60, false);
            validateRepairStringList(
                    attempt.affectedDates(), "affectedDates",
                    0, MAX_REPAIR_VALUES, 10, false);
            for (String affectedDate : attempt.affectedDates()) {
                try {
                    LocalDate.parse(affectedDate);
                } catch (DateTimeParseException exception) {
                    throw new IllegalArgumentException(
                            "repair attempt affectedDates must contain ISO dates", exception);
                }
            }
            validateRepairStringList(
                    attempt.affectedEntityRefs(), "affectedEntityRefs",
                    0, MAX_REPAIR_ENTITY_REFS, 200, true);
            if (attempt.beforeFingerprint() == null
                    || !FINGERPRINT.matcher(attempt.beforeFingerprint()).matches()
                    || attempt.afterFingerprint() == null
                    || !FINGERPRINT.matcher(attempt.afterFingerprint()).matches()) {
                throw new IllegalArgumentException(
                        "repair attempt fingerprints must be 64 lowercase hex");
            }
            if (attempt.resultingStatus() == null) {
                throw new IllegalArgumentException(
                        "repair attempt resultingStatus must not be null");
            }
        }
    }

    private static void validateRepairStringList(
            List<String> values,
            String field,
            int minimumSize,
            int maximumSize,
            int maximumLength,
            boolean unique
    ) {
        if (values == null || values.size() < minimumSize || values.size() > maximumSize) {
            throw new IllegalArgumentException(
                    "repair attempt " + field + " has invalid size");
        }
        if (values.stream().anyMatch(value -> isBlank(value) || value.length() > maximumLength)) {
            throw new IllegalArgumentException(
                    "repair attempt " + field + " has invalid values");
        }
        if (unique && new LinkedHashSet<>(values).size() != values.size()) {
            throw new IllegalArgumentException(
                    "repair attempt " + field + " must contain unique values");
        }
    }

    private static void validateEvidenceSafety(List<FeasibilityReport.RuleResult> results) {
        for (FeasibilityReport.RuleResult result : results) {
            for (FeasibilityReport.EvidenceReference ref : result.evidenceRefs()) {
                if (ref.hardConstraintEligible() && ref.state() != EvidenceState.VERIFIED) {
                    throw new IllegalArgumentException(
                            "hard-constraint-eligible evidence must be VERIFIED");
                }
            }
            validateOpeningSafety(result);
        }
    }

    private static void validateOpeningSafety(FeasibilityReport.RuleResult result) {
        if (!OPENING_RULE_ID.equals(result.ruleId())) {
            return;
        }
        List<FeasibilityReport.EvidenceReference> opening = result.evidenceRefs().stream()
                .filter(ref -> OPENING_EVIDENCE_TYPE.equals(ref.evidenceType()))
                .toList();
        boolean hasVerifiedEligible = opening.stream().anyMatch(
                ref -> ref.state() == EvidenceState.VERIFIED && ref.hardConstraintEligible()
        );
        if ((result.outcome() == RuleOutcome.PASS || result.outcome() == RuleOutcome.FAIL)
                && !hasVerifiedEligible) {
            throw new IllegalArgumentException(
                    "opening-hours " + result.outcome() + " requires VERIFIED eligible evidence");
        }
        if (!opening.isEmpty() && !hasVerifiedEligible && result.outcome() != RuleOutcome.UNKNOWN) {
            throw new IllegalArgumentException(
                    "opening-hours rule with only non-verified evidence must be UNKNOWN");
        }
    }
}
