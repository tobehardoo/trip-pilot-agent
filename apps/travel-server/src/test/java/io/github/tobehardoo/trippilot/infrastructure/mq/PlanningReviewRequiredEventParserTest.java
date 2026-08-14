package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.nio.charset.StandardCharsets;
import java.util.UUID;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import io.github.tobehardoo.trippilot.support.PlanningCompletedEventFixture;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PlanningReviewRequiredEventParserTest {

    private final ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();
    private final PlanningReviewRequiredEventParser parser =
            new PlanningReviewRequiredEventParser(objectMapper);

    @Test
    void parsesSharedReviewFixtureAndPreservesReport() {
        PlanningReviewRequiredEvent event = parser.parse(bytes(
                PlanningCompletedEventFixture.sharedReviewV1Fixture(
                        "review-v1-unverified-demo.json"
                )
        ));

        assertThat(event.schemaVersion()).isEqualTo(1);
        assertThat(event.payload().status()).isEqualTo("WAITING_USER");
        io.github.tobehardoo.trippilot.feasibility.FeasibilityReport report =
                event.payload().feasibilityReport();
        assertThat(report.status())
                .isEqualTo(io.github.tobehardoo.trippilot.feasibility.FeasibilityStatus.UNVERIFIED);
        assertThat(report.schemaVersion()).isEqualTo(1);
        assertThat(report.itineraryFingerprint())
                .isEqualTo("dce5e94d5981b3ffec3a0aff9dcfc29245d874552e863f4b432a47985bc7d025");
        assertThat(report.ruleResults()).hasSize(11);
        assertThat(event.payload().itinerary().days().get(0).transitLegs()).hasSize(1);
    }

    @Test
    void rejectsMissingFeasibilityReport() throws Exception {
        ObjectNode event = sharedReviewEvent();
        ((ObjectNode) event.at("/payload")).remove("feasibilityReport");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("feasibilityReport field types do not match");
    }

    @Test
    void rejectsEvaluationInReviewPayload() throws Exception {
        ObjectNode event = sharedReviewEvent();
        ((ObjectNode) event.at("/payload")).putObject("evaluation");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("evaluation is not allowed");
    }

    @Test
    void rejectsVerifiedReportStatus() throws Exception {
        ObjectNode event = sharedReviewEvent();
        ((ObjectNode) event.at("/payload/feasibilityReport")).put("status", "VERIFIED");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("feasibilityReport is invalid: status must be UNVERIFIED");
    }

    @Test
    void acceptsNeedsRepairReportStatus() throws Exception {
        PlanningReviewRequiredEvent parsed = parser.parse(bytes(
                PlanningCompletedEventFixture.sharedReviewV1Fixture(
                        "review-v1-needs-repair-demo.json"
                )
        ));

        io.github.tobehardoo.trippilot.feasibility.FeasibilityReport report =
                parsed.payload().feasibilityReport();
        assertThat(report.status())
                .isEqualTo(io.github.tobehardoo.trippilot.feasibility.FeasibilityStatus.NEEDS_REPAIR);
        assertThat(report.ruleResults()).anyMatch(
                r -> r.outcome() == io.github.tobehardoo.trippilot.feasibility.RuleOutcome.FAIL);
        assertThat(report.repairAttempts()).isNotEmpty();
        assertThat(report.repairAttempts().get(0).attemptIndex()).isEqualTo(1);
    }

    @Test
    void acceptsExplicitUnavailableKnowledgeFreshnessFromCandidateOutcome() throws Exception {
        ObjectNode event = sharedReviewEvent();
        ObjectNode knowledge = (ObjectNode) event.at("/payload/knowledge");
        knowledge.put("status", "DEMO");
        knowledge.put("message", "Local demo evidence is unavailable");
        knowledge.putArray("citations");
        ObjectNode freshness = knowledge.putObject("freshness");
        freshness.put("status", "UNAVAILABLE");
        freshness.putNull("checkedAt");
        freshness.putNull("staleReason");

        PlanningReviewRequiredEvent parsed = parser.parse(
                objectMapper.writeValueAsBytes(event));

        assertThat(parsed.payload().knowledge().freshness().status())
                .isEqualTo("UNAVAILABLE");
        assertThat(parsed.payload().knowledge().freshness().checkedAt()).isNull();
    }

    @Test
    void acceptsHardValidatorV5RepairHistory() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.sharedReviewV1Fixture(
                        "review-v1-needs-repair-demo.json"
                )
        );
        ((ObjectNode) event.at("/payload/feasibilityReport"))
                .put("validatorVersion", "hard-validator-v5");

        PlanningReviewRequiredEvent parsed = parser.parse(
                objectMapper.writeValueAsBytes(event));

        assertThat(parsed.payload().feasibilityReport().validatorVersion())
                .isEqualTo("hard-validator-v5");
        assertThat(parsed.payload().feasibilityReport().repairAttempts())
                .extracting("attemptIndex")
                .containsExactly(1);
    }

    @Test
    void rejectsMismatchedItineraryFingerprint() throws Exception {
        ObjectNode event = sharedReviewEvent();
        ((ObjectNode) event.at("/payload/feasibilityReport"))
                .put("itineraryFingerprint", "0".repeat(64));

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("itineraryFingerprint does not match the itinerary");
    }

    @Test
    void rejectsNonWaitingUserStatus() throws Exception {
        ObjectNode event = sharedReviewEvent();
        ((ObjectNode) event.at("/payload")).put("status", "REVIEWING");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("status must be WAITING_USER");
    }

    @Test
    void rejectsSchemaVersionNotOne() throws Exception {
        ObjectNode event = sharedReviewEvent();
        event.put("schemaVersion", 2);

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("unsupported eventType or schemaVersion");
    }

    // ── B6J.2.1 F1: v4 typed refs semantic gate ───────────────────────────

    @Test
    void rejectsV4BareUuidEntityRef() throws Exception {
        ObjectNode event = sharedReviewEvent();
        setFirstRuleRef(event, "8f5ef9c2-c194-4292-b847-5b9dcfda978b");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("feasibilityReport is invalid");
    }

    @Test
    void rejectsV4UnknownKindEntityRef() throws Exception {
        ObjectNode event = sharedReviewEvent();
        setFirstRuleRef(event, "unknown:value");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("feasibilityReport is invalid");
    }

    @Test
    void rejectsV4NonCanonicalActivityUuidRef() throws Exception {
        ObjectNode event = sharedReviewEvent();
        setFirstRuleRef(event, "activity:10000000-0000-4000-8000-AABBCCDDEEFF");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("feasibilityReport is invalid");
    }

    @Test
    void rejectsV4InvalidRepairAttemptRef() throws Exception {
        ObjectNode event = sharedReviewEvent();
        com.fasterxml.jackson.databind.node.ArrayNode attempts = objectMapper.createArrayNode();
        ObjectNode attempt = attempts.addObject();
        attempt.put("attemptIndex", 1);
        attempt.putArray("triggeringRuleIds").add("DUPLICATE_POI");
        attempt.putArray("actionCodes").add("REMOVE_DUPLICATE");
        attempt.putArray("affectedDates").add("2026-08-01");
        attempt.putArray("affectedEntityRefs").add("8f5ef9c2-c194-4292-b847-5b9dcfda978b");
        attempt.put("beforeFingerprint", "dce5e94d5981b3ffec3a0aff9dcfc29245d874552e863f4b432a47985bc7d025");
        attempt.put("afterFingerprint", "dce5e94d5981b3ffec3a0aff9dcfc29245d874552e863f4b432a47985bc7d025");
        attempt.put("resultingStatus", "NEEDS_REPAIR");
        ((ObjectNode) event.at("/payload/feasibilityReport")).set("repairAttempts", attempts);

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("feasibilityReport is invalid");
    }

    @Test
    void rejectsUnknownValidatorVersionWithTypedRefs() throws Exception {
        ObjectNode event = sharedReviewEvent();
        ((ObjectNode) event.at("/payload/feasibilityReport"))
                .put("validatorVersion", "hard-validator-v9");
        setFirstRuleRef(event, "poi:POI-1");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("feasibilityReport is invalid");
    }

    @Test
    void rejectsUnknownValidatorVersionEvenWithEmptyRefs() throws Exception {
        ObjectNode event = sharedReviewEvent();
        ((ObjectNode) event.at("/payload/feasibilityReport"))
                .put("validatorVersion", "arbitrary-validator");
        clearAllRuleRefs(event);

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("feasibilityReport is invalid");
    }

    private void setFirstRuleRef(ObjectNode event, String value) {
        com.fasterxml.jackson.databind.JsonNode results =
                event.at("/payload/feasibilityReport/ruleResults");
        for (com.fasterxml.jackson.databind.JsonNode rule : results) {
            if (rule.path("affectedEntityRefs").isArray()
                    && rule.path("affectedEntityRefs").size() > 0) {
                ((com.fasterxml.jackson.databind.node.ArrayNode) rule.path("affectedEntityRefs"))
                        .set(0, objectMapper.getNodeFactory().textNode(value));
                return;
            }
        }
        com.fasterxml.jackson.databind.node.ArrayNode refs = objectMapper.createArrayNode();
        refs.add(value);
        ((ObjectNode) results.get(0)).set("affectedEntityRefs", refs);
    }

    private void clearAllRuleRefs(ObjectNode event) {
        com.fasterxml.jackson.databind.JsonNode results =
                event.at("/payload/feasibilityReport/ruleResults");
        for (com.fasterxml.jackson.databind.JsonNode rule : results) {
            ((ObjectNode) rule).set("affectedEntityRefs", objectMapper.createArrayNode());
        }
    }

    // ── B6J.2.2 R1: validated raw itinerary snapshot ──────────────────────

    @Test
    void parsedEventCarriesRawItinerarySnapshot() throws Exception {
        PlanningReviewRequiredEvent event = parser.parse(bytes(
                PlanningCompletedEventFixture.sharedReviewV1Fixture(
                        "review-v1-needs-repair-demo.json"
                )
        ));

        com.fasterxml.jackson.databind.JsonNode snapshot =
                event.payload().validatedItineraryJson();
        assertThat(snapshot).isNotNull();
        assertThat(snapshot.isObject()).isTrue();
        assertThat(snapshot.path("title").asText()).isEqualTo("Benchmark itinerary");
    }

    @Test
    void snapshotDeepEqualsInputWireItinerary() throws Exception {
        ObjectNode tree = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.sharedReviewV1Fixture(
                        "review-v1-needs-repair-demo.json"
                )
        );
        com.fasterxml.jackson.databind.JsonNode wireItinerary =
                tree.at("/payload/itinerary");

        PlanningReviewRequiredEvent event = parser.parse(
                objectMapper.writeValueAsBytes(tree));

        assertThat(event.payload().validatedItineraryJson())
                .isEqualTo(wireItinerary);
    }

    @Test
    void serializedParsedEventNeverContainsInternalSnapshotField() throws Exception {
        PlanningReviewRequiredEvent event = parser.parse(bytes(
                PlanningCompletedEventFixture.sharedReviewV1Fixture(
                        "review-v1-needs-repair-demo.json"
                )
        ));

        String serialized = objectMapper.writeValueAsString(event);
        assertThat(serialized).doesNotContain("validatedItineraryJson");
        assertThat(serialized).doesNotContain("rawItinerary");
        // The wire candidate is still the typed itinerary under payload.
        assertThat(objectMapper.readTree(serialized).at("/payload/itinerary").isObject())
                .isTrue();
    }

    @Test
    void snapshotIsDefensiveCopyNotAffectedByExternalMutation() throws Exception {
        ObjectNode tree = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.sharedReviewV1Fixture(
                        "review-v1-needs-repair-demo.json"
                )
        );
        PlanningReviewRequiredEvent event = parser.parse(
                objectMapper.writeValueAsBytes(tree));

        // Mutate the caller's tree after parse; the internal snapshot must not
        // change (deepCopy captured at parse time).
        ((ObjectNode) tree.at("/payload/itinerary")).put("title", "mutated");
        assertThat(event.payload().validatedItineraryJson().path("title").asText())
                .isEqualTo("Benchmark itinerary");
    }

    @Test
    void fingerprintMismatchStillRejectedWithSnapshotDesign() throws Exception {
        ObjectNode tree = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.sharedReviewV1Fixture(
                        "review-v1-needs-repair-demo.json"
                )
        );
        ((ObjectNode) tree.at("/payload/feasibilityReport"))
                .put("itineraryFingerprint", "0".repeat(64));

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(tree)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("itineraryFingerprint does not match");
    }

    @Test
    void acceptsNullActivityIdFromProviderPlaceholders() throws Exception {
        // The Python contract declares activityId as UUID | None; provider
        // placeholders (e.g. Demo activities without a resolved POI id)
        // legally emit null.  Only a present non-textual value is rejected.
        ObjectNode event = sharedReviewEvent();
        ((ObjectNode) event.at("/payload/itinerary/days/0/activities/0"))
                .putNull("activityId");
        refreshFingerprint(event);

        PlanningReviewRequiredEvent parsed =
                parser.parse(objectMapper.writeValueAsBytes(event));

        assertThat(parsed.payload().itinerary().days().get(0).activities().get(0)
                .activityId()).isNull();
    }

    @Test
    void stillRejectsNonTextualActivityId() throws Exception {
        ObjectNode event = sharedReviewEvent();
        ((ObjectNode) event.at("/payload/itinerary/days/0/activities/0"))
                .put("activityId", 12345);
        refreshFingerprint(event);

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("activityId must be a UUID string");
    }

    private void refreshFingerprint(ObjectNode event) {
        String fingerprint = io.github.tobehardoo.trippilot.feasibility
                .ItineraryFingerprintVerifier.compute(event.at("/payload/itinerary"));
        ((ObjectNode) event.at("/payload/feasibilityReport"))
                .put("itineraryFingerprint", fingerprint);
    }

    private ObjectNode sharedReviewEvent() throws Exception {
        return (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.sharedReviewV1Fixture(
                        "review-v1-unverified-demo.json"
                )
        );
    }

    private byte[] bytes(String value) {
        return value.getBytes(StandardCharsets.UTF_8);
    }
}
