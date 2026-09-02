package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.util.UUID;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import io.github.tobehardoo.trippilot.common.EventContractException;
import io.github.tobehardoo.trippilot.support.PlanningCompletedEventFixture;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PlanningCompletedEventParserTest {

    @Test
    void parsesEverySharedPlanEvaluationFixtureAndKeepsLegacyV6Compatible() throws Exception {
        assertRuntimeRejects(PlanningCompletedEventFixture.sharedV6Fixture(
                "completion-v6-legacy-without-evaluation.json"
        ));
    }
    @Test
    void rejectsEvaluationWhenOverallScoreDoesNotMatchWeightedDimensions() throws Exception {
        assertRuntimeRejects(PlanningCompletedEventFixture.sharedV6Fixture(
                "completion-v6-evaluation-clean.json"
        ));
    }
    @Test
    void acceptsEvaluationHalfUpRoundingAtTheCrossLanguageBoundary() throws Exception {
        assertRuntimeRejects(PlanningCompletedEventFixture.sharedV6Fixture(
                "completion-v6-evaluation-clean.json"
        ));
    }
    @Test
    void acceptsV2EvaluationWithNormalizedNotApplicableDimensions() throws Exception {
        assertRuntimeRejects(PlanningCompletedEventFixture.sharedV6Fixture(
                "completion-v6-evaluation-clean.json"
        ));
    }
    @Test
    void rejectsEvaluationValuesOutsideTheSharedSchemaEnumsAndCardinality() throws Exception {
        assertRuntimeRejects(eventJson());
    }
    @Test
    void acceptsHistoricalV6WithoutInventingProviderProvenance() throws Exception {
        assertRuntimeRejects(PlanningCompletedEventFixture.sharedV6Fixture(
                "completion-v6-legacy-amap.json"
        ));
    }
    @Test
    void parsesMultiTransitV6ProvenanceByStableTransitIdentity() throws Exception {
        assertRuntimeRejects(PlanningCompletedEventFixture.sharedV6Fixture(
                "completion-v6-multi-transit-mixed.json"
        ));
    }
    @Test
    void rejectsFallbackOperationThatDoesNotMatchItsTransitIdentity() throws Exception {
        assertRuntimeRejects(PlanningCompletedEventFixture.sharedV6Fixture(
                "completion-v6-multi-transit-mixed.json"
        ));
    }
    @Test
    void rejectsRealOnlyCompletionThatContainsDemoEvidence() throws Exception {
        assertRuntimeRejects(PlanningCompletedEventFixture.sharedV6Fixture(
                "completion-v6-multi-transit-mixed.json"
        ));
    }
    @Test
    void rejectsSuccessfulFallbackWithoutAnAttempt() throws Exception {
        assertRuntimeRejects(PlanningCompletedEventFixture.sharedV6Fixture(
                "completion-v6-multi-transit-mixed.json"
        ));
    }
    private final ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();
    private final PlanningCompletedEventParser parser = new PlanningCompletedEventParser(objectMapper);

    @Test
    void acceptsNullActivityIdAndTransitIdInV9Placeholders() throws Exception {
        // The Python contract declares activityId/transitId as UUID | None;
        // provider placeholders legally emit null for unresolved nodes.
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV9(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        ((ObjectNode) event.at("/payload/itinerary/days/0/activities/0"))
                .putNull("activityId");
        ((ObjectNode) event.at("/payload/itinerary/days/0/transitLegs/0"))
                .putNull("transitId");
        ((ObjectNode) event.at("/payload/feasibilityReport"))
                .put("itineraryFingerprint",
                        io.github.tobehardoo.trippilot.feasibility.ItineraryFingerprintVerifier
                                .compute(event.at("/payload/itinerary")));

        PlanningCompletedEvent parsed =
                parser.parse(objectMapper.writeValueAsBytes(event));

        assertThat(parsed.payload().itinerary().days().get(0).activities().get(0)
                .activityId()).isNull();
        assertThat(parsed.payload().itinerary().days().get(0).transitLegs().get(0)
                .transitId()).isNull();
    }

    @Test
    void stillRejectsNonTextualV9ActivityId() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV9(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        ((ObjectNode) event.at("/payload/itinerary/days/0/activities/0"))
                .put("activityId", 12345);

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("activityId is only supported as a UUID string");
    }

    @Test
    void runtimeAcceptsOnlySchemaVersionNine() throws Exception {
        ObjectNode v2 = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV2(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        ObjectNode v3 = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV3(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        ObjectNode v4 = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV4(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        ObjectNode v9 = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV9(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        for (int version : new int[]{1, 2, 3, 4, 5, 6, 7, 8}) {
            ObjectNode event = version == 2 ? v2
                    : version == 3 ? v3
                    : version == 4 ? v4 : (ObjectNode) v9.deepCopy();
            event.put("schemaVersion", version);
            assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                    .isInstanceOf(EventContractException.class)
                    .hasMessageContaining("unsupported eventType or schemaVersion");
        }
        assertThat(parser.parse(objectMapper.writeValueAsBytes(v9)).schemaVersion())
                .isEqualTo(9);
    }

    @Test
    void parsesThePythonCompletedEventContract() throws Exception {
        assertRuntimeRejects(eventJson());
    }
    @Test
    void parsesV2AmapActivityMetadataWhileKeepingV1Compatible() throws Exception {
        assertRuntimeRejects(PlanningCompletedEventFixture.completedAmapEventV2(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                ));
    }
    @Test
    void parsesV3TransitLegsWhileKeepingOlderContractsCompatible() throws Exception {
        assertRuntimeRejects(amapV3Event());
    }
    @Test
    void acceptsDrivingTransfersOnlyInTheV5Contract() throws Exception {
        assertRuntimeRejects(amapV4Event());
    }
    @Test
    void parsesV6FactImpactsWithTraceableLifecycleFields() throws Exception {
        assertRuntimeRejects(amapV4Event());
    }
    @Test
    void rejectsTheUnreleasedV7CompletedEventContract() throws Exception {
        ObjectNode event = amapV4Event();
        event.put("schemaVersion", 7);
        ((ObjectNode) event.at("/payload/itinerary/days/0/transitLegs/0"))
                .put("mode", "TAXI")
                .put("estimatedCost", 42.50)
                .put("costSource", "PROVIDER");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("unsupported eventType or schemaVersion");
    }

    @Test
    void rejectsV3TransitLegsThatDoNotConnectEveryAdjacentActivity() throws Exception {
        assertRuntimeRejects(amapV3Event());
    }
    @Test
    void acceptsOutOfOrderTransitLegsByTheirActivityEndpointsAndRejectsDuplicateEndpoints() throws Exception {
        assertRuntimeRejects(amapV4Event());
    }
    @Test
    void rejectsV3TransitLegWithInvalidPolylineOrImpossibleTravelTime() throws Exception {
        assertRuntimeRejects(amapV3Event());
    }
    @Test
    void rejectsInvalidV4KnowledgeEvidenceStates() throws Exception {
        assertRuntimeRejects(amapV4Event());
    }
    @Test
    void rejectsV4CitationWithNonHttpSourceUrl() throws Exception {
        assertRuntimeRejects(amapV4Event());
    }
    @Test
    void parsesV2DemoFallbackWithoutAmapMetadata() throws Exception {
        assertRuntimeRejects(eventJson());
    }
    @Test
    void rejectsV2AmapActivityWithoutCoordinates() throws Exception {
        assertRuntimeRejects(amapV2Event());
    }
    @Test
    void rejectsV2PayloadAndActivityProviderMismatch() throws Exception {
        assertRuntimeRejects(amapV2Event());
    }
    @Test
    void rejectsV2AmapCoordinatesOutsideValidBounds() throws Exception {
        assertRuntimeRejects(amapV2Event());
    }
    @Test
    void rejectsV2AmapCoordinateStringCoercion() throws Exception {
        assertRuntimeRejects(amapV2Event());
    }
    @Test
    void rejectsV2DemoActivityThatClaimsAmapMetadata() throws Exception {
        assertRuntimeRejects(amapV2Event());
    }
    @Test
    void rejectsUnknownWireFields() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(eventJson());
        event.put("unexpected", true);

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("Invalid PLANNING_COMPLETED event");
    }

    @Test
    void rejectsAnEmptyMessageAsAContractViolation() {
        assertThatThrownBy(() -> parser.parse(new byte[0]))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("Invalid PLANNING_COMPLETED event");
    }

    @Test
    void rejectsAnActivityWhoseEndIsNotAfterItsStart() throws Exception {
        assertRuntimeRejects(eventJson());
    }
    @Test
    void rejectsAnEmptyItinerary() throws Exception {
        assertRuntimeRejects(eventJson());
    }
    @Test
    void rejectsScalarTypeCoercionThatTheJsonSchemaDoesNotAllow() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(eventJson());
        event.put("schemaVersion", "1");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("Invalid PLANNING_COMPLETED event");
    }

    @Test
    void rejectsOverlappingActivities() throws Exception {
        assertRuntimeRejects(eventJson());
    }
    @Test
    void rejectsTextThatCannotFitThePersistenceSchema() throws Exception {
        assertRuntimeRejects(eventJson());
    }
    @Test
    void rejectsMoneyThatCannotFitThePersistenceSchema() throws Exception {
        assertRuntimeRejects(eventJson());
    }
    private String eventJson() {
        return PlanningCompletedEventFixture.completedEvent(
                UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID()
        );
    }

    @Test
    void parsesV9ScheduleFieldsAndPreservesThem() {
        PlanningCompletedEvent event = parser.parse(bytes(
                PlanningCompletedEventFixture.completedAmapEventV9(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        ));

        assertThat(event.schemaVersion()).isEqualTo(9);
        PlanningCompletedEvent.Day day = event.payload().itinerary().days().get(0);
        assertThat(day.dayType()).isEqualTo("ARRIVAL_DAY");
        assertThat(day.activities().get(0).kind()).isEqualTo("ARRIVAL");
        assertThat(day.activities().get(0).timeFixed()).isTrue();
        assertThat(day.activities().get(1).kind()).isEqualTo("ATTRACTION");
        assertThat(day.activities().get(1).timeFixed()).isFalse();
        assertThat(day.activities().get(2).kind()).isEqualTo("MEAL");
        assertThat(day.activities().get(2).timeFixed()).isFalse();
    }

    @Test
    void v9AcceptsStructuralMealNodeWithoutProviderMetadataAndTransitGap() {
        PlanningCompletedEvent event = parser.parse(bytes(
                PlanningCompletedEventFixture.completedAmapEventV9(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        ));

        PlanningCompletedEvent.Activity meal = event.payload().itinerary().days().get(0)
                .activities().get(2);
        assertThat(meal.kind()).isEqualTo("MEAL");
        assertThat(meal.providerPoiId()).isNull();
        assertThat(meal.coordinates()).isNull();
        assertThat(meal.address()).isNull();
        // Only one transit leg covers activities 0->1; the meal gap (1->2) has none.
        assertThat(event.payload().itinerary().days().get(0).transitLegs()).hasSize(1);
    }

    @Test
    void v9RejectsUnknownActivityKind() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV9(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        ((ObjectNode) event.at("/payload/itinerary/days/0/activities/1")).put("kind", "TRANSFER");
        ((ObjectNode) event.at("/payload/feasibilityReport")).put(
                "itineraryFingerprint",
                io.github.tobehardoo.trippilot.feasibility.ItineraryFingerprintVerifier
                        .compute(event.at("/payload/itinerary")));

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("activity kind is not a supported value");
    }

    @Test
    void v9RejectsUnknownDayType() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV9(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        ((ObjectNode) event.at("/payload/itinerary/days/0")).put("dayType", "NIGHT_DAY");
        ((ObjectNode) event.at("/payload/feasibilityReport")).put(
                "itineraryFingerprint",
                io.github.tobehardoo.trippilot.feasibility.ItineraryFingerprintVerifier
                        .compute(event.at("/payload/itinerary")));

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("dayType is not a supported value");
    }

    @Test
    void v9RejectsNonStructuralActivityMissingProviderMetadata() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV9(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        // Make the ATTRACTION lose its provider metadata: structural-only exemption.
        ObjectNode attraction = (ObjectNode) event.at("/payload/itinerary/days/0/activities/1");
        attraction.remove("providerPoiId");
        attraction.remove("coordinates");
        attraction.remove("address");
        ((ObjectNode) event.at("/payload/feasibilityReport")).put(
                "itineraryFingerprint",
                io.github.tobehardoo.trippilot.feasibility.ItineraryFingerprintVerifier
                        .compute(event.at("/payload/itinerary")));

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("AMAP activity requires valid provider metadata");
    }

    @Test
    void parsesSharedV9FixtureAndPreservesFeasibilityReport() {
        PlanningCompletedEvent event = parser.parse(bytes(
                PlanningCompletedEventFixture.sharedV9Fixture(
                        "completion-v9-verified-amap.json"
                )
        ));

        assertThat(event.schemaVersion()).isEqualTo(9);
        io.github.tobehardoo.trippilot.feasibility.FeasibilityReport report =
                event.payload().feasibilityReport();
        assertThat(report.status())
                .isEqualTo(io.github.tobehardoo.trippilot.feasibility.FeasibilityStatus.VERIFIED);
        assertThat(report.schemaVersion()).isEqualTo(1);
        assertThat(report.itineraryFingerprint())
                .isEqualTo("e8e68b0750eed9238cfbee315b813a44319172020c7b52e32e47b0ca9e7aa21e");
        assertThat(report.summary().totalCount()).isEqualTo(11);
        assertThat(report.ruleResults()).hasSize(11);
        io.github.tobehardoo.trippilot.feasibility.FeasibilityReport.RuleResult opening =
                report.ruleResults().stream()
                        .filter(r -> "OPENING_HOURS".equals(r.ruleId()))
                        .findFirst().orElseThrow();
        assertThat(opening.outcome())
                .isEqualTo(io.github.tobehardoo.trippilot.feasibility.RuleOutcome.PASS);
        assertThat(opening.evidenceRefs()).isNotEmpty();
        assertThat(opening.evidenceRefs().get(0).evidenceType()).isEqualTo("OPENING_HOURS");
        assertThat(opening.evidenceRefs().get(0).state())
                .isEqualTo(io.github.tobehardoo.trippilot.feasibility.EvidenceState.VERIFIED);
        assertThat(opening.evidenceRefs().get(0).hardConstraintEligible()).isTrue();
        assertThat(event.payload().evaluation().feasible()).isTrue();
    }

    @Test
    void v9RejectsMissingFeasibilityReport() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV9(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        ((ObjectNode) event.at("/payload")).remove("feasibilityReport");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("feasibilityReport field types do not match");
    }

    @Test
    void v9RejectsMissingEvaluation() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV9(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        ((ObjectNode) event.at("/payload")).remove("evaluation");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("evaluation is required in schema v9");
    }

    @Test
    void v9RejectsNonVerifiedReportStatus() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV9(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        ((ObjectNode) event.at("/payload/feasibilityReport")).put("status", "NEEDS_REPAIR");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("feasibilityReport is invalid: status must be VERIFIED");
    }

    // ── B16: v10 savable UNVERIFIED completions (Information Missing !=
    //    Planning Failed) ────────────────────────────────────────────────────

    @Test
    void v10AcceptsSavableUnverifiedReportWithHasBlockerFalse() throws Exception {
        PlanningCompletedEvent event = parser.parse(bytes(
                PlanningCompletedEventFixture.completedAmapEventV10(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        ));

        assertThat(event.schemaVersion()).isEqualTo(10);
        assertThat(event.payload().hasBlocker()).isFalse();
        assertThat(event.payload().feasibilityReport().status())
                .isEqualTo(io.github.tobehardoo.trippilot.feasibility.FeasibilityStatus.UNVERIFIED);
        assertThat(event.payload().evaluation().feasible()).isTrue();
    }

    @Test
    void v10RejectsBlockerReportEvenWhenFlagMatches() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV10(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        // A blocker report: one hard FAIL with consistent summary counts.
        ObjectNode report = (ObjectNode) event.at("/payload/feasibilityReport");
        report.put("status", "NEEDS_REPAIR");
        ((ObjectNode) report.path("summary")).put("failCount", 1);
        ((ObjectNode) report.path("summary")).put("unknownCount", 10);
        ObjectNode failing = (ObjectNode) report.path("ruleResults").path(0);
        failing.put("outcome", "FAIL");
        failing.put("reasonCode", "TIME_CONFLICT");
        failing.put("message", "activity conflicts with a fixed schedule");
        ((ObjectNode) event.at("/payload")).put("hasBlocker", true);

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("feasibilityReport status must be VERIFIED");
    }

    @Test
    void v10RejectsHasBlockerMismatchWithReportContent() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV10(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        // Report is UNVERIFIED with no blocker, but the flag lies.
        ((ObjectNode) event.at("/payload")).put("hasBlocker", true);

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("v10 hasBlocker must match the feasibility report blocker state");
    }

    @Test
    void v10RequiresBooleanHasBlocker() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV10(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        ((ObjectNode) event.at("/payload")).put("hasBlocker", "yes");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("v10 payload requires a boolean hasBlocker");
    }

    @Test
    void v10AcceptsProviderProvenanceWithRealOnlyEvidence() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV10(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        ObjectNode provenance = objectMapper.createObjectNode()
                .put("requestedProviderMode", "REAL_ONLY")
                .put("primaryProvider", "AMAP");
        provenance.putArray("actualProviders").add("AMAP");
        provenance.put("fallbackAttempted", false);
        provenance.put("fallbackSucceeded", false);
        provenance.putNull("fallbackReason");
        provenance.putArray("fallbackOperations");
        ((ObjectNode) event.at("/payload")).set("providerProvenance", provenance);

        PlanningCompletedEvent parsed = parser.parse(objectMapper.writeValueAsBytes(event));

        assertThat(parsed.schemaVersion()).isEqualTo(10);
        assertThat(parsed.payload().providerProvenance().requestedProviderMode())
                .isEqualTo(PlanningCompletedEvent.ProviderExecutionMode.REAL_ONLY);
    }

    @Test
    void v9RejectsMismatchedItineraryFingerprint() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV9(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        ((ObjectNode) event.at("/payload/feasibilityReport"))
                .put("itineraryFingerprint", "0".repeat(64));

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("itineraryFingerprint does not match the itinerary");
    }

    @Test
    void v9RejectsReportSchemaVersionNotOne() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV9(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        ((ObjectNode) event.at("/payload/feasibilityReport")).put("schemaVersion", 2);

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("feasibilityReport is invalid: schemaVersion must be 1");
    }

    @Test
    void rejectsSupersededV8SharedFixture() {
        assertThatThrownBy(() -> parser.parse(bytes(
                PlanningCompletedEventFixture.sharedV8Fixture(
                        "completion-v8-real-only-amap.json"
                )
        )))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("unsupported eventType or schemaVersion");
    }

    @Test
    void rejectsAbandonedV7EvenWhenStructurallyWellFormed() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV9(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        event.put("schemaVersion", 7);

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("unsupported eventType or schemaVersion");
    }

    private ObjectNode amapV2Event() throws Exception {
        return (ObjectNode) objectMapper.readTree(PlanningCompletedEventFixture.completedAmapEventV2(
                UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID()
        ));
    }

    private ObjectNode amapV3Event() throws Exception {
        return (ObjectNode) objectMapper.readTree(PlanningCompletedEventFixture.completedAmapEventV3(
                UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID()
        ));
    }

    private ObjectNode amapV4Event() throws Exception {
        return (ObjectNode) objectMapper.readTree(PlanningCompletedEventFixture.completedAmapEventV4(
                UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID()
        ));
    }

    private ObjectNode evaluationFixture(String fixtureName) throws Exception {
        return (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.sharedV6Fixture(fixtureName));
    }

    private byte[] bytes(String value) {
        return value.getBytes(StandardCharsets.UTF_8);
    }

    private void assertRuntimeRejects(String body) {
        assertThatThrownBy(() -> parser.parse(bytes(body)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("unsupported eventType or schemaVersion");
    }

    private void assertRuntimeRejects(ObjectNode event) throws Exception {
        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("unsupported eventType or schemaVersion");
    }

    // ── B6J.2.1 F1: v4 typed refs semantic gate ───────────────────────────

    @Test
    void rejectsV9BareUuidEntityRef() throws Exception {
        ObjectNode event = amapV9Event();
        setFirstRuleRef(event, "8f5ef9c2-c194-4292-b847-5b9dcfda978b");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("feasibilityReport is invalid");
    }

    @Test
    void rejectsV9UnknownKindEntityRef() throws Exception {
        ObjectNode event = amapV9Event();
        setFirstRuleRef(event, "unknown:value");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("feasibilityReport is invalid");
    }

    @Test
    void rejectsV9NonCanonicalActivityUuidRef() throws Exception {
        ObjectNode event = amapV9Event();
        setFirstRuleRef(event, "activity:10000000-0000-4000-8000-AABBCCDDEEFF");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("feasibilityReport is invalid");
    }

    @Test
    void rejectsV9InvalidRepairAttemptRef() throws Exception {
        ObjectNode event = amapV9Event();
        ArrayNode attempts = objectMapper.createArrayNode();
        ObjectNode attempt = attempts.addObject();
        attempt.put("attemptIndex", 1);
        attempt.putArray("triggeringRuleIds").add("DUPLICATE_POI");
        attempt.putArray("actionCodes").add("REMOVE_DUPLICATE");
        attempt.putArray("affectedDates").add("2026-08-01");
        attempt.putArray("affectedEntityRefs").add("8f5ef9c2-c194-4292-b847-5b9dcfda978b");
        attempt.put("beforeFingerprint", "e8e68b0750eed9238cfbee315b813a44319172020c7b52e32e47b0ca9e7aa21e");
        attempt.put("afterFingerprint", "e8e68b0750eed9238cfbee315b813a44319172020c7b52e32e47b0ca9e7aa21e");
        attempt.put("resultingStatus", "VERIFIED");
        ((ObjectNode) event.at("/payload/feasibilityReport")).set("repairAttempts", attempts);

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("feasibilityReport is invalid");
    }

    @Test
    void rejectsV9UnknownValidatorVersion() throws Exception {
        ObjectNode event = amapV9Event();
        ((ObjectNode) event.at("/payload/feasibilityReport"))
                .put("validatorVersion", "hard-validator-v9");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("feasibilityReport is invalid");
    }

    @Test
    void acceptsV9HardValidatorV5Report() throws Exception {
        ObjectNode event = amapV9Event();
        ((ObjectNode) event.at("/payload/feasibilityReport"))
                .put("validatorVersion", "hard-validator-v5");

        PlanningCompletedEvent parsed = parser.parse(objectMapper.writeValueAsBytes(event));

        assertThat(parsed.payload().feasibilityReport().validatorVersion())
                .isEqualTo("hard-validator-v5");
    }

    private ObjectNode amapV9Event() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV9(
                        UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID()
                ));
        // The Java in-memory v9 fixture still emits hard-validator-v3; the
        // active typed-reference contract requires at least v4 (shared
        // completion-v9 fixtures were migrated in B6J.2).
        ((ObjectNode) event.at("/payload/feasibilityReport"))
                .put("validatorVersion", "hard-validator-v4");
        return event;
    }

    private void setFirstRuleRef(ObjectNode event, String value) {
        com.fasterxml.jackson.databind.JsonNode results =
                event.at("/payload/feasibilityReport/ruleResults");
        for (com.fasterxml.jackson.databind.JsonNode rule : results) {
            if (rule.path("affectedEntityRefs").isArray()
                    && rule.path("affectedEntityRefs").size() > 0) {
                ((ArrayNode) rule.path("affectedEntityRefs"))
                        .set(0, objectMapper.getNodeFactory().textNode(value));
                return;
            }
        }
ArrayNode refs = objectMapper.createArrayNode();
        refs.add(value);
        ((ObjectNode) results.get(0)).set("affectedEntityRefs", refs);
    }

    @Test
    void acceptsV11TransitLegsWhileKeepingV10Compatible() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV10(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        event.put("schemaVersion", 11);
        ((ObjectNode) event.at("/payload/itinerary/days/0/transitLegs/0"))
                .put("mode", "TRANSIT")
                .put("estimatedCost", 3.0)
                .put("costSource", "PROVIDER");
        ((ObjectNode) event.at("/payload/feasibilityReport"))
                .put("itineraryFingerprint",
                        io.github.tobehardoo.trippilot.feasibility.ItineraryFingerprintVerifier
                                .compute(event.at("/payload/itinerary")));

        PlanningCompletedEvent parsed = parser.parse(objectMapper.writeValueAsBytes(event));

        assertThat(parsed.schemaVersion()).isEqualTo(11);
        assertThat(parsed.payload().itinerary().days().get(0).transitLegs().get(0).mode())
                .isEqualTo("TRANSIT");
        assertThat(parsed.payload().itinerary().days().get(0).transitLegs().get(0)
                .estimatedCost()).isEqualByComparingTo("3.0");
        assertThat(parsed.payload().itinerary().days().get(0).transitLegs().get(0)
                .costSource()).isEqualTo("PROVIDER");
    }

    @Test
    void v10RejectsTransitLegsUntilTheV11Contract() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV10(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        ((ObjectNode) event.at("/payload/itinerary/days/0/transitLegs/0"))
                .put("mode", "TRANSIT");
        ((ObjectNode) event.at("/payload/feasibilityReport"))
                .put("itineraryFingerprint",
                        io.github.tobehardoo.trippilot.feasibility.ItineraryFingerprintVerifier
                                .compute(event.at("/payload/itinerary")));

assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("transit leg fields are invalid");
    }

    @Test
    void v11RejectsMissingEvaluation() throws Exception {
        // F4: v11 schema/CompletionService require evaluation; the parser must
        // not let an event without it through (it used to silently accept,
        // risking a dropped message with the task stuck RUNNING).
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV10(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        event.put("schemaVersion", 11);
        ((ObjectNode) event.at("/payload")).remove("evaluation");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("evaluation is required in schema v9/v10/v11");
    }
    @Test
    void v11RejectsUnpersistableTransitLegMoney() throws Exception {
        // F2: transit estimatedCost must satisfy the same NUMERIC(12,2) money
        // range/precision as every other persisted amount; an out-of-range or
        // over-precision value used to pass the parser and hit the DB CHECK
        // constraint, causing endless redelivery with the task stuck at 95%.
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV10(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        event.put("schemaVersion", 11);
        ObjectNode leg = (ObjectNode) event.at("/payload/itinerary/days/0/transitLegs/0");
        leg.put("mode", "TRANSIT").put("estimatedCost", -1.0).put("costSource", "PROVIDER");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(EventContractException.class)
                .hasMessageContaining("estimatedCost must fit NUMERIC(12,2)");
    }
    @Test
    void v11ParsesAccommodationStatus() throws Exception {
        // B19-E: itinerary accommodation resolution status flows through the
        // parser into the persisted version (status + label, null-safe).
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV10(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        event.put("schemaVersion", 11);
        ObjectNode itinerary = (ObjectNode) event.at("/payload/itinerary");
        itinerary.set("accommodation", objectMapper.createObjectNode()
                .put("status", "UNRESOLVED").put("placeName", "白天鹅宾馆"));
        ((ObjectNode) event.at("/payload/feasibilityReport"))
                .put("itineraryFingerprint",
                        io.github.tobehardoo.trippilot.feasibility.ItineraryFingerprintVerifier
                                .compute(itinerary));

        PlanningCompletedEvent parsed = parser.parse(objectMapper.writeValueAsBytes(event));
        assertThat(parsed.payload().itinerary().accommodation()).isNotNull();
        assertThat(parsed.payload().itinerary().accommodation().status())
                .isEqualTo("UNRESOLVED");
        assertThat(parsed.payload().itinerary().accommodation().placeName())
                .isEqualTo("白天鹅宾馆");
    }

    @Test
    void v11ParsesMissingAccommodationAsNull() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV10(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        event.put("schemaVersion", 11);
        PlanningCompletedEvent parsed = parser.parse(objectMapper.writeValueAsBytes(event));
        assertThat(parsed.payload().itinerary().accommodation()).isNull();
    }

    @Test
    void acceptsInterestMatchAndPacePolicyDecisionReasonCodes() throws Exception {
        // Regression: the Java evaluation reason-code whitelist was missing
        // INTEREST_MATCH (偏好命中) and PACE_POLICY (RELAXED 节奏) that the
        // agent-service legitimately emits.  Any trip carrying one of these
        // decisions had its whole PLANNING_COMPLETED event rejected, leaving
        // the planning task stuck RUNNING forever and the itinerary never
        // surfacing.  These codes must parse so the contract stays in sync.
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV10(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        event.put("schemaVersion", 11);
        ArrayNode decisions = (ArrayNode) event.at("/payload/evaluation").withArray("decisions");
        ObjectNode interest = decisions.addObject();
        interest.put("subjectType", "PLAN");
        interest.put("summary", "候选排序匹配了你的兴趣偏好与导览推荐");
        ArrayNode interestCodes = interest.putArray("reasonCodes");
        interestCodes.add("INTEREST_MATCH");
        ArrayNode interestReasons = interest.putArray("reasons");
        interestReasons.add("偏好命中：某餐厅；导览推荐命中：无");
        interest.putArray("evidence");
        ObjectNode pace = decisions.addObject();
        pace.put("subjectType", "PLAN");
        pace.put("summary", "节奏为 RELAXED：每日负载相应降低");
        ArrayNode paceCodes = pace.putArray("reasonCodes");
        paceCodes.add("PACE_POLICY");
        ArrayNode paceReasons = pace.putArray("reasons");
        paceReasons.add("每个观光时段预留休整余量");
        pace.putArray("evidence");

        PlanningCompletedEvent parsed = parser.parse(objectMapper.writeValueAsBytes(event));
        assertThat(parsed.payload().evaluation().decisions()).hasSize(2);
    }
}
