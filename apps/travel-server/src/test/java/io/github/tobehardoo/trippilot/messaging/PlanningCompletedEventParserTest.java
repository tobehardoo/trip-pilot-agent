package io.github.tobehardoo.trippilot.messaging;

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

    private byte[] bytes(String value) {
        return value.getBytes(StandardCharsets.UTF_8);
    }
}
