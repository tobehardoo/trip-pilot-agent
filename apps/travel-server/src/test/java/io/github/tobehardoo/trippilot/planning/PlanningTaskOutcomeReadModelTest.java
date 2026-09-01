package io.github.tobehardoo.trippilot.planning;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import io.github.tobehardoo.trippilot.support.PlanningCompletedEventFixture;
import java.time.Instant;
import java.util.UUID;
import org.junit.jupiter.api.Test;

/**
 * B16 regression coverage for the task outcome read model: a SUCCEEDED task
 * whose terminal event carries a savable UNVERIFIED report (Information
 * Missing != Planning Failed) must be readable; a blocker report must still
 * fail closed.
 */
class PlanningTaskOutcomeReadModelTest {

    private final ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();
    private final PlanningTaskOutcomeReadModel readModel =
            new PlanningTaskOutcomeReadModel(objectMapper);

    private PlanningTaskEventRecord completedEvent(JsonNode payload) {
        return new PlanningTaskEventRecord(
                1L, UUID.randomUUID(), UUID.randomUUID(),
                "PLANNING_COMPLETED", 10, payload.toString(), Instant.now()
        );
    }

    private PlanningTaskRecord succeededTask() {
        return new PlanningTaskRecord(
                UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(), "CREATE",
                "SUCCEEDED", 0, null, null, null, null, UUID.randomUUID(),
                0, null, null, 0, Instant.now(), Instant.now()
        );
    }

    @Test
    void readAcceptsSavableUnverifiedV10Completion() throws Exception {
        String wire = PlanningCompletedEventFixture.completedAmapEventV10(
                UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID()
        );
        ObjectNode event = (ObjectNode) objectMapper.readTree(wire);
        PlanningTaskEventRecord record = completedEvent(event.path("payload"));

        PlanningTaskOutcomeReadModel.Outcome outcome =
                readModel.read(succeededTask(), record);

        assertThat(outcome.feasibilityReport()).isNotNull();
        assertThat(outcome.feasibilityReport().status().name()).isEqualTo("UNVERIFIED");
        assertThat(outcome.evaluation()).isNotNull();
    }

    @Test
    void readRejectsBlockerReport() throws Exception {
        String wire = PlanningCompletedEventFixture.completedAmapEventV10(
                UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID()
        );
        ObjectNode event = (ObjectNode) objectMapper.readTree(wire);
        ObjectNode report = (ObjectNode) event.at("/payload/feasibilityReport");
        report.put("status", "NEEDS_REPAIR");
        ((ObjectNode) report.path("summary")).put("failCount", 1);
        ObjectNode failing = (ObjectNode) report.path("ruleResults").path(0);
        failing.put("outcome", "FAIL");
        failing.put("reasonCode", "TIME_CONFLICT");
        failing.put("message", "activity conflicts with a fixed schedule");
        PlanningTaskEventRecord record = completedEvent(event.path("payload"));

        assertThatThrownBy(() -> readModel.read(succeededTask(), record))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("Planning task terminal event is invalid");
    }

    @Test
    void readFailedExposesConflictsAndRelaxationSuggestions() throws Exception {
        ObjectMapper mapper = new ObjectMapper().findAndRegisterModules();
        com.fasterxml.jackson.databind.node.ObjectNode payload = mapper.createObjectNode();
        payload.put("status", "FAILED");
        payload.put("errorCode", "NO_FEASIBLE_ITINERARY");
        payload.put("errorCategory", "PLANNING_INFEASIBLE");
        payload.put("provider", "AMAP");
        payload.put("operation", "PLANNING");
        payload.put("retryable", false);
        payload.put("retryCount", 0);
        payload.put("fallbackAttempted", false);
        payload.put("fallbackSucceeded", false);
        payload.put("safeMessage", "时间不足，请调整条件后重试");
        payload.put("requestedProviderMode", "REAL_ONLY");
        payload.put("primaryProvider", "AMAP");
        payload.putArray("actualProviders").add("AMAP");
        payload.put("fallbackReason", "fallback disabled for infeasible plans");
        payload.putArray("fallbackOperations");
        com.fasterxml.jackson.databind.node.ArrayNode conflicts = payload.putArray("conflicts");
        conflicts.addObject()
                .put("code", "INSUFFICIENT_DAY_CAPACITY")
                .put("message", "实际交通时长无法在固定返程时间前完成")
                .putArray("affected").add("DEPARTURE");
        com.fasterxml.jackson.databind.node.ArrayNode relaxations =
                payload.putArray("relaxationSuggestions");
        relaxations.addObject()
                .put("code", "EXTEND_AVAILABLE_TIME")
                .put("message", "请提前出发、延后返程时间，或减少前序行程");

        PlanningTaskEventRecord record = new PlanningTaskEventRecord(
                1L, UUID.randomUUID(), UUID.randomUUID(),
                "PLANNING_FAILED", 2, payload.toString(), Instant.now()
        );
        PlanningTaskRecord task = new PlanningTaskRecord(
                UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(), "CREATE",
                "FAILED", 0, null, null, null, null, UUID.randomUUID(),
                0, "NO_FEASIBLE_ITINERARY", "时间不足，请调整条件后重试",
                0, Instant.now(), Instant.now()
        );

        PlanningTaskOutcomeReadModel.Outcome outcome = readModel.read(task, record);

        assertThat(outcome.conflicts()).hasSize(1);
        assertThat(outcome.conflicts().get(0).code()).isEqualTo("INSUFFICIENT_DAY_CAPACITY");
        assertThat(outcome.conflicts().get(0).message()).contains("固定返程时间");
        assertThat(outcome.conflicts().get(0).affected()).containsExactly("DEPARTURE");
        assertThat(outcome.relaxationSuggestions()).hasSize(1);
        assertThat(outcome.relaxationSuggestions().get(0).code())
                .isEqualTo("EXTEND_AVAILABLE_TIME");
        assertThat(outcome.relaxationSuggestions().get(0).message()).contains("提前出发");
    }
}
