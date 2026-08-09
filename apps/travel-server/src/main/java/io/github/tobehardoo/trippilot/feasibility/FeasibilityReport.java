package io.github.tobehardoo.trippilot.feasibility;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Standalone feasibility report (schemaVersion 1) — B1 contract foundation.
 *
 * Deliberately NOT wired into any runtime parser or envelope; v8/v2 remain
 * unchanged. Cross-field semantics are enforced by {@link FeasibilityReportValidator}.
 */
public record FeasibilityReport(
        @JsonProperty("schemaVersion") int schemaVersion,
        @JsonProperty("reportId") UUID reportId,
        @JsonProperty("validatorVersion") String validatorVersion,
        @JsonProperty("itineraryFingerprint") String itineraryFingerprint,
        @JsonProperty("status") FeasibilityStatus status,
        @JsonProperty("validatedAt") OffsetDateTime validatedAt,
        @JsonProperty("requiredRuleIds") List<String> requiredRuleIds,
        @JsonProperty("missingRequiredRuleIds") List<String> missingRequiredRuleIds,
        @JsonProperty("summary") Summary summary,
        @JsonProperty("ruleResults") List<RuleResult> ruleResults,
        @JsonProperty("repairAttempts") List<RepairAttempt> repairAttempts
) {

    public record Summary(
            @JsonProperty("totalCount") int totalCount,
            @JsonProperty("passCount") int passCount,
            @JsonProperty("failCount") int failCount,
            @JsonProperty("unknownCount") int unknownCount,
            @JsonProperty("notApplicableCount") int notApplicableCount,
            @JsonProperty("missingRequiredCount") int missingRequiredCount
    ) {
        @JsonCreator
        public Summary {
        }
    }

    public record RuleResult(
            @JsonProperty("ruleId") String ruleId,
            @JsonProperty("ruleVersion") String ruleVersion,
            @JsonProperty("outcome") RuleOutcome outcome,
            @JsonProperty("reasonCode") String reasonCode,
            @JsonProperty("message") String message,
            @JsonProperty("affectedDates") List<String> affectedDates,
            @JsonProperty("affectedEntityRefs") List<String> affectedEntityRefs,
            @JsonProperty("evidenceRefs") List<EvidenceReference> evidenceRefs,
            @JsonProperty("repairable") boolean repairable
    ) {
        @JsonCreator
        public RuleResult {
        }
    }

    public record EvidenceReference(
            @JsonProperty("evidenceId") String evidenceId,
            @JsonProperty("evidenceType") String evidenceType,
            @JsonProperty("state") EvidenceState state,
            @JsonProperty("hardConstraintEligible") boolean hardConstraintEligible
    ) {
        @JsonCreator
        public EvidenceReference {
        }
    }

    public record RepairAttempt(
            @JsonProperty("attemptIndex") int attemptIndex,
            @JsonProperty("triggeringRuleIds") List<String> triggeringRuleIds,
            @JsonProperty("actionCodes") List<String> actionCodes,
            @JsonProperty("affectedDates") List<String> affectedDates,
            @JsonProperty("affectedEntityRefs") List<String> affectedEntityRefs,
            @JsonProperty("beforeFingerprint") String beforeFingerprint,
            @JsonProperty("afterFingerprint") String afterFingerprint,
            @JsonProperty("resultingStatus") FeasibilityStatus resultingStatus
    ) {
        @JsonCreator
        public RepairAttempt {
        }
    }

    @JsonCreator
    public FeasibilityReport {
    }
}
