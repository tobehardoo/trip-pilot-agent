package io.github.tobehardoo.trippilot.itinerary;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.WeakHashMap;

import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.planning.PlanningTaskService;
import io.github.tobehardoo.trippilot.route.AgentRouteClient;
import io.github.tobehardoo.trippilot.route.AgentRouteDtos;
import io.github.tobehardoo.trippilot.trip.TripService;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

/**
 * Keeps synchronous route recommendation outside the candidate-validation
 * transaction. The worker remains the authority that validates and reroutes
 * the complete candidate before a formal itinerary version is persisted.
 */
@Service
public class ItineraryEditRoutingCoordinator {

    private static final List<String> PROVIDER_MODES =
            List.of("WALKING", "TRANSIT", "DRIVING");

    /**
     * F7: per (tripId, idempotencyKey) monitors serializing AUTO resolution.
     * Concurrent requests with the same key used to both call the external
     * route service before the DB idempotency reservation rejected one; the
     * loser must replay the winner's task, never recommend again.  Weak keys
     * so finished keys can be collected.
     */
    private final Map<String, Object> autoLocks =
            Collections.synchronizedMap(new WeakHashMap<>());

    private final ItineraryService itineraryService;
    private final PlanningTaskService planningTaskService;
    private final TripService tripService;
    private final AgentRouteClient routeClient;

    public ItineraryEditRoutingCoordinator(
            ItineraryService itineraryService,
            PlanningTaskService planningTaskService,
            TripService tripService,
            AgentRouteClient routeClient
    ) {
        this.itineraryService = itineraryService;
        this.planningTaskService = planningTaskService;
        this.tripService = tripService;
        this.routeClient = routeClient;
    }

    private Object autoLock(UUID tripId, UUID idempotencyKey) {
        String key = tripId + ":" + idempotencyKey;
        synchronized (autoLocks) {
            return autoLocks.computeIfAbsent(key, ignored -> new Object());
        }
    }

    public PlanningTaskService.PlanningTaskResponse validateEditCandidate(
            UUID ownerId,
            UUID tripId,
            UUID idempotencyKey,
            ItineraryService.ItineraryEditRequest request,
            String requestHash
    ) {
        if (request == null || request.baseVersionId() == null) {
            return itineraryService.validateEditCandidate(
                    ownerId, tripId, idempotencyKey, request, requestHash);
        }
        rejectExplicitDriving(request);
        var replay = planningTaskService.replayCandidateValidation(
                ownerId, tripId, idempotencyKey, "EDIT",
                request.baseVersionId(), request.baseVersionId(), requestHash);
        if (replay.isPresent()) {
            return replay.get();
        }
        ItineraryService.ItineraryEditRequest resolved = request;
        if ("AUTO".equals(request.transitMode())) {
            ItineraryService.ItineraryResponse current = currentBaseline(
                    ownerId, tripId, request.baseVersionId());
            TripService.TripResponse trip = tripService.get(ownerId, tripId);
            resolved = resolveAuto(current, current, trip, request);
        }
        return itineraryService.validateEditCandidate(
                ownerId, tripId, idempotencyKey, resolved, requestHash);
    }

