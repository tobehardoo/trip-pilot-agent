package io.github.tobehardoo.trippilot.itinerary;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.persistence.PersistenceSupport;
import io.github.tobehardoo.trippilot.planning.PlanningFactImpactMapper;
import io.github.tobehardoo.trippilot.route.AgentRouteClient;
import io.github.tobehardoo.trippilot.route.AgentRouteDtos;
import io.github.tobehardoo.trippilot.trip.TripMapper;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

/**
 * The user edit engine: reads an editable in-memory itinerary, evaluates edit
 * requests against it, applies edits, and persists a new edited version.
 * Split out of {@link ItineraryService}; always called inside a facade-level
 * transaction, so it carries no transaction annotations of its own.
 */
@Component
public class ItineraryEditEngine {

    private static final String TRANSIT_REFRESH_WARNING =
            "Transit routes for impacted days will be refreshed by local replanning";

    private final ItineraryMapper itineraryMapper;
    private final ItineraryVersionPersister versionPersister;
    private final ObjectMapper objectMapper;
    private final AgentRouteClient routeClient;
    private final TripMapper tripMapper;
    private final PlanningFactImpactMapper factImpactMapper;
    private final ItineraryResponseAssembler responseAssembler;

    public ItineraryEditEngine(
            ItineraryMapper itineraryMapper,
            ItineraryVersionPersister versionPersister,
            ObjectMapper objectMapper,
            AgentRouteClient routeClient,
            TripMapper tripMapper,
            PlanningFactImpactMapper factImpactMapper,
            ItineraryResponseAssembler responseAssembler
    ) {
        this.itineraryMapper = itineraryMapper;
        this.versionPersister = versionPersister;
        this.objectMapper = objectMapper;
        this.routeClient = routeClient;
        this.tripMapper = tripMapper;
        this.factImpactMapper = factImpactMapper;
        this.responseAssembler = responseAssembler;
    }

    public EditableItinerary readEditableItinerary(UUID versionId, UUID tripId) {
        // The trip destination scopes TRANSIT route lookups (AMap transit is
        // city-scoped); WALKING/DRIVING ignore it.
        String city = tripMapper.findById(tripId)
                .map(trip -> trip.destination())
                .orElse(null);
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
        return new EditableItinerary(days, city);
    }

    private EditableActivity toEditableActivity(ItineraryMapper.StoredActivity activity) {
        return new EditableActivity(
                activity.id(), activity.title(), activity.startTime(), activity.endTime(),
                activity.estimatedCost(), activity.source(), activity.providerPoiId(),
                activity.longitude(), activity.latitude(), activity.address(), activity.locked(),
                activity.typeCode(), activity.typeName(), activity.kind(), activity.timeFixed(),
                activity.costSource() == null ? "UNKNOWN" : activity.costSource()
        );
    }

