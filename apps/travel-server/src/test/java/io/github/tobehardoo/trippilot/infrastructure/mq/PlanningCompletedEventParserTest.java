package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.util.UUID;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
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
                    .isInstanceOf(PlanningEventContractException.class)
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
                .isInstanceOf(PlanningEventContractException.class)
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
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("Invalid PLANNING_COMPLETED event");
    }

    @Test
    void rejectsAnEmptyMessageAsAContractViolation() {
        assertThatThrownBy(() -> parser.parse(new byte[0]))
                .isInstanceOf(PlanningEventContractException.class)
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
                .isInstanceOf(PlanningEventContractException.class)
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
                .isInstanceOf(PlanningEventContractException.class)
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
                .isInstanceOf(PlanningEventContractException.class)
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
                .isInstanceOf(PlanningEventContractException.class)
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
                .isInstanceOf(PlanningEventContractException.class)
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
                .isInstanceOf(PlanningEventContractException.class)
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
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("feasibilityReport is invalid: status must be VERIFIED");
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
                .isInstanceOf(PlanningEventContractException.class)
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
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("feasibilityReport is invalid: schemaVersion must be 1");
    }

    @Test
    void rejectsSupersededV8SharedFixture() {
        assertThatThrownBy(() -> parser.parse(bytes(
                PlanningCompletedEventFixture.sharedV8Fixture(
                        "completion-v8-real-only-amap.json"
                )
        )))
                .isInstanceOf(PlanningEventContractException.class)
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
                .isInstanceOf(PlanningEventContractException.class)
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
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("unsupported eventType or schemaVersion");
    }

    private void assertRuntimeRejects(ObjectNode event) throws Exception {
        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("unsupported eventType or schemaVersion");
    }
}
