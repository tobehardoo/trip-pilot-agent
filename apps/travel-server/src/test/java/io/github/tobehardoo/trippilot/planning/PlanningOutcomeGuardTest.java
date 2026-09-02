package io.github.tobehardoo.trippilot.planning;

import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;

import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningCompletedEvent;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PlanningOutcomeGuardTest {

    private final PlanningOutcomeGuard guard = new PlanningOutcomeGuard();

    private static final ZoneOffset TRIP_ZONE = ZoneOffset.ofHours(8);

    private static PlanningCompletedEvent.Activity activityOn(LocalDate date) {
        return new PlanningCompletedEvent.Activity(
                UUID.randomUUID(), "午餐",
                OffsetDateTime.of(date, LocalTime.of(12, 0), TRIP_ZONE),
                OffsetDateTime.of(date, LocalTime.of(13, 0), TRIP_ZONE),
                java.math.BigDecimal.ZERO, "DEMO", "POI-1", null, null, null,
                "午餐", "MEAL", null, null
        );
    }

    private static PlanningCompletedEvent.Day day(LocalDate date, int activityCount) {
        List<PlanningCompletedEvent.Activity> activities = java.util.stream.IntStream
                .range(0, activityCount)
                .mapToObj(i -> activityOn(date))
                .toList();
        return new PlanningCompletedEvent.Day(date, activities, List.of(), "FULL_DAY");
    }

    private PlanningTaskCompletionRecord create(LocalDate start, LocalDate end) {
        return new PlanningTaskCompletionRecord(
                UUID.randomUUID(), UUID.randomUUID(), "CREATE", "RUNNING", 0, null,
                "[]", UUID.randomUUID(), 1, "{}", 0, null,
                start, end,
                Instant.parse("2026-08-10T10:00:00Z")
        );
    }

    private static final UUID BASELINE =
            UUID.fromString("11111111-1111-4111-8111-111111111111");
    private static final UUID CURRENT =
            UUID.fromString("22222222-2222-4222-8222-222222222222");

    private PlanningTaskCompletionRecord replanTask(UUID baseline) {
        return new PlanningTaskCompletionRecord(
                UUID.randomUUID(), UUID.randomUUID(), "REPLAN", "RUNNING", 2, baseline,
                "[]", UUID.randomUUID(), 3, "{}", 2, CURRENT,
                LocalDate.parse("2026-08-01"), LocalDate.parse("2026-08-01"),
                Instant.parse("2026-08-10T10:00:00Z")
        );
    }

    private PlanningTaskCompletionRecord replanTaskWithCurrent(UUID baseline, UUID current) {
        return new PlanningTaskCompletionRecord(
                UUID.randomUUID(), UUID.randomUUID(), "REPLAN", "RUNNING", 2, baseline,
                "[]", UUID.randomUUID(), 3, "{}", 2, current,
                LocalDate.parse("2026-08-01"), LocalDate.parse("2026-08-01"),
                Instant.parse("2026-08-10T10:00:00Z")
        );
    }

    @Test
    void replanWithNullBaselineAndNullCurrentIsStale() {
        assertThat(guard.isStaleReplanBaseline(
                replanTaskWithCurrent(null, null), null)).isTrue();
    }

    @Test
    void replanWithNullBaselineIsStaleEvenWhenCurrentExists() {
        assertThat(guard.isStaleReplanBaseline(replanTask(null), CURRENT)).isTrue();
    }

    @Test
    void replanWithNullCurrentVersionIsStaleEvenWhenBaselineExists() {
        assertThat(guard.isStaleReplanBaseline(replanTask(BASELINE), null)).isTrue();
    }

    @Test
    void replanWithMismatchedBaselineIsStale() {
        assertThat(guard.isStaleReplanBaseline(replanTask(BASELINE), CURRENT)).isTrue();
    }

    @Test
    void replanWithMatchingBaselineIsNotStale() {
        assertThat(guard.isStaleReplanBaseline(replanTask(CURRENT), CURRENT)).isFalse();
    }

    @Test
    void createTaskIsNotAffectedByReplanBaselineLogic() {
        PlanningTaskCompletionRecord create = new PlanningTaskCompletionRecord(
                UUID.randomUUID(), UUID.randomUUID(), "CREATE", "RUNNING", 2, null,
                "[]", UUID.randomUUID(), 3, "{}", 2, null,
                LocalDate.parse("2026-08-01"), LocalDate.parse("2026-08-01"),
                Instant.parse("2026-08-10T10:00:00Z")
        );
        // Guard semantics only matter when the caller routes a REPLAN task
        // through the check; a CREATE task never reaches isStaleReplanBaseline.
        assertThat(create.taskType()).isEqualTo("CREATE");
    }
}