    public PlanningTaskService.PlanningTaskResponse validateEditCandidates(
            UUID ownerId,
            UUID tripId,
            UUID idempotencyKey,
            ItineraryService.ItineraryBatchEditRequest request,
            String requestHash
    ) {
        if (request == null || request.baseVersionId() == null) {
            return itineraryService.validateEditCandidates(
                    ownerId, tripId, idempotencyKey, request, requestHash);
        }
        if (request.edits() != null) {
            request.edits().stream()
                    .filter(java.util.Objects::nonNull)
                    .forEach(this::rejectExplicitDriving);
        }
        var replay = planningTaskService.replayCandidateValidation(
                ownerId, tripId, idempotencyKey, "EDIT",
                request.baseVersionId(), request.baseVersionId(), requestHash);
        if (replay.isPresent()) {
            return replay.get();
        }
        if (request.edits() == null || request.edits().isEmpty()) {
            return itineraryService.validateEditCandidates(
                    ownerId, tripId, idempotencyKey, request, requestHash);
        }
        boolean hasAuto = request.edits().stream()
                .filter(java.util.Objects::nonNull)
                .anyMatch(edit -> "AUTO".equals(edit.transitMode()));
        if (!hasAuto) {
            return itineraryService.validateEditCandidates(
                    ownerId, tripId, idempotencyKey, request, requestHash);
        }
        // F7: serialize AUTO batches per (tripId, idempotencyKey) so that
        // concurrent requests with the same key resolve (and call the route
        // service) exactly once; the loser hits the replay path below.
        synchronized (autoLock(tripId, idempotencyKey)) {
            var serializedReplay = planningTaskService.replayCandidateValidation(
                    ownerId, tripId, idempotencyKey, "EDIT",
                    request.baseVersionId(), request.baseVersionId(), requestHash);
            if (serializedReplay.isPresent()) {
                return serializedReplay.get();
            }
            for (ItineraryService.ItineraryEditRequest edit : request.edits()) {
                if (edit == null || !request.baseVersionId().equals(edit.baseVersionId())) {
                    throw new ApiException(
                            HttpStatus.CONFLICT, "ITINERARY_VERSION_CONFLICT",
                            "The itinerary draft does not match the current version");
                }
            }
            ItineraryService.ItineraryResponse current = currentBaseline(
                    ownerId, tripId, request.baseVersionId());
            TripService.TripResponse trip = tripService.get(ownerId, tripId);
            // F1: resolve AUTO edits against the itinerary AS EDITED by the
            // preceding edits (a prior MOVE shifts the OD/departure time the
            // recommendation sees), never against the untouched baseline.
            List<ItineraryService.ItineraryEditRequest> resolved = new ArrayList<>();
            ItineraryService.ItineraryResponse working = current;
            for (ItineraryService.ItineraryEditRequest edit : request.edits()) {
                resolved.add("AUTO".equals(edit.transitMode())
                        ? resolveAuto(current, working, trip, edit) : edit);
                working = itineraryService.simulateEdits(
                        ownerId, tripId, request.baseVersionId(), List.copyOf(resolved));
            }
            return itineraryService.validateEditCandidates(
                    ownerId, tripId, idempotencyKey,
                    new ItineraryService.ItineraryBatchEditRequest(
                            request.baseVersionId(), List.copyOf(resolved)),
                    requestHash);
        }
    }

    private ItineraryService.ItineraryResponse currentBaseline(
            UUID ownerId,
            UUID tripId,
            UUID baseVersionId
    ) {
        ItineraryService.ItineraryResponse current =
                itineraryService.getCurrent(ownerId, tripId);
        if (!baseVersionId.equals(current.versionId())) {
            throw new ApiException(
                    HttpStatus.CONFLICT, "ITINERARY_VERSION_CONFLICT",
                    "The itinerary was updated. Reload it before applying this edit");
        }
        return current;
    }

    private ItineraryService.ItineraryEditRequest resolveAuto(
            ItineraryService.ItineraryResponse itinerary,
            ItineraryService.ItineraryResponse working,
            TripService.TripResponse trip,
            ItineraryService.ItineraryEditRequest request
    ) {
        LocatedTransit located = locateTransit(itinerary, request.transitLegId());
        if (located.leg().locked()) {
            throw new ApiException(
                    HttpStatus.CONFLICT, "ITINERARY_TRANSIT_LEG_LOCKED",
                    "A locked transit leg cannot change its mode");
        }
        requireCoordinates(located.from());
        requireCoordinates(located.to());
        // F1: the departure time must reflect the FROM activity as EDITED by
        // the preceding batch edits (a prior MOVE shifts it).  The working
        // view carries the updated activity times; coordinates do not change
        // on a MOVE, so they come from the baseline leg location.
        java.time.OffsetDateTime departure = findActivityEndTime(working, located.from().id())
                .orElse(located.from().endTime());
        AgentRouteDtos.RecommendRequest routeRequest =
                new AgentRouteDtos.RecommendRequest(
                        coordinates(located.from().coordinates()),
                        coordinates(located.to().coordinates()),
                        departure,
                        located.from().providerPoiId(),
                        located.to().providerPoiId(),
                        trip.destination(),
                        trip.constraints().mobilityLevel());
        AgentRouteDtos.Recommendation recommendation =
                routeClient.recommend(routeRequest);
        validateRecommendation(recommendation);
        return new ItineraryService.ItineraryEditRequest(
                request.baseVersionId(), request.operation(), request.activityId(),
                request.transitLegId(), request.targetDate(), request.targetOrder(),
                request.targetStartTime(), request.targetEndTime(),
                recommendation.selectedMode(), request.transitLocked(),
                request.newTitle(), request.newPoiId(),
                request.newLongitude(), request.newLatitude(),
                request.newAddress(), request.newTypeName(), request.newKind());
    }

