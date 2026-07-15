package io.github.tobehardoo.trippilot.planning;

import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.messaging.OutboxEventRecord;
import io.github.tobehardoo.trippilot.messaging.OutboxMapper;
import io.github.tobehardoo.trippilot.trip.TripService;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PlanningTaskService {

    private static final String TASK_TYPE = "CREATE";
    private static final String TASK_STATUS = "QUEUED";
    private static final String COMMAND_TYPE = "PLANNING_CREATE_REQUESTED";
    private static final String ROUTING_KEY = "planning.create";

    private final PlanningTaskMapper planningTaskMapper;
    private final PlanningTaskEventMapper planningTaskEventMapper;
    private final OutboxMapper outboxMapper;
    private final TripService tripService;
    private final ObjectMapper objectMapper;

    public PlanningTaskService(PlanningTaskMapper planningTaskMapper,
                               PlanningTaskEventMapper planningTaskEventMapper,
                               OutboxMapper outboxMapper,
                               TripService tripService,
                               ObjectMapper objectMapper) {
        this.planningTaskMapper = planningTaskMapper;
        this.planningTaskEventMapper = planningTaskEventMapper;
        this.outboxMapper = outboxMapper;
        this.tripService = tripService;
        this.objectMapper = objectMapper;
    }

    @Transactional
    public PlanningTaskResponse create(UUID ownerId, UUID tripId, UUID idempotencyKey) {
        TripService.TripResponse trip = tripService.get(ownerId, tripId);
        var existing = planningTaskMapper.findOwnedByIdempotencyKey(tripId, idempotencyKey, ownerId);
        if (existing.isPresent()) {
            return toResponse(existing.get());
        }

        Instant now = Instant.now();
        String constraintSnapshotJson = writeJson(trip.constraints());
        PlanningTaskRecord task = new PlanningTaskRecord(
                UUID.randomUUID(), tripId, idempotencyKey, TASK_TYPE, TASK_STATUS,
                trip.version(), constraintSnapshotJson, UUID.randomUUID(), 0, null, null, 0, now, now
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
                COMMAND_TYPE, 1, eventId, task.traceId(), task.id(), tripId, now,
                new PlanningCreatePayload(
                        TASK_TYPE,
                        trip.version(),
                        idempotencyKey,
                        new TripSnapshot(
                                trip.title(), trip.destination(), trip.startDate(), trip.endDate(),
                                trip.status(), trip.version(), trip.constraints()
                        )
                )
        );
        outboxMapper.insert(new OutboxEventRecord(
                eventId, "PLANNING_TASK", task.id(), COMMAND_TYPE, ROUTING_KEY,
                writeJson(command), "PENDING", 0, now, null, now, null
        ));
        return toResponse(task);
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
            TripSnapshot trip
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

    private record TaskStatusPayload(String status) {
    }
}
