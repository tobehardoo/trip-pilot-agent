package io.github.tobehardoo.trippilot.planning;

import java.time.Instant;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.cityintelligence.CityIntelligencePlanningPreflightService;
import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.guide.GuideImportService;
import io.github.tobehardoo.trippilot.itinerary.ItineraryMapper;
import io.github.tobehardoo.trippilot.itinerary.ItineraryService;
import io.github.tobehardoo.trippilot.infrastructure.mq.OutboxEventRecord;
import io.github.tobehardoo.trippilot.infrastructure.mq.OutboxMapper;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningCompletedEvent;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningCompletedEvent.PlanEvaluation;
import io.github.tobehardoo.trippilot.planning.PlanningContextSnapshotService.PlanningContextSnapshot;
import io.github.tobehardoo.trippilot.trip.TripService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class PlanningTaskService {

    private static final Logger log = LoggerFactory.getLogger(PlanningTaskService.class);

    private static final String CREATE_TASK_TYPE = "CREATE";
    private static final String REPLAN_TASK_TYPE = "REPLAN";
    private static final String TASK_STATUS = "QUEUED";
    private static final String COMMAND_TYPE = "PLANNING_CREATE_REQUESTED";
    private static final String ROUTING_KEY = "planning.create";
    private static final String REPLAN_COMMAND_TYPE = "PLANNING_REPLAN_REQUESTED";
    private static final String REPLAN_ROUTING_KEY = "planning.replan";
    private static final String CANDIDATE_COMMAND_TYPE =
            "PLANNING_CANDIDATE_VALIDATION_REQUESTED";
    private static final String CANDIDATE_ROUTING_KEY = "planning.candidate-validation";
    private static final String CANCEL_COMMAND_TYPE = "PLANNING_CANCEL_REQUESTED";
    private static final String CANCEL_ROUTING_KEY = "planning.cancel";
    private static final long MAX_TRIP_DAYS = 7;

    private final PlanningTaskMapper planningTaskMapper;
    private final ItineraryMapper itineraryMapper;
    private final ItineraryService itineraryService;
    private final PlanningTaskEventMapper planningTaskEventMapper;
    private final OutboxMapper outboxMapper;
    private final TripService tripService;
    private final CityIntelligencePlanningPreflightService cityIntelligencePlanningPreflightService;
    private final GuideImportService guideImportService;
    private final PlanningContextSnapshotService planningContextSnapshotService;
    private final ObjectMapper objectMapper;
    private final ApplicationEventPublisher eventPublisher;
    private final TransactionTemplate transactionTemplate;
    private final PlanningMetrics metrics;
    private final PlanningTaskOutcomeReadModel outcomeReadModel;

    public PlanningTaskService(PlanningTaskMapper planningTaskMapper,
                               ItineraryMapper itineraryMapper,
                               ItineraryService itineraryService,
                               PlanningTaskEventMapper planningTaskEventMapper,
                               OutboxMapper outboxMapper,
                               TripService tripService,
                               CityIntelligencePlanningPreflightService
                                       cityIntelligencePlanningPreflightService,
                               GuideImportService guideImportService,
                               PlanningContextSnapshotService planningContextSnapshotService,
                               ObjectMapper objectMapper,
                               ApplicationEventPublisher eventPublisher,
                               PlatformTransactionManager transactionManager,
                               PlanningMetrics metrics,
                               PlanningTaskOutcomeReadModel outcomeReadModel) {
        this.planningTaskMapper = planningTaskMapper;
        this.itineraryMapper = itineraryMapper;
        this.itineraryService = itineraryService;
        this.planningTaskEventMapper = planningTaskEventMapper;
        this.outboxMapper = outboxMapper;
        this.tripService = tripService;
        this.cityIntelligencePlanningPreflightService =
                cityIntelligencePlanningPreflightService;
        this.guideImportService = guideImportService;
        this.planningContextSnapshotService = planningContextSnapshotService;
        this.objectMapper = objectMapper;
        this.eventPublisher = eventPublisher;
        this.transactionTemplate = new TransactionTemplate(transactionManager);
        this.metrics = metrics;
        this.outcomeReadModel = outcomeReadModel;
    }

    public PlanningTaskResponse create(UUID ownerId, UUID tripId, UUID idempotencyKey) {
        var existing = planningTaskMapper.findOwnedByIdempotencyKey(tripId, idempotencyKey, ownerId);
        if (existing.isPresent()) {
            PlanningTaskIdempotency.requireCreateMatch(existing.get());
            return toResponse(existing.get());
        }
        TripService.TripResponse trip = tripService.get(ownerId, tripId);
        validateTripDuration(trip);
        cityIntelligencePlanningPreflightService.prepare(trip);

        PlanningTaskResponse response = transactionTemplate.execute(
                ignored -> createTransactional(ownerId, tripId, idempotencyKey)
        );
        if (response == null) {
            throw new IllegalStateException("Planning transaction returned no response");
        }
        return response;
    }

    @Transactional(readOnly = true)
    public PlanningTaskResponse get(UUID ownerId, UUID taskId) {
        return planningTaskMapper.findOwnedById(taskId, ownerId)
                .map(this::toResponse)
                .orElseThrow(() -> new ApiException(
                        HttpStatus.NOT_FOUND,
                        "PLANNING_TASK_NOT_FOUND",
                        "Planning task was not found"
                ));
    }

    /**
     * Returns the newest planning task owned by the caller for the trip, or
     * 404 when the trip has no task (or the trip does not exist / is not
     * owned by the caller).  Read-only: never mutates task state and never
     * produces task events.  Ordering is {@code created_at DESC, id DESC}.
     */
    @Transactional(readOnly = true)
    public PlanningTaskResponse latest(UUID ownerId, UUID tripId) {
        return planningTaskMapper.findLatestOwnedByTripId(tripId, ownerId)
                .map(this::toResponse)
                .orElseThrow(() -> new ApiException(
                        HttpStatus.NOT_FOUND,
                        "PLANNING_TASK_NOT_FOUND",
                        "Planning task was not found"
                ));
    }

    private PlanningTaskResponse createTransactional(
            UUID ownerId,
            UUID tripId,
            UUID idempotencyKey
    ) {
        TripService.TripResponse trip = tripService.get(ownerId, tripId);
        var existing = planningTaskMapper.findOwnedByIdempotencyKey(
                tripId,
                idempotencyKey,
                ownerId
        );
        if (existing.isPresent()) {
            PlanningTaskIdempotency.requireCreateMatch(existing.get());
            return toResponse(existing.get());
        }
        validateTripDuration(trip);
        Instant now = Instant.now();
        itineraryMapper.findStateForUpdate(tripId);
        if (itineraryMapper.hasLockedItineraryElements(tripId)) {
            throw new ApiException(
                    HttpStatus.CONFLICT,
                    "ITINERARY_LOCKED_ACTIVITIES",
                    "Unlock locked activities before starting full replanning"
            );
        }
        List<GuideImportService.PlanningGuideFact> guideFacts =
                guideImportService.planningEvidence(ownerId, tripId, now);
        String constraintSnapshotJson = writeJson(trip.constraints());
        GuideEvidenceSnapshot guideEvidenceSnapshot = new GuideEvidenceSnapshot(guideFacts);
        String guideEvidenceSnapshotJson = writeJson(guideEvidenceSnapshot);
        PlanningTaskRecord task = new PlanningTaskRecord(
                UUID.randomUUID(), tripId, idempotencyKey, CREATE_TASK_TYPE, TASK_STATUS,
                trip.version(), null, null, constraintSnapshotJson, guideEvidenceSnapshotJson,
                UUID.randomUUID(), 0, null, null, 0, now, now
        );
        if (planningTaskMapper.insert(task) == 0) {
            return planningTaskMapper.findOwnedByIdempotencyKey(tripId, idempotencyKey, ownerId)
                    .map(existingTask -> {
                        PlanningTaskIdempotency.requireCreateMatch(existingTask);
                        return toResponse(existingTask);
                    })
                    .orElseThrow(() -> new ApiException(
                            HttpStatus.CONFLICT,
                            "PLANNING_TASK_ACTIVE",
                            "This trip already has an active planning task"
                    ));
        }
        metrics.taskCreated(task.taskType());
        PlanningContextSnapshot planningContext = planningContextSnapshotService.freeze(
                ownerId,
                task.id(),
                trip,
                guideFacts,
                now
        );

        int insertedEventCount = planningTaskEventMapper.insert(new PlanningTaskEventRecord(
                null, UUID.randomUUID(), task.id(), "PLANNING_QUEUED", 1,
                writeJson(new TaskStatusPayload(TASK_STATUS)), now
        ));
        if (insertedEventCount != 1) {
            throw new IllegalStateException("Could not persist planning queued event");
        }

        UUID eventId = UUID.randomUUID();
        PlanningCreateCommand command = new PlanningCreateCommand(
                COMMAND_TYPE, 3, eventId, task.traceId(), task.id(), tripId, now,
                new PlanningCreatePayload(
                        CREATE_TASK_TYPE,
                        trip.version(),
                        idempotencyKey,
                        new TripSnapshot(
                                trip.title(), trip.destination(), trip.startDate(), trip.endDate(),
                                trip.status(), trip.version(), trip.constraints()
                        ),
                        guideEvidenceSnapshot,
                        planningContext
                )
        );
        outboxMapper.insert(new OutboxEventRecord(
                eventId, "PLANNING_TASK", task.id(), COMMAND_TYPE, ROUTING_KEY,
                writeJson(command), "PENDING", 0, now, null, now, null
        ));
        log.info("task queued: taskType=CREATE");
        return toResponse(task);
    }

    private void validateTripDuration(TripService.TripResponse trip) {
        if (ChronoUnit.DAYS.between(trip.startDate(), trip.endDate()) + 1 > MAX_TRIP_DAYS) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "TRIP_DURATION_UNSUPPORTED",
                    "Planning supports trips up to 7 days; shorten the trip dates and retry"
            );
        }
    }

    @Transactional
    public PlanningTaskResponse createReplan(
            UUID ownerId, UUID tripId, UUID idempotencyKey, LocalReplanRequest request) {
        TripService.TripResponse trip = tripService.get(ownerId, tripId);
        var existing = planningTaskMapper.findOwnedByIdempotencyKey(tripId, idempotencyKey, ownerId);
        if (existing.isPresent()) {
            PlanningTaskIdempotency.requireReplanMatch(existing.get(), request, objectMapper);
            return toResponse(existing.get());
        }
        ItineraryMapper.EditableCurrentVersion current = itineraryMapper
                .findCurrentVersionOwnedForEditForUpdate(tripId, ownerId)
                .orElseThrow(() -> new ApiException(
                        HttpStatus.NOT_FOUND, "ITINERARY_NOT_FOUND", "Itinerary was not found"
                ));
        if (request == null || request.baseVersionId() == null
                || !request.baseVersionId().equals(current.versionId())) {
            throw new ApiException(
                    HttpStatus.CONFLICT,
                    "ITINERARY_VERSION_CONFLICT",
                    "The itinerary was updated. Reload it before starting local replanning"
            );
        }
        List<LocalDate> dates = validateReplanDates(request.dates(), current.versionId());
        ItineraryService.ItineraryResponse itinerary = itineraryService.getCurrent(ownerId, tripId);
        Instant now = Instant.now();
        String constraintSnapshotJson = writeJson(trip.constraints());
        String impactedDatesJson = writeJson(dates);
        PlanningTaskRecord task = new PlanningTaskRecord(
                UUID.randomUUID(), tripId, idempotencyKey, REPLAN_TASK_TYPE, TASK_STATUS,
                trip.version(), current.versionId(), impactedDatesJson,
                constraintSnapshotJson, writeJson(new GuideEvidenceSnapshot(List.of())),
                UUID.randomUUID(), 0, null, null, 0, now, now
        );
        if (planningTaskMapper.insert(task) == 0) {
            return planningTaskMapper.findOwnedByIdempotencyKey(tripId, idempotencyKey, ownerId)
                    .map(existingTask -> {
                        PlanningTaskIdempotency.requireReplanMatch(
                                existingTask, request, objectMapper
                        );
                        return toResponse(existingTask);
                    })
                    .orElseThrow(() -> new ApiException(
                            HttpStatus.CONFLICT,
                            "PLANNING_TASK_ACTIVE",
                            "This trip already has an active planning task"
                    ));
        }
        metrics.taskCreated(task.taskType());
        if (planningTaskEventMapper.insert(new PlanningTaskEventRecord(
                null, UUID.randomUUID(), task.id(), "PLANNING_QUEUED", 1,
                writeJson(new TaskStatusPayload(TASK_STATUS)), now
        )) != 1) {
            throw new IllegalStateException("Could not persist planning queued event");
        }

        UUID eventId = UUID.randomUUID();
        ReplanItinerarySnapshot snapshot = toReplanSnapshot(itinerary);
        PlanningReplanCommand command = new PlanningReplanCommand(
                REPLAN_COMMAND_TYPE, 1, eventId, task.traceId(), task.id(), tripId, now,
                new PlanningReplanPayload(
                        REPLAN_TASK_TYPE, trip.version(), current.versionId(), idempotencyKey,
                        dates,
                        new TripSnapshot(
                                trip.title(), trip.destination(), trip.startDate(), trip.endDate(),
                                trip.status(), trip.version(), trip.constraints()
                        ),
                        snapshot,
                        itinerary.knowledge()
                )
        );
        outboxMapper.insert(new OutboxEventRecord(
                eventId, "PLANNING_TASK", task.id(), REPLAN_COMMAND_TYPE, REPLAN_ROUTING_KEY,
                writeJson(command), "PENDING", 0, now, null, now, null
        ));
        log.info("task queued: taskType=REPLAN");
        return toResponse(task);
    }

    @Transactional
    public PlanningTaskResponse createCandidateValidation(
            UUID ownerId,
            UUID tripId,
            UUID idempotencyKey,
            String candidateType,
            UUID baselineVersionId,
            UUID sourceVersionId,
            String requestHash,
            List<LocalDate> changedDates,
            ItineraryService.ItineraryResponse candidate
    ) {
        TripService.TripResponse trip = tripService.get(ownerId, tripId);
        List<LocalDate> canonicalChanged = validateCandidateDates(changedDates, trip);
        List<LocalDate> impacted = expandCandidateDates(canonicalChanged, trip);
        var existing = planningTaskMapper.findOwnedByIdempotencyKey(
                tripId, idempotencyKey, ownerId);
        if (existing.isPresent()) {
            PlanningTaskIdempotency.requireCandidateMatch(
                    existing.get(), candidateType, baselineVersionId, sourceVersionId,
                    requestHash, canonicalChanged, impacted, objectMapper);
            return toResponse(existing.get());
        }
        ItineraryMapper.EditableCurrentVersion current = itineraryMapper
                .findCurrentVersionOwnedForEditForUpdate(tripId, ownerId)
                .orElseThrow(() -> new ApiException(
                        HttpStatus.NOT_FOUND, "ITINERARY_NOT_FOUND", "Itinerary was not found"));
        if (!baselineVersionId.equals(current.versionId())) {
            throw new ApiException(HttpStatus.CONFLICT, "ITINERARY_VERSION_CONFLICT",
                    "The itinerary was updated. Reload it before validating this candidate");
        }
        if (planningTaskMapper.existsActiveByTripId(tripId)) {
            throw new ApiException(HttpStatus.CONFLICT, "PLANNING_TASK_ACTIVE",
                    "This trip already has an active planning task");
        }
        Instant now = Instant.now();
        List<GuideImportService.PlanningGuideFact> guideFacts =
                guideImportService.planningEvidence(ownerId, tripId, now);
        PlanningTaskRecord task = new PlanningTaskRecord(
                UUID.randomUUID(), tripId, idempotencyKey, candidateType + "_VALIDATE",
                TASK_STATUS, trip.version(), baselineVersionId, writeJson(impacted),
                writeJson(trip.constraints()), writeJson(new GuideEvidenceSnapshot(guideFacts)),
                UUID.randomUUID(), 0, null, null, 0, now, now,
                candidateType, sourceVersionId, requestHash, writeJson(canonicalChanged)
        );
        if (planningTaskMapper.insert(task) == 0) {
            return planningTaskMapper.findOwnedByIdempotencyKey(tripId, idempotencyKey, ownerId)
                    .map(found -> {
                        PlanningTaskIdempotency.requireCandidateMatch(
                                found, candidateType, baselineVersionId, sourceVersionId,
                                requestHash, canonicalChanged, impacted, objectMapper);
                        return toResponse(found);
                    })
                    .orElseThrow(() -> new ApiException(
                            HttpStatus.CONFLICT, "PLANNING_TASK_ACTIVE",
                            "This trip already has an active planning task"));
        }
        metrics.taskCreated(task.taskType());
        PlanningContextSnapshot context = planningContextSnapshotService.freeze(
                ownerId, task.id(), trip, guideFacts, now);
        if (planningTaskEventMapper.insert(new PlanningTaskEventRecord(
                null, UUID.randomUUID(), task.id(), "PLANNING_QUEUED", 1,
                writeJson(new TaskStatusPayload(TASK_STATUS)), now
        )) != 1) {
            throw new IllegalStateException("Could not persist candidate planning queued event");
        }
        UUID eventId = UUID.randomUUID();
        PlanningCandidateValidationCommand command = new PlanningCandidateValidationCommand(
                CANDIDATE_COMMAND_TYPE, 1, eventId, task.traceId(), task.id(), tripId, now,
                new PlanningCandidateValidationPayload(
                        task.taskType(), candidateType, trip.version(), baselineVersionId,
                        "ROLLBACK".equals(candidateType) ? sourceVersionId : null,
                        idempotencyKey, canonicalChanged, impacted,
                        new TripSnapshot(
                                trip.title(), trip.destination(), trip.startDate(), trip.endDate(),
                                trip.status(), trip.version(), trip.constraints()),
                        toReplanSnapshot(candidate), candidate.knowledge(), context
                )
        );
        if (outboxMapper.insert(new OutboxEventRecord(
                eventId, "PLANNING_TASK", task.id(), CANDIDATE_COMMAND_TYPE,
                CANDIDATE_ROUTING_KEY, writeJson(command), "PENDING", 0,
                now, null, now, null
        )) != 1) {
            throw new IllegalStateException("Could not persist candidate validation outbox event");
        }
        log.info("candidate queued: taskType={} candidateType={}",
                task.taskType(), candidateType);
        return toResponse(task);
    }

    private List<LocalDate> validateCandidateDates(
            List<LocalDate> dates, TripService.TripResponse trip) {
        if (dates == null || dates.isEmpty()) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY,
                    "ITINERARY_EDIT_INVALID", "Candidate changes must identify a trip date");
        }
        List<LocalDate> canonical = dates.stream().distinct().sorted().toList();
        if (canonical.size() != dates.size() || canonical.stream().anyMatch(date ->
                date.isBefore(trip.startDate()) || date.isAfter(trip.endDate()))) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY,
                    "ITINERARY_EDIT_INVALID", "Candidate dates must belong to the trip");
        }
        return canonical;
    }

    private List<LocalDate> expandCandidateDates(
            List<LocalDate> changed, TripService.TripResponse trip) {
        return changed.stream()
                .flatMap(date -> java.util.stream.Stream.of(
                        date.minusDays(1), date, date.plusDays(1)))
                .filter(date -> !date.isBefore(trip.startDate())
                        && !date.isAfter(trip.endDate()))
                .distinct().sorted().toList();
    }

    private List<LocalDate> validateReplanDates(List<LocalDate> requestedDates, UUID versionId) {
        if (requestedDates == null || requestedDates.isEmpty()) {
            throw invalidReplanScope("At least one itinerary date must be selected");
        }
        LinkedHashSet<LocalDate> dates = new LinkedHashSet<>(requestedDates);
        if (dates.size() != requestedDates.size()) {
            throw invalidReplanScope("Itinerary dates must not be repeated");
        }
        var availableDates = itineraryMapper.findDays(versionId).stream()
                .map(ItineraryMapper.StoredDay::date)
                .collect(java.util.stream.Collectors.toSet());
        if (!availableDates.containsAll(dates)) {
            throw invalidReplanScope("Every replanning date must belong to the current itinerary");
        }
        return dates.stream().sorted().toList();
    }

    private ApiException invalidReplanScope(String message) {
        return new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "ITINERARY_REPLAN_INVALID", message);
    }

    private ReplanItinerarySnapshot toReplanSnapshot(ItineraryService.ItineraryResponse itinerary) {
        List<ReplanDaySnapshot> days = itinerary.days().stream().map(day -> {
            Map<UUID, Integer> activityIndexes = new HashMap<>();
            List<ReplanActivitySnapshot> activities = new java.util.ArrayList<>();
            for (int index = 0; index < day.activities().size(); index++) {
                ItineraryService.ActivityResponse activity = day.activities().get(index);
                activityIndexes.put(activity.id(), index);
                activities.add(new ReplanActivitySnapshot(
                        activity.title(), activity.startTime(), activity.endTime(),
                        activity.estimatedCost(), activity.source(), activity.providerPoiId(),
                        activity.coordinates(), activity.address(), activity.typeCode(),
                        activity.typeName(), activity.kind(), activity.timeFixed(),
                        activity.locked()
                ));
            }
            List<ReplanTransitSnapshot> transitLegs = day.transitLegs().stream()
                    .map(leg -> new ReplanTransitSnapshot(
                            activityIndexes.get(leg.fromActivityId()),
                            activityIndexes.get(leg.toActivityId()), leg.mode(),
                            leg.distanceMeters(), leg.durationSeconds(), leg.provider(),
                            leg.estimated(), leg.polyline(), leg.locked()
                    ))
                    .toList();
            return new ReplanDaySnapshot(day.date(), activities, transitLegs, day.dayType());
        }).toList();
        return new ReplanItinerarySnapshot(
                itinerary.title(), planningProvider(itinerary), days,
                itinerary.estimatedTotalCost()
        );
    }

    private String planningProvider(ItineraryService.ItineraryResponse itinerary) {
        if ("MIXED".equals(itinerary.provider())) {
            return "MIXED";
        }
        return itinerary.days().stream()
                .flatMap(day -> day.activities().stream())
                .map(ItineraryService.ActivityResponse::source)
                .findFirst()
                .orElse(itinerary.provider());
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
        // B12: WAITING_USER review candidates are abandoned locally.  The
        // review outcome is already complete on the Python side, so the
        // abandonment only transitions the task, writes one terminal event
        // and notifies SSE subscribers — no cancel-command outbox, no
        // itinerary version, no feasibility report, no current-version
        // change.  QUEUED/RUNNING/CANCELLING keep the original cancel
        // semantics (with cancel-command outbox).
        boolean cancelledQueuedOrRunning = planningTaskMapper.cancelOwned(taskId, ownerId) == 1;
        boolean abandonedReview = false;
        if (!cancelledQueuedOrRunning) {
            abandonedReview = planningTaskMapper.abandonWaitingUserOwned(taskId, ownerId) == 1;
        }
        if (!cancelledQueuedOrRunning && !abandonedReview) {
            throw new ApiException(
                    HttpStatus.CONFLICT,
                    "PLANNING_TASK_TERMINAL",
                    "Completed or failed planning tasks cannot be cancelled"
            );
        }
        Instant now = Instant.now();
        metrics.taskFinished(existing.taskType(), "CANCELLED", java.time.Duration.between(existing.createdAt(), now));
        PlanningTaskEventRecord event = new PlanningTaskEventRecord(
                null, UUID.randomUUID(), taskId, "PLANNING_CANCELLED", 1,
                writeJson(new TaskStatusPayload("CANCELLED")), now
        );
        if (planningTaskEventMapper.insert(event) != 1) {
            throw new IllegalStateException("Could not persist planning cancelled event");
        }
        if (!abandonedReview) {
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
        }
        PlanningTaskEventRecord stored = planningTaskEventMapper.findByEventId(event.eventId())
                .orElseThrow(() -> new IllegalStateException("Cancelled event could not be read"));
        eventPublisher.publishEvent(new PlanningTaskEventCreated(stored));
        return planningTaskMapper.findOwnedById(taskId, ownerId)
                .map(this::toResponse)
                .orElseThrow(() -> new IllegalStateException("Cancelled task could not be read"));
    }

    private PlanningTaskResponse toResponse(PlanningTaskRecord task) {
        TerminalMetadata metadata = terminalMetadata(task);
        return new PlanningTaskResponse(
                task.id(), task.tripId(), task.taskType(), task.status(), task.baselineTripVersion(),
                task.baselineItineraryVersionId(), task.candidateType(),
                "/api/planning-tasks/" + task.id() + "/events",
                metadata.errorCode(), metadata.errorCategory(), metadata.provider(),
                metadata.operation(), metadata.retryable(), metadata.retryCount(),
                metadata.fallbackAttempted(), metadata.fallbackSucceeded(),
                metadata.safeMessage(), metadata.safeProviderCode(),
                metadata.requestedProviderMode(), metadata.primaryProvider(),
                metadata.actualProviders(), metadata.fallbackReason(),
                metadata.fallbackOperations(), metadata.evaluation(),
                metadata.feasibilityReport(), metadata.candidateItinerary(),
                task.createdAt(), task.updatedAt()
        );
    }

    private TerminalMetadata terminalMetadata(PlanningTaskRecord task) {
        return planningTaskEventMapper.findLatestOutcome(task.id())
                .map(event -> toTerminalMetadata(task, event))
                .orElseGet(() -> new TerminalMetadata(
                        task.errorCode(), null, null, null, null, null,
                        null, null, task.errorMessage(), null, null, null,
                        List.of(), null, List.of(), null, null, null
                ));
    }

    private TerminalMetadata toTerminalMetadata(
            PlanningTaskRecord task, PlanningTaskEventRecord event
    ) {
        PlanningTaskOutcomeReadModel.Outcome outcome = outcomeReadModel.read(task, event);
        String errorCategory = outcome.errorCategory() != null
                ? outcome.errorCategory() : legacyErrorCategory(outcome.errorCode());
        return new TerminalMetadata(
                outcome.errorCode(), errorCategory, outcome.provider(), outcome.operation(),
                outcome.retryable(), outcome.retryCount(), outcome.fallbackAttempted(),
                outcome.fallbackSucceeded(), outcome.safeMessage(), outcome.safeProviderCode(),
                outcome.requestedProviderMode(), outcome.primaryProvider(),
                outcome.actualProviders(), outcome.fallbackReason(),
                outcome.fallbackOperations(), outcome.evaluation(),
                outcome.feasibilityReport() == null ? null
                        : objectMapper.valueToTree(outcome.feasibilityReport()),
                outcome.candidateItinerary()
        );
    }

    private String legacyErrorCategory(String errorCode) {
        return "NO_FEASIBLE_ITINERARY".equals(errorCode)
                ? "PLANNING_INFEASIBLE" : null;
    }

    @Transactional(readOnly = true)
    public boolean hasActiveTask(UUID tripId) {
        return planningTaskMapper.existsActiveByTripId(tripId);
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
            UUID baselineItineraryVersionId,
            String candidateType,
            String eventStreamUrl,
            String errorCode,
            String errorCategory,
            String provider,
            String operation,
            Boolean retryable,
            Integer retryCount,
            Boolean fallbackAttempted,
            Boolean fallbackSucceeded,
            String safeMessage,
            String safeProviderCode,
            String requestedProviderMode,
            String primaryProvider,
            List<String> actualProviders,
            String fallbackReason,
            List<FallbackOperationResponse> fallbackOperations,
            PlanEvaluation evaluation,
            JsonNode feasibilityReport,
            JsonNode candidateItinerary,
            Instant createdAt,
            Instant updatedAt
    ) {
    }

    private record TerminalMetadata(
            String errorCode,
            String errorCategory,
            String provider,
            String operation,
            Boolean retryable,
            Integer retryCount,
            Boolean fallbackAttempted,
            Boolean fallbackSucceeded,
            String safeMessage,
            String safeProviderCode,
            String requestedProviderMode,
            String primaryProvider,
            List<String> actualProviders,
            String fallbackReason,
            List<FallbackOperationResponse> fallbackOperations,
            PlanEvaluation evaluation,
            JsonNode feasibilityReport,
            JsonNode candidateItinerary
    ) {
    }

    public record FallbackOperationResponse(
            String operation,
            UUID transitId,
            UUID fromActivityId,
            UUID toActivityId,
            String requestedMode,
            String actualProvider,
            String errorCategory,
            String errorCode,
            int retryCount
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
            GuideEvidenceSnapshot guideEvidence,
            PlanningContextSnapshot planningContext
    ) {
    }

    public record LocalReplanRequest(UUID baseVersionId, List<LocalDate> dates) {
    }

    private record PlanningReplanCommand(
            String eventType,
            int schemaVersion,
            UUID eventId,
            UUID traceId,
            UUID taskId,
            UUID tripId,
            Instant occurredAt,
            PlanningReplanPayload payload
    ) {
    }

    private record PlanningReplanPayload(
            String taskType,
            int baselineTripVersion,
            UUID baselineItineraryVersionId,
            UUID idempotencyKey,
            List<LocalDate> impactedDates,
            TripSnapshot trip,
            ReplanItinerarySnapshot itinerary,
            ItineraryService.KnowledgeResponse knowledge
    ) {
    }

    private record PlanningCandidateValidationCommand(
            String eventType,
            int schemaVersion,
            UUID eventId,
            UUID traceId,
            UUID taskId,
            UUID tripId,
            Instant occurredAt,
            PlanningCandidateValidationPayload payload
    ) {
    }

    private record PlanningCandidateValidationPayload(
            String taskType,
            String candidateType,
            int baselineTripVersion,
            UUID baselineItineraryVersionId,
            UUID rollbackFromVersionId,
            UUID idempotencyKey,
            List<LocalDate> changedDates,
            List<LocalDate> impactedDates,
            TripSnapshot trip,
            ReplanItinerarySnapshot itinerary,
            ItineraryService.KnowledgeResponse knowledge,
            PlanningContextSnapshot planningContext
    ) {
    }

    private record ReplanItinerarySnapshot(
            String title,
            String provider,
            List<ReplanDaySnapshot> days,
            java.math.BigDecimal estimatedTotalCost
    ) {
    }

    private record ReplanDaySnapshot(
            LocalDate date,
            List<ReplanActivitySnapshot> activities,
            List<ReplanTransitSnapshot> transitLegs,
            String dayType
    ) {
    }

    private record ReplanActivitySnapshot(
            String title,
            java.time.OffsetDateTime startTime,
            java.time.OffsetDateTime endTime,
            java.math.BigDecimal estimatedCost,
            String source,
            String providerPoiId,
            ItineraryService.CoordinatesResponse coordinates,
            String address,
            String typeCode,
            String typeName,
            String kind,
            boolean timeFixed,
            boolean locked
    ) {
    }

    private record ReplanTransitSnapshot(
            int fromActivityIndex,
            int toActivityIndex,
            String mode,
            int distanceMeters,
            int durationSeconds,
            String provider,
            boolean estimated,
            List<ItineraryService.CoordinatesResponse> polyline,
            boolean locked
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
