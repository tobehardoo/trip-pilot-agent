package io.github.tobehardoo.trippilot.planning;

import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningCompletedEvent;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningReviewRequiredEvent;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.context.ApplicationEventPublisher;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PlanningReviewServiceTest {

    private static final UUID EVENT_ID = UUID.randomUUID();
    private static final UUID TASK_ID = UUID.randomUUID();
    private static final UUID TRIP_ID = UUID.randomUUID();
    private static final UUID TRACE_ID = UUID.randomUUID();
    private static final UUID RUN_ID = UUID.randomUUID();

    private FakePlanningTaskMapper taskMapper;
    private FakePlanningTaskEventMapper taskEventMapper;
    private List<Object> publishedEvents;
    private PlanningReviewService service;

    @BeforeEach
    void setUp() {
        taskMapper = new FakePlanningTaskMapper();
        taskEventMapper = new FakePlanningTaskEventMapper();
        publishedEvents = new ArrayList<>();
        service = new PlanningReviewService(
                taskMapper, taskEventMapper, new PlanningOutcomeGuard(),
                new ObjectMapper().findAndRegisterModules(),
                java.time.Clock.fixed(Instant.parse("2026-08-10T12:00:00Z"),
                        java.time.ZoneOffset.UTC),
                publishedEvents::add,
                tripId -> UUID.fromString("11111111-1111-4111-8111-111111111111")
        );
    }

    @Test
    void marksRunningTaskWaitingUserWithoutCreatingItineraryVersion() {
        taskMapper.completionContext = Optional.of(completionContext("RUNNING"));
        taskEventMapper.eventByEventId = Optional.empty();
        taskMapper.waitingUserResult = 1;
        taskEventMapper.insertResult = 1;

        service.handle(reviewEvent());

        assertThat(taskMapper.markedWaitingUserTaskId).isEqualTo(TASK_ID);
        assertThat(taskMapper.markedWaitingUserVersion).isEqualTo(3);
        assertThat(taskEventMapper.inserted).isNotNull();
        assertThat(taskEventMapper.inserted.eventType()).isEqualTo("PLANNING_REVIEW_REQUIRED");
        assertThat(taskEventMapper.inserted.schemaVersion()).isEqualTo(1);
        assertThat(taskEventMapper.inserted.payloadJson()).contains("WAITING_USER");
        assertThat(publishedEvents).hasSize(1);
        assertThat(publishedEvents.get(0)).isInstanceOf(PlanningTaskEventCreated.class);
    }

    @Test
    void ignoresRedeliveredReviewEventIdempotently() {
        taskMapper.completionContext = Optional.of(completionContext("RUNNING"));
        taskEventMapper.eventByEventId = Optional.of(new PlanningTaskEventRecord(
                1L, EVENT_ID, TASK_ID, "PLANNING_REVIEW_REQUIRED", 1, "{}",
                Instant.parse("2026-08-10T11:00:00Z")
        ));

        service.handle(reviewEvent());

        assertThat(taskMapper.markedWaitingUserTaskId).isNull();
        assertThat(taskEventMapper.inserted).isNull();
        assertThat(publishedEvents).isEmpty();
    }

    @Test
    void rejectsEventIdAlreadyBelongingToAnotherTask() {
        taskMapper.completionContext = Optional.of(completionContext("RUNNING"));
        taskEventMapper.eventByEventId = Optional.of(new PlanningTaskEventRecord(
                1L, EVENT_ID, UUID.randomUUID(), "PLANNING_REVIEW_REQUIRED", 1, "{}",
                Instant.parse("2026-08-10T11:00:00Z")
        ));

        assertThatThrownBy(() -> service.handle(reviewEvent()))
                .isInstanceOf(PlanningEventRejectedException.class)
                .hasMessageContaining("belongs to another planning task event");
        assertThat(taskMapper.markedWaitingUserTaskId).isNull();
    }

    @Test
    void rejectsEventIdAlreadyBelongingToAnotherEventType() {
        taskMapper.completionContext = Optional.of(completionContext("RUNNING"));
        taskEventMapper.eventByEventId = Optional.of(new PlanningTaskEventRecord(
                1L, EVENT_ID, TASK_ID, "PLANNING_COMPLETED", 1, "{}",
                Instant.parse("2026-08-10T11:00:00Z")
        ));

        assertThatThrownBy(() -> service.handle(reviewEvent()))
                .isInstanceOf(PlanningEventRejectedException.class)
                .hasMessageContaining("belongs to another planning task event");
        assertThat(taskMapper.markedWaitingUserTaskId).isNull();
    }

    @Test
    void rejectsCandidateDateOutsideTripRange() {
        taskMapper.completionContext = Optional.of(completionContext("RUNNING"));
        taskEventMapper.eventByEventId = Optional.empty();
        PlanningReviewRequiredEvent event = reviewEvent();
        ObjectMapper mapper = new ObjectMapper().findAndRegisterModules();
        PlanningCompletedEvent.Itinerary outOfRangeItinerary =
                new PlanningCompletedEvent.Itinerary(
                        event.payload().itinerary().title(),
                        List.of(new PlanningCompletedEvent.Day(
                                LocalDate.parse("2026-08-02"),
                                event.payload().itinerary().days().get(0).activities(),
                                List.of()
                        )),
                        event.payload().itinerary().estimatedTotalCost()
                );
        com.fasterxml.jackson.databind.JsonNode rawOutOfRange =
                mapper.valueToTree(outOfRangeItinerary);
        String fingerprint = io.github.tobehardoo.trippilot.feasibility
                .ItineraryFingerprintVerifier.compute(rawOutOfRange);
        PlanningReviewRequiredEvent outOfRange = new PlanningReviewRequiredEvent(
                event.eventType(), event.schemaVersion(), event.eventId(), event.traceId(),
                event.taskId(), event.tripId(), event.runId(), event.occurredAt(),
                new PlanningReviewRequiredEvent.Payload(
                        event.payload().status(), event.payload().provider(),
                        outOfRangeItinerary,
                        event.payload().knowledge(), event.payload().factImpacts(),
                        event.payload().providerProvenance(),
                        withFingerprint(event.payload().feasibilityReport(), fingerprint),
                        rawOutOfRange.deepCopy()
                )
        );

        assertThatThrownBy(() -> service.handle(outOfRange))
                .isInstanceOf(PlanningEventRejectedException.class)
                .hasMessageContaining("within the trip range");
        assertThat(taskMapper.markedWaitingUserTaskId).isNull();
    }

    private io.github.tobehardoo.trippilot.feasibility.FeasibilityReport withFingerprint(
            io.github.tobehardoo.trippilot.feasibility.FeasibilityReport report,
            String fingerprint
    ) {
        return new io.github.tobehardoo.trippilot.feasibility.FeasibilityReport(
                report.schemaVersion(), report.reportId(), report.validatorVersion(),
                fingerprint, report.status(), report.validatedAt(),
                report.requiredRuleIds(), report.missingRequiredRuleIds(), report.summary(),
                report.ruleResults(), report.repairAttempts()
        );
    }

    @Test
    void marksStaleTripBaselineAsFailedWithoutWaitingUser() {
        taskMapper.completionContext = Optional.of(new PlanningTaskCompletionRecord(
                TASK_ID, TRIP_ID, "CREATE", "RUNNING", 2, null,
                "[]", TRACE_ID, 3, "{}", 1, null,
                LocalDate.parse("2026-08-01"), LocalDate.parse("2026-08-01"),
                Instant.parse("2026-08-10T10:00:00Z")
        ));
        taskEventMapper.eventByEventId = Optional.empty();
        taskMapper.terminalResult = 1;
        taskEventMapper.insertResult = 1;

        service.handle(reviewEvent());

        assertThat(taskMapper.markedWaitingUserTaskId).isNull();
        assertThat(taskMapper.terminalStatus).isEqualTo("FAILED");
        assertThat(taskMapper.terminalErrorCode).isEqualTo("STALE_TRIP_VERSION");
        assertThat(taskEventMapper.inserted.eventType()).isEqualTo("PLANNING_FAILED");
        assertThat(publishedEvents).hasSize(1);
    }

    @Test
    void marksStaleReplanBaselineAsFailedWithoutWaitingUser() {
        taskMapper.completionContext = Optional.of(new PlanningTaskCompletionRecord(
                TASK_ID, TRIP_ID, "REPLAN", "RUNNING", 2,
                UUID.fromString("11111111-1111-4111-8111-111111111111"),
                "[]", TRACE_ID, 3, "{}", 2,
                UUID.fromString("22222222-2222-4222-8222-222222222222"),
                LocalDate.parse("2026-08-01"), LocalDate.parse("2026-08-01"),
                Instant.parse("2026-08-10T10:00:00Z")
        ));
        taskEventMapper.eventByEventId = Optional.empty();
        taskMapper.terminalResult = 1;
        taskEventMapper.insertResult = 1;
        service.setReplanCurrentVersionId(
                UUID.fromString("22222222-2222-4222-8222-222222222222"));

        service.handle(reviewEvent());

        assertThat(taskMapper.markedWaitingUserTaskId).isNull();
        assertThat(taskMapper.terminalStatus).isEqualTo("FAILED");
        assertThat(taskMapper.terminalErrorCode).isEqualTo("STALE_ITINERARY_VERSION");
        assertThat(taskEventMapper.inserted.eventType()).isEqualTo("PLANNING_FAILED");
        assertThat(publishedEvents).hasSize(1);
    }

    @Test
    void persistsCompleteCandidatePayload() {
        taskMapper.completionContext = Optional.of(completionContext("RUNNING"));
        taskEventMapper.eventByEventId = Optional.empty();
        taskMapper.waitingUserResult = 1;
        taskEventMapper.insertResult = 1;

        service.handle(reviewEvent());

        assertThat(taskEventMapper.inserted.payloadJson())
                .contains("\"status\":\"WAITING_USER\"")
                .contains("\"candidateItinerary\"")
                .contains("\"feasibilityReport\"")
                .contains("\"itineraryFingerprint\"")
                .contains("\"knowledge\"")
                .contains("\"factImpacts\"")
                .contains("\"providerProvenance\"");
    }

    @Test
    void rejectsTaskNotInQueuedOrRunningStatus() {
        taskMapper.completionContext = Optional.of(completionContext("SUCCEEDED"));

        assertThatThrownBy(() -> service.handle(reviewEvent()))
                .isInstanceOf(PlanningEventRejectedException.class)
                .hasMessageContaining("cannot accept a review event in status SUCCEEDED");
    }

    @Test
    void rejectsIdentityMismatch() {
        taskMapper.completionContext = Optional.of(new PlanningTaskCompletionRecord(
                TASK_ID, UUID.randomUUID(), "CREATE", "RUNNING", 1, null,
                "[]", UUID.randomUUID(), 3, "{}", 1, null,
                LocalDate.parse("2026-08-01"), LocalDate.parse("2026-08-01"),
                Instant.parse("2026-08-10T10:00:00Z")
        ));

        assertThatThrownBy(() -> service.handle(reviewEvent()))
                .isInstanceOf(PlanningEventRejectedException.class)
                .hasMessageContaining("does not match its planning task");
    }

    @Test
    void rejectsUnknownTask() {
        taskMapper.completionContext = Optional.empty();

        assertThatThrownBy(() -> service.handle(reviewEvent()))
                .isInstanceOf(PlanningEventRejectedException.class)
                .hasMessageContaining("Planning task was not found");
    }

    @Test
    void rejectsStaleVersionWhenMarkWaitingUserUpdatesNoRow() {
        taskMapper.completionContext = Optional.of(completionContext("RUNNING"));
        taskEventMapper.eventByEventId = Optional.empty();
        taskMapper.waitingUserResult = 0;

        assertThatThrownBy(() -> service.handle(reviewEvent()))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("planning task status");
    }

    private PlanningTaskCompletionRecord completionContext(String status) {
        return new PlanningTaskCompletionRecord(
                TASK_ID, TRIP_ID, "CREATE", status, 1, null,
                "[]", TRACE_ID, 3, "{}", 1, null,
                LocalDate.parse("2026-08-01"), LocalDate.parse("2026-08-01"),
                Instant.parse("2026-08-10T10:00:00Z")
        );
    }

    private PlanningReviewRequiredEvent reviewEvent() {
        ObjectMapper mapper = new ObjectMapper().findAndRegisterModules();
        PlanningCompletedEvent.Itinerary itinerary =
                new PlanningCompletedEvent.Itinerary(
                        "Benchmark itinerary",
                        List.of(new PlanningCompletedEvent.Day(
                                LocalDate.parse("2026-08-01"),
                                List.of(new PlanningCompletedEvent.Activity(
                                        null, "Activity 1",
                                        OffsetDateTime.parse("2026-08-01T09:00:00Z"),
                                        OffsetDateTime.parse("2026-08-01T10:00:00Z"),
                                        new java.math.BigDecimal("0"),
                                        "DEMO", null, null, null, null, null
                                )),
                                List.of()
                        )),
                        new java.math.BigDecimal("0")
                );
        // The raw validated snapshot must be the exact tree the typed
        // itinerary deserialises from, and the report fingerprint must bind
        // it (B6J.2.2 integrity gate).
        com.fasterxml.jackson.databind.JsonNode rawItinerary =
                mapper.valueToTree(itinerary);
        String fingerprint = io.github.tobehardoo.trippilot.feasibility
                .ItineraryFingerprintVerifier.compute(rawItinerary);

        io.github.tobehardoo.trippilot.feasibility.FeasibilityReport.RuleResult rule =
                new io.github.tobehardoo.trippilot.feasibility.FeasibilityReport.RuleResult(
                        "R1", "1",
                        io.github.tobehardoo.trippilot.feasibility.RuleOutcome.UNKNOWN,
                        "REASON_OK", "evaluated",
                        List.of(), List.of(), List.of(), false
                );
        io.github.tobehardoo.trippilot.feasibility.FeasibilityReport report =
                new io.github.tobehardoo.trippilot.feasibility.FeasibilityReport(
                        1, UUID.randomUUID(), "hard-validator-v3",
                        fingerprint,
                        io.github.tobehardoo.trippilot.feasibility.FeasibilityStatus.UNVERIFIED,
                        OffsetDateTime.parse("2026-08-10T12:00:00Z"),
                        List.of("R1"), List.of(),
                        new io.github.tobehardoo.trippilot.feasibility.FeasibilityReport.Summary(
                                1, 0, 0, 1, 0, 0),
                        List.of(rule), List.of()
                );
        PlanningReviewRequiredEvent.Payload payload =
                new PlanningReviewRequiredEvent.Payload(
                        "WAITING_USER", "DEMO",
                        itinerary,
                        null, List.of(), null, report,
                        rawItinerary.deepCopy()
                );
        return new PlanningReviewRequiredEvent(
                "PLANNING_REVIEW_REQUIRED", 1, EVENT_ID, TRACE_ID, TASK_ID, TRIP_ID, RUN_ID,
                OffsetDateTime.parse("2026-08-10T12:00:00Z"), payload
        );
    }

    private static final class FakePlanningTaskMapper implements PlanningTaskMapper {

        private Optional<PlanningTaskCompletionRecord> completionContext;
        private int waitingUserResult;
        private UUID markedWaitingUserTaskId;
        private int markedWaitingUserVersion;
        private int terminalResult;
        private String terminalStatus;
        private String terminalErrorCode;

        @Override
        public Optional<PlanningTaskCompletionRecord> findCompletionContextForUpdate(UUID taskId) {
            return completionContext == null
                    ? Optional.empty() : completionContext;
        }

        @Override
        public int markWaitingUser(UUID taskId, int expectedVersion) {
            markedWaitingUserTaskId = taskId;
            markedWaitingUserVersion = expectedVersion;
            return waitingUserResult;
        }

        @Override
        public int updateTerminalStatus(
                UUID taskId, int expectedVersion, String status,
                String errorCode, String errorMessage) {
            terminalStatus = status;
            terminalErrorCode = errorCode;
            return terminalResult;
        }

        @Override
        public int insert(PlanningTaskRecord task) {
            throw new UnsupportedOperationException("not used in this test");
        }

        @Override
        public Optional<PlanningTaskRecord> findOwnedByIdempotencyKey(
                UUID tripId, UUID idempotencyKey, UUID ownerId) {
            throw new UnsupportedOperationException("not used in this test");
        }

        @Override
        public Optional<PlanningTaskRecord> findOwnedById(UUID taskId, UUID ownerId) {
            throw new UnsupportedOperationException("not used in this test");
        }

        @Override
        public Optional<PlanningTaskRecord> findLatestOwnedByTripId(
                UUID tripId, UUID ownerId) {
            throw new UnsupportedOperationException("not used in this test");
        }

        @Override
        public int markRunning(UUID taskId, int expectedVersion) {
            throw new UnsupportedOperationException("not used in this test");
        }

        @Override
        public int cancelOwned(UUID taskId, UUID ownerId) {
            throw new UnsupportedOperationException("not used in this test");
        }

        @Override
        public int abandonWaitingUserOwned(UUID taskId, UUID ownerId) {
            throw new UnsupportedOperationException("not used in this test");
        }

        @Override
        public boolean existsActiveByTripId(UUID tripId) {
            throw new UnsupportedOperationException("not used in this test");
        }

        @Override
        public List<FailedTaskDiagnostic> findRecentFailures(int limit) {
            throw new UnsupportedOperationException("not used in this test");
        }

        @Override
        public Optional<RetryableFailedTask> findRetryableFailedCreate(UUID taskId) {
            throw new UnsupportedOperationException("not used in this test");
        }
    }

    private static final class FakePlanningTaskEventMapper implements PlanningTaskEventMapper {

        private Optional<PlanningTaskEventRecord> eventByEventId;
        private int insertResult;
        private PlanningTaskEventRecord inserted;

        @Override
        public int insert(PlanningTaskEventRecord event) {
            inserted = event;
            eventByEventId = Optional.of(new PlanningTaskEventRecord(
                    1L, event.eventId(), event.taskId(), event.eventType(),
                    event.schemaVersion(), event.payloadJson(), event.createdAt()
            ));
            return insertResult;
        }

        @Override
        public Optional<PlanningTaskEventRecord> findByEventId(UUID eventId) {
            return eventByEventId == null ? Optional.empty() : eventByEventId;
        }

        @Override
        public List<PlanningTaskEventRecord> findAfter(UUID taskId, long afterId) {
            throw new UnsupportedOperationException("not used in this test");
        }

        @Override
        public int findLatestProgressSequence(UUID taskId) {
            throw new UnsupportedOperationException("not used in this test");
        }

        @Override
        public Optional<LatestProgressRecord> findLatestProgress(UUID taskId) {
            throw new UnsupportedOperationException("not used in this test");
        }

        @Override
        public Optional<PlanningTaskEventRecord> findLatestOutcome(UUID taskId) {
            throw new UnsupportedOperationException("not used in this test");
        }
    }
}
