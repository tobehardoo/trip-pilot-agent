package io.github.tobehardoo.trippilot.feasibility;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.OffsetDateTime;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * B1-D: independent feasibility contract DTO + semantic validator.
 *
 * Reads the same shared fixtures as the Python model.  NOT wired into any
 * runtime parser: this validates the standalone contract only.
 */
public class FeasibilityReportContractTest {

    private final ObjectMapper mapper = new ObjectMapper().findAndRegisterModules();

    private String fixture(String name) {
        Path relative = Path.of("contracts", "fixtures", "feasibility-report-v1", name + ".json");
        Path workingDirectory = Path.of("").toAbsolutePath();
        Path fixture = workingDirectory.resolve(relative);
        if (!Files.isRegularFile(fixture)) {
            fixture = workingDirectory.resolve(Path.of("..", "..")).resolve(relative).normalize();
        }
        try {
            return Files.readString(fixture, StandardCharsets.UTF_8);
        } catch (Exception exception) {
            throw new IllegalStateException("could not read feasibility fixture " + name, exception);
        }
    }

    private FeasibilityReport parse(String json) throws JsonProcessingException {
        return mapper.readValue(json, FeasibilityReport.class);
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "verified",
            "needs-repair",
            "unverified-unknown",
            "unverified-missing-required",
            "opening-stale",
            "opening-conflicting",
            "opening-unknown",
            "opening-unknown-no-evidence",
    })
    void validFixturesParseAndValidate(String name) throws Exception {
        FeasibilityReport report = parse(fixture(name));
        assertThatCode(() -> FeasibilityReportValidator.validate(report))
                .doesNotThrowAnyException();
        assertThat(report.schemaVersion()).isEqualTo(1);
    }

    @Test
    void aggregatesVerifiedStatus() throws Exception {
        FeasibilityReport report = parse(fixture("verified"));
        assertThat(report.status()).isEqualTo(FeasibilityStatus.VERIFIED);
    }

    @Test
    void aggregatesNeedsRepairStatus() throws Exception {
        FeasibilityReport report = parse(fixture("needs-repair"));
        assertThat(report.status()).isEqualTo(FeasibilityStatus.NEEDS_REPAIR);
        assertThat(report.ruleResults()).anyMatch(r -> r.outcome() == RuleOutcome.FAIL);
    }

    @Test
    void aggregatesUnverifiedStatusForUnknown() throws Exception {
        FeasibilityReport report = parse(fixture("unverified-unknown"));
        assertThat(report.status()).isEqualTo(FeasibilityStatus.UNVERIFIED);
    }

    @Test
    void openingStaleEvidenceYieldsUnverifiedUnknown() throws Exception {
        FeasibilityReport report = parse(fixture("opening-stale"));
        assertThat(report.status()).isEqualTo(FeasibilityStatus.UNVERIFIED);
        assertThat(report.ruleResults()).singleElement()
                .satisfies(r -> {
                    assertThat(r.outcome()).isEqualTo(RuleOutcome.UNKNOWN);
                    assertThat(r.evidenceRefs()).singleElement().satisfies(e -> {
                        assertThat(e.state()).isEqualTo(EvidenceState.STALE);
                        assertThat(e.hardConstraintEligible()).isFalse();
                    });
                });
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "forged-verified-unknown",
            "forged-verified-missing-required",
            "forged-verified-fail",
            "summary-mismatch",
            "duplicate-rule-id",
            "repair-index-gap",
            "stale-eligible",
            "conflicting-eligible",
            "opening-pass-stale",
            "opening-pass-no-eligible",
            "opening-pass-no-evidence",
            "opening-fail-no-evidence",
            "opening-pass-wrong-evidence-type",
            "invalid-schema-version",
    })
    void semanticInvalidFixturesRejectedByValidator(String name) throws Exception {
        FeasibilityReport report = parse(fixture(name));
        assertThatThrownBy(() -> FeasibilityReportValidator.validate(report))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void naiveValidatedAtRejected() throws Exception {
        // OffsetDateTime requires an explicit offset; a naive timestamp is
        // rejected at parse time on the Java side.
        assertThatThrownBy(() -> parse(fixture("naive-validated-at")))
                .isInstanceOf(Exception.class);
    }

    @Test
    void invalidStatusEnumRejectedAtParseTime() throws Exception {
        assertThatThrownBy(() -> parse(fixture("invalid-status-enum")))
                .isInstanceOf(Exception.class);
    }

    @Test
    void invalidOutcomeEnumRejectedAtParseTime() throws Exception {
        assertThatThrownBy(() -> parse(fixture("invalid-outcome-enum")))
                .isInstanceOf(Exception.class);
    }

    @Test
    void badFingerprintRejectedByValidator() throws Exception {
        FeasibilityReport report = parse(fixture("bad-fingerprint"));
        assertThatThrownBy(() -> FeasibilityReportValidator.validate(report))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void tooManyRepairAttemptsRejectedByValidator() throws Exception {
        FeasibilityReport report = parse(fixture("too-many-repair-attempts"));
        assertThatThrownBy(() -> FeasibilityReportValidator.validate(report))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void additionalPropertyRejectedAtParseTime() throws Exception {
        assertThatThrownBy(() -> parse(fixture("additional-property")))
                .isInstanceOf(Exception.class);
    }

    // ── B1.1 fix 3: fail-closed null / blank handling ──────────────────────

    private FeasibilityReport.EvidenceReference verifiedOpeningEvidence() {
        return new FeasibilityReport.EvidenceReference(
                "ev-oh-1", "OPENING_HOURS", EvidenceState.VERIFIED, true);
    }

    private FeasibilityReport.RuleResult openingPassRule(
            List<FeasibilityReport.EvidenceReference> evidenceRefs
    ) {
        return new FeasibilityReport.RuleResult(
                "OPENING_HOURS", "1", RuleOutcome.PASS, "REASON_OK", "ok",
                List.of(), List.of(), evidenceRefs, false);
    }

    private FeasibilityReport validReport() {
        return new FeasibilityReport(
                1,
                UUID.fromString("c9c467cc-65c4-8ff1-e175-4af42f2ed545"),
                "feasibility-v1",
                "a".repeat(64),
                FeasibilityStatus.VERIFIED,
                OffsetDateTime.parse("2026-08-09T12:00:00Z"),
                List.of("OPENING_HOURS"),
                List.of(),
                new FeasibilityReport.Summary(1, 1, 0, 0, 0, 0),
                List.of(openingPassRule(List.of(verifiedOpeningEvidence()))),
                List.of());
    }

    @Test
    void nullValidatedAtRejectedWithIllegalArgumentException() {
        FeasibilityReport report = new FeasibilityReport(
                1,
                UUID.fromString("c9c467cc-65c4-8ff1-e175-4af42f2ed545"),
                "feasibility-v1",
                "a".repeat(64),
                FeasibilityStatus.VERIFIED,
                null,
                List.of("OPENING_HOURS"),
                List.of(),
                new FeasibilityReport.Summary(1, 1, 0, 0, 0, 0),
                List.of(openingPassRule(List.of(verifiedOpeningEvidence()))),
                List.of());
        assertThatThrownBy(() -> FeasibilityReportValidator.validate(report))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void nullOutcomeInRuleResultRejected() {
        FeasibilityReport.RuleResult nullOutcome = new FeasibilityReport.RuleResult(
                "OPENING_HOURS", "1", null, "REASON_OK", "ok",
                List.of(), List.of(), List.of(verifiedOpeningEvidence()), false);
        FeasibilityReport report = new FeasibilityReport(
                1,
                UUID.fromString("c9c467cc-65c4-8ff1-e175-4af42f2ed545"),
                "feasibility-v1",
                "a".repeat(64),
                FeasibilityStatus.VERIFIED,
                OffsetDateTime.parse("2026-08-09T12:00:00Z"),
                List.of("OPENING_HOURS"),
                List.of(),
                new FeasibilityReport.Summary(1, 0, 0, 0, 0, 0),
                List.of(nullOutcome),
                List.of());
        assertThatThrownBy(() -> FeasibilityReportValidator.validate(report))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void nullReportIdRejected() {
        FeasibilityReport report = new FeasibilityReport(
                1,
                null,
                "feasibility-v1",
                "a".repeat(64),
                FeasibilityStatus.VERIFIED,
                OffsetDateTime.parse("2026-08-09T12:00:00Z"),
                List.of("OPENING_HOURS"),
                List.of(),
                new FeasibilityReport.Summary(1, 1, 0, 0, 0, 0),
                List.of(openingPassRule(List.of(verifiedOpeningEvidence()))),
                List.of());
        assertThatThrownBy(() -> FeasibilityReportValidator.validate(report))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void nullStatusRejected() {
        FeasibilityReport report = new FeasibilityReport(
                1,
                UUID.fromString("c9c467cc-65c4-8ff1-e175-4af42f2ed545"),
                "feasibility-v1",
                "a".repeat(64),
                null,
                OffsetDateTime.parse("2026-08-09T12:00:00Z"),
                List.of("OPENING_HOURS"),
                List.of(),
                new FeasibilityReport.Summary(1, 1, 0, 0, 0, 0),
                List.of(openingPassRule(List.of(verifiedOpeningEvidence()))),
                List.of());
        assertThatThrownBy(() -> FeasibilityReportValidator.validate(report))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void nullSummaryRejected() {
        FeasibilityReport report = new FeasibilityReport(
                1,
                UUID.fromString("c9c467cc-65c4-8ff1-e175-4af42f2ed545"),
                "feasibility-v1",
                "a".repeat(64),
                FeasibilityStatus.VERIFIED,
                OffsetDateTime.parse("2026-08-09T12:00:00Z"),
                List.of("OPENING_HOURS"),
                List.of(),
                null,
                List.of(openingPassRule(List.of(verifiedOpeningEvidence()))),
                List.of());
        assertThatThrownBy(() -> FeasibilityReportValidator.validate(report))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void nullRequiredRuleIdsRejected() {
        FeasibilityReport report = new FeasibilityReport(
                1,
                UUID.fromString("c9c467cc-65c4-8ff1-e175-4af42f2ed545"),
                "feasibility-v1",
                "a".repeat(64),
                FeasibilityStatus.VERIFIED,
                OffsetDateTime.parse("2026-08-09T12:00:00Z"),
                null,
                List.of(),
                new FeasibilityReport.Summary(1, 1, 0, 0, 0, 0),
                List.of(openingPassRule(List.of(verifiedOpeningEvidence()))),
                List.of());
        assertThatThrownBy(() -> FeasibilityReportValidator.validate(report))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void nullRuleResultsRejected() {
        FeasibilityReport report = new FeasibilityReport(
                1,
                UUID.fromString("c9c467cc-65c4-8ff1-e175-4af42f2ed545"),
                "feasibility-v1",
                "a".repeat(64),
                FeasibilityStatus.VERIFIED,
                OffsetDateTime.parse("2026-08-09T12:00:00Z"),
                List.of("OPENING_HOURS"),
                List.of(),
                new FeasibilityReport.Summary(0, 0, 0, 0, 0, 0),
                null,
                List.of());
        assertThatThrownBy(() -> FeasibilityReportValidator.validate(report))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void nullRepairAttemptsRejected() {
        FeasibilityReport report = new FeasibilityReport(
                1,
                UUID.fromString("c9c467cc-65c4-8ff1-e175-4af42f2ed545"),
                "feasibility-v1",
                "a".repeat(64),
                FeasibilityStatus.VERIFIED,
                OffsetDateTime.parse("2026-08-09T12:00:00Z"),
                List.of("OPENING_HOURS"),
                List.of(),
                new FeasibilityReport.Summary(1, 1, 0, 0, 0, 0),
                List.of(openingPassRule(List.of(verifiedOpeningEvidence()))),
                null);
        assertThatThrownBy(() -> FeasibilityReportValidator.validate(report))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void nullElementInRuleResultsRejected() {
        FeasibilityReport report = new FeasibilityReport(
                1,
                UUID.fromString("c9c467cc-65c4-8ff1-e175-4af42f2ed545"),
                "feasibility-v1",
                "a".repeat(64),
                FeasibilityStatus.VERIFIED,
                OffsetDateTime.parse("2026-08-09T12:00:00Z"),
                List.of("OPENING_HOURS"),
                List.of(),
                new FeasibilityReport.Summary(1, 1, 0, 0, 0, 0),
                Arrays.asList(openingPassRule(List.of(verifiedOpeningEvidence())), null),
                List.of());
        assertThatThrownBy(() -> FeasibilityReportValidator.validate(report))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void nullElementInEvidenceRefsRejected() {
        FeasibilityReport report = new FeasibilityReport(
                1,
                UUID.fromString("c9c467cc-65c4-8ff1-e175-4af42f2ed545"),
                "feasibility-v1",
                "a".repeat(64),
                FeasibilityStatus.VERIFIED,
                OffsetDateTime.parse("2026-08-09T12:00:00Z"),
                List.of("OPENING_HOURS"),
                List.of(),
                new FeasibilityReport.Summary(1, 1, 0, 0, 0, 0),
                List.of(openingPassRule(Arrays.asList(verifiedOpeningEvidence(), null))),
                List.of());
        assertThatThrownBy(() -> FeasibilityReportValidator.validate(report))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void blankRequiredStringFieldsRejected() {
        FeasibilityReport blankRuleId = new FeasibilityReport(
                1,
                UUID.fromString("c9c467cc-65c4-8ff1-e175-4af42f2ed545"),
                "feasibility-v1",
                "a".repeat(64),
                FeasibilityStatus.VERIFIED,
                OffsetDateTime.parse("2026-08-09T12:00:00Z"),
                List.of("OPENING_HOURS"),
                List.of(),
                new FeasibilityReport.Summary(1, 1, 0, 0, 0, 0),
                List.of(new FeasibilityReport.RuleResult(
                        " ", "1", RuleOutcome.PASS, "REASON_OK", "ok",
                        List.of(), List.of(), List.of(verifiedOpeningEvidence()), false)),
                List.of());
        assertThatThrownBy(() -> FeasibilityReportValidator.validate(blankRuleId))
                .isInstanceOf(IllegalArgumentException.class);

        FeasibilityReport blankEvidenceType = new FeasibilityReport(
                1,
                UUID.fromString("c9c467cc-65c4-8ff1-e175-4af42f2ed545"),
                "feasibility-v1",
                "a".repeat(64),
                FeasibilityStatus.VERIFIED,
                OffsetDateTime.parse("2026-08-09T12:00:00Z"),
                List.of("OPENING_HOURS"),
                List.of(),
                new FeasibilityReport.Summary(1, 1, 0, 0, 0, 0),
                List.of(openingPassRule(List.of(new FeasibilityReport.EvidenceReference(
                        "ev-oh-1", "", EvidenceState.VERIFIED, true)))),
                List.of());
        assertThatThrownBy(() -> FeasibilityReportValidator.validate(blankEvidenceType))
                .isInstanceOf(IllegalArgumentException.class);
    }

    // ── B6J.2.1 F1: validatorVersion policy (legacy vs v4 vs unknown) ─────

    @Test
    void v4RuleResultRefsAreValidatedStrictly() {
        FeasibilityReport report = reportWithValidatorVersion(
                "hard-validator-v4",
                List.of(new FeasibilityReport.RuleResult(
                        "OPENING_HOURS", "1", RuleOutcome.PASS, "REASON_OK", "ok",
                        List.of(), List.of("8f5ef9c2-c194-4292-b847-5b9dcfda978b"),
                        List.of(verifiedOpeningEvidence()), false)),
                List.of());
        assertThatThrownBy(() -> FeasibilityReportValidator.validate(report))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("entity reference");
    }

    @Test
    void v4RepairAttemptRefsAreValidatedStrictly() {
        FeasibilityReport report = reportWithValidatorVersion(
                "hard-validator-v4",
                List.of(openingPassRule(List.of(verifiedOpeningEvidence()))),
                List.of(new FeasibilityReport.RepairAttempt(
                        1, List.of("OPENING_HOURS"), List.of("MOVE_ACTIVITY"),
                        List.of("2026-08-09"), List.of("unknown:value"),
                        "a".repeat(64), "a".repeat(64), FeasibilityStatus.VERIFIED)));
        assertThatThrownBy(() -> FeasibilityReportValidator.validate(report))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("entity reference");
    }

    @Test
    void v4ValidTypedRefsPass() {
        FeasibilityReport report = reportWithValidatorVersion(
                "hard-validator-v4",
                List.of(new FeasibilityReport.RuleResult(
                        "OPENING_HOURS", "1", RuleOutcome.PASS, "REASON_OK", "ok",
                        List.of(),
                        List.of("poi:POI-1",
                                "activity:10000000-0000-4000-8000-000000000031"),
                        List.of(verifiedOpeningEvidence()), false)),
                List.of());
        org.junit.jupiter.api.Assertions.assertDoesNotThrow(
                () -> FeasibilityReportValidator.validate(report));
    }

    @Test
    void legacyVersionsKeepUnprefixedRefsCompatible() {
        for (String legacy : new String[]{
                "feasibility-v1", "hard-validator-v1", "hard-validator-v2",
                "hard-validator-v3"}) {
            FeasibilityReport report = reportWithValidatorVersion(
                    legacy,
                    List.of(new FeasibilityReport.RuleResult(
                            "OPENING_HOURS", "1", RuleOutcome.PASS, "REASON_OK", "ok",
                            List.of(), List.of("8f5ef9c2-c194-4292-b847-5b9dcfda978b"),
                            List.of(verifiedOpeningEvidence()), false)),
                    List.of());
            org.junit.jupiter.api.Assertions.assertDoesNotThrow(
                    () -> FeasibilityReportValidator.validate(report),
                    "legacy version " + legacy + " must keep unprefixed refs");
        }
    }

    @Test
    void unknownValidatorVersionFailsClosedEvenWithValidTypedRefs() {
        FeasibilityReport report = reportWithValidatorVersion(
                "hard-validator-v9",
                List.of(new FeasibilityReport.RuleResult(
                        "OPENING_HOURS", "1", RuleOutcome.PASS, "REASON_OK", "ok",
                        List.of(), List.of("poi:POI-1"),
                        List.of(verifiedOpeningEvidence()), false)),
                List.of());
        assertThatThrownBy(() -> FeasibilityReportValidator.validate(report))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("validatorVersion");
    }

    private FeasibilityReport reportWithValidatorVersion(
            String validatorVersion,
            List<FeasibilityReport.RuleResult> ruleResults,
            List<FeasibilityReport.RepairAttempt> repairAttempts) {
        return new FeasibilityReport(
                1,
                UUID.fromString("c9c467cc-65c4-8ff1-e175-4af42f2ed545"),
                validatorVersion,
                "a".repeat(64),
                FeasibilityStatus.VERIFIED,
                OffsetDateTime.parse("2026-08-09T12:00:00Z"),
                List.of("OPENING_HOURS"),
                List.of(),
                new FeasibilityReport.Summary(ruleResults.size(), 1, 0, 0, 0, 0),
                ruleResults,
                repairAttempts);
    }
}
