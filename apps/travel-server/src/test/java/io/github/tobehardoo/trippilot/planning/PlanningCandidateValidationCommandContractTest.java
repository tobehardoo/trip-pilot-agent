package io.github.tobehardoo.trippilot.planning;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.util.HashSet;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PlanningCandidateValidationCommandContractTest {

    private final ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();

    @Test
    void sharedEditAndRollbackFixturesPreserveCandidateSemantics() throws Exception {
        JsonNode edit = fixture("valid-edit.json");
        JsonNode rollback = fixture("valid-rollback.json");

        validate(edit);
        validate(rollback);
        assertThat(edit.at("/payload/itinerary/days/0/activities/0/locked").asBoolean())
                .isTrue();
        assertThat(rollback.at("/payload/itinerary/provider").asText()).isEqualTo("DEMO");
    }

    @Test
    void invalidSharedFixtureFailsClosed() throws Exception {
        JsonNode invalid = fixture("invalid/edit-with-rollback-source.json");

        assertThatThrownBy(() -> validate(invalid))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("rollbackFromVersionId");
    }

    private void validate(JsonNode command) {
        if (!"PLANNING_CANDIDATE_VALIDATION_REQUESTED".equals(
                command.path("eventType").asText()) || command.path("schemaVersion").asInt() != 1) {
            throw new IllegalArgumentException("candidate command envelope is invalid");
        }
        JsonNode payload = command.path("payload");
        String candidateType = payload.path("candidateType").asText();
        String expectedTaskType = candidateType + "_VALIDATE";
        if (!expectedTaskType.equals(payload.path("taskType").asText())) {
            throw new IllegalArgumentException("candidateType must match taskType");
        }
        boolean rollback = "ROLLBACK".equals(candidateType);
        if (rollback != payload.path("rollbackFromVersionId").isTextual()) {
            throw new IllegalArgumentException(
                    "rollbackFromVersionId must exist only for rollback candidates");
        }
        LocalDate start = LocalDate.parse(payload.at("/trip/startDate").asText());
        LocalDate end = LocalDate.parse(payload.at("/trip/endDate").asText());
        Set<LocalDate> changed = dates(payload.path("changedDates"));
        Set<LocalDate> expectedImpacted = new HashSet<>();
        for (LocalDate date : changed) {
            for (LocalDate candidate : Set.of(date.minusDays(1), date, date.plusDays(1))) {
                if (!candidate.isBefore(start) && !candidate.isAfter(end)) {
                    expectedImpacted.add(candidate);
                }
            }
        }
        assertThat(dates(payload.path("impactedDates"))).isEqualTo(expectedImpacted);
        assertThat(payload.at("/itinerary/days").size())
                .isEqualTo((int) (end.toEpochDay() - start.toEpochDay() + 1));
    }

    private Set<LocalDate> dates(JsonNode values) {
        Set<LocalDate> dates = new HashSet<>();
        values.forEach(value -> dates.add(LocalDate.parse(value.asText())));
        return dates;
    }

    private JsonNode fixture(String name) throws Exception {
        Path path = Path.of("..", "..", "contracts", "fixtures",
                "planning-candidate-validation-command-v1", name);
        return objectMapper.readTree(Files.readString(path, StandardCharsets.UTF_8));
    }
}