    public EditEvaluation evaluate(
            EditableItinerary itinerary,
            ItineraryService.ItineraryEditRequest request,
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
            case REPLACE_ACTIVITY -> evaluateReplace(itinerary, request, location);
            case UPDATE_TRANSIT_LEG -> throw new IllegalStateException("Transit leg edits are evaluated separately");
        };
    }

    private EditEvaluation evaluateReplace(
            EditableItinerary itinerary, ItineraryService.ItineraryEditRequest request, ActivityLocation source) {
        // 功能①：替换真实地点。校验请求字段；时间的可行性校验由编辑任务
        // （EDIT_VALIDATE → local replan）对替换后的行程统一执行。
        if (source.activity().locked()) {
            return EditEvaluation.blocked("ITINERARY_ACTIVITY_LOCKED", "A locked activity cannot be replaced");
        }
        boolean hasTitle = request.newTitle() != null && !request.newTitle().isBlank();
        boolean hasPoi = request.newPoiId() != null && !request.newPoiId().isBlank();
        if (!hasTitle && !hasPoi) {
            return EditEvaluation.blocked("ITINERARY_EDIT_INVALID",
                    "Replacing an activity requires a new place title or POI id");
        }
        if ((request.newLongitude() == null) != (request.newLatitude() == null)) {
            return EditEvaluation.blocked("ITINERARY_EDIT_INVALID",
                    "A new place must carry both longitude and latitude or neither");
        }
        return EditEvaluation.allowed(
                EditOperation.REPLACE_ACTIVITY,
                impacted(source.day(), List.of(source.activity().id()), true)
        );
    }

    private EditEvaluation evaluateTransitLeg(
            EditableItinerary itinerary,
            ItineraryService.ItineraryEditRequest request,
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
            EditableItinerary itinerary, ItineraryService.ItineraryEditRequest request, ActivityLocation source) {
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

    public void apply(
            EditableItinerary itinerary,
            ItineraryService.ItineraryEditRequest request,
            EditOperation operation,
            boolean refreshRouteFacts) {
        if (operation == EditOperation.UPDATE_TRANSIT_LEG) {
            TransitLocation location = itinerary.findTransitLeg(request.transitLegId());
            if (location == null) {
                throw new IllegalStateException("Validated transit leg was not found");
            }
            ItineraryMapper.StoredTransitLeg leg = location.leg();
            location.day().transitLegs().set(
                    location.index(),
                    applyTransitLegEdit(
                            itinerary, leg, request.transitMode(), request.transitLocked(),
                            refreshRouteFacts)
            );
            return;
        }
        ActivityLocation source = itinerary.findActivity(request.activityId());
        if (source == null) {
            throw new IllegalStateException("Validated activity was not found");
        }
        switch (operation) {
            case DELETE_ACTIVITY -> {
                // AUDIT-FIX：删除活动必须先清理引用它的 transit legs ——
                // Python 端 ReplanItineraryDay 校验 transit 必须连接相邻活动，
                // 残留的孤儿 transit（from/to 指向被删活动）会让编辑任务命令
                // 解析失败（COMMAND_VALIDATION_FAILED），导致删除不生效。
                UUID deletedActivityId = source.activity().id();
                source.day().transitLegs().removeIf(
                        leg -> deletedActivityId.equals(leg.fromActivityId())
                                || deletedActivityId.equals(leg.toActivityId())
                );
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
                // AUDIT-FIX：仅跨天移动时，原天残留引用被移走活动的 transit 会形成
                // 孤儿（Python 端要求 transit 连接相邻活动），需一并清理；同一天内
                // 重排时活动仍在原天，transit 仍连接相邻活动，交由下游 replan 重算。
                if (!target.date().equals(source.day().date())) {
                    UUID movedActivityId = source.activity().id();
                    source.day().transitLegs().removeIf(
                            leg -> movedActivityId.equals(leg.fromActivityId())
                                    || movedActivityId.equals(leg.toActivityId())
                    );
                }
                source.day().activities().remove(source.index());
                EditableActivity moved = source.activity().withSchedule(
                        request.targetStartTime(), request.targetEndTime()
                );
                target.activities().add(request.targetOrder(), moved);
                source.day().transitNeedsRefresh = true;
                target.transitNeedsRefresh = true;
            }
            case REPLACE_ACTIVITY -> {
                // 功能①：替换为真实地点（保留 id/时间/费用/来源），
                // transit 由下游编辑任务（local replan）重新计算。
                source.day().activities().set(
                        source.index(),
                        source.activity().withPlace(
                                request.newTitle(), request.newPoiId(),
                                request.newLongitude(), request.newLatitude(),
                                request.newAddress(), request.newTypeName(), request.newKind()
                        )
                );
                source.day().transitNeedsRefresh = true;
            }
        }
    }

    private ItineraryMapper.StoredTransitLeg applyTransitLegEdit(
            EditableItinerary itinerary,
            ItineraryMapper.StoredTransitLeg leg,
            String requestedMode,
            Boolean requestedLocked,
            boolean refreshRouteFacts) {
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
        if (!refreshRouteFacts) {
            // Simulation (working view for later batch edits): keep the old
            // route facts but mark them stale — they no longer describe the
            // requested mode, and no provider call is spent here.
            return new ItineraryMapper.StoredTransitLeg(
                    leg.id(), leg.legOrder(), leg.fromActivityId(), leg.toActivityId(),
                    mode, leg.distanceMeters(), leg.durationSeconds(), leg.provider(),
                    true, leg.polylineJson(), locked, leg.estimatedCost(),
                    leg.providerRouteId(), leg.calculatedAt(), true
            );
        }
        // Manual-edit TRANSIT realification (P2.9): a mode change is refreshed
        // against the provider right away instead of persisting a speed-model
        // estimate.  The downstream candidate worker still re-validates the
        // leg with fresh provider facts; this snapshot is persisted so the
        // candidate never carries fabricated duration/cost data.
        EditableActivity from = requireLegEndpoint(itinerary, leg.fromActivityId());
        EditableActivity to = requireLegEndpoint(itinerary, leg.toActivityId());
        if (from.longitude() == null || from.latitude() == null
                || to.longitude() == null || to.latitude() == null) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "ITINERARY_EDIT_INVALID",
                    "The transit endpoints carry no coordinates to route against");
        }
        // TAXI rides on the DRIVING road route and the rule fare; the wire
        // keeps the request/persisted mode distinction (F8).
        String providerMode = "TAXI".equals(mode) ? "DRIVING" : mode;
        if ("TRANSIT".equals(providerMode) && (itinerary.city() == null || itinerary.city().isBlank())) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "ITINERARY_EDIT_INVALID",
                    "A transit route requires the trip destination");
        }
        AgentRouteDtos.RouteFacts facts;
        try {
            facts = routeClient.route(new AgentRouteDtos.RouteRequest(
                    new AgentRouteDtos.Coordinates(from.longitude(), from.latitude()),
                    new AgentRouteDtos.Coordinates(to.longitude(), to.latitude()),
                    providerMode,
                    from.endTime(),
                    from.providerPoiId(),
                    to.providerPoiId(),
                    itinerary.city()
            ));
        } catch (RuntimeException exception) {
            // Fail closed: an unavailable provider never persists fabricated
            // route facts for the edited leg.
            throw new ApiException(HttpStatus.BAD_GATEWAY, "ITINERARY_TRANSIT_ROUTE_UNAVAILABLE",
                    "The route provider could not refresh this transit leg; the edit was not applied");
        }
        BigDecimal cost = "TAXI".equals(mode)
                ? TransitLegSemantics.taxiFare(facts.distanceMeters())
                : facts.estimatedCost();
        // The presentation layer stores TAXI durations inclusive of the wait
        // time; a real road route shorter than the wait would violate that
        // invariant, so the wait floors the stored duration.
        int durationSeconds = "TAXI".equals(mode)
                ? Math.max(facts.durationSeconds(), TransitLegSemantics.TAXI_WAIT_SECONDS)
                : facts.durationSeconds();
        return new ItineraryMapper.StoredTransitLeg(
                leg.id(), leg.legOrder(), leg.fromActivityId(), leg.toActivityId(),
                mode, facts.distanceMeters(), durationSeconds, facts.provider(),
                facts.estimated(), writePolyline(facts.polyline()), locked, cost,
                null, Instant.now(), false
        );
    }

    private EditableActivity requireLegEndpoint(EditableItinerary itinerary, UUID activityId) {
        ActivityLocation location = itinerary.findActivity(activityId);
        if (location == null) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "ITINERARY_EDIT_INVALID",
                    "The transit leg references an activity outside the itinerary");
        }
        return location.activity();
    }

    private String writePolyline(List<AgentRouteDtos.Coordinates> polyline) {
        try {
            return objectMapper.writeValueAsString(polyline);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Route polyline could not be serialized", exception);
        }
    }

    public BigDecimal budgetFrom(String constraintSnapshotJson) {
        try {
            var budget = objectMapper.readTree(constraintSnapshotJson).get("budgetAmount");
            return budget == null || budget.isNull() ? null : budget.decimalValue();
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Could not read itinerary budget snapshot", exception);
        }
    }

    public UUID persistEditedVersion(
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
                        activity.typeCode(), activity.typeName(), activity.kind(), activity.timeFixed(),
                        activity.costSource()
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

    public ItineraryService.ItineraryResponse toCandidateResponse(
            ItineraryMapper.EditableCurrentVersion version,
            EditableItinerary itinerary
    ) {
        List<ItineraryService.DayResponse> days = itinerary.days().stream().map(day -> {
            Map<UUID, Integer> orders = new HashMap<>();
            List<ItineraryService.ActivityResponse> activities = new ArrayList<>();
            for (int index = 0; index < day.activities().size(); index++) {
                EditableActivity activity = day.activities().get(index);
                orders.put(activity.id(), index);
                activities.add(new ItineraryService.ActivityResponse(
                        activity.id(), activity.title(), activity.startTime(), activity.endTime(),
                        activity.estimatedCost(), activity.source(), activity.providerPoiId(),
                        activity.longitude() == null ? null : new ItineraryService.CoordinatesResponse(
                                activity.longitude(), activity.latitude()),
                        activity.address(), activity.locked(), activity.typeCode(),
                        activity.typeName(), activity.kind(), activity.timeFixed(),
                        activity.costSource() == null ? "UNKNOWN" : activity.costSource()
                ));
            }
            List<ItineraryService.TransitLegResponse> transit = day.transitNeedsRefresh
                    ? List.of()
                    : day.transitLegs().stream()
                            .filter(leg -> orders.containsKey(leg.fromActivityId())
                                    && orders.containsKey(leg.toActivityId()))
                            .map(responseAssembler::toTransitLegResponse)
                            .toList();
            return new ItineraryService.DayResponse(day.date(), activities, transit, day.dayType());
        }).toList();
        return new ItineraryService.ItineraryResponse(
                version.versionId(), version.versionNumber(), version.parentVersionId(),
                version.title(), itinerary.totalCost(),
                version.provider(), days,
                responseAssembler.toKnowledgeResponse(version.versionId()), List.of(),
                null, null, List.of(), version.createdAt(), null
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
        PersistenceSupport.requireOne(updatedRows, operation);
    }

    enum EditOperation {
        DELETE_ACTIVITY,
            LOCK_ACTIVITY,
            UNLOCK_ACTIVITY,
        MOVE_ACTIVITY,
        REPLACE_ACTIVITY,
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

    record EditImpact(
            List<LocalDate> dates,
            List<UUID> activityIds,
            List<String> warnings
    ) {
    }

    record EditEvaluation(
            EditOperation operation,
            EditImpact impact,
            ItineraryService.EditBlockingReason blockingReason,
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
                    new ItineraryService.EditBlockingReason(code, message), false, selectionState);
        }

        static EditEvaluation requiresReplan(
                EditOperation operation, EditImpact impact, String code, String message) {
            EditImpact replanImpact = new EditImpact(
                    impact.dates(), impact.activityIds(),
                    List.of("The selected transit mode requires schedule replanning")
            );
            return new EditEvaluation(operation, replanImpact,
                    new ItineraryService.EditBlockingReason(code, message), true, "REQUIRES_REPLAN");
        }

        boolean canApply() {
            return blockingReason == null;
        }

        ItineraryService.ItineraryEditPreviewResponse toPreview(String requestedOperation) {
            return new ItineraryService.ItineraryEditPreviewResponse(
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

    static final class EditableItinerary {
        private final List<EditableDay> days;
        private final String city;

        private EditableItinerary(List<EditableDay> days, String city) {
            this.days = days;
            this.city = city;
        }

        List<EditableDay> days() {
            return days;
        }

        String city() {
            return city;
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

    static final class EditableDay {
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

    record EditableActivity(
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
            boolean timeFixed,
            String costSource
    ) {
        EditableActivity withLocked(boolean value) {
            return new EditableActivity(
                    id, title, startTime, endTime, estimatedCost, source, providerPoiId,
                    longitude, latitude, address, value, typeCode, typeName, kind,
                    timeFixed, costSource
            );
        }

        EditableActivity withSchedule(OffsetDateTime start, OffsetDateTime end) {
            return new EditableActivity(
                    id, title, start, end, estimatedCost, source, providerPoiId,
                    longitude, latitude, address, locked, typeCode, typeName, kind,
                    timeFixed, costSource
            );
        }

        /** 功能①：替换活动地点（保留 id/时间/费用/来源/锁定），供 REPLACE_ACTIVITY。 */
        EditableActivity withPlace(
                String newTitle, String newPoiId, BigDecimal newLng, BigDecimal newLat,
                String newAddress, String newTypeName, String newKind
        ) {
            return new EditableActivity(
                    id, newTitle, startTime, endTime, estimatedCost, source, newPoiId,
                    newLng, newLat, newAddress, locked,
                    typeCode, newTypeName != null ? newTypeName : typeName,
                    newKind != null ? newKind : kind, timeFixed, costSource
            );
        }
    }

    record ActivityLocation(EditableDay day, int index, EditableActivity activity) {
    }

    record TransitLocation(EditableDay day, int index, ItineraryMapper.StoredTransitLeg leg) {
    }
}