    private java.util.Optional<java.time.OffsetDateTime> findActivityEndTime(
            ItineraryService.ItineraryResponse itinerary,
            UUID activityId
    ) {
        for (ItineraryService.DayResponse day : itinerary.days()) {
            for (ItineraryService.ActivityResponse activity : day.activities()) {
                if (activity.id().equals(activityId)) {
                    return java.util.Optional.of(activity.endTime());
                }
            }
        }
        return java.util.Optional.empty();
    }

    private LocatedTransit locateTransit(
            ItineraryService.ItineraryResponse itinerary,
            UUID transitLegId
    ) {
        if (transitLegId == null) {
            throw invalid("A transit leg must be selected");
        }
        List<LocatedTransit> matches = new ArrayList<>();
        for (ItineraryService.DayResponse day : itinerary.days()) {
            for (ItineraryService.TransitLegResponse leg : day.transitLegs()) {
                if (!transitLegId.equals(leg.id())) {
                    continue;
                }
                ItineraryService.ActivityResponse from = day.activities().stream()
                        .filter(activity -> leg.fromActivityId().equals(activity.id()))
                        .findFirst().orElse(null);
                ItineraryService.ActivityResponse to = day.activities().stream()
                        .filter(activity -> leg.toActivityId().equals(activity.id()))
                        .findFirst().orElse(null);
                matches.add(new LocatedTransit(leg, from, to));
            }
        }
        if (matches.size() != 1 || matches.getFirst().from() == null
                || matches.getFirst().to() == null) {
            throw invalid("The selected transit leg is not in this itinerary");
        }
        return matches.getFirst();
    }

    private void validateRecommendation(AgentRouteDtos.Recommendation recommendation) {
        if (recommendation == null || !PROVIDER_MODES.contains(recommendation.selectedMode())
                || recommendation.route() == null
                || !recommendation.selectedMode().equals(recommendation.route().mode())
                || !"AMAP".equals(recommendation.route().provider())
                || recommendation.route().estimated()
                || recommendation.route().polyline().isEmpty()
                || recommendation.providerCallsUsed() < 1
                || recommendation.providerCallsUsed() > 3) {
            throw new ApiException(
                    HttpStatus.BAD_GATEWAY, "ROUTE_PROVIDER_INVALID_RESPONSE",
                    "Route service returned an invalid recommendation");
        }
    }

    private void requireCoordinates(ItineraryService.ActivityResponse activity) {
        if (activity.coordinates() == null
                || activity.coordinates().longitude() == null
                || activity.coordinates().latitude() == null) {
            throw invalid("Transit endpoints require coordinates for AUTO routing");
        }
    }

    private AgentRouteDtos.Coordinates coordinates(
            ItineraryService.CoordinatesResponse coordinates
    ) {
        return new AgentRouteDtos.Coordinates(
                coordinates.longitude(), coordinates.latitude());
    }

    private ApiException invalid(String message) {
        return new ApiException(
                HttpStatus.UNPROCESSABLE_ENTITY,
                "ITINERARY_TRANSIT_LEG_NOT_FOUND", message);
    }

    private void rejectExplicitDriving(ItineraryService.ItineraryEditRequest request) {
        if ("DRIVING".equals(request.transitMode())) {
            throw new ApiException(
                    HttpStatus.UNPROCESSABLE_ENTITY,
                    "ITINERARY_EDIT_INVALID",
                    "DRIVING is a technical route mode; select TAXI for a road journey");
        }
    }

    private record LocatedTransit(
            ItineraryService.TransitLegResponse leg,
            ItineraryService.ActivityResponse from,
            ItineraryService.ActivityResponse to
    ) {
    }
}
