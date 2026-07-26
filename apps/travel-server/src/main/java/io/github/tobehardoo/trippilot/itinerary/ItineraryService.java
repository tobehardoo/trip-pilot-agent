package io.github.tobehardoo.trippilot.itinerary;

import java.math.BigDecimal;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
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

    public ItineraryService(
            ItineraryMapper itineraryMapper,
            ItineraryVersionPersister versionPersister,
            ObjectMapper objectMapper,
            @Lazy PlanningTaskService planningTaskService
    ) {
        this.itineraryMapper = itineraryMapper;
        this.versionPersister = versionPersister;
        this.objectMapper = objectMapper;
        this.planningTaskService = planningTaskService;
    }

    @Transactional(readOnly = true)
    public ItineraryResponse getCurrent(UUID ownerId, UUID tripId) {
        ItineraryMapper.CurrentVersion version = itineraryMapper.findCurrentVersionOwned(tripId, ownerId)
                .orElseThrow(this::itineraryNotFound);
        return toItineraryResponse(version);
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
        EditEvaluation evaluation = evaluate(itinerary, request);
        return evaluation.toPreview(request.operation());
    }

    @Transactional
    public ItineraryResponse applyEdit(UUID ownerId, UUID tripId, ItineraryEditRequest request) {
        ItineraryMapper.EditableCurrentVersion version = itineraryMapper
                .findCurrentVersionOwnedForEditForUpdate(tripId, ownerId)
                .orElseThrow(this::itineraryNotFound);
        if (request == null || request.baseVersionId() == null || !request.baseVersionId().equals(version.versionId())) {
            throw new ApiException(HttpStatus.CONFLICT, "ITINERARY_VERSION_CONFLICT",
                    "The itinerary was updated. Reload it before applying this edit");
        }
        if (planningTaskService.hasActiveTask(tripId)) {
            throw new ApiException(HttpStatus.CONFLICT, "ITINERARY_PLANNING_ACTIVE", PLANNING_ACTIVE_MESSAGE);
        }

        EditableItinerary itinerary = readEditableItinerary(version.versionId());
        EditEvaluation evaluation = evaluate(itinerary, request);
        if (!evaluation.canApply()) {
            throw evaluation.toApiException();
        }

        apply(itinerary, request, evaluation.operation());
        persistEditedVersion(version, itinerary);
        return getCurrent(ownerId, tripId);
    }

    private ItineraryEditPreviewResponse blockedPreview(
            ItineraryEditRequest request, String code, String message) {
        return new ItineraryEditPreviewResponse(
                request == null ? null : request.operation(), false, List.of(), List.of(), List.of(),
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
                                .toList()
                ))
                .toList();
        return new ItineraryResponse(
                version.id(), version.versionNumber(), version.parentVersionId(), version.title(),
                version.estimatedTotalCost(), version.provider(), days,
                toKnowledgeResponse(version.id()), version.createdAt()
        );
    }

    private EditableItinerary readEditableItinerary(UUID versionId) {
        List<EditableDay> days = itineraryMapper.findDays(versionId).stream()
                .map(day -> new EditableDay(
                        day.date(),
                        new ArrayList<>(itineraryMapper.findActivities(day.id()).stream()
                                .map(this::toEditableActivity)
                                .toList()),
                        new ArrayList<>(itineraryMapper.findTransitLegs(day.id()))
                ))
                .toList();
        return new EditableItinerary(days);
    }

    private EditableActivity toEditableActivity(ItineraryMapper.StoredActivity activity) {
        return new EditableActivity(
                activity.id(), activity.title(), activity.startTime(), activity.endTime(),
                activity.estimatedCost(), activity.source(), activity.providerPoiId(),
                activity.longitude(), activity.latitude(), activity.address(), activity.locked()
        );
    }

    private EditEvaluation evaluate(EditableItinerary itinerary, ItineraryEditRequest request) {
        EditOperation operation = EditOperation.from(request.operation());
        if (operation == null) {
            return EditEvaluation.blocked("ITINERARY_EDIT_INVALID", "The edit operation is not supported");
        }
        if (operation == EditOperation.UPDATE_TRANSIT_LEG) {
            return evaluateTransitLeg(itinerary, request);
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
            EditableItinerary itinerary, ItineraryEditRequest request) {
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
                && !List.of("WALKING", "DRIVING").contains(request.transitMode())) {
            return EditEvaluation.blocked("ITINERARY_EDIT_INVALID",
                    "The selected transit mode is not supported");
        }
        if (location.leg().locked() && request.transitMode() != null
                && !request.transitMode().equals(location.leg().mode())) {
            return EditEvaluation.blocked("ITINERARY_TRANSIT_LEG_LOCKED",
                    "A locked transit leg cannot change its mode");
        }
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
                    leg.estimated(), leg.polylineJson(), locked
            );
        }
        return new ItineraryMapper.StoredTransitLeg(
                leg.id(), leg.legOrder(), leg.fromActivityId(), leg.toActivityId(),
                mode, leg.distanceMeters(), estimatedTransitDuration(mode, leg.distanceMeters()),
                "DEMO", true, "[]", locked
        );
    }

    private static int estimatedTransitDuration(String mode, int distanceMeters) {
        double seconds = switch (mode) {
            case "WALKING" -> distanceMeters / 1.25;
            case "DRIVING" -> distanceMeters / 8.33 + 180;
            default -> throw new IllegalArgumentException("Unsupported transit mode: " + mode);
        };
        return Math.max(60, (int) Math.round(seconds / 60) * 60);
    }

    private void persistEditedVersion(
            ItineraryMapper.EditableCurrentVersion sourceVersion, EditableItinerary itinerary) {
        UUID versionId = UUID.randomUUID();
        BigDecimal totalCost = itinerary.days().stream()
                .flatMap(day -> day.activities().stream())
                .map(EditableActivity::estimatedCost)
                .reduce(BigDecimal.ZERO, BigDecimal::add);
        requireOne(itineraryMapper.insertVersion(new ItineraryMapper.VersionWrite(
                versionId, sourceVersion.itineraryId(), sourceVersion.versionNumber() + 1,
                sourceVersion.versionId(), null, "USER_EDIT", sourceVersion.title(), totalCost,
                sourceVersion.provider(), sourceVersion.constraintSnapshotJson(), Instant.now()
        )), "itinerary edit version");
        versionPersister.copyKnowledge(sourceVersion.versionId(), versionId, "itinerary edit knowledge");

        for (int dayIndex = 0; dayIndex < itinerary.days().size(); dayIndex++) {
            EditableDay day = itinerary.days().get(dayIndex);
            UUID newDayId = UUID.randomUUID();
            requireOne(itineraryMapper.insertDay(new ItineraryMapper.DayWrite(
                    newDayId, versionId, day.date(), dayIndex
            )), "itinerary edit day");
            Map<UUID, UUID> activityIds = new HashMap<>();
            for (int activityIndex = 0; activityIndex < day.activities().size(); activityIndex++) {
                EditableActivity activity = day.activities().get(activityIndex);
                UUID newActivityId = UUID.randomUUID();
                activityIds.put(activity.id(), newActivityId);
                requireOne(itineraryMapper.insertActivity(new ItineraryMapper.ActivityWrite(
                    newActivityId, newDayId, activityIndex, activity.title(), activity.startTime(),
                        activity.endTime(), activity.estimatedCost(), activity.source(), activity.providerPoiId(),
                        activity.longitude(), activity.latitude(), activity.address(), activity.locked()
                )), "itinerary edit activity");
            }
            if (!day.transitNeedsRefresh) {
                copyTransitLegs(day.transitLegs(), newDayId, activityIds);
            }
        }
        requireOne(itineraryMapper.updateCurrentVersion(sourceVersion.itineraryId(), versionId),
                "current itinerary version");
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
                    leg.locked()
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
                activity.address(), activity.locked()
        );
    }

    private TransitLegResponse toTransitLegResponse(ItineraryMapper.StoredTransitLeg leg) {
        return new TransitLegResponse(
                leg.id(), leg.legOrder(), leg.fromActivityId(), leg.toActivityId(), leg.mode(),
                leg.distanceMeters(), leg.durationSeconds(), leg.provider(), leg.estimated(),
                readPolyline(leg.polylineJson()), leg.locked()
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
            List<LocalDate> impactedDates,
            List<UUID> impactedActivityIds,
            List<String> warnings,
            List<EditBlockingReason> blockingReasons
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
            Instant createdAt
    ) {
    }

    public record DayResponse(
            LocalDate date,
            List<ActivityResponse> activities,
            List<TransitLegResponse> transitLegs
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
            boolean locked
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
            boolean locked
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
            EditBlockingReason blockingReason
    ) {
        static EditEvaluation allowed(EditOperation operation, EditImpact impact) {
            return new EditEvaluation(operation, impact, null);
        }

        static EditEvaluation blocked(String code, String message) {
            return new EditEvaluation(null, new EditImpact(List.of(), List.of(), List.of()),
                    new EditBlockingReason(code, message));
        }

        boolean canApply() {
            return blockingReason == null;
        }

        ItineraryEditPreviewResponse toPreview(String requestedOperation) {
            return new ItineraryEditPreviewResponse(
                    requestedOperation, canApply(), impact.dates(), impact.activityIds(), impact.warnings(),
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
        private boolean transitNeedsRefresh;

        private EditableDay(
                LocalDate date,
                List<EditableActivity> activities,
                List<ItineraryMapper.StoredTransitLeg> transitLegs) {
            this.date = date;
            this.activities = activities;
            this.transitLegs = transitLegs;
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
            boolean locked
    ) {
        EditableActivity withLocked(boolean value) {
            return new EditableActivity(
                    id, title, startTime, endTime, estimatedCost, source, providerPoiId,
                    longitude, latitude, address, value
            );
        }

        EditableActivity withSchedule(OffsetDateTime start, OffsetDateTime end) {
            return new EditableActivity(
                    id, title, start, end, estimatedCost, source, providerPoiId,
                    longitude, latitude, address, locked
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
        requireOne(
                itineraryMapper.insertVersion(new ItineraryMapper.VersionWrite(
                        versionId, itinerary.id(), versionNumber,
                        itinerary.currentVersionId(), planningTaskId,
                        "PLANNING_TASK", result.title().strip(),
                        result.estimatedTotalCost(), event.payload().provider(),
                        constraintSnapshotJson, now
                )),
                "itinerary version"
        );
        versionPersister.persistKnowledge(
                versionId, event.payload().knowledge(),
                "itinerary knowledge evidence"
        );
        for (int dayIndex = 0; dayIndex < result.days().size(); dayIndex++) {
            persistDay(versionId, dayIndex, result.days().get(dayIndex));
        }
        requireOne(
                itineraryMapper.updateCurrentVersion(itinerary.id(), versionId),
                "current version"
        );
        return new CreateItineraryResult(
                versionId, versionNumber, event.payload().provider()
        );
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
        requireOne(
                itineraryMapper.insertVersion(new ItineraryMapper.VersionWrite(
                        versionId, source.itineraryId(),
                        source.versionNumber() + 1, source.id(), task.id(),
                        "LOCAL_REPLAN", source.title(),
                        source.estimatedTotalCost(), source.provider(),
                        source.constraintSnapshotJson(), now
                )),
                "local replan itinerary version"
        );
        versionPersister.copyKnowledge(
                source.id(), versionId, "local replan knowledge");

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
                            sourceDay.date(), sourceDay.dayIndex()
                    )),
                    "local replan day"
            );
            List<UUID> activityIds =
                    persistSourceActivities(targetDayId, activities);
            List<ItineraryMapper.StoredTransitLeg> sourceTransitLegs =
                    itineraryMapper.findTransitLegs(sourceDay.id());
            if (impactedDates.contains(sourceDay.date())) {
                persistResultTransit(
                        targetDayId, activityIds,
                        sourceTransitLegs, resultDay.transitLegs()
                );
            } else {
                copyTransitLegsFromSource(
                        targetDayId, activityIds,
                        activities, sourceTransitLegs
                );
            }
        }
        requireOne(
                itineraryMapper.updateCurrentVersion(
                        itinerary.id(), versionId),
                "current itinerary version"
        );
        return new CreateItineraryResult(
                versionId, source.versionNumber() + 1, source.provider()
        );
    }

    // ---- planning-completion helpers (moved from PlanningCompletionService) --

    private void persistDay(
            UUID versionId, int dayIndex, PlanningCompletedEvent.Day day) {
        UUID dayId = UUID.randomUUID();
        requireOne(
                itineraryMapper.insertDay(
                        new ItineraryMapper.DayWrite(
                                dayId, versionId, day.date(), dayIndex
                        )
                ),
                "itinerary day"
        );
        List<UUID> activityIds = new ArrayList<>(day.activities().size());
        for (int activityIndex = 0;
                activityIndex < day.activities().size();
                activityIndex++) {
            PlanningCompletedEvent.Activity activity =
                    day.activities().get(activityIndex);
            PlanningCompletedEvent.Coordinates coordinates =
                    activity.coordinates();
            UUID activityId = UUID.randomUUID();
            activityIds.add(activityId);
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
                                    activity.address(), false
                            )
                    ),
                    "itinerary activity"
            );
        }
        for (int legIndex = 0;
                legIndex < day.transitLegs().size();
                legIndex++) {
            PlanningCompletedEvent.TransitLeg leg =
                    day.transitLegs().get(legIndex);
            requireOne(
                    itineraryMapper.insertTransitLeg(
                            new ItineraryMapper.TransitLegWrite(
                                    UUID.randomUUID(), dayId, legIndex,
                                    activityIds.get(leg.fromActivityIndex()),
                                    activityIds.get(leg.toActivityIndex()),
                                    leg.mode(), leg.distanceMeters(),
                                    leg.durationSeconds(), leg.provider(),
                                    leg.estimated(),
                                    writeJson(leg.polyline()), false
                            )
                    ),
                    "itinerary transit leg"
            );
        }
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
                                    activity.locked()
                            )
                    ),
                    "local replan activity"
            );
        }
        return activityIds;
    }

    private void persistResultTransit(
            UUID dayId,
            List<UUID> activityIds,
            List<ItineraryMapper.StoredTransitLeg> sourceLegs,
            List<PlanningCompletedEvent.TransitLeg> legs) {
        for (int index = 0; index < legs.size(); index++) {
            PlanningCompletedEvent.TransitLeg leg = legs.get(index);
            if (leg.fromActivityIndex() >= activityIds.size()
                    || leg.toActivityIndex() >= activityIds.size()) {
                throw rejected(
                        "Local replanning returned an invalid transit leg");
            }
            UUID fromActivityId =
                    activityIds.get(leg.fromActivityIndex());
            UUID toActivityId =
                    activityIds.get(leg.toActivityIndex());
            requireOne(
                    itineraryMapper.insertTransitLeg(
                            new ItineraryMapper.TransitLegWrite(
                                    UUID.randomUUID(), dayId, index,
                                    fromActivityId, toActivityId,
                                    leg.mode(), leg.distanceMeters(),
                                    leg.durationSeconds(), leg.provider(),
                                    leg.estimated(),
                                    writeJson(leg.polyline()),
                                    index < sourceLegs.size()
                                            && sourceLegs.get(index).locked()
                            )
                    ),
                    "local replan transit leg"
            );
        }
    }

    private void copyTransitLegsFromSource(
            UUID dayId,
            List<UUID> activityIds,
            List<ItineraryMapper.StoredActivity> activities,
            List<ItineraryMapper.StoredTransitLeg> legs) {
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
            requireOne(
                    itineraryMapper.insertTransitLeg(
                            new ItineraryMapper.TransitLegWrite(
                                    UUID.randomUUID(), dayId, index,
                                    fromActivityId, toActivityId,
                                    leg.mode(), leg.distanceMeters(),
                                    leg.durationSeconds(), leg.provider(),
                                    leg.estimated(), leg.polylineJson(),
                                    leg.locked()
                            )
                    ),
                    "local replan transit leg"
            );
        }
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
                            source.address(), result.address())) {
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
            String provider
    ) {
    }
}
