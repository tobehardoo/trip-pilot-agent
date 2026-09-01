package io.github.tobehardoo.trippilot.planning;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import io.github.tobehardoo.trippilot.common.ApiException;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.catchThrowable;

class PlanningTaskIdempotencyTest {

    private final ObjectMapper objectMapper =
            new ObjectMapper().registerModule(new JavaTimeModule());

    @Test
    void rejectsCreateWhenTheIdempotencyKeyBelongsToAReplan() {
        Throwable failure = catchThrowable(() -> PlanningTaskIdempotency.requireCreateMatch(
                task("REPLAN", UUID.randomUUID(), "[\"2026-08-01\"]")
        ));

        assertIdempotencyConflict(failure);
    }

    @Test
    void rejectsReplanWhenTheIdempotencyKeyBelongsToCreate() {
        Throwable failure = catchThrowable(() -> PlanningTaskIdempotency.requireReplanMatch(
                task("CREATE", null, null),
                request(UUID.randomUUID(), "2026-08-01"),
                objectMapper
        ));

        assertIdempotencyConflict(failure);
    }

    @Test
    void rejectsReplanWhenTheSameKeyHasDifferentDates() {
        UUID baselineVersionId = UUID.randomUUID();
        Throwable failure = catchThrowable(() -> PlanningTaskIdempotency.requireReplanMatch(
                task("REPLAN", baselineVersionId, "[\"2026-08-01\"]"),
                request(baselineVersionId, "2026-08-02"),
                objectMapper
        ));

        assertIdempotencyConflict(failure);
    }

    @Test
    void acceptsEquivalentReplanDatesInAnyOrder() {
        UUID baselineVersionId = UUID.randomUUID();
        PlanningTaskRecord existing = task(
                "REPLAN",
                baselineVersionId,
                "[\"2026-08-01\",\"2026-08-02\"]"
        );
        var replay = new PlanningTaskService.LocalReplanRequest(
                baselineVersionId,
                List.of(LocalDate.parse("2026-08-02"), LocalDate.parse("2026-08-01"))
        );

        assertThatCode(() -> PlanningTaskIdempotency.requireReplanMatch(
                existing, replay, objectMapper
        )).doesNotThrowAnyException();
    }

    private PlanningTaskService.LocalReplanRequest request(UUID baselineVersionId, String date) {
        return new PlanningTaskService.LocalReplanRequest(
                baselineVersionId, List.of(LocalDate.parse(date))
        );
    }

    private PlanningTaskRecord task(
            String taskType,
            UUID baselineVersionId,
            String impactedDatesJson
    ) {
        Instant now = Instant.parse("2026-07-26T02:00:00Z");
        return new PlanningTaskRecord(
                UUID.randomUUID(),
                UUID.randomUUID(),
                UUID.randomUUID(),
                taskType,
                "QUEUED",
                2,
                baselineVersionId,
                impactedDatesJson,
                "{}",
                "{\"facts\":[]}",
                UUID.randomUUID(),
                0,
                null,
                null,
                0,
                now,
                now
        );
    }

    private void assertIdempotencyConflict(Throwable failure) {
        assertThat(failure).isInstanceOf(ApiException.class);
        ApiException apiException = (ApiException) failure;
        assertThat(apiException.status()).isEqualTo(HttpStatus.CONFLICT);
        assertThat(apiException.code()).isEqualTo("IDEMPOTENCY_KEY_REUSED");
    }
}
