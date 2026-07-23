package io.github.tobehardoo.trippilot.planning;

import java.time.Instant;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.guide.GuideImportService;
import io.github.tobehardoo.trippilot.messaging.OutboxEventRecord;
import io.github.tobehardoo.trippilot.messaging.OutboxMapper;
import io.github.tobehardoo.trippilot.trip.TripService;
import org.springframework.http.HttpStatus;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PlanningTaskService {

    private static final String TASK_TYPE = "CREATE";
    private static final String TASK_STATUS = "QUEUED";
    private static final String COMMAND_TYPE = "PLANNING_CREATE_REQUESTED";
    private static final String ROUTING_KEY = "planning.create";
    private static final String CANCEL_COMMAND_TYPE = "PLANNING_CANCEL_REQUESTED";
    private static final String CANCEL_ROUTING_KEY = "planning.cancel";
    private static final long MAX_TRIP_DAYS = 7;

    private final PlanningTaskMapper planningTaskMapper;
    private final PlanningTaskEventMapper planningTaskEventMapper;
    private final OutboxMapper outboxMapper;
    private final TripService tripService;
    private final GuideImportService guideImportService;
    private final ObjectMapper objectMapper;
    private final ApplicationEventPublisher eventPublisher;

    public PlanningTaskService(PlanningTaskMapper planningTaskMapper,
                               PlanningTaskEventMapper planningTaskEventMapper,
                               OutboxMapper outboxMapper,
                               TripService tripService,
                               GuideImportService guideImportService,
                               ObjectMapper objectMapper,
                               ApplicationEventPublisher eventPublisher) {
        this.planningTaskMapper = planningTaskMapper;
        this.planningTaskEventMapper = planningTaskEventMapper;
        this.outboxMapper = outboxMapper;
        this.tripService = tripService;
        this.guideImportService = guideImportService;
        this.objectMapper = objectMapper;
        this.eventPublisher = eventPublisher;
    }

    @Transactional
    public PlanningTaskResponse create(UUID ownerId, UUID tripId, UUID idempotencyKey) {
        TripService.TripResponse trip = tripService.get(ownerId, tripId);
        var existing = planningTaskMapper.findOwnedByIdempotencyKey(tripId, idempotencyKey, ownerId);
        if (existing.isPresent()) {
            return toResponse(existing.get());
        }
        if (ChronoUnit.DAYS.between(trip.startDate(), trip.endDate()) + 1 > MAX_TRIP_DAYS) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "TRIP_DURATION_UNSUPPORTED",
                    "Planning supports trips up to 7 days; shorten the trip dates and retry"
            );
        }

        Instant now = Instant.now();
        List<GuideImportService.PlanningGuideFact> guideFacts =
                guideImportService.planningEvidence(ownerId, tripId, now);
        String constraintSnapshotJson = writeJson(trip.constraints());
        GuideEvidenceSnapshot guideEvidenceSnapshot = new GuideEvidenceSnapshot(guideFacts);
        String guideEvidenceSnapshotJson = writeJson(guideEvidenceSnapshot);
        PlanningTaskRecord task = new PlanningTaskRecord(
                UUID.randomUUID(), tripId, idempotencyKey, TASK_TYPE, TASK_STATUS,
                trip.version(), constraintSnapshotJson, guideEvidenceSnapshotJson,
                UUID.randomUUID(), 0, null, null, 0, now, now
        );
        if (planningTaskMapper.insert(task) == 0) {
            return planningTaskMapper.findOwnedByIdempotencyKey(tripId, idempotencyKey, ownerId)
                    .map(this::toResponse)
                    .orElseThrow(() -> new ApiException(
                            HttpStatus.CONFLICT,
                            "PLANNING_TASK_ACTIVE",
                            "This trip already has an active planning task"
                    ));
        }

        int insertedEventCount = planningTaskEventMapper.insert(new PlanningTaskEventRecord(
                null, UUID.randomUUID(), task.id(), "PLANNING_QUEUED", 1,
                writeJson(new TaskStatusPayload(TASK_STATUS)), now
        ));
        if (insertedEventCount != 1) {
            throw new IllegalStateException("Could not persist planning queued event");
        }

        UUID eventId = UUID.randomUUID();
        PlanningCreateCommand command = new PlanningCreateCommand(
                COMMAND_TYPE, 2, eventId, task.traceId(), task.id(), tripId, now,
                new PlanningCreatePayload(
                        TASK_TYPE,
                        trip.version(),
                        idempotencyKey,
                        new TripSnapshot(
                                trip.title(), trip.destination(), trip.startDate(), trip.endDate(),
                                trip.status(), trip.version(), trip.constraints()
                        ),
                        guideEvidenceSnapshot
                )
        );
        outboxMapper.insert(new OutboxEventRecord(
                eventId, "PLANNING_TASK", task.id(), COMMAND_TYPE, ROUTING_KEY,
                writeJson(command), "PENDING", 0, now, null, now, null
        ));
        return toResponse(task);
    }

    @Transactional
    public PlanningTaskResponse cancel(UUID ownerId, UUID taskId) {
        PlanningTaskRecord existing = planningTaskMapper.findOwnedById(taskId, ownerId)
                .orElseThrow(() -> new ApiException(
                        HttpStatus.NOT_FOUND, "PLANNING_TASK_NOT_FOUND", "Planning task was not found"
                ));
        if ("CANCELLED".equals(existing.status())) {
            return toResponse(existing);
        }
        if (planningTaskMapper.cancelOwned(taskId, ownerId) != 1) {
            throw new ApiException(
                    HttpStatus.CONFLICT,
                    "PLANNING_TASK_TERMINAL",
                    "Completed or failed planning tasks cannot be cancelled"
            );
        }
        Instant now = Instant.now();
        PlanningTaskEventRecord event = new PlanningTaskEventRecord(
                null, UUID.randomUUID(), taskId, "PLANNING_CANCELLED", 1,
                writeJson(new TaskStatusPayload("CANCELLED")), now
        );
        if (planningTaskEventMapper.insert(event) != 1) {
            throw new IllegalStateException("Could not persist planning cancelled event");
        }
        UUID cancelEventId = UUID.randomUUID();
        PlanningCancelCommand cancelCommand = new PlanningCancelCommand(
                CANCEL_COMMAND_TYPE, 1, cancelEventId, existing.traceId(), taskId,
                existing.tripId(), now
        );
        outboxMapper.insert(new OutboxEventRecord(
                cancelEventId, "PLANNING_TASK", taskId, CANCEL_COMMAND_TYPE,
                CANCEL_ROUTING_KEY, writeJson(cancelCommand), "PENDING", 0,
                now, null, now, null
        ));
        PlanningTaskEventRecord stored = planningTaskEventMapper.findByEventId(event.eventId())
                .orElseThrow(() -> new IllegalStateException("Cancelled event could not be read"));
        eventPublisher.publishEvent(new PlanningTaskEventCreated(stored));
        return planningTaskMapper.findOwnedById(taskId, ownerId)
                .map(this::toResponse)
                .orElseThrow(() -> new IllegalStateException("Cancelled task could not be read"));
    }

    private PlanningTaskResponse toResponse(PlanningTaskRecord task) {
        return new PlanningTaskResponse(
                task.id(), task.tripId(), task.taskType(), task.status(), task.baselineTripVersion(),
                "/api/planning-tasks/" + task.id() + "/events", task.createdAt(), task.updatedAt()
        );
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Could not serialize planning command", exception);
        }
    }

    public record PlanningTaskResponse(
            UUID taskId,
            UUID tripId,
            String taskType,
            String status,
            int baselineTripVersion,
            String eventStreamUrl,
            Instant createdAt,
            Instant updatedAt
    ) {
    }

    private record PlanningCreateCommand(
            String eventType,
            int schemaVersion,
            UUID eventId,
            UUID traceId,
            UUID taskId,
            UUID tripId,
            Instant occurredAt,
            PlanningCreatePayload payload
    ) {
    }

    private record PlanningCreatePayload(
            String taskType,
            int baselineTripVersion,
            UUID idempotencyKey,
            TripSnapshot trip,
            GuideEvidenceSnapshot guideEvidence
    ) {
    }

    private record PlanningCancelCommand(
            String eventType,
            int schemaVersion,
            UUID eventId,
            UUID traceId,
            UUID taskId,
            UUID tripId,
            Instant occurredAt
    ) {
    }

    private record TripSnapshot(
            String title,
            String destination,
            LocalDate startDate,
            LocalDate endDate,
            String status,
            int version,
            TripService.ConstraintResponse constraints
    ) {
    }

    private record GuideEvidenceSnapshot(
            List<GuideImportService.PlanningGuideFact> facts
    ) {
    }

    private record TaskStatusPayload(String status) {
    }
}
