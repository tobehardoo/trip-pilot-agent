package io.github.tobehardoo.trippilot.itinerary;

import java.math.BigDecimal;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningCompletedEvent;
import io.github.tobehardoo.trippilot.planning.PlanningEventRejectedException;
import io.github.tobehardoo.trippilot.planning.PlanningFactImpactMapper;
import io.github.tobehardoo.trippilot.planning.PlanningTaskCompletionRecord;
import io.github.tobehardoo.trippilot.planning.PlanningTaskService;
import org.springframework.context.annotation.Lazy;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ItineraryService {

    private static final String TRANSIT_REFRESH_WARNING =
            "Transit routes for impacted days will be refreshed by local replanning";
    private static final String PLANNING_ACTIVE_MESSAGE =
            "Itinerary editing is temporarily unavailable while planning is running";

    private final ItineraryMapper itineraryMapper;
    private final ItineraryVersionPersister versionPersister;
    private final ObjectMapper objectMapper;
    private final PlanningTaskService planningTaskService;
    private final PlanningFactImpactMapper factImpactMapper;

    public ItineraryService(
            ItineraryMapper itineraryMapper,
            ItineraryVersionPersister versionPersister,
            ObjectMapper objectMapper,
            @Lazy PlanningTaskService planningTaskService,
            PlanningFactImpactMapper factImpactMapper
    ) {
        this.itineraryMapper = itineraryMapper;
        this.versionPersister = versionPersister;
        this.objectMapper = objectMapper;
        this.planningTaskService = planningTaskService;
        this.factImpactMapper = factImpactMapper;
    }

    @Transactional(readOnly = true)
    public ItineraryResponse getCurrent(UUID ownerId, UUID tripId) {
        ItineraryMapper.CurrentVersion version = itineraryMapper.findCurrentVersionOwned(tripId, ownerId)
                .orElseThrow(this::itineraryNotFound);
        return toItineraryResponse(version);
    }

    @Transactional(readOnly = true)
    public ItineraryResponse getVersion(UUID ownerId, UUID tripId, UUID versionId) {
        ItineraryMapper.CurrentVersion version = itineraryMapper
                .findVersionOwned(tripId, versionId, ownerId)
                .orElseThrow(this::itineraryNotFound);
        return toItineraryResponse(version);
    }

    /**
     * Resolves a version only after a caller has independently authorized public sharing.
     * This method intentionally has no controller exposure so ownership checks cannot be bypassed.
     */
    @Transactional(readOnly = true)
    public ItineraryResponse getVersionForAuthorizedShare(UUID versionId) {
        ItineraryMapper.StoredVersion version = itineraryMapper.findVersion(versionId)
                .orElseThrow(this::itineraryNotFound);
        return toItineraryResponse(new ItineraryMapper.CurrentVersion(
                version.id(), version.versionNumber(), version.parentVersionId(), version.title(),
                version.estimatedTotalCost(), version.provider(),
                version.accommodationStatus(), version.accommodationLabel(),
                version.createdAt(), null
        ));
    }

    @Transactional(readOnly = true)
    public ItineraryEditPreviewResponse previewEdit(
            UUID ownerId, UUID tripId, ItineraryEditRequest request) {
        ItineraryMapper.EditableCurrentVersion version = itineraryMapper.findCurrentVersionOwnedForEdit(tripId, ownerId)
                .orElseThrow(this::itineraryNotFound);
        if (request == null || request.baseVersionId() == null || !request.baseVersionId().equals(version.versionId())) {
            return blockedPreview(request, "ITINERARY_VERSION_CONFLICT",
                    "The itinerary was updated. Reload it before applying this edit");
        }
        if (planningTaskService.hasActiveTask(tripId)) {
            return blockedPreview(request, "ITINERARY_PLANNING_ACTIVE", PLANNING_ACTIVE_MESSAGE);
        }
        EditableItinerary itinerary = readEditableItinerary(version.versionId());
        EditEvaluation evaluation = evaluate(itinerary, request, budgetFrom(version.constraintSnapshotJson()));
        return evaluation.toPreview(request.operation());
    }

    @Transactional
    public ItineraryResponse applyEdit(
            UUID ownerId, UUID tripId, UUID idempotencyKey, ItineraryEditRequest request,
            String requestHash) {
        ItineraryResponse previousResult = existingEditResult(ownerId, tripId, idempotencyKey, requestHash);
        if (previousResult != null) {
            return previousResult;
        }
        if (itineraryMapper.reserveEditIdempotency(tripId, idempotencyKey, requestHash) == 0) {
            return requiredExistingEditResult(ownerId, tripId, idempotencyKey, requestHash);
        }

        ItineraryMapper.EditableCurrentVersion version = lockCurrentVersionForEdit(ownerId, tripId);
        if (request == null || request.baseVersionId() == null || !request.baseVersionId().equals(version.versionId())) {
            throw new ApiException(HttpStatus.CONFLICT, "ITINERARY_VERSION_CONFLICT",
                    "The itinerary was updated. Reload it before applying this edit");
        }
        if (planningTaskService.hasActiveTask(tripId)) {
            throw new ApiException(HttpStatus.CONFLICT, "ITINERARY_PLANNING_ACTIVE", PLANNING_ACTIVE_MESSAGE);
        }

        EditableItinerary itinerary = readEditableItinerary(version.versionId());
        EditEvaluation evaluation = evaluate(itinerary, request, budgetFrom(version.constraintSnapshotJson()));
        if (!evaluation.canApply()) {
            throw evaluation.toApiException();
        }

        apply(itinerary, request, evaluation.operation());
        UUID resultVersionId = persistEditedVersion(version, itinerary);
        requireOne(itineraryMapper.completeEditIdempotency(
                tripId, idempotencyKey, requestHash, resultVersionId), "itinerary edit idempotency");
        return getVersion(ownerId, tripId, resultVersionId);
    }

    /**
     * F1: apply a batch of edits strictly in order against the current draft
     * and return the resulting candidate view WITHOUT persisting anything.
     * Lets the routing coordinator resolve a later AUTO edit against the
     * itinerary as edited by the preceding edits (moved activities shift the
     * OD and departure time the recommendation sees), instead of against the
     * untouched baseline.
     */
    @Transactional
    public ItineraryResponse simulateEdits(
            UUID ownerId, UUID tripId, UUID baseVersionId,
            List<ItineraryEditRequest> edits) {
        ItineraryMapper.EditableCurrentVersion version = lockCurrentVersionForEdit(ownerId, tripId);
        if (baseVersionId == null || !baseVersionId.equals(version.versionId())) {
            throw new ApiException(HttpStatus.CONFLICT, "ITINERARY_VERSION_CONFLICT",
                    "The itinerary draft does not match the current version");
        }
        EditableItinerary itinerary = readEditableItinerary(version.versionId());
        for (ItineraryEditRequest edit : edits) {
            if (edit == null || !baseVersionId.equals(edit.baseVersionId())) {
                throw new ApiException(HttpStatus.CONFLICT, "ITINERARY_VERSION_CONFLICT",
                        "The itinerary draft does not match the current version");
            }
            EditEvaluation evaluation = evaluate(
                    itinerary, edit, budgetFrom(version.constraintSnapshotJson()));
            if (!evaluation.canApply()) {
                throw evaluation.toApiException();
            }
            apply(itinerary, edit, evaluation.operation());
        }
        return toCandidateResponse(version, itinerary);
    }

    /**
     * Builds an immutable edit candidate and submits it to the authoritative
     * planning validation gate. No itinerary version is written here.
     */
    @Transactional
    public PlanningTaskService.PlanningTaskResponse validateEditCandidate(
            UUID ownerId, UUID tripId, UUID idempotencyKey,
            ItineraryEditRequest request, String requestHash
    ) {
        if (request != null && request.baseVersionId() != null) {
            java.util.Optional<PlanningTaskService.PlanningTaskResponse> replay =
                    planningTaskService.replayCandidateValidation(
                            ownerId, tripId, idempotencyKey, "EDIT",
                            request.baseVersionId(), request.baseVersionId(), requestHash);
            if (replay.isPresent()) {
                return replay.get();
            }
        }
        ItineraryMapper.EditableCurrentVersion version = lockCurrentVersionForEdit(ownerId, tripId);
        if (request == null || request.baseVersionId() == null
                || !request.baseVersionId().equals(version.versionId())) {
            throw new ApiException(HttpStatus.CONFLICT, "ITINERARY_VERSION_CONFLICT",
                    "The itinerary was updated. Reload it before applying this edit");
        }
        EditableItinerary itinerary = readEditableItinerary(version.versionId());
        EditEvaluation evaluation = evaluate(itinerary, request, budgetFrom(version.constraintSnapshotJson()));
        if (!evaluation.canApply()) {
            throw evaluation.toApiException();
        }
        apply(itinerary, request, evaluation.operation());
        ItineraryResponse candidate = toCandidateResponse(version, itinerary);
        return planningTaskService.createCandidateValidation(
                ownerId, tripId, idempotencyKey, "EDIT", version.versionId(),
                version.versionId(), requestHash, evaluation.impact().dates(), candidate
        );
    }

    @Transactional
    public PlanningTaskService.PlanningTaskResponse validateEditCandidates(
            UUID ownerId, UUID tripId, UUID idempotencyKey,
            ItineraryBatchEditRequest request, String requestHash
    ) {
        if (request != null && request.baseVersionId() != null) {
            java.util.Optional<PlanningTaskService.PlanningTaskResponse> replay =
                    planningTaskService.replayCandidateValidation(
                            ownerId, tripId, idempotencyKey, "EDIT",
                            request.baseVersionId(), request.baseVersionId(), requestHash);
            if (replay.isPresent()) {
                return replay.get();
            }
        }
        ItineraryMapper.EditableCurrentVersion version = lockCurrentVersionForEdit(ownerId, tripId);
        if (request == null || request.baseVersionId() == null
                || !request.baseVersionId().equals(version.versionId())) {
            throw new ApiException(HttpStatus.CONFLICT, "ITINERARY_VERSION_CONFLICT",
                    "The itinerary draft does not match the current version");
        }
        if (request.edits() == null || request.edits().isEmpty()) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "ITINERARY_EDIT_EMPTY",
                    "At least one itinerary edit is required");
        }
        EditableItinerary itinerary = readEditableItinerary(version.versionId());
        LinkedHashSet<LocalDate> changedDates = new LinkedHashSet<>();
        for (ItineraryEditRequest edit : request.edits()) {
            if (edit == null || !version.versionId().equals(edit.baseVersionId())) {
                throw new ApiException(HttpStatus.CONFLICT, "ITINERARY_VERSION_CONFLICT",
                        "The itinerary draft does not match the current version");
            }
            EditEvaluation evaluation = evaluate(
                    itinerary, edit, budgetFrom(version.constraintSnapshotJson()));
            if (!evaluation.canApply()) {
                throw evaluation.toApiException();
            }
            changedDates.addAll(evaluation.impact().dates());
            apply(itinerary, edit, evaluation.operation());
        }
        ItineraryResponse candidate = toCandidateResponse(version, itinerary);
        return planningTaskService.createCandidateValidation(
                ownerId, tripId, idempotencyKey, "EDIT", version.versionId(),
                version.versionId(), requestHash, List.copyOf(changedDates),
                candidate);
    }

    /** Commits a user-reviewed draft as one immutable version. */
    @Transactional
    public ItineraryResponse applyEdits(
            UUID ownerId, UUID tripId, UUID idempotencyKey,
            ItineraryBatchEditRequest request, String requestHash) {
        ItineraryResponse previousResult = existingEditResult(ownerId, tripId, idempotencyKey, requestHash);
        if (previousResult != null) {
            return previousResult;
        }
        if (itineraryMapper.reserveEditIdempotency(tripId, idempotencyKey, requestHash) == 0) {
            return requiredExistingEditResult(ownerId, tripId, idempotencyKey, requestHash);
        }
        ItineraryMapper.EditableCurrentVersion version = lockCurrentVersionForEdit(ownerId, tripId);
        if (request == null || request.baseVersionId() == null
                || !request.baseVersionId().equals(version.versionId())) {
            throw new ApiException(HttpStatus.CONFLICT, "ITINERARY_VERSION_CONFLICT",
                    "The itinerary was updated. Reload it before saving this draft");
        }
        if (request.edits() == null || request.edits().isEmpty()) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "ITINERARY_EDIT_EMPTY",
                    "At least one itinerary edit is required");
        }
        if (planningTaskService.hasActiveTask(tripId)) {
            throw new ApiException(HttpStatus.CONFLICT, "ITINERARY_PLANNING_ACTIVE", PLANNING_ACTIVE_MESSAGE);
        }
        EditableItinerary itinerary = readEditableItinerary(version.versionId());
        for (ItineraryEditRequest edit : request.edits()) {
            if (edit == null || edit.baseVersionId() == null
                    || !edit.baseVersionId().equals(version.versionId())) {
                throw new ApiException(HttpStatus.CONFLICT, "ITINERARY_VERSION_CONFLICT",
                        "The itinerary draft does not match the current version");
            }
            EditEvaluation evaluation = evaluate(itinerary, edit, budgetFrom(version.constraintSnapshotJson()));
            if (!evaluation.canApply()) {
                throw evaluation.toApiException();
            }
            apply(itinerary, edit, evaluation.operation());
        }
        UUID resultVersionId = persistEditedVersion(version, itinerary);
        requireOne(itineraryMapper.completeEditIdempotency(
                tripId, idempotencyKey, requestHash, resultVersionId), "itinerary edit idempotency");
        return getVersion(ownerId, tripId, resultVersionId);
    }

    private ItineraryResponse existingEditResult(
            UUID ownerId, UUID tripId, UUID idempotencyKey, String requestHash) {
        ItineraryMapper.EditIdempotencyRecord record =
                itineraryMapper.findEditIdempotency(tripId, idempotencyKey);
        if (record == null) {
            return null;
        }
        return resolveEditIdempotency(ownerId, tripId, idempotencyKey, requestHash, record);
    }

    private ItineraryResponse requiredExistingEditResult(
            UUID ownerId, UUID tripId, UUID idempotencyKey, String requestHash) {
        ItineraryMapper.EditIdempotencyRecord record =
                itineraryMapper.findEditIdempotency(tripId, idempotencyKey);
        if (record == null) {
            throw new IllegalStateException("Itinerary edit idempotency record disappeared");
        }
        return resolveEditIdempotency(ownerId, tripId, idempotencyKey, requestHash, record);
    }

    private ItineraryResponse resolveEditIdempotency(
            UUID ownerId, UUID tripId, UUID idempotencyKey, String requestHash,
            ItineraryMapper.EditIdempotencyRecord record) {
        if (record.requestHash() == null || record.requestHash().strip().isEmpty()
                || !record.requestHash().equals(requestHash)) {
            throw idempotencyConflict();
        }
        if (!"COMPLETED".equals(record.status()) || record.resultVersionId() == null) {
            throw idempotencyConflict();
        }
        return getVersion(ownerId, tripId, record.resultVersionId());
    }

    private ApiException idempotencyConflict() {
        return new ApiException(HttpStatus.CONFLICT, "IDEMPOTENCY_KEY_CONFLICT",
                "Idempotency-Key was already used for a different or indeterminate itinerary edit");
    }

    private ItineraryMapper.EditableCurrentVersion lockCurrentVersionForEdit(UUID ownerId, UUID tripId) {
        ItineraryMapper.EditableCurrentVersion version = itineraryMapper
                .findCurrentVersionOwnedForEditForUpdate(tripId, ownerId)
                .orElse(null);
        if (version != null) {
            return version;
        }
        if (itineraryMapper.findCurrentVersionOwned(tripId, ownerId).isPresent()) {
            throw new ApiException(HttpStatus.CONFLICT, "ITINERARY_VERSION_CONFLICT",
                    "The itinerary was updated. Reload it before applying this edit");
        }
        throw itineraryNotFound();
    }

    private ItineraryEditPreviewResponse blockedPreview(
            ItineraryEditRequest request, String code, String message) {
        return new ItineraryEditPreviewResponse(
                request == null ? null : request.operation(), false, false, null,
                List.of(), List.of(), List.of(),
                List.of(new EditBlockingReason(code, message))
        );
    }

    private ItineraryResponse toItineraryResponse(ItineraryMapper.CurrentVersion version) {
        List<DayResponse> days = itineraryMapper.findDays(version.id()).stream()
                .map(day -> new DayResponse(
                        day.date(),
                        itineraryMapper.findActivities(day.id()).stream()
                                .map(this::toActivityResponse)
                                .toList(),
                        itineraryMapper.findTransitLegs(day.id()).stream()
                                .map(this::toTransitLegResponse)
                                .toList(),
                        day.dayType()
                ))
                .toList();
        return new ItineraryResponse(
                version.id(), version.versionNumber(), version.parentVersionId(), version.title(),
                humanVisibleTotalCost(version.estimatedTotalCost(), days),
                responseProvider(version.provider(), days), days,
                toKnowledgeResponse(version.id()),
                factImpactMapper.findByVersion(version.id()).stream()
                        .map(impact -> new FactImpactResponse(
                                impact.factId(), impact.category(),
                                impact.applicableDate(), impact.effect(),
                                impact.targetPoiId(), impact.targetName(), impact.reason(),
                                impact.sourceName(), impact.sourceType(),
                                impact.sourceUrl(), impact.reliabilityLevel(),
                                impact.checkedAt(), impact.evidence(), impact.stale(),
                                impact.conflicted(), impact.refreshFailed()
                        ))
                        .toList(),
                version.accommodationStatus(), version.accommodationLabel(),
                version.createdAt(), version.rollbackFromVersionId()
        );
    }

    private String responseProvider(String storedProvider, List<DayResponse> days) {
        Set<String> providers = new HashSet<>();
        providers.add(storedProvider);
        days.forEach(day -> {
            day.activities().forEach(activity -> providers.add(activity.source()));
            day.transitLegs().forEach(leg -> providers.add(leg.provider()));
        });
        return providers.contains("AMAP") && providers.contains("DEMO")
                ? "MIXED" : storedProvider;
    }

    private static BigDecimal humanVisibleTotalCost(
            BigDecimal storedTotal,
            List<DayResponse> days
    ) {
        BigDecimal roadTolls = days.stream()
                .flatMap(day -> day.transitLegs().stream())
                .filter(leg -> "DRIVING".equals(leg.mode()))
                .map(TransitLegResponse::estimatedCost)
                .filter(java.util.Objects::nonNull)
                .reduce(BigDecimal.ZERO, BigDecimal::add);
        return storedTotal.subtract(roadTolls).max(BigDecimal.ZERO);
    }

    private EditableItinerary readEditableItinerary(UUID versionId) {
        List<EditableDay> days = itineraryMapper.findDays(versionId).stream()
                .map(day -> new EditableDay(
                        day.date(),
                        new ArrayList<>(itineraryMapper.findActivities(day.id()).stream()
                                .map(this::toEditableActivity)
                                .toList()),
                        new ArrayList<>(itineraryMapper.findTransitLegs(day.id())),
                        day.dayType()
                ))
                .toList();
        return new EditableItinerary(days);
    }

    private EditableActivity toEditableActivity(ItineraryMapper.StoredActivity activity) {
        return new EditableActivity(
                activity.id(), activity.title(), activity.startTime(), activity.endTime(),
                activity.estimatedCost(), activity.source(), activity.providerPoiId(),
                activity.longitude(), activity.latitude(), activity.address(), activity.locked(),
                activity.typeCode(), activity.typeName(), activity.kind(), activity.timeFixed()
        );
    }

    private EditEvaluation evaluate(
            EditableItinerary itinerary,
            ItineraryEditRequest request,
            BigDecimal budgetAmount
    ) {
        EditOperation operation = EditOperation.from(request.operation());
        if (operation == null) {
            return EditEvaluation.blocked("ITINERARY_EDIT_INVALID", "The edit operation is not supported");
        }
        if (operation == EditOperation.UPDATE_TRANSIT_LEG) {
            return evaluateTransitLeg(itinerary, request, budgetAmount);
        }
        if (request.activityId() == null) {
            return EditEvaluation.blocked("ITINERARY_ACTIVITY_NOT_FOUND", "An activity must be selected");
        }
        ActivityLocation location = itinerary.findActivity(request.activityId());
        if (location == null) {
            return EditEvaluation.blocked("ITINERARY_ACTIVITY_NOT_FOUND", "The selected activity is not in this itinerary");
        }

        return switch (operation) {
            case DELETE_ACTIVITY -> evaluateDelete(location);
            case LOCK_ACTIVITY, UNLOCK_ACTIVITY -> EditEvaluation.allowed(
                    operation, impacted(location.day(), List.of(location.activity().id()), false)
            );
            case MOVE_ACTIVITY -> evaluateMove(itinerary, request, location);
            case UPDATE_TRANSIT_LEG -> throw new IllegalStateException("Transit leg edits are evaluated separately");
        };
    }

    private EditEvaluation evaluateTransitLeg(
            EditableItinerary itinerary,
            ItineraryEditRequest request,
            BigDecimal budgetAmount
    ) {
        if (request.transitLegId() == null) {
            return EditEvaluation.blocked("ITINERARY_TRANSIT_LEG_NOT_FOUND", "A transit leg must be selected");
        }
        TransitLocation location = itinerary.findTransitLeg(request.transitLegId());
        if (location == null) {
            return EditEvaluation.blocked("ITINERARY_TRANSIT_LEG_NOT_FOUND",
                    "The selected transit leg is not in this itinerary");
        }
        if (request.transitMode() == null && request.transitLocked() == null) {
            return EditEvaluation.blocked("ITINERARY_EDIT_INVALID",
                    "A transit mode or lock state is required");
        }
        if (request.transitMode() != null
                && !List.of("WALKING", "TRANSIT", "TAXI", "AUTO")
                        .contains(request.transitMode())) {
            return EditEvaluation.blocked("ITINERARY_EDIT_INVALID",
                    "The selected transit mode is not supported");
        }
        if ("DRIVING".equals(request.transitMode())) {
            // F8: DRIVING is a technical route mode (persisted DRIVING is
            // shown as TAXI).  Preview must reject it exactly like commit.
            return EditEvaluation.blocked("ITINERARY_EDIT_INVALID",
                    "DRIVING is a technical route mode; select TAXI for a road journey");
        }
        if (location.leg().locked() && request.transitMode() != null
                && !request.transitMode().equals(location.leg().mode())) {
            return EditEvaluation.blocked("ITINERARY_TRANSIT_LEG_LOCKED",
                    "A locked transit leg cannot change its mode");
        }
        // The candidate worker validates mode changes against refreshed
        // provider facts. The legacy speed/cost estimates below are only a
        // transient snapshot placeholder and must not veto AUTO or real
        // provider decisions before that validation runs.
        return EditEvaluation.allowed(
                EditOperation.UPDATE_TRANSIT_LEG,
                impacted(location.day(), List.of(location.leg().fromActivityId(), location.leg().toActivityId()), false)
        );
    }

    private EditEvaluation evaluateDelete(ActivityLocation source) {
        if (source.activity().locked()) {
            return EditEvaluation.blocked("ITINERARY_ACTIVITY_LOCKED", "A locked activity cannot be deleted");
        }
        return EditEvaluation.allowed(
                EditOperation.DELETE_ACTIVITY,
                impacted(source.day(), List.of(source.activity().id()), true)
        );
    }

    private EditEvaluation evaluateMove(
            EditableItinerary itinerary, ItineraryEditRequest request, ActivityLocation source) {
        if (source.activity().locked()) {
            return EditEvaluation.blocked("ITINERARY_ACTIVITY_LOCKED", "A locked activity cannot be moved");
        }
        if (request.targetDate() == null || request.targetOrder() == null
                || request.targetStartTime() == null || request.targetEndTime() == null) {
            return EditEvaluation.blocked("ITINERARY_EDIT_INVALID",
                    "Moving an activity requires a target date, order, start time, and end time");
        }
        EditableDay target = itinerary.findDay(request.targetDate());
        if (target == null) {
            return EditEvaluation.blocked("ITINERARY_EDIT_OUT_OF_BOUNDS",
                    "The target date is outside the itinerary");
        }
        LocalDate targetStartDate = request.targetStartTime()
                .withOffsetSameInstant(ZoneOffset.ofHours(8)).toLocalDate();
        LocalDate targetEndDate = request.targetEndTime()
                .withOffsetSameInstant(ZoneOffset.ofHours(8)).toLocalDate();
        if (!request.targetDate().equals(targetStartDate)
                || !request.targetDate().equals(targetEndDate)
                || !request.targetEndTime().isAfter(request.targetStartTime())) {
            return EditEvaluation.blocked("ITINERARY_EDIT_INVALID",
                    "The activity time must be valid and remain within its target date");
        }
        int targetSizeAfterRemoval = target.activities().size()
                - (target == source.day() ? 1 : 0);
        if (request.targetOrder() < 0 || request.targetOrder() > targetSizeAfterRemoval) {
            return EditEvaluation.blocked("ITINERARY_EDIT_OUT_OF_BOUNDS",
                    "The target order is outside the itinerary day");
        }
        boolean overlaps = target.activities().stream()
                .filter(activity -> !activity.id().equals(source.activity().id()))
                .anyMatch(activity -> overlaps(
                        request.targetStartTime(), request.targetEndTime(),
                        activity.startTime(), activity.endTime()
                ));
        if (overlaps) {
            return EditEvaluation.blocked("ITINERARY_ACTIVITY_CONFLICT",
                    "The target time overlaps another activity");
        }
        LinkedHashSet<UUID> impactedIds = new LinkedHashSet<>();
        source.day().activities().forEach(activity -> impactedIds.add(activity.id()));
        target.activities().forEach(activity -> impactedIds.add(activity.id()));
        return EditEvaluation.allowed(
                EditOperation.MOVE_ACTIVITY,
                impacted(List.of(source.day(), target), new ArrayList<>(impactedIds), true)
        );
    }

    private boolean overlaps(
            OffsetDateTime start, OffsetDateTime end, OffsetDateTime otherStart, OffsetDateTime otherEnd) {
        return start.isBefore(otherEnd) && end.isAfter(otherStart);
    }

    private EditImpact impacted(EditableDay day, List<UUID> ids, boolean refreshTransit) {
        return impacted(List.of(day), ids, refreshTransit);
    }

    private EditImpact impacted(List<EditableDay> days, List<UUID> ids, boolean refreshTransit) {
        List<LocalDate> dates = days.stream().map(EditableDay::date).distinct().toList();
        return new EditImpact(
                dates, ids, refreshTransit ? List.of(TRANSIT_REFRESH_WARNING) : List.of()
        );
    }

    private void apply(EditableItinerary itinerary, ItineraryEditRequest request, EditOperation operation) {
        if (operation == EditOperation.UPDATE_TRANSIT_LEG) {
            TransitLocation location = itinerary.findTransitLeg(request.transitLegId());
            if (location == null) {
                throw new IllegalStateException("Validated transit leg was not found");
            }
            ItineraryMapper.StoredTransitLeg leg = location.leg();
            location.day().transitLegs().set(
                    location.index(),
                    applyTransitLegEdit(leg, request.transitMode(), request.transitLocked())
            );
            return;
        }
        ActivityLocation source = itinerary.findActivity(request.activityId());
        if (source == null) {
            throw new IllegalStateException("Validated activity was not found");
        }
        switch (operation) {
            case DELETE_ACTIVITY -> {
                source.day().activities().remove(source.index());
                source.day().transitNeedsRefresh = true;
            }
            case LOCK_ACTIVITY -> source.day().activities().set(
                    source.index(), source.activity().withLocked(true)
            );
            case UNLOCK_ACTIVITY -> source.day().activities().set(
                    source.index(), source.activity().withLocked(false)
            );
            case MOVE_ACTIVITY -> {
                EditableDay target = itinerary.findDay(request.targetDate());
                source.day().activities().remove(source.index());
                EditableActivity moved = source.activity().withSchedule(
                        request.targetStartTime(), request.targetEndTime()
                );
                target.activities().add(request.targetOrder(), moved);
                source.day().transitNeedsRefresh = true;
                target.transitNeedsRefresh = true;
            }
        }
    }

    static ItineraryMapper.StoredTransitLeg applyTransitLegEdit(
            ItineraryMapper.StoredTransitLeg leg,
            String requestedMode,
            Boolean requestedLocked) {
        String mode = requestedMode == null ? leg.mode() : requestedMode;
        boolean locked = requestedLocked == null ? leg.locked() : requestedLocked;
        if (mode.equals(leg.mode())) {
            return new ItineraryMapper.StoredTransitLeg(
                    leg.id(), leg.legOrder(), leg.fromActivityId(), leg.toActivityId(),
                    leg.mode(), leg.distanceMeters(), leg.durationSeconds(), leg.provider(),
                    leg.estimated(), leg.polylineJson(), locked, leg.estimatedCost(),
                    leg.providerRouteId(), leg.calculatedAt(), leg.stale()
            );
        }
        return new ItineraryMapper.StoredTransitLeg(
                leg.id(), leg.legOrder(), leg.fromActivityId(), leg.toActivityId(),
                mode, leg.distanceMeters(), estimatedTransitDuration(mode, leg.distanceMeters()),
                "DEMO", true, "[]", locked,
                estimatedTransitCost(mode, leg.distanceMeters()), null, Instant.now(), false
        );
    }

    private static int estimatedTransitDuration(String mode, int distanceMeters) {
        double seconds = switch (mode) {
            case "WALKING" -> distanceMeters / 1.25;
            case "TRANSIT" -> distanceMeters / 5.5 + 420;
            case "DRIVING" -> distanceMeters / 8.33 + 180;
            case "TAXI" -> distanceMeters / 8.33 + 300;
            default -> throw new IllegalArgumentException("Unsupported transit mode: " + mode);
        };
        return Math.max(60, (int) Math.round(seconds / 60) * 60);
    }

    private static BigDecimal estimatedTransitCost(String mode, int distanceMeters) {
        double kilometers = Math.max(1, distanceMeters) / 1_000D;
        double cost = switch (mode) {
            case "WALKING" -> 0D;
            case "TRANSIT" -> 2D + Math.floor(kilometers / 6D);
            case "DRIVING" -> Math.max(3D, kilometers * 0.8D);
            case "TAXI" -> 12D + kilometers * 2.6D;
            default -> throw new IllegalArgumentException("Unsupported transit mode: " + mode);
        };
        return BigDecimal.valueOf(cost).setScale(2, java.math.RoundingMode.HALF_UP);
    }

    private BigDecimal budgetFrom(String constraintSnapshotJson) {
        try {
            var budget = objectMapper.readTree(constraintSnapshotJson).get("budgetAmount");
            return budget == null || budget.isNull() ? null : budget.decimalValue();
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Could not read itinerary budget snapshot", exception);
        }
    }

    private UUID persistEditedVersion(
            ItineraryMapper.EditableCurrentVersion sourceVersion, EditableItinerary itinerary) {
        UUID versionId = UUID.randomUUID();
        BigDecimal totalCost = itinerary.days().stream()
                .flatMap(day -> day.activities().stream())
                .map(EditableActivity::estimatedCost)
                .reduce(BigDecimal.ZERO, BigDecimal::add)
                .add(itinerary.days().stream()
                        .flatMap(day -> day.transitLegs().stream())
                        .map(leg -> leg.estimatedCost() == null
                                ? BigDecimal.ZERO : leg.estimatedCost())
                        .reduce(BigDecimal.ZERO, BigDecimal::add));
        requireOne(itineraryMapper.insertVersion(new ItineraryMapper.VersionWrite(
                versionId, sourceVersion.itineraryId(), sourceVersion.versionNumber() + 1,
                sourceVersion.versionId(), null, "USER_EDIT", sourceVersion.title(), totalCost,
                sourceVersion.provider(), sourceVersion.constraintSnapshotJson(),
                sourceVersion.accommodationStatus(), sourceVersion.accommodationLabel(),
                Instant.now()
        )), "itinerary edit version");
        versionPersister.copyKnowledge(sourceVersion.versionId(), versionId, "itinerary edit knowledge");
        factImpactMapper.copyToVersion(sourceVersion.versionId(), versionId);

        for (int dayIndex = 0; dayIndex < itinerary.days().size(); dayIndex++) {
            EditableDay day = itinerary.days().get(dayIndex);
            UUID newDayId = UUID.randomUUID();
            requireOne(itineraryMapper.insertDay(new ItineraryMapper.DayWrite(
                    newDayId, versionId, day.date(), dayIndex, day.dayType()
            )), "itinerary edit day");
            Map<UUID, UUID> activityIds = new HashMap<>();
            for (int activityIndex = 0; activityIndex < day.activities().size(); activityIndex++) {
                EditableActivity activity = day.activities().get(activityIndex);
                UUID newActivityId = UUID.randomUUID();
                activityIds.put(activity.id(), newActivityId);
                requireOne(itineraryMapper.insertActivity(new ItineraryMapper.ActivityWrite(
                    newActivityId, newDayId, activityIndex, activity.title(), activity.startTime(),
                        activity.endTime(), activity.estimatedCost(), activity.source(), activity.providerPoiId(),
                        activity.longitude(), activity.latitude(), activity.address(), activity.locked(),
                        activity.typeCode(), activity.typeName(), activity.kind(), activity.timeFixed()
                )), "itinerary edit activity");
            }
            if (!day.transitNeedsRefresh) {
                copyTransitLegs(day.transitLegs(), newDayId, activityIds);
            }
        }
        requireOne(itineraryMapper.updateCurrentVersion(sourceVersion.itineraryId(), versionId),
                "current itinerary version");
        return versionId;
    }

    private ItineraryResponse toCandidateResponse(
            ItineraryMapper.EditableCurrentVersion version,
            EditableItinerary itinerary
    ) {
        List<DayResponse> days = itinerary.days().stream().map(day -> {
            Map<UUID, Integer> orders = new HashMap<>();
            List<ActivityResponse> activities = new ArrayList<>();
            for (int index = 0; index < day.activities().size(); index++) {
                EditableActivity activity = day.activities().get(index);
                orders.put(activity.id(), index);
                activities.add(new ActivityResponse(
                        activity.id(), activity.title(), activity.startTime(), activity.endTime(),
                        activity.estimatedCost(), activity.source(), activity.providerPoiId(),
                        activity.longitude() == null ? null : new CoordinatesResponse(
                                activity.longitude(), activity.latitude()),
                        activity.address(), activity.locked(), activity.typeCode(),
                        activity.typeName(), activity.kind(), activity.timeFixed()
                ));
            }
            List<TransitLegResponse> transit = day.transitNeedsRefresh
                    ? List.of()
                    : day.transitLegs().stream()
                            .filter(leg -> orders.containsKey(leg.fromActivityId())
                                    && orders.containsKey(leg.toActivityId()))
                            .map(this::toTransitLegResponse)
                            .toList();
            return new DayResponse(day.date(), activities, transit, day.dayType());
        }).toList();
        return new ItineraryResponse(
                version.versionId(), version.versionNumber(), version.parentVersionId(),
                version.title(), itinerary.totalCost(),
                version.provider(), days,
                toKnowledgeResponse(version.versionId()), List.of(),
                null, null, version.createdAt(), null
        );
    }

    private void copyTransitLegs(
            List<ItineraryMapper.StoredTransitLeg> transitLegs,
            UUID newDayId,
            Map<UUID, UUID> activityIds) {
        for (int index = 0; index < transitLegs.size(); index++) {
            ItineraryMapper.StoredTransitLeg leg = transitLegs.get(index);
            UUID fromActivityId = activityIds.get(leg.fromActivityId());
            UUID toActivityId = activityIds.get(leg.toActivityId());
            if (fromActivityId == null || toActivityId == null) {
                continue;
            }
            requireOne(itineraryMapper.insertTransitLeg(new ItineraryMapper.TransitLegWrite(
                    UUID.randomUUID(), newDayId, index, fromActivityId, toActivityId, leg.mode(),
                    leg.distanceMeters(), leg.durationSeconds(), leg.provider(), leg.estimated(), leg.polylineJson(),
                    leg.locked(), leg.estimatedCost(), leg.providerRouteId(), leg.calculatedAt(), leg.stale()
            )), "itinerary edit transit leg");
        }
    }

    private void requireOne(int updatedRows, String operation) {
        if (updatedRows != 1) {
            throw new IllegalStateException("Could not persist " + operation);
        }
    }

    private ApiException itineraryNotFound() {
        return new ApiException(HttpStatus.NOT_FOUND, "ITINERARY_NOT_FOUND", "Itinerary was not found");
    }

    private KnowledgeResponse toKnowledgeResponse(UUID versionId) {
        return itineraryMapper.findKnowledge(versionId)
                .map(knowledge -> new KnowledgeResponse(
                        knowledge.status(), knowledge.query(),
                        itineraryMapper.findKnowledgeCitations(versionId).stream()
                                .map(citation -> new KnowledgeCitationResponse(
                                        citation.documentId(), citation.documentVersion(),
                                        citation.chunkId(), citation.chunkIndex(), citation.title(),
                                        citation.sourceUrl(), citation.sourceName(), citation.collectedAt(),
                                        citation.reliabilityLevel(), citation.similarity()
                                ))
                                .toList(),
                        new KnowledgeFreshnessResponse(
                                knowledge.freshnessStatus(), knowledge.freshnessCheckedAt(),
                                knowledge.staleReason()
                        ),
                        knowledge.message()
                ))
                .orElseGet(() -> new KnowledgeResponse(
                        "UNAVAILABLE", "未记录", List.of(),
                        new KnowledgeFreshnessResponse("UNAVAILABLE", null, null),
                        "该行程版本未包含知识引用"
                ));
    }

    private ActivityResponse toActivityResponse(ItineraryMapper.StoredActivity activity) {
        return new ActivityResponse(
                activity.id(), activity.title(), activity.startTime(), activity.endTime(),
                activity.estimatedCost(), activity.source(), activity.providerPoiId(),
                activity.longitude() == null
                        ? null
                        : new CoordinatesResponse(activity.longitude(), activity.latitude()),
                activity.address(), activity.locked(),
                activity.typeCode(), activity.typeName(),
                activity.kind(), activity.timeFixed()
        );
    }

    private TransitLegResponse toTransitLegResponse(ItineraryMapper.StoredTransitLeg leg) {
        TransitLegSemantics.Presentation presentation = TransitLegSemantics.present(
                leg.mode(), leg.durationSeconds(), leg.provider(), leg.estimated(), leg.estimatedCost());
        return new TransitLegResponse(
                leg.id(), leg.legOrder(), leg.fromActivityId(), leg.toActivityId(), leg.mode(),
                leg.distanceMeters(), leg.durationSeconds(), leg.provider(), leg.estimated(),
                readPolyline(leg.polylineJson()), leg.locked(), leg.estimatedCost(),
                leg.providerRouteId(), leg.calculatedAt(), leg.stale(),
                presentation.modeLabel(), presentation.routeDurationSeconds(),
                presentation.waitSeconds(), presentation.costSource(),
                presentation.costMeaning(), presentation.displayCost()
        );
    }

    private List<CoordinatesResponse> readPolyline(String polylineJson) {
        try {
            return objectMapper.readValue(polylineJson, new TypeReference<>() {
            });
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Stored transit leg polyline is invalid", exception);
        }
    }

    public record ItineraryEditRequest(
            UUID baseVersionId,
            String operation,
            UUID activityId,
            UUID transitLegId,
            LocalDate targetDate,
            Integer targetOrder,
            OffsetDateTime targetStartTime,
            OffsetDateTime targetEndTime,
            String transitMode,
            Boolean transitLocked
    ) {
    }

    public record ItineraryEditPreviewResponse(
            String operation,
            boolean canApply,
            boolean requiresReplan,
            String transitSelectionState,
            List<LocalDate> impactedDates,
            List<UUID> impactedActivityIds,
            List<String> warnings,
            List<EditBlockingReason> blockingReasons
    ) {
    }

    public record ItineraryBatchEditRequest(
            UUID baseVersionId,
            List<ItineraryEditRequest> edits
    ) {
    }

    public record EditBlockingReason(String code, String message) {
    }

    public record ItineraryResponse(
            UUID versionId,
            int versionNumber,
            UUID parentVersionId,
            String title,
            BigDecimal estimatedTotalCost,
            String provider,
            List<DayResponse> days,
            KnowledgeResponse knowledge,
            List<FactImpactResponse> factImpacts,
            String accommodationStatus,
            String accommodationLabel,
            Instant createdAt,
            UUID rollbackFromVersionId
    ) {
    }

    public record FactImpactResponse(
            String factId,
            String category,
            LocalDate date,
            String effect,
            String targetPoiId,
            String targetName,
            String reason,
            String sourceName,
            String sourceType,
            String sourceUrl,
            String reliabilityLevel,
            Instant checkedAt,
            String evidence,
            boolean stale,
            boolean conflicted,
            boolean refreshFailed
    ) {
    }

    public record DayResponse(
            LocalDate date,
            List<ActivityResponse> activities,
            List<TransitLegResponse> transitLegs,
            String dayType
    ) {
    }

    public record ActivityResponse(
            UUID id,
            String title,
            OffsetDateTime startTime,
            OffsetDateTime endTime,
            BigDecimal estimatedCost,
            String source,
            String providerPoiId,
            CoordinatesResponse coordinates,
            String address,
            boolean locked,
            String typeCode,
            String typeName,
            String kind,
            boolean timeFixed
    ) {
    }

    public record CoordinatesResponse(BigDecimal longitude, BigDecimal latitude) {
    }

    public record TransitLegResponse(
            UUID id,
            int legOrder,
            UUID fromActivityId,
            UUID toActivityId,
            String mode,
            int distanceMeters,
            int durationSeconds,
            String provider,
            boolean estimated,
            List<CoordinatesResponse> polyline,
            boolean locked,
            BigDecimal estimatedCost,
            String providerRouteId,
            Instant calculatedAt,
            boolean stale,
            String modeLabel,
            int routeDurationSeconds,
            int waitSeconds,
            String costSource,
            String costMeaning,
            BigDecimal displayCost
        ) {
    }

    public record KnowledgeResponse(
            String status,
            String query,
            List<KnowledgeCitationResponse> citations,
            KnowledgeFreshnessResponse freshness,
            String message
    ) {
    }

    public record KnowledgeCitationResponse(
            String documentId,
            int documentVersion,
            String chunkId,
            int chunkIndex,
            String title,
            String sourceUrl,
            String sourceName,
            OffsetDateTime collectedAt,
            String reliabilityLevel,
            double similarity
    ) {
    }

    public record KnowledgeFreshnessResponse(
            String status,
            OffsetDateTime checkedAt,
            String staleReason
    ) {
    }

    private enum EditOperation {
        DELETE_ACTIVITY,
            LOCK_ACTIVITY,
            UNLOCK_ACTIVITY,
        MOVE_ACTIVITY,
        UPDATE_TRANSIT_LEG;

        static EditOperation from(String value) {
            if (value == null) {
                return null;
            }
            try {
                return EditOperation.valueOf(value);
            } catch (IllegalArgumentException exception) {
                return null;
            }
        }
    }

    private record EditImpact(
            List<LocalDate> dates,
            List<UUID> activityIds,
            List<String> warnings
    ) {
    }

    private record EditEvaluation(
            EditOperation operation,
            EditImpact impact,
            EditBlockingReason blockingReason,
            boolean requiresReplan,
            String transitSelectionState
    ) {
        static EditEvaluation allowed(EditOperation operation, EditImpact impact) {
            String selectionState = operation == EditOperation.UPDATE_TRANSIT_LEG ? "AVAILABLE" : null;
            return new EditEvaluation(operation, impact, null, false, selectionState);
        }

        static EditEvaluation blocked(String code, String message) {
            String selectionState = "ITINERARY_TRANSIT_LEG_LOCKED".equals(code) ? "USER_LOCKED" : null;
            return new EditEvaluation(null, new EditImpact(List.of(), List.of(), List.of()),
                    new EditBlockingReason(code, message), false, selectionState);
        }

        static EditEvaluation requiresReplan(
                EditOperation operation, EditImpact impact, String code, String message) {
            EditImpact replanImpact = new EditImpact(
                    impact.dates(), impact.activityIds(),
                    List.of("The selected transit mode requires schedule replanning")
            );
            return new EditEvaluation(operation, replanImpact,
                    new EditBlockingReason(code, message), true, "REQUIRES_REPLAN");
        }

        boolean canApply() {
            return blockingReason == null;
        }

        ItineraryEditPreviewResponse toPreview(String requestedOperation) {
            return new ItineraryEditPreviewResponse(
                    requestedOperation, canApply(), requiresReplan, transitSelectionState,
                    impact.dates(), impact.activityIds(), impact.warnings(),
                    canApply() ? List.of() : List.of(blockingReason)
            );
        }

        ApiException toApiException() {
            HttpStatus status = switch (blockingReason.code()) {
                case "ITINERARY_ACTIVITY_LOCKED", "ITINERARY_TRANSIT_LEG_LOCKED",
                        "ITINERARY_VERSION_CONFLICT" -> HttpStatus.CONFLICT;
                default -> HttpStatus.UNPROCESSABLE_ENTITY;
            };
            return new ApiException(status, blockingReason.code(), blockingReason.message());
        }
    }

    private static final class EditableItinerary {
        private final List<EditableDay> days;

        private EditableItinerary(List<EditableDay> days) {
            this.days = days;
        }

        List<EditableDay> days() {
            return days;
        }

        EditableDay findDay(LocalDate date) {
            return days.stream().filter(day -> day.date().equals(date)).findFirst().orElse(null);
        }

        BigDecimal totalCost() {
            return days.stream()
                    .flatMap(day -> day.activities().stream())
                    .map(EditableActivity::estimatedCost)
                    .reduce(BigDecimal.ZERO, BigDecimal::add)
                    .add(days.stream()
                            .flatMap(day -> day.transitLegs().stream())
                            .map(leg -> leg.estimatedCost() == null
                                    ? BigDecimal.ZERO : leg.estimatedCost())
                            .reduce(BigDecimal.ZERO, BigDecimal::add));
        }

        ActivityLocation findActivity(UUID activityId) {
            for (EditableDay day : days) {
                for (int index = 0; index < day.activities().size(); index++) {
                    EditableActivity activity = day.activities().get(index);
                    if (activity.id().equals(activityId)) {
                        return new ActivityLocation(day, index, activity);
                    }
                }
            }
            return null;
        }

        TransitLocation findTransitLeg(UUID transitLegId) {
            for (EditableDay day : days) {
                for (int index = 0; index < day.transitLegs().size(); index++) {
                    ItineraryMapper.StoredTransitLeg leg = day.transitLegs().get(index);
                    if (leg.id().equals(transitLegId)) {
                        return new TransitLocation(day, index, leg);
                    }
                }
            }
            return null;
        }
    }

    private static final class EditableDay {
        private final LocalDate date;
        private final List<EditableActivity> activities;
        private final List<ItineraryMapper.StoredTransitLeg> transitLegs;
        private final String dayType;
        private boolean transitNeedsRefresh;

        private EditableDay(
                LocalDate date,
                List<EditableActivity> activities,
                List<ItineraryMapper.StoredTransitLeg> transitLegs,
                String dayType) {
            this.date = date;
            this.activities = activities;
            this.transitLegs = transitLegs;
            this.dayType = dayType;
        }

        LocalDate date() {
            return date;
        }

        List<EditableActivity> activities() {
            return activities;
        }

        List<ItineraryMapper.StoredTransitLeg> transitLegs() {
            return transitLegs;
        }

        String dayType() {
            return dayType;
        }
    }

    private record EditableActivity(
            UUID id,
            String title,
            OffsetDateTime startTime,
            OffsetDateTime endTime,
            BigDecimal estimatedCost,
            String source,
            String providerPoiId,
            BigDecimal longitude,
            BigDecimal latitude,
            String address,
            boolean locked,
            String typeCode,
            String typeName,
            String kind,
            boolean timeFixed
    ) {
        EditableActivity withLocked(boolean value) {
            return new EditableActivity(
                    id, title, startTime, endTime, estimatedCost, source, providerPoiId,
                    longitude, latitude, address, value, typeCode, typeName, kind, timeFixed
            );
        }

        EditableActivity withSchedule(OffsetDateTime start, OffsetDateTime end) {
            return new EditableActivity(
                    id, title, start, end, estimatedCost, source, providerPoiId,
                    longitude, latitude, address, locked, typeCode, typeName, kind, timeFixed
            );
        }
    }

    private record ActivityLocation(EditableDay day, int index, EditableActivity activity) {
    }

    private record TransitLocation(EditableDay day, int index, ItineraryMapper.StoredTransitLeg leg) {
    }

    // ---- planning completion: CREATE path -----------------------------------

    /**
     * Create a brand-new itinerary with its first version from a planning
     * result.  Owned by {@code ItineraryService} so that every itinerary
     * mutation goes through a single write path — whether triggered by
     * planning completion, user editing, or local replanning.
     */
    @Transactional
    public CreateItineraryResult createInitialItinerary(
            UUID tripId,
            PlanningCompletedEvent event,
            UUID planningTaskId,
            String constraintSnapshotJson,
            Clock clock
    ) {
        Instant now = clock.instant();
        itineraryMapper.insertItinerary(UUID.randomUUID(), tripId);
        ItineraryMapper.ItineraryState itinerary =
                itineraryMapper.findStateForUpdate(tripId)
                        .orElseThrow(() -> new IllegalStateException(
                                "Itinerary could not be created"));
        UUID versionId = UUID.randomUUID();
        int versionNumber = itinerary.currentVersionNumber() + 1;
        PlanningCompletedEvent.Itinerary result = event.payload().itinerary();
        String provider = completionProvider(event);
        requireOne(
                itineraryMapper.insertVersion(new ItineraryMapper.VersionWrite(
                        versionId, itinerary.id(), versionNumber,
                        itinerary.currentVersionId(), planningTaskId,
                        "PLANNING_TASK", result.title().strip(),
                        result.estimatedTotalCost(), provider,
                        constraintSnapshotJson,
                        result.accommodation() == null ? null : result.accommodation().status(),
                        result.accommodation() == null ? null : result.accommodation().placeName(),
                        now
                )),
                "itinerary version"
        );
        versionPersister.persistKnowledge(
                versionId, event.payload().knowledge(),
                "itinerary knowledge evidence"
        );
        List<PersistedActivityReference> persistedActivities = new ArrayList<>();
        List<PersistedTransitReference> persistedTransit = new ArrayList<>();
        for (int dayIndex = 0; dayIndex < result.days().size(); dayIndex++) {
            PersistedDayReferences references = persistDay(
                    versionId, dayIndex, result.days().get(dayIndex), false);
            persistedActivities.addAll(references.activities());
            persistedTransit.addAll(references.transit());
        }
        requireOne(
                itineraryMapper.updateCurrentVersion(itinerary.id(), versionId),
                "current version"
        );
        return new CreateItineraryResult(
                versionId, versionNumber, provider,
                persistedActivities, persistedTransit
        );
    }

    /** Persists a validated edit/rollback candidate as a new formal version. */
    @Transactional
    public CreateItineraryResult createCandidateVersion(
            UUID tripId,
            PlanningCompletedEvent event,
            PlanningTaskCompletionRecord task,
            Clock clock,
            List<PlanningTaskService.TransitRouteIntent> routeIntents
    ) {
        ItineraryMapper.ItineraryState itinerary = itineraryMapper.findStateForUpdate(tripId)
                .orElseThrow(() -> rejected("Itinerary was not found for candidate validation"));
        if (!task.baselineItineraryVersionId().equals(itinerary.currentVersionId())) {
            throw rejected("Candidate baseline no longer matches the current itinerary");
        }
        PlanningCompletedEvent.Itinerary result = event.payload().itinerary();
        UUID versionId = UUID.randomUUID();
        String versionSource = "ROLLBACK".equals(task.candidateType())
                ? "ROLLBACK" : "USER_EDIT";
        String provider = completionProvider(event);
        BigDecimal estimatedTotalCost = candidateEstimatedTotalCost(
                result, routeIntents);
        validateCandidateTransitSemantics(
                result, routeIntents, estimatedTotalCost,
                budgetFrom(task.constraintSnapshotJson()));
        requireOne(itineraryMapper.insertVersion(new ItineraryMapper.VersionWrite(
                versionId, itinerary.id(), itinerary.currentVersionNumber() + 1,
                itinerary.currentVersionId(), task.id(), versionSource,
                result.title().strip(), estimatedTotalCost, provider,
                task.constraintSnapshotJson(),
                result.accommodation() == null ? null : result.accommodation().status(),
                result.accommodation() == null ? null : result.accommodation().placeName(),
                clock.instant()
        )), "candidate itinerary version");
        if ("ROLLBACK".equals(task.candidateType())) {
            requireOne(itineraryMapper.setRollbackSource(
                    versionId, task.candidateSourceVersionId()), "rollback source");
        }
        versionPersister.persistKnowledge(
                versionId, event.payload().knowledge(), "candidate knowledge evidence");
        List<PersistedActivityReference> persistedActivities = new ArrayList<>();
        List<PersistedTransitReference> persistedTransit = new ArrayList<>();
        for (int dayIndex = 0; dayIndex < result.days().size(); dayIndex++) {
            PersistedDayReferences references = persistDay(
                    versionId, dayIndex, result.days().get(dayIndex), true,
                    routeIntents);
            persistedActivities.addAll(references.activities());
            persistedTransit.addAll(references.transit());
        }
        requireOne(itineraryMapper.updateCurrentVersion(itinerary.id(), versionId),
                "current candidate version");
        return new CreateItineraryResult(
                versionId, itinerary.currentVersionNumber() + 1, provider,
                persistedActivities, persistedTransit);
    }

    // ---- planning completion: REPLAN path ----------------------------------

    @Transactional(readOnly = true)
    public UUID getCurrentVersionForTask(UUID tripId) {
        return itineraryMapper.findStateForUpdate(tripId)
                .map(ItineraryMapper.ItineraryState::currentVersionId)
                .orElse(null);
    }

    @Transactional
    public CreateItineraryResult createReplanVersion(
            UUID tripId,
            PlanningCompletedEvent event,
            PlanningTaskCompletionRecord task,
            Clock clock
    ) {
        ItineraryMapper.ItineraryState itinerary =
                itineraryMapper.findStateForUpdate(tripId)
                        .orElseThrow(() -> rejected(
                                "Itinerary was not found for local replanning"));
        ItineraryMapper.StoredVersion source =
                itineraryMapper.findVersion(itinerary.currentVersionId())
                        .orElseThrow(() -> rejected(
                                "Current itinerary version was not found"));
        Set<LocalDate> impactedDates = readImpactedDates(
                task.impactedDatesJson());
        Map<LocalDate, PlanningCompletedEvent.Day> resultDays =
                event.payload().itinerary().days().stream()
                        .collect(java.util.stream.Collectors.toMap(
                                PlanningCompletedEvent.Day::date,
                                day -> day,
                                (first, second) -> first
                        ));
        List<ItineraryMapper.StoredDay> sourceDays =
                itineraryMapper.findDays(source.id());
        if (sourceDays.size() != resultDays.size()
                || !resultDays.keySet().equals(sourceDays.stream()
                        .map(ItineraryMapper.StoredDay::date)
                        .collect(java.util.stream.Collectors.toSet()))) {
            throw rejected(
                    "Local replanning result must contain the current"
                            + " itinerary dates");
        }
        Instant now = clock.instant();
        UUID versionId = UUID.randomUUID();
        String provider = completionProvider(event);
        requireOne(
                itineraryMapper.insertVersion(new ItineraryMapper.VersionWrite(
                        versionId, source.itineraryId(),
                        source.versionNumber() + 1, source.id(), task.id(),
                        "LOCAL_REPLAN", source.title(),
                        source.estimatedTotalCost(), provider,
                        source.constraintSnapshotJson(),
                        source.accommodationStatus(), source.accommodationLabel(),
                        now
                )),
                "local replan itinerary version"
        );
        versionPersister.copyKnowledge(
                source.id(), versionId, "local replan knowledge");
        factImpactMapper.copyToVersion(source.id(), versionId);

        List<PersistedActivityReference> persistedActivities = new ArrayList<>();
        List<PersistedTransitReference> persistedTransit = new ArrayList<>();
        java.math.BigDecimal transitCostDelta = java.math.BigDecimal.ZERO;
        for (ItineraryMapper.StoredDay sourceDay : sourceDays) {
            PlanningCompletedEvent.Day resultDay =
                    resultDays.get(sourceDay.date());
            List<ItineraryMapper.StoredActivity> activities =
                    itineraryMapper.findActivities(sourceDay.id());
            validateReplannedActivities(activities, resultDay);
            UUID targetDayId = UUID.randomUUID();
            requireOne(
                    itineraryMapper.insertDay(new ItineraryMapper.DayWrite(
                            targetDayId, versionId,
                            sourceDay.date(), sourceDay.dayIndex(), sourceDay.dayType()
                    )),
                    "local replan day"
            );
            List<UUID> activityIds =
                    persistSourceActivities(targetDayId, activities);
            for (int index = 0; index < activityIds.size(); index++) {
                UUID sourceActivityId = resultDay.activities().get(index).activityId();
                if (sourceActivityId != null) {
                    persistedActivities.add(new PersistedActivityReference(
                            sourceActivityId, activityIds.get(index)));
                }
            }
            List<ItineraryMapper.StoredTransitLeg> sourceTransitLegs =
                    itineraryMapper.findTransitLegs(sourceDay.id());
            if (impactedDates.contains(sourceDay.date())) {
                PersistedReplanTransit resultTransit = persistResultTransit(
                        targetDayId, activityIds,
                        activities, sourceTransitLegs, resultDay
                );
                persistedTransit.addAll(resultTransit.references());
                transitCostDelta = transitCostDelta
                        .subtract(totalTransitCost(sourceTransitLegs))
                        .add(resultTransit.estimatedCost());
            } else {
                persistedTransit.addAll(copyTransitLegsFromSource(
                        targetDayId, activityIds,
                        activities, sourceTransitLegs, resultDay
                ));
            }
        }
        requireOne(itineraryMapper.updateEstimatedTotalCost(
                versionId, source.estimatedTotalCost().add(transitCostDelta)),
                "local replan itinerary total cost");
        requireOne(
                itineraryMapper.updateCurrentVersion(
                        itinerary.id(), versionId),
                "current itinerary version"
        );
        return new CreateItineraryResult(
                versionId, source.versionNumber() + 1, provider,
                persistedActivities, persistedTransit
        );
    }

    // ---- planning-completion helpers (moved from PlanningCompletionService) --

    private PersistedDayReferences persistDay(
            UUID versionId,
            int dayIndex,
            PlanningCompletedEvent.Day day,
            boolean preserveCandidateLocks
    ) {
        return persistDay(versionId, dayIndex, day, preserveCandidateLocks, List.of());
    }

    private PersistedDayReferences persistDay(
            UUID versionId,
            int dayIndex,
            PlanningCompletedEvent.Day day,
            boolean preserveCandidateLocks,
            List<PlanningTaskService.TransitRouteIntent> routeIntents
    ) {
        UUID dayId = UUID.randomUUID();
        requireOne(
                itineraryMapper.insertDay(
                        new ItineraryMapper.DayWrite(
                                dayId, versionId, day.date(), dayIndex, day.dayType()
                        )
                ),
                "itinerary day"
        );
        List<UUID> activityIds = new ArrayList<>(day.activities().size());
        List<PersistedActivityReference> persistedActivities = new ArrayList<>();
        for (int activityIndex = 0;
                activityIndex < day.activities().size();
                activityIndex++) {
            PlanningCompletedEvent.Activity activity =
                    day.activities().get(activityIndex);
            PlanningCompletedEvent.Coordinates coordinates =
                    activity.coordinates();
            UUID activityId = UUID.randomUUID();
            activityIds.add(activityId);
            if (activity.activityId() != null) {
                persistedActivities.add(new PersistedActivityReference(
                        activity.activityId(), activityId));
            }
            requireOne(
                    itineraryMapper.insertActivity(
                            new ItineraryMapper.ActivityWrite(
                                    activityId, dayId, activityIndex,
                                    activity.title().strip(),
                                    activity.startTime(), activity.endTime(),
                                    activity.estimatedCost(),
                                    activity.source(),
                                    activity.providerPoiId(),
                                    coordinates == null
                                            ? null : coordinates.longitude(),
                                    coordinates == null
                                            ? null : coordinates.latitude(),
                                    activity.address(),
                                    preserveCandidateLocks && Boolean.TRUE.equals(activity.locked()),
                                    activity.typeCode(), activity.typeName(),
                                    activity.kind(),
                                    Boolean.TRUE.equals(activity.timeFixed())
                            )
                    ),
                    "itinerary activity"
            );
        }
        List<PlanningCompletedEvent.TransitLeg> orderedLegs = day.transitLegs()
                .stream()
                .sorted(Comparator.comparingInt(
                                PlanningCompletedEvent.TransitLeg::fromActivityIndex)
                        .thenComparingInt(
                                PlanningCompletedEvent.TransitLeg::toActivityIndex))
                .toList();
        List<PersistedTransitReference> persistedTransit = new ArrayList<>();
        for (int legIndex = 0; legIndex < orderedLegs.size(); legIndex++) {
            PlanningCompletedEvent.TransitLeg leg = restoreCandidateTransitIntent(
                    day.date(), orderedLegs.get(legIndex), routeIntents);
            UUID transitId = UUID.randomUUID();
            UUID fromActivityId = activityIds.get(leg.fromActivityIndex());
            UUID toActivityId = activityIds.get(leg.toActivityIndex());
            requireOne(
                    itineraryMapper.insertTransitLeg(
                            new ItineraryMapper.TransitLegWrite(
                                    transitId, dayId, legIndex,
                                    fromActivityId, toActivityId,
                                    leg.mode(), leg.distanceMeters(),
                                    leg.durationSeconds(), leg.provider(),
                                    leg.estimated(),
                                    writeJson(leg.polyline()),
                                    preserveCandidateLocks && Boolean.TRUE.equals(leg.locked()),
                                    leg.estimatedCost(),
                                    null, Instant.now(), false
                            )
                    ),
                    "itinerary transit leg"
            );
            persistedTransit.add(new PersistedTransitReference(
                    leg.transitId(),
                    day.activities().get(leg.fromActivityIndex()).activityId(),
                    day.activities().get(leg.toActivityIndex()).activityId(),
                    transitId, fromActivityId, toActivityId
            ));
        }
        return new PersistedDayReferences(persistedActivities, persistedTransit);
    }

    private BigDecimal candidateEstimatedTotalCost(
            PlanningCompletedEvent.Itinerary itinerary,
            List<PlanningTaskService.TransitRouteIntent> routeIntents
    ) {
        if (routeIntents == null || routeIntents.isEmpty()) {
            return itinerary.estimatedTotalCost();
        }
        validateCandidateRouteIntents(itinerary, routeIntents);
        BigDecimal result = itinerary.estimatedTotalCost();
        for (PlanningTaskService.TransitRouteIntent intent : routeIntents) {
            PlanningCompletedEvent.TransitLeg leg = candidateIntentLeg(
                    itinerary, intent);
            BigDecimal returnedWireCost = leg.estimatedCost() == null
                    ? BigDecimal.ZERO : leg.estimatedCost();
            result = result.subtract(returnedWireCost)
                    .add(TransitLegSemantics.taxiFare(leg.distanceMeters()));
        }
        return result;
    }

    private void validateCandidateTransitSemantics(
            PlanningCompletedEvent.Itinerary itinerary,
            List<PlanningTaskService.TransitRouteIntent> routeIntents,
            BigDecimal estimatedTotalCost,
            BigDecimal budgetAmount
    ) {
        if (routeIntents == null || routeIntents.isEmpty()) {
            return;
        }
        for (PlanningTaskService.TransitRouteIntent intent : routeIntents) {
            PlanningCompletedEvent.Day day = itinerary.days().stream()
                    .filter(candidate -> candidate.date().equals(intent.date()))
                    .findFirst()
                    .orElseThrow(() -> rejected(
                            "Candidate route intent date is missing"));
            PlanningCompletedEvent.TransitLeg leg = candidateIntentLeg(
                    itinerary, intent);
            PlanningCompletedEvent.Activity from =
                    day.activities().get(leg.fromActivityIndex());
            PlanningCompletedEvent.Activity to =
                    day.activities().get(leg.toActivityIndex());
            long availableSeconds = Duration.between(
                    from.endTime(), to.startTime()).getSeconds();
            long effectiveDuration = (long) leg.durationSeconds()
                    + TransitLegSemantics.TAXI_WAIT_SECONDS;
            if (availableSeconds < effectiveDuration) {
                throw rejected(
                        "Validated taxi route does not fit between its activities");
            }
        }
        if (budgetAmount != null && estimatedTotalCost.compareTo(budgetAmount) > 0) {
            throw rejected("Validated taxi route exceeds the trip budget");
        }
    }

    private void validateCandidateRouteIntents(
            PlanningCompletedEvent.Itinerary itinerary,
            List<PlanningTaskService.TransitRouteIntent> routeIntents
    ) {
        Set<String> identities = new HashSet<>();
        for (PlanningTaskService.TransitRouteIntent intent : routeIntents) {
            String identity = intent.date() + ":" + intent.fromActivityIndex()
                    + ":" + intent.toActivityIndex();
            if (!identities.add(identity)) {
                throw rejected("Candidate validation contains duplicate route intents");
            }
            candidateIntentLeg(itinerary, intent);
        }
    }

    private PlanningCompletedEvent.TransitLeg candidateIntentLeg(
            PlanningCompletedEvent.Itinerary itinerary,
            PlanningTaskService.TransitRouteIntent intent
    ) {
        List<PlanningCompletedEvent.Day> days = itinerary.days().stream()
                .filter(day -> day.date().equals(intent.date())).toList();
        if (days.size() != 1) {
            throw rejected("Candidate route intent date is missing or ambiguous");
        }
        List<PlanningCompletedEvent.TransitLeg> legs = days.getFirst().transitLegs()
                .stream()
                .filter(leg -> leg.fromActivityIndex() == intent.fromActivityIndex()
                        && leg.toActivityIndex() == intent.toActivityIndex())
                .toList();
        if (legs.size() != 1) {
            throw rejected("Candidate route intent endpoints are missing or ambiguous");
        }
        PlanningCompletedEvent.TransitLeg leg = legs.getFirst();
        boolean validProvider = ("AMAP".equals(leg.provider()) && !leg.estimated())
                || (!intent.requireRealRoute()
                        && "DEMO".equals(leg.provider()) && leg.estimated());
        if (!"TAXI".equals(intent.targetMode())
                || !"DRIVING".equals(leg.mode())
                || !validProvider
                || leg.polyline().isEmpty()) {
            throw rejected(intent.requireRealRoute()
                    ? "TAXI candidate must return real AMAP DRIVING route facts"
                    : "TAXI candidate must return valid technical DRIVING route facts");
        }
        return leg;
    }

    private PlanningCompletedEvent.TransitLeg restoreCandidateTransitIntent(
            LocalDate date,
            PlanningCompletedEvent.TransitLeg leg,
            List<PlanningTaskService.TransitRouteIntent> routeIntents
    ) {
        boolean taxi = routeIntents != null && routeIntents.stream().anyMatch(intent ->
                intent.date().equals(date)
                        && intent.fromActivityIndex() == leg.fromActivityIndex()
                        && intent.toActivityIndex() == leg.toActivityIndex());
        if (!taxi) {
            return leg;
        }
        return new PlanningCompletedEvent.TransitLeg(
                leg.transitId(), leg.fromActivityIndex(), leg.toActivityIndex(),
                "TAXI", leg.distanceMeters(),
                leg.durationSeconds() + TransitLegSemantics.TAXI_WAIT_SECONDS,
                leg.provider(), true, leg.polyline(),
                TransitLegSemantics.taxiFare(leg.distanceMeters()),
                "RULE_ESTIMATE", leg.locked());
    }

    private List<UUID> persistSourceActivities(
            UUID dayId,
            List<ItineraryMapper.StoredActivity> activities) {
        List<UUID> activityIds = new ArrayList<>(activities.size());
        for (ItineraryMapper.StoredActivity activity : activities) {
            UUID activityId = UUID.randomUUID();
            activityIds.add(activityId);
            requireOne(
                    itineraryMapper.insertActivity(
                            new ItineraryMapper.ActivityWrite(
                                    activityId, dayId,
                                    activity.activityOrder(),
                                    activity.title(),
                                    activity.startTime(),
                                    activity.endTime(),
                                    activity.estimatedCost(),
                                    activity.source(),
                                    activity.providerPoiId(),
                                    activity.longitude(),
                                    activity.latitude(),
                                    activity.address(),
                                    activity.locked(),
                                    activity.typeCode(), activity.typeName(),
                                    activity.kind(), activity.timeFixed()
                            )
                    ),
                    "local replan activity"
            );
        }
        return activityIds;
    }

    private PersistedReplanTransit persistResultTransit(
            UUID dayId,
            List<UUID> activityIds,
            List<ItineraryMapper.StoredActivity> sourceActivities,
            List<ItineraryMapper.StoredTransitLeg> sourceLegs,
            PlanningCompletedEvent.Day resultDay) {
        List<PlanningCompletedEvent.TransitLeg> legs = resultDay.transitLegs()
                .stream()
                .sorted(Comparator.comparingInt(
                                PlanningCompletedEvent.TransitLeg::fromActivityIndex)
                        .thenComparingInt(
                                PlanningCompletedEvent.TransitLeg::toActivityIndex))
                .toList();
        List<PersistedTransitReference> persistedTransit = new ArrayList<>();
        java.math.BigDecimal estimatedCost = java.math.BigDecimal.ZERO;
        for (int index = 0; index < legs.size(); index++) {
            PlanningCompletedEvent.TransitLeg leg = legs.get(index);
            if (leg.fromActivityIndex() < 0 || leg.toActivityIndex() < 0
                    || leg.fromActivityIndex() >= activityIds.size()
                    || leg.toActivityIndex() >= activityIds.size()) {
                throw rejected(
                        "Local replanning returned an invalid transit leg");
            }
            UUID fromActivityId =
                    activityIds.get(leg.fromActivityIndex());
            UUID toActivityId =
                    activityIds.get(leg.toActivityIndex());
            ResolvedReplanTransit resolved = resolveReplanTransit(
                    sourceActivities, sourceLegs, leg);
            UUID transitId = UUID.randomUUID();
            requireOne(
                    itineraryMapper.insertTransitLeg(
                            new ItineraryMapper.TransitLegWrite(
                                    transitId, dayId, index,
                                    fromActivityId, toActivityId,
                                    resolved.mode(), resolved.distanceMeters(),
                                    resolved.durationSeconds(), resolved.provider(),
                                    resolved.estimated(),
                                    writeJson(resolved.polyline()),
                                    resolved.locked(),
                                    resolved.estimatedCost(), null, Instant.now(), false
                            )
                    ),
                    "local replan transit leg"
            );
            persistedTransit.add(new PersistedTransitReference(
                    leg.transitId(),
                    resultDay.activities().get(leg.fromActivityIndex()).activityId(),
                    resultDay.activities().get(leg.toActivityIndex()).activityId(),
                    transitId, fromActivityId, toActivityId
            ));
            if (resolved.estimatedCost() != null) {
                estimatedCost = estimatedCost.add(resolved.estimatedCost());
            }
        }
        return new PersistedReplanTransit(List.copyOf(persistedTransit), estimatedCost);
    }

    private static String completionProvider(PlanningCompletedEvent event) {
        PlanningCompletedEvent.ProviderProvenance provenance =
                event.payload().providerProvenance();
        if (provenance == null) {
            return event.payload().provider();
        }
        if (provenance.actualProviders().contains(
                PlanningCompletedEvent.ProviderSource.AMAP)
                && provenance.actualProviders().contains(
                        PlanningCompletedEvent.ProviderSource.DEMO)) {
            return "MIXED";
        }
        return provenance.actualProviders().getFirst().name();
    }

    private static ResolvedReplanTransit resolveReplanTransit(
            List<ItineraryMapper.StoredActivity> sourceActivities,
            List<ItineraryMapper.StoredTransitLeg> sourceLegs,
            PlanningCompletedEvent.TransitLeg resultLeg) {
        UUID sourceFromActivityId = sourceActivities.get(resultLeg.fromActivityIndex()).id();
        UUID sourceToActivityId = sourceActivities.get(resultLeg.toActivityIndex()).id();
        List<ItineraryMapper.StoredTransitLeg> matchingLegs = sourceLegs.stream()
                .filter(sourceLeg -> sourceLeg.fromActivityId().equals(sourceFromActivityId)
                        && sourceLeg.toActivityId().equals(sourceToActivityId))
                .toList();
        if (matchingLegs.size() > 1) {
            throw rejected("Current itinerary contains duplicate transit endpoints");
        }
        if (matchingLegs.isEmpty()) {
            if ("DRIVING".equals(resultLeg.mode())) {
                throw rejected("Current itinerary has no intent for a returned road route");
            }
            return ResolvedReplanTransit.from(resultLeg, false);
        }
        ItineraryMapper.StoredTransitLeg sourceLeg = matchingLegs.getFirst();
        if (!"TAXI".equals(sourceLeg.mode())) {
            return ResolvedReplanTransit.from(resultLeg, sourceLeg.locked());
        }
        if (!"DRIVING".equals(resultLeg.mode())) {
            throw rejected("Taxi replanning must return DRIVING route facts");
        }
        return new ResolvedReplanTransit(
                "TAXI", resultLeg.distanceMeters(),
                resultLeg.durationSeconds() + TransitLegSemantics.TAXI_WAIT_SECONDS,
                resultLeg.provider(), true, resultLeg.polyline(), sourceLeg.locked(),
                TransitLegSemantics.taxiFare(resultLeg.distanceMeters()));
    }

    private static java.math.BigDecimal totalTransitCost(
            List<ItineraryMapper.StoredTransitLeg> legs) {
        return legs.stream()
                .map(ItineraryMapper.StoredTransitLeg::estimatedCost)
                .filter(java.util.Objects::nonNull)
                .reduce(java.math.BigDecimal.ZERO, java.math.BigDecimal::add);
    }

    private List<PersistedTransitReference> copyTransitLegsFromSource(
            UUID dayId,
            List<UUID> activityIds,
            List<ItineraryMapper.StoredActivity> activities,
            List<ItineraryMapper.StoredTransitLeg> legs,
            PlanningCompletedEvent.Day resultDay) {
        List<PersistedTransitReference> persistedTransit = new ArrayList<>();
        for (int index = 0; index < legs.size(); index++) {
            ItineraryMapper.StoredTransitLeg leg = legs.get(index);
            Integer fromIndex =
                    findSourceActivityIndex(leg.fromActivityId(), activities);
            Integer toIndex =
                    findSourceActivityIndex(leg.toActivityId(), activities);
            if (fromIndex == null || toIndex == null) {
                throw rejected(
                        "Current itinerary contains an invalid transit leg");
            }
            UUID fromActivityId = activityIds.get(fromIndex);
            UUID toActivityId = activityIds.get(toIndex);
            UUID transitId = UUID.randomUUID();
            PlanningCompletedEvent.TransitLeg resultLeg = resultDay.transitLegs()
                    .stream()
                    .filter(candidate -> candidate.fromActivityIndex() == fromIndex
                            && candidate.toActivityIndex() == toIndex)
                    .findFirst()
                    .orElseThrow(() -> rejected(
                            "Local replanning result is missing a transit leg"));
            requireOne(
                    itineraryMapper.insertTransitLeg(
                            new ItineraryMapper.TransitLegWrite(
                                    transitId, dayId, index,
                                    fromActivityId, toActivityId,
                                    leg.mode(), leg.distanceMeters(),
                                    leg.durationSeconds(), leg.provider(),
                                    leg.estimated(), leg.polylineJson(),
                                    leg.locked(), leg.estimatedCost(), leg.providerRouteId(),
                                    leg.calculatedAt(), leg.stale()
                            )
                    ),
                    "local replan transit leg"
            );
            if (resultLeg.transitId() != null) {
                persistedTransit.add(new PersistedTransitReference(
                        resultLeg.transitId(),
                        resultDay.activities().get(fromIndex).activityId(),
                        resultDay.activities().get(toIndex).activityId(),
                        transitId, fromActivityId, toActivityId
                ));
            }
        }
        return List.copyOf(persistedTransit);
    }

    private static Integer findSourceActivityIndex(
            UUID sourceActivityId,
            List<ItineraryMapper.StoredActivity> activities) {
        for (int index = 0; index < activities.size(); index++) {
            if (activities.get(index).id().equals(sourceActivityId)) {
                return index;
            }
        }
        return null;
    }

    private void validateReplannedActivities(
            List<ItineraryMapper.StoredActivity> sourceActivities,
            PlanningCompletedEvent.Day resultDay) {
        if (sourceActivities.size() != resultDay.activities().size()) {
            throw rejected(
                    "Local replanning must preserve the activity set");
        }
        for (int index = 0;
                index < sourceActivities.size();
                index++) {
            ItineraryMapper.StoredActivity source =
                    sourceActivities.get(index);
            PlanningCompletedEvent.Activity result =
                    resultDay.activities().get(index);
            if (!source.title().strip().equals(result.title().strip())
                    || !source.startTime().isEqual(result.startTime())
                    || !source.endTime().isEqual(result.endTime())
                    || source.estimatedCost()
                            .compareTo(result.estimatedCost()) != 0
                    || !java.util.Objects.equals(
                            source.source(), result.source())
                    || !java.util.Objects.equals(
                            source.providerPoiId(), result.providerPoiId())
                    || !sameCoordinates(
                            source, result.coordinates())
                    || !java.util.Objects.equals(
                            source.address(), result.address())
                    || !java.util.Objects.equals(
                            source.kind(), result.kind())
                    || !java.util.Objects.equals(
                            source.timeFixed(), Boolean.TRUE.equals(result.timeFixed()))) {
                throw rejected(
                        "Local replanning must preserve activity details");
            }
        }
    }

    private static boolean sameCoordinates(
            ItineraryMapper.StoredActivity source,
            PlanningCompletedEvent.Coordinates result) {
        if (source.longitude() == null || result == null) {
            return source.longitude() == null && result == null;
        }
        return source.longitude().compareTo(result.longitude()) == 0
                && source.latitude().compareTo(result.latitude()) == 0;
    }

    private Set<LocalDate> readImpactedDates(String json) {
        try {
            return new HashSet<>(
                    objectMapper.readValue(
                            json,
                            new TypeReference<List<LocalDate>>() { }
                    )
            );
        } catch (JsonProcessingException exception) {
            throw rejected(
                    "Planning task contains invalid local replan dates");
        }
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException(
                    "Could not serialize itinerary data", exception);
        }
    }

    private static PlanningEventRejectedException rejected(String message) {
        return new PlanningEventRejectedException(message);
    }

    public record CreateItineraryResult(
            UUID versionId,
            int versionNumber,
            String provider,
            List<PersistedActivityReference> persistedActivities,
            List<PersistedTransitReference> persistedTransit
    ) {
        public CreateItineraryResult {
            persistedActivities = List.copyOf(persistedActivities);
            persistedTransit = List.copyOf(persistedTransit);
        }
    }

    public record PersistedActivityReference(
            UUID sourceActivityId,
            UUID activityId
    ) {
    }

    public record PersistedTransitReference(
            UUID sourceTransitId,
            UUID sourceFromActivityId,
            UUID sourceToActivityId,
            UUID transitId,
            UUID fromActivityId,
            UUID toActivityId
    ) {
    }

    private record PersistedReplanTransit(
            List<PersistedTransitReference> references,
            java.math.BigDecimal estimatedCost
    ) {
        private PersistedReplanTransit {
            references = List.copyOf(references);
        }
    }

    private record ResolvedReplanTransit(
            String mode,
            int distanceMeters,
            int durationSeconds,
            String provider,
            boolean estimated,
            List<PlanningCompletedEvent.Coordinates> polyline,
            boolean locked,
            java.math.BigDecimal estimatedCost
    ) {
        private ResolvedReplanTransit {
            polyline = List.copyOf(polyline);
        }

        private static ResolvedReplanTransit from(
                PlanningCompletedEvent.TransitLeg leg,
                boolean locked
        ) {
            return new ResolvedReplanTransit(
                    leg.mode(), leg.distanceMeters(), leg.durationSeconds(),
                    leg.provider(), leg.estimated(), leg.polyline(), locked,
                    leg.estimatedCost());
        }
    }

    private record PersistedDayReferences(
            List<PersistedActivityReference> activities,
            List<PersistedTransitReference> transit
    ) {
        private PersistedDayReferences {
            activities = List.copyOf(activities);
            transit = List.copyOf(transit);
        }
    }
}
