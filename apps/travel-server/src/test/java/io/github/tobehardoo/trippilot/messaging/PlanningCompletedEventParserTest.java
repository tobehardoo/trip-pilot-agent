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

    private byte[] bytes(String value) {
        return value.getBytes(StandardCharsets.UTF_8);
    }
}
