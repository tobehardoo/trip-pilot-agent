package io.github.tobehardoo.trippilot.planning;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.itinerary.ItineraryMapper;
import io.github.tobehardoo.trippilot.messaging.PlanningCompletedEvent;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PlanningCompletionService implements PlanningCompletionHandler {

    private static final String SUCCEEDED = "SUCCEEDED";
    private static final String FAILED = "FAILED";

    private final PlanningTaskMapper taskMapper;
    private final PlanningTaskEventMapper taskEventMapper;
    private final ItineraryMapper itineraryMapper;
    private final ObjectMapper objectMapper;
    private final Clock clock;
    private final ApplicationEventPublisher eventPublisher;

    public PlanningCompletionService(PlanningTaskMapper taskMapper,
                                     PlanningTaskEventMapper taskEventMapper,
                                     ItineraryMapper itineraryMapper,
                                     ObjectMapper objectMapper,
                                     Clock clock,
                                     ApplicationEventPublisher eventPublisher) {
        this.taskMapper = taskMapper;
        this.taskEventMapper = taskEventMapper;
        this.itineraryMapper = itineraryMapper;
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
            persistStaleFailure(event, task);
            return;
        }
        persistCompletedItinerary(event, task);
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
                if (!day.date().equals(activity.startTime().toLocalDate())
                        || !day.date().equals(activity.endTime().toLocalDate())) {
                    throw rejected("Activities must remain within their itinerary day");
                }
            }
        }
    }

    private void persistCompletedItinerary(PlanningCompletedEvent event,
                                           PlanningTaskCompletionRecord task) {
        Instant now = clock.instant();
        itineraryMapper.insertItinerary(UUID.randomUUID(), task.tripId());
        ItineraryMapper.ItineraryState itinerary = itineraryMapper.findStateForUpdate(task.tripId())
                .orElseThrow(() -> new IllegalStateException("Itinerary could not be created"));
        UUID versionId = UUID.randomUUID();
        int versionNumber = itinerary.currentVersionNumber() + 1;
        PlanningCompletedEvent.Itinerary result = event.payload().itinerary();
        requireOne(itineraryMapper.insertVersion(new ItineraryMapper.VersionWrite(
                versionId, itinerary.id(), versionNumber, itinerary.currentVersionId(), task.id(),
                result.title().strip(), result.estimatedTotalCost(), event.payload().provider(),
                task.constraintSnapshotJson(), now
        )), "itinerary version");
        persistKnowledge(versionId, event.payload().knowledge());
        for (int dayIndex = 0; dayIndex < result.days().size(); dayIndex++) {
            persistDay(versionId, dayIndex, result.days().get(dayIndex));
        }
        requireOne(itineraryMapper.updateCurrentVersion(itinerary.id(), versionId), "current version");
        requireOne(taskMapper.updateTerminalStatus(
                task.id(), task.taskVersion(), SUCCEEDED, null, null
        ), "planning task status");
        publishAfterCommit(insertTaskEvent(new PlanningTaskEventRecord(
                null, event.eventId(), task.id(), "PLANNING_COMPLETED", 1,
                writeJson(new CompletionPayload(
                        SUCCEEDED, event.runId(), versionId, versionNumber, event.payload().provider()
                )), now
        )));
    }

    private void persistKnowledge(UUID versionId,
                                  PlanningCompletedEvent.KnowledgeEvidence knowledge) {
        if (knowledge == null) {
            return;
        }
        PlanningCompletedEvent.KnowledgeFreshness freshness = knowledge.freshness();
        requireOne(itineraryMapper.insertKnowledge(new ItineraryMapper.KnowledgeWrite(
                versionId, knowledge.status(), knowledge.query().strip(), freshness.status(),
                freshness.checkedAt(), freshness.staleReason(), knowledge.message()
        )), "itinerary knowledge evidence");
        for (int index = 0; index < knowledge.citations().size(); index++) {
            PlanningCompletedEvent.KnowledgeCitation citation = knowledge.citations().get(index);
            requireOne(itineraryMapper.insertKnowledgeCitation(
                    new ItineraryMapper.KnowledgeCitationWrite(
                            UUID.randomUUID(), versionId, index, citation.documentId(),
                            citation.documentVersion(), citation.chunkId(), citation.chunkIndex(),
                            citation.title().strip(), citation.sourceUrl(), citation.sourceName().strip(),
                            citation.collectedAt(), citation.reliabilityLevel(), citation.similarity()
                    )
            ), "itinerary knowledge citation");
        }
    }

    private void persistDay(UUID versionId, int dayIndex, PlanningCompletedEvent.Day day) {
        UUID dayId = UUID.randomUUID();
        requireOne(itineraryMapper.insertDay(new ItineraryMapper.DayWrite(
                dayId, versionId, day.date(), dayIndex
        )), "itinerary day");
        List<UUID> activityIds = new ArrayList<>(day.activities().size());
        for (int activityIndex = 0; activityIndex < day.activities().size(); activityIndex++) {
            PlanningCompletedEvent.Activity activity = day.activities().get(activityIndex);
            PlanningCompletedEvent.Coordinates coordinates = activity.coordinates();
            UUID activityId = UUID.randomUUID();
            activityIds.add(activityId);
            requireOne(itineraryMapper.insertActivity(new ItineraryMapper.ActivityWrite(
                    activityId, dayId, activityIndex, activity.title().strip(),
                    activity.startTime(), activity.endTime(), activity.estimatedCost(), activity.source(),
                    activity.providerPoiId(), coordinates == null ? null : coordinates.longitude(),
                    coordinates == null ? null : coordinates.latitude(), activity.address()
            )), "itinerary activity");
        }
        for (int legIndex = 0; legIndex < day.transitLegs().size(); legIndex++) {
            PlanningCompletedEvent.TransitLeg leg = day.transitLegs().get(legIndex);
            requireOne(itineraryMapper.insertTransitLeg(new ItineraryMapper.TransitLegWrite(
                    UUID.randomUUID(), dayId, legIndex,
                    activityIds.get(leg.fromActivityIndex()),
                    activityIds.get(leg.toActivityIndex()),
                    leg.mode(), leg.distanceMeters(), leg.durationSeconds(), leg.provider(),
                    leg.estimated(), writeJson(leg.polyline())
            )), "itinerary transit leg");
        }
    }

    private void persistStaleFailure(PlanningCompletedEvent event,
                                     PlanningTaskCompletionRecord task) {
        Instant now = clock.instant();
        requireOne(taskMapper.updateTerminalStatus(
                task.id(), task.taskVersion(), FAILED, "STALE_TRIP_VERSION",
                "Trip constraints changed while planning was running"
        ), "planning task status");
        publishAfterCommit(insertTaskEvent(new PlanningTaskEventRecord(
                null, event.eventId(), task.id(), "PLANNING_FAILED", 1,
                writeJson(new FailurePayload(
                        FAILED, "STALE_TRIP_VERSION",
                        "Trip constraints changed while planning was running"
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
