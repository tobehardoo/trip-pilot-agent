package io.github.tobehardoo.trippilot.planning;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.itinerary.ItineraryService;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningCompletedEvent;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PlanningCompletionService implements PlanningCompletionHandler {

    private static final String SUCCEEDED = "SUCCEEDED";
    private static final String FAILED = "FAILED";

    private final PlanningTaskMapper taskMapper;
    private final PlanningTaskEventMapper taskEventMapper;
    private final ItineraryService itineraryService;
    private final ObjectMapper objectMapper;
    private final Clock clock;
    private final ApplicationEventPublisher eventPublisher;

    public PlanningCompletionService(PlanningTaskMapper taskMapper,
                                     PlanningTaskEventMapper taskEventMapper,
                                     ItineraryService itineraryService,
                                     ObjectMapper objectMapper,
                                     Clock clock,
                                     ApplicationEventPublisher eventPublisher) {
        this.taskMapper = taskMapper;
        this.taskEventMapper = taskEventMapper;
        this.itineraryService = itineraryService;
        this.objectMapper = objectMapper;
        this.clock = clock;
        this.eventPublisher = eventPublisher;
    }

    @Transactional
    @Override
    public void handle(PlanningCompletedEvent event) {
        PlanningTaskCompletionRecord task = taskMapper.findCompletionContextForUpdate(event.taskId())
                .orElseThrow(() -> rejected("Planning task was not found"));
        validateIdentity(event, task);
        var existingEvent = taskEventMapper.findByEventId(event.eventId());
        if (existingEvent.isPresent()) {
            PlanningTaskEventRecord existing = existingEvent.get();
            boolean isSameCompletedDelivery = existing.taskId().equals(task.id())
                    && ("PLANNING_COMPLETED".equals(existing.eventType())
                    || "PLANNING_FAILED".equals(existing.eventType()));
            if (isSameCompletedDelivery) {
                return;
            }
            throw rejected("Completed eventId already belongs to another planning task event");
        }
        if (!"QUEUED".equals(task.status()) && !"RUNNING".equals(task.status())) {
            throw rejected("Planning task cannot accept a completion event in status " + task.status());
        }
        validateDates(event, task);
        if (task.baselineTripVersion() != task.currentTripVersion()) {
            persistStaleFailure(event, task, "STALE_TRIP_VERSION",
                    "Trip constraints changed while planning was running");
            return;
        }
        if ("REPLAN".equals(task.taskType())) {
            if (!task.baselineItineraryVersionId()
                    .equals(itineraryService.getCurrentVersionForTask(task.tripId()))) {
                persistStaleFailure(event, task, "STALE_ITINERARY_VERSION",
                        "The itinerary changed while local replanning was running");
                return;
            }
            ItineraryService.CreateItineraryResult result =
                    itineraryService.createReplanVersion(
                            task.tripId(), event, task, clock);
            updateTaskToSucceeded(
                    event, task, result, "PLANNING_COMPLETED",
                    writeJson(new CompletionPayload(SUCCEEDED, event.runId(),
                            result.versionId(), result.versionNumber(),
                            result.provider())));
            return;
        }
        ItineraryService.CreateItineraryResult result =
                itineraryService.createInitialItinerary(
                        task.tripId(), event, task.id(),
                        task.constraintSnapshotJson(), clock);
        updateTaskToSucceeded(
                event, task, result, "PLANNING_COMPLETED",
                writeJson(new CompletionPayload(SUCCEEDED, event.runId(),
                        result.versionId(), result.versionNumber(),
                        result.provider())));
    }

    private void validateIdentity(PlanningCompletedEvent event, PlanningTaskCompletionRecord task) {
        if (!event.tripId().equals(task.tripId()) || !event.traceId().equals(task.traceId())) {
            throw rejected("Completed event does not match its planning task");
        }
    }

    private void validateDates(PlanningCompletedEvent event, PlanningTaskCompletionRecord task) {
        var days = event.payload().itinerary().days();
        long expectedDayCount = ChronoUnit.DAYS.between(task.tripStartDate(), task.tripEndDate()) + 1;
        if (days.size() != expectedDayCount) {
            throw rejected("Completed itinerary must contain every trip date exactly once");
        }
        for (int dayIndex = 0; dayIndex < days.size(); dayIndex++) {
            PlanningCompletedEvent.Day day = days.get(dayIndex);
            LocalDate expectedDate = task.tripStartDate().plusDays(dayIndex);
            if (!expectedDate.equals(day.date())) {
                throw rejected("Completed itinerary dates must be ordered within the trip range");
            }
            for (PlanningCompletedEvent.Activity activity : day.activities()) {
                if (!day.date().equals(activity.startTime().withOffsetSameInstant(ZoneOffset.ofHours(8)).toLocalDate())
                        || !day.date().equals(activity.endTime().withOffsetSameInstant(ZoneOffset.ofHours(8)).toLocalDate())) {
                    throw rejected("Activities must remain within their itinerary day");
                }
            }
        }
    }

    private void updateTaskToSucceeded(
            PlanningCompletedEvent event,
            PlanningTaskCompletionRecord task,
            ItineraryService.CreateItineraryResult version,
            String eventType,
            String payloadJson) {
        Instant now = clock.instant();
        requireOne(taskMapper.updateTerminalStatus(
                task.id(), task.taskVersion(), SUCCEEDED, null, null
        ), "planning task status");
        publishAfterCommit(insertTaskEvent(new PlanningTaskEventRecord(
                null, event.eventId(), task.id(), eventType, 1, payloadJson, now
        )));
    }

    private void persistStaleFailure(PlanningCompletedEvent event,
                                     PlanningTaskCompletionRecord task,
                                     String errorCode,
                                     String message) {
        Instant now = clock.instant();
        requireOne(taskMapper.updateTerminalStatus(
                task.id(), task.taskVersion(), FAILED, errorCode, message
        ), "planning task status");
        publishAfterCommit(insertTaskEvent(new PlanningTaskEventRecord(
                null, event.eventId(), task.id(), "PLANNING_FAILED", 1,
                writeJson(new FailurePayload(
                        FAILED, errorCode, message
                )), now
        )));
    }

    private PlanningTaskEventRecord insertTaskEvent(PlanningTaskEventRecord event) {
        requireOne(taskEventMapper.insert(event), "planning task event");
        return taskEventMapper.findByEventId(event.eventId())
                .orElseThrow(() -> new IllegalStateException("Planning task event could not be read"));
    }

    private void publishAfterCommit(PlanningTaskEventRecord event) {
        eventPublisher.publishEvent(new PlanningTaskEventCreated(event));
    }

    private void requireOne(int updatedRows, String operation) {
        if (updatedRows != 1) {
            throw new IllegalStateException("Could not persist " + operation);
        }
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Could not serialize planning task event", exception);
        }
    }

    private PlanningEventRejectedException rejected(String message) {
        return new PlanningEventRejectedException(message);
    }

    private record CompletionPayload(
            String status,
            UUID runId,
            UUID itineraryVersionId,
            int itineraryVersionNumber,
            String provider
    ) {
    }

    private record FailurePayload(String status, String errorCode, String message) {
    }
}
