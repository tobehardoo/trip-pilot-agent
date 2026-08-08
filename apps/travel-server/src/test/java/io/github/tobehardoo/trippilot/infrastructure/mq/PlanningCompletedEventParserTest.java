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
    void parsesEverySharedPlanEvaluationFixtureAndKeepsLegacyV6Compatible() {
        String[] evaluationFixtures = {
                "completion-v6-evaluation-clean.json",
                "completion-v6-evaluation-warnings.json",
                "completion-v6-evaluation-mixed-provider.json",
                "completion-v6-evaluation-fixed-appointment.json"
        };

        for (String fixture : evaluationFixtures) {
            PlanningCompletedEvent event = parser.parse(bytes(
                    PlanningCompletedEventFixture.sharedV6Fixture(fixture)
            ));

            assertThat(event.payload().evaluation()).isNotNull();
            assertThat(event.payload().evaluation().evaluatorVersion()).isEqualTo("rule-v1");
            assertThat(event.payload().evaluation().feasible()).isTrue();
        }

        PlanningCompletedEvent legacy = parser.parse(bytes(
                PlanningCompletedEventFixture.sharedV6Fixture(
                        "completion-v6-legacy-without-evaluation.json"
                )
        ));
        assertThat(legacy.payload().evaluation()).isNull();
    }

    @Test
    void rejectsEvaluationWhenOverallScoreDoesNotMatchWeightedDimensions() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.sharedV6Fixture(
                        "completion-v6-evaluation-clean.json"
                )
        );
        ((ObjectNode) event.at("/payload/evaluation")).put("overallScore", 1);

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("overallScore must match weighted dimensions");
    }

    @Test
    void acceptsEvaluationHalfUpRoundingAtTheCrossLanguageBoundary() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.sharedV6Fixture(
                        "completion-v6-evaluation-clean.json"
                )
        );
        ObjectNode evaluation = (ObjectNode) event.at("/payload/evaluation");
        evaluation.put("overallScore", 99);
        ((ObjectNode) evaluation.path("dimensions"))
                .put("constraintSatisfaction", 100)
                .put("timeFeasibility", 100)
                .put("budgetFit", 100)
                .put("routeEfficiency", 90)
                .put("interestMatch", 100);

        PlanningCompletedEvent parsed = parser.parse(
                objectMapper.writeValueAsBytes(event));

        assertThat(parsed.payload().evaluation().overallScore()).isEqualTo(99);
    }

    @Test
    void acceptsV2EvaluationWithNormalizedNotApplicableDimensions() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.sharedV6Fixture(
                        "completion-v6-evaluation-clean.json"
                )
        );
        ObjectNode evaluation = (ObjectNode) event.at("/payload/evaluation");
        evaluation.put("schemaVersion", 2);
        evaluation.put("evaluatorVersion", "rule-v2");
        evaluation.put("overallScore", 84);
        ((ObjectNode) evaluation.path("dimensions"))
                .put("constraintSatisfaction", 100)
                .put("timeFeasibility", 80)
                .putNull("budgetFit")
                .put("routeEfficiency", 60)
                .putNull("interestMatch");

        PlanningCompletedEvent parsed = parser.parse(
                objectMapper.writeValueAsBytes(event));

        assertThat(parsed.payload().evaluation().schemaVersion()).isEqualTo(2);
        assertThat(parsed.payload().evaluation().overallScore()).isEqualTo(84);
        assertThat(parsed.payload().evaluation().dimensions().budgetFit()).isNull();
        assertThat(parsed.payload().evaluation().dimensions().interestMatch()).isNull();
    }

    @Test
    void rejectsEvaluationValuesOutsideTheSharedSchemaEnumsAndCardinality()
            throws Exception {
        ObjectNode invalidWarning = evaluationFixture("completion-v6-evaluation-warnings.json");
        ((ObjectNode) invalidWarning.at("/payload/evaluation/warnings/0"))
                .put("severity", "BLOCKER");
        ObjectNode invalidReason = evaluationFixture(
                "completion-v6-evaluation-fixed-appointment.json");
        ((ArrayNode) invalidReason.at(
                "/payload/evaluation/decisions/0/reasonCodes"))
                .set(0, objectMapper.getNodeFactory().textNode("INVENTED_REASON"));
        ObjectNode unmatchedReasons = evaluationFixture(
                "completion-v6-evaluation-fixed-appointment.json");
        ((ArrayNode) unmatchedReasons.at(
                "/payload/evaluation/decisions/0/reasons")).removeAll();

        assertThatThrownBy(() -> parser.parse(
                objectMapper.writeValueAsBytes(invalidWarning)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("warning is invalid");
        assertThatThrownBy(() -> parser.parse(
                objectMapper.writeValueAsBytes(invalidReason)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("decision is invalid");
        assertThatThrownBy(() -> parser.parse(
                objectMapper.writeValueAsBytes(unmatchedReasons)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("decision is invalid");
    }

    @Test
    void acceptsHistoricalV6WithoutInventingProviderProvenance() {
        PlanningCompletedEvent event = parser.parse(bytes(
                PlanningCompletedEventFixture.sharedV6Fixture(
                        "completion-v6-legacy-amap.json"
                )
        ));

        assertThat(event.schemaVersion()).isEqualTo(6);
        assertThat(event.payload().providerProvenance()).isNull();
    }

    @Test
    void parsesMultiTransitV6ProvenanceByStableTransitIdentity() {
        PlanningCompletedEvent event = parser.parse(bytes(
                PlanningCompletedEventFixture.sharedV6Fixture(
                        "completion-v6-multi-transit-mixed.json"
                )
        ));

        PlanningCompletedEvent.ProviderProvenance provenance =
                event.payload().providerProvenance();
        assertThat(provenance.requestedProviderMode())
                .isEqualTo(PlanningCompletedEvent.ProviderExecutionMode.REAL_WITH_EXPLICIT_FALLBACK);
        assertThat(provenance.actualProviders())
                .containsExactly(
                        PlanningCompletedEvent.ProviderSource.AMAP,
                        PlanningCompletedEvent.ProviderSource.DEMO
                );
        assertThat(provenance.fallbackOperations()).singleElement().satisfies(operation -> {
            assertThat(operation.transitId())
                    .isEqualTo(UUID.fromString("20000000-0000-4000-8000-000000000032"));
            assertThat(operation.fromActivityId())
                    .isEqualTo(UUID.fromString("10000000-0000-4000-8000-000000000032"));
            assertThat(operation.toActivityId())
                    .isEqualTo(UUID.fromString("10000000-0000-4000-8000-000000000033"));
            assertThat(operation.errorCategory())
                    .isEqualTo(PlanningCompletedEvent.ProviderErrorCategory.TIMEOUT);
            assertThat(operation.retryCount()).isEqualTo(2);
        });
    }

    @Test
    void rejectsFallbackOperationThatDoesNotMatchItsTransitIdentity() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.sharedV6Fixture(
                        "completion-v6-multi-transit-mixed.json"
                )
        );
        ((ObjectNode) event.at("/payload/providerProvenance/fallbackOperations/0"))
                .put("transitId", "20000000-0000-4000-8000-000000000031");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("fallback operation must match one transit identity");
    }

    @Test
    void rejectsRealOnlyCompletionThatContainsDemoEvidence() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.sharedV6Fixture(
                        "completion-v6-multi-transit-mixed.json"
                )
        );
        ((ObjectNode) event.at("/payload/providerProvenance"))
                .put("requestedProviderMode", "REAL_ONLY");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("REAL_ONLY completion must only contain AMAP evidence");
    }

    @Test
    void rejectsSuccessfulFallbackWithoutAnAttempt() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.sharedV6Fixture(
                        "completion-v6-multi-transit-mixed.json"
                )
        );
        ((ObjectNode) event.at("/payload/providerProvenance"))
                .put("fallbackAttempted", false);

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("successful completion cannot contain a failed fallback");
    }

    private final ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();
    private final PlanningCompletedEventParser parser = new PlanningCompletedEventParser(objectMapper);

    @Test
    void parsesThePythonCompletedEventContract() {
        UUID eventId = UUID.randomUUID();
        UUID traceId = UUID.randomUUID();
        UUID taskId = UUID.randomUUID();
        UUID tripId = UUID.randomUUID();

        PlanningCompletedEvent event = parser.parse(bytes(
                PlanningCompletedEventFixture.completedEvent(eventId, traceId, taskId, tripId)
        ));

        assertThat(event.eventId()).isEqualTo(eventId);
        assertThat(event.traceId()).isEqualTo(traceId);
        assertThat(event.taskId()).isEqualTo(taskId);
        assertThat(event.tripId()).isEqualTo(tripId);
        assertThat(event.payload().provider()).isEqualTo("DEMO");
        assertThat(event.payload().itinerary().days()).hasSize(1);
        assertThat(event.payload().itinerary().days().getFirst().activities()).hasSize(1);
    }

    @Test
    void parsesV2AmapActivityMetadataWhileKeepingV1Compatible() {
        PlanningCompletedEvent event = parser.parse(bytes(
                PlanningCompletedEventFixture.completedAmapEventV2(
                        UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID()
                )
        ));

        PlanningCompletedEvent.Activity activity =
                event.payload().itinerary().days().getFirst().activities().getFirst();
        assertThat(event.schemaVersion()).isEqualTo(2);
        assertThat(event.payload().provider()).isEqualTo("AMAP");
        assertThat(activity.source()).isEqualTo("AMAP");
        assertThat(activity.providerPoiId()).isEqualTo("B00140TWHT");
        assertThat(activity.coordinates().longitude()).isEqualByComparingTo("113.319263");
        assertThat(activity.coordinates().latitude()).isEqualByComparingTo("23.109078");
        assertThat(activity.address()).isEqualTo("珠江东路2号");
        assertThat(event.payload().itinerary().days().getFirst().transitLegs()).isEmpty();
    }

    @Test
    void parsesV3TransitLegsWhileKeepingOlderContractsCompatible() {
        PlanningCompletedEvent event = parser.parse(bytes(
                PlanningCompletedEventFixture.completedAmapEventV3(
                        UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID()
                )
        ));

        PlanningCompletedEvent.TransitLeg leg =
                event.payload().itinerary().days().getFirst().transitLegs().getFirst();
        assertThat(event.schemaVersion()).isEqualTo(3);
        assertThat(leg.fromActivityIndex()).isZero();
        assertThat(leg.toActivityIndex()).isOne();
        assertThat(leg.mode()).isEqualTo("WALKING");
        assertThat(leg.distanceMeters()).isEqualTo(1280);
        assertThat(leg.durationSeconds()).isEqualTo(960);
        assertThat(leg.provider()).isEqualTo("AMAP");
        assertThat(leg.estimated()).isFalse();
        assertThat(leg.polyline()).hasSize(2);
    }

    @Test
    void acceptsDrivingTransfersOnlyInTheV5Contract() throws Exception {
        ObjectNode current = amapV4Event();
        current.put("schemaVersion", 5);
        ((ObjectNode) current.at(
                "/payload/itinerary/days/0/transitLegs/0"
        )).put("mode", "DRIVING");
        ObjectNode legacy = amapV4Event();
        ((ObjectNode) legacy.at(
                "/payload/itinerary/days/0/transitLegs/0"
        )).put("mode", "DRIVING");

        assertThat(parser.parse(objectMapper.writeValueAsBytes(current))
                .payload().itinerary().days().getFirst().transitLegs().getFirst().mode())
                .isEqualTo("DRIVING");
        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(legacy)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("transit leg fields are invalid");
    }

    @Test
    void parsesV6FactImpactsWithTraceableLifecycleFields() throws Exception {
        ObjectNode event = amapV4Event();
        event.put("schemaVersion", 6);
        ArrayNode impacts = objectMapper.createArrayNode();
        impacts.addObject()
                .put("factId", "fact_0123456789abcdef0123456789abcdef")
                .put("category", "WEATHER")
                .put("date", "2026-08-01")
                .put("effect", "OUTDOOR_POI_DOWNRANKED")
                .put("targetName", "广州塔")
                .put("reason", "对应日期预计降雨，露天候选降低优先级")
                .put("sourceName", "高德天气")
                .put("sourceType", "WEATHER_PROVIDER")
                .put("sourceUrl", "https://restapi.amap.com/")
                .put("reliabilityLevel", "PROVIDER")
                .put("checkedAt", "2026-07-26T08:30:00Z")
                .put("evidence", "8 月 1 日预计有雨")
                .put("stale", false)
                .put("conflicted", false)
                .put("refreshFailed", false);
        ((ObjectNode) event.path("payload")).set("factImpacts", impacts);

        PlanningCompletedEvent parsed = parser.parse(
                objectMapper.writeValueAsBytes(event)
        );

        assertThat(parsed.payload().factImpacts()).singleElement()
                .satisfies(impact -> {
                    assertThat(impact.category()).isEqualTo("WEATHER");
                    assertThat(impact.date()).isEqualTo(
                            java.time.LocalDate.of(2026, 8, 1)
                    );
                    assertThat(impact.stale()).isFalse();
                    assertThat(impact.evidence()).contains("预计有雨");
                    assertThat(impact.sourceUrl()).startsWith("https://");
                });
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
        ObjectNode wrongIndex = amapV3Event();
        ((ObjectNode) wrongIndex.at(
                "/payload/itinerary/days/0/transitLegs/0"
        )).put("fromActivityIndex", 1);
        ObjectNode missingLeg = amapV3Event();
        ((ArrayNode) missingLeg.at("/payload/itinerary/days/0/transitLegs")).removeAll();

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(wrongIndex)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("connect adjacent activities in order");
        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(missingLeg)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("connect every adjacent activity");
    }

    @Test
    void acceptsOutOfOrderTransitLegsByTheirActivityEndpointsAndRejectsDuplicateEndpoints()
            throws Exception {
        ObjectNode reordered = amapV4Event();
        reordered.put("schemaVersion", 5);
        ArrayNode activities = (ArrayNode) reordered.at("/payload/itinerary/days/0/activities");
        ObjectNode thirdActivity = activities.get(1).deepCopy();
        thirdActivity.put("title", "Late stop");
        thirdActivity.put("startTime", "2026-08-01T17:00:00+08:00");
        thirdActivity.put("endTime", "2026-08-01T19:00:00+08:00");
        activities.add(thirdActivity);
        ArrayNode transitLegs = (ArrayNode) reordered.at("/payload/itinerary/days/0/transitLegs");
        ObjectNode firstLeg = transitLegs.get(0).deepCopy();
        ObjectNode secondLeg = firstLeg.deepCopy();
        secondLeg.put("fromActivityIndex", 1);
        secondLeg.put("toActivityIndex", 2);
        secondLeg.put("mode", "DRIVING");
        transitLegs.removeAll();
        transitLegs.add(secondLeg);
        transitLegs.add(firstLeg);

        PlanningCompletedEvent parsed = parser.parse(objectMapper.writeValueAsBytes(reordered));

        assertThat(parsed.payload().itinerary().days().getFirst().transitLegs())
                .extracting(PlanningCompletedEvent.TransitLeg::mode)
                .containsExactly("DRIVING", "WALKING");

        ObjectNode duplicateEndpoints = reordered.deepCopy();
        ((ObjectNode) duplicateEndpoints.at("/payload/itinerary/days/0/transitLegs/0"))
                .put("fromActivityIndex", 0)
                .put("toActivityIndex", 1);

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(duplicateEndpoints)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("unique adjacent activity endpoints");
    }

    @Test
    void rejectsV3TransitLegWithInvalidPolylineOrImpossibleTravelTime() throws Exception {
        ObjectNode invalidPolyline = amapV3Event();
        ((ObjectNode) invalidPolyline.at(
                "/payload/itinerary/days/0/transitLegs/0/polyline/0"
        )).put("longitude", 181);
        ObjectNode impossibleTravelTime = amapV3Event();
        ((ObjectNode) impossibleTravelTime.at(
                "/payload/itinerary/days/0/transitLegs/0"
        )).put("durationSeconds", 8000);

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(invalidPolyline)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("transit leg fields are invalid");
        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(impossibleTravelTime)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("travel time must fit between activities");
    }

    @Test
    void rejectsInvalidV4KnowledgeEvidenceStates() throws Exception {
        ObjectNode realWithoutCitations = amapV4Event();
        ((ArrayNode) realWithoutCitations.at("/payload/knowledge/citations")).removeAll();
        ObjectNode demoWithCitation = amapV4Event();
        ((ObjectNode) demoWithCitation.at("/payload/knowledge")).put("status", "DEMO")
                .put("message", "demo");
        ObjectNode unavailableWithVerification = amapV4Event();
        ObjectNode unavailableKnowledge = (ObjectNode) unavailableWithVerification.at(
                "/payload/knowledge"
        );
        unavailableKnowledge.put("status", "UNAVAILABLE").put("message", "unavailable");
        ((ArrayNode) unavailableKnowledge.path("citations")).removeAll();
        ((ObjectNode) unavailableKnowledge.path("freshness")).put("status", "UNAVAILABLE");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(realWithoutCitations)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("real knowledge evidence requires citations");
        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(demoWithCitation)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("non-real knowledge evidence");
        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(
                        unavailableWithVerification
                )))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("unavailable freshness cannot contain verification details");
    }

    @Test
    void rejectsV4CitationWithNonHttpSourceUrl() throws Exception {
        ObjectNode event = amapV4Event();
        ((ObjectNode) event.at("/payload/knowledge/citations/0"))
                .put("sourceUrl", "ftp://example.com/source");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("knowledge citation is invalid");
    }

    @Test
    void parsesV2DemoFallbackWithoutAmapMetadata() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(eventJson());
        event.put("schemaVersion", 2);

        PlanningCompletedEvent parsed = parser.parse(objectMapper.writeValueAsBytes(event));

        PlanningCompletedEvent.Activity activity =
                parsed.payload().itinerary().days().getFirst().activities().getFirst();
        assertThat(parsed.schemaVersion()).isEqualTo(2);
        assertThat(parsed.payload().provider()).isEqualTo("DEMO");
        assertThat(activity.source()).isEqualTo("DEMO");
        assertThat(activity.providerPoiId()).isNull();
        assertThat(activity.coordinates()).isNull();
        assertThat(activity.address()).isNull();
    }

    @Test
    void rejectsV2AmapActivityWithoutCoordinates() throws Exception {
        ObjectNode event = amapV2Event();
        ObjectNode activity = (ObjectNode) event.at("/payload/itinerary/days/0/activities/0");
        activity.remove("coordinates");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("AMAP activity requires valid provider metadata");
    }

    @Test
    void rejectsV2PayloadAndActivityProviderMismatch() throws Exception {
        ObjectNode event = amapV2Event();
        ((ObjectNode) event.path("payload")).put("provider", "DEMO");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("activity source must match payload provider");
    }

    @Test
    void rejectsV2AmapCoordinatesOutsideValidBounds() throws Exception {
        ObjectNode event = amapV2Event();
        ObjectNode coordinates =
                (ObjectNode) event.at("/payload/itinerary/days/0/activities/0/coordinates");
        coordinates.put("longitude", new BigDecimal("181"));

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("AMAP activity requires valid provider metadata");
    }

    @Test
    void rejectsV2AmapCoordinateStringCoercion() throws Exception {
        ObjectNode event = amapV2Event();
        ObjectNode coordinates =
                (ObjectNode) event.at("/payload/itinerary/days/0/activities/0/coordinates");
        coordinates.put("longitude", "113.319263");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("activity metadata types do not match the JSON Schema");
    }

    @Test
    void rejectsV2DemoActivityThatClaimsAmapMetadata() throws Exception {
        ObjectNode event = amapV2Event();
        ObjectNode payload = (ObjectNode) event.path("payload");
        ObjectNode activity = (ObjectNode) event.at("/payload/itinerary/days/0/activities/0");
        payload.put("provider", "DEMO");
        activity.put("source", "DEMO");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("DEMO activity must not contain provider metadata");
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
        ObjectNode event = (ObjectNode) objectMapper.readTree(eventJson());
        ObjectNode activity = (ObjectNode) event.at("/payload/itinerary/days/0/activities/0");
        activity.put("endTime", "2026-08-01T08:00:00+08:00");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("activity endTime must be after startTime");
    }

    @Test
    void rejectsAnEmptyItinerary() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(eventJson());
        ObjectNode itinerary = (ObjectNode) event.at("/payload/itinerary");
        itinerary.set("days", objectMapper.createArrayNode());

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("itinerary days must not be empty");
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
        ObjectNode event = (ObjectNode) objectMapper.readTree(eventJson());
        ArrayNode activities = (ArrayNode) event.at("/payload/itinerary/days/0/activities");
        ObjectNode overlapping = activities.get(0).deepCopy();
        overlapping.put("startTime", "2026-08-01T10:00:00+08:00");
        overlapping.put("endTime", "2026-08-01T12:00:00+08:00");
        activities.add(overlapping);

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("activities must be ordered without overlap");
    }

    @Test
    void rejectsTextThatCannotFitThePersistenceSchema() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(eventJson());
        ObjectNode itinerary = (ObjectNode) event.at("/payload/itinerary");
        itinerary.put("title", "x".repeat(201));

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("itinerary title must contain 1 to 200 characters");
    }

    @Test
    void rejectsMoneyThatCannotFitThePersistenceSchema() throws Exception {
        ObjectNode excessiveScale = (ObjectNode) objectMapper.readTree(eventJson());
        ObjectNode excessiveScaleItinerary = (ObjectNode) excessiveScale.at("/payload/itinerary");
        excessiveScaleItinerary.put("estimatedTotalCost", new BigDecimal("0.001"));
        ObjectNode excessiveValue = (ObjectNode) objectMapper.readTree(eventJson());
        ObjectNode excessiveValueActivity =
                (ObjectNode) excessiveValue.at("/payload/itinerary/days/0/activities/0");
        excessiveValueActivity.put("estimatedCost", new BigDecimal("10000000000.00"));

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(excessiveScale)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("estimatedTotalCost must fit NUMERIC(12,2)");
        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(excessiveValue)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("activity fields are invalid");
    }

    private String eventJson() {
        return PlanningCompletedEventFixture.completedEvent(
                UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID()
        );
    }

    @Test
    void parsesV8ScheduleFieldsAndPreservesThem() {
        PlanningCompletedEvent event = parser.parse(bytes(
                PlanningCompletedEventFixture.completedAmapEventV8(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        ));

        assertThat(event.schemaVersion()).isEqualTo(8);
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
    void v8AcceptsStructuralMealNodeWithoutProviderMetadataAndTransitGap() {
        PlanningCompletedEvent event = parser.parse(bytes(
                PlanningCompletedEventFixture.completedAmapEventV8(
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
    void v8RejectsUnknownActivityKind() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV8(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        ((ObjectNode) event.at("/payload/itinerary/days/0/activities/1")).put("kind", "TRANSFER");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("activity kind is not a supported value");
    }

    @Test
    void v8RejectsUnknownDayType() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV8(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        ((ObjectNode) event.at("/payload/itinerary/days/0")).put("dayType", "NIGHT_DAY");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("dayType is not a supported value");
    }

    @Test
    void v8RejectsNonStructuralActivityMissingProviderMetadata() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV8(
                        UUID.randomUUID(), UUID.randomUUID(),
                        UUID.randomUUID(), UUID.randomUUID()
                )
        );
        // Make the ATTRACTION lose its provider metadata: structural-only exemption.
        ObjectNode attraction = (ObjectNode) event.at("/payload/itinerary/days/0/activities/1");
        attraction.remove("providerPoiId");
        attraction.remove("coordinates");
        attraction.remove("address");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("AMAP activity requires valid provider metadata");
    }

    @Test
    void parsesSharedV8FixtureAndPreservesScheduleFields() {
        PlanningCompletedEvent event = parser.parse(bytes(
                PlanningCompletedEventFixture.sharedV8Fixture(
                        "completion-v8-real-only-amap.json"
                )
        ));

        assertThat(event.schemaVersion()).isEqualTo(8);
        PlanningCompletedEvent.Day day = event.payload().itinerary().days().get(0);
        assertThat(day.dayType()).isEqualTo("ARRIVAL_DAY");
        assertThat(day.activities().get(0).kind()).isEqualTo("ARRIVAL");
        assertThat(day.activities().get(0).timeFixed()).isTrue();
        assertThat(day.activities().get(2).kind()).isEqualTo("MEAL");
        assertThat(day.activities().get(2).providerPoiId()).isNull();
        // The meal gap has no transit leg; only 0->1 is covered.
        assertThat(day.transitLegs()).hasSize(1);
    }

    @Test
    void rejectsAbandonedV7EvenWhenStructurallyWellFormed() throws Exception {
        ObjectNode event = (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.completedAmapEventV8(
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
}
