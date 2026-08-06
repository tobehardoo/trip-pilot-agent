package io.github.tobehardoo.trippilot.trip;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.cityintelligence.CityIntelligencePrewarmService;
import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.trip.TripRequests.Accommodation;
import io.github.tobehardoo.trippilot.trip.TripRequests.ConstraintInput;
import io.github.tobehardoo.trippilot.trip.TripRequests.CreateTripRequest;
import io.github.tobehardoo.trippilot.trip.TripRequests.FixedSchedule;
import io.github.tobehardoo.trippilot.trip.TripRequests.MealWindow;
import io.github.tobehardoo.trippilot.trip.TripRequests.TravelAnchor;
import io.github.tobehardoo.trippilot.trip.TripRequests.UpdateConfigurationRequest;
import io.github.tobehardoo.trippilot.trip.TripRequests.UpdateConstraintRequest;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class TripService {

    private static final TypeReference<List<String>> STRING_LIST = new TypeReference<>() { };
    private static final TypeReference<List<FixedSchedule>> SCHEDULE_LIST = new TypeReference<>() { };
    private static final TypeReference<List<MealWindow>> MEAL_WINDOW_LIST = new TypeReference<>() { };

    private final TripMapper tripMapper;
    private final ObjectMapper objectMapper;
    private final TripConstraintValidator validator;
    private final TripDatePolicy datePolicy;
    private final CityIntelligencePrewarmService cityIntelligencePrewarmService;

    public TripService(
            TripMapper tripMapper,
            ObjectMapper objectMapper,
            TripConstraintValidator validator,
            TripDatePolicy datePolicy,
            CityIntelligencePrewarmService cityIntelligencePrewarmService
    ) {
        this.tripMapper = tripMapper;
        this.objectMapper = objectMapper;
        this.validator = validator;
        this.datePolicy = datePolicy;
        this.cityIntelligencePrewarmService = cityIntelligencePrewarmService;
    }

    @Transactional
    public TripResponse create(UUID ownerId, CreateTripRequest request) {
        datePolicy.validateNewTripStartDate(request.startDate());
        validator.validateDateRange(request.startDate(), request.endDate());
        validator.validateSchedules(request.constraints().fixedSchedules(), request.startDate(), request.endDate());
        validator.validateContext(request.constraints(), request.destination(), request.startDate(), request.endDate());
        UUID tripId = UUID.randomUUID();
        TripRecord trip = new TripRecord(
                tripId, ownerId, request.title().trim(), request.destination().trim(),
                request.startDate(), request.endDate(), "DRAFT", 0, null, null, null
        );
        tripMapper.insertTrip(trip);
        tripMapper.insertConstraint(toRecord(tripId, request.constraints()));
        cityIntelligencePrewarmService.request(
                tripId,
                trip.destination(),
                trip.startDate(),
                trip.endDate()
        );
        return get(ownerId, tripId);
    }

    @Transactional(readOnly = true)
    public List<TripResponse> list(UUID ownerId) {
        return tripMapper.findAllOwned(ownerId).stream().map(this::toResponse).toList();
    }

    @Transactional(readOnly = true)
    public TripPage search(UUID ownerId, TripSearch search) {
        TripSearch normalized = normalizeSearch(search);
        long totalElements = tripMapper.countSearchOwned(
                ownerId, normalized.destination(), normalized.status(), normalized.startDate(),
                normalized.endDate(), normalized.includeArchived()
        );
        int offset = Math.multiplyExact(normalized.page(), normalized.size());
        List<TripResponse> items = tripMapper.searchOwned(
                ownerId, normalized.destination(), normalized.status(), normalized.startDate(),
                normalized.endDate(), normalized.includeArchived(), normalized.size(), offset
        ).stream().map(this::toResponse).toList();
        int totalPages = (int) Math.ceil((double) totalElements / normalized.size());
        return new TripPage(items, normalized.page(), normalized.size(), totalElements, totalPages);
    }

    @Transactional(readOnly = true)
    public TripResponse get(UUID ownerId, UUID tripId) {
        return tripMapper.findOwnedSnapshot(tripId, ownerId)
                .map(this::toResponse)
                .orElseThrow(() -> new ApiException(
                        HttpStatus.NOT_FOUND, "TRIP_NOT_FOUND", "Trip was not found"
                ));
    }

    @Transactional
    public TripResponse updateConstraints(UUID ownerId, UUID tripId, UpdateConstraintRequest request) {
        TripRecord trip = findOwned(ownerId, tripId);
        validator.validateSchedules(request.fixedSchedules(), trip.startDate(), trip.endDate());
        validator.validateContext(request.asConstraintInput(), trip.destination(), trip.startDate(), trip.endDate());
        if (tripMapper.incrementVersion(tripId, ownerId, request.version()) != 1) {
            throw new ApiException(HttpStatus.CONFLICT, "TRIP_VERSION_CONFLICT",
                    "Trip was updated by another request; reload it before retrying");
        }
        tripMapper.updateConstraint(toRecord(tripId, request.asConstraintInput()));
        return get(ownerId, tripId);
    }

    /**
     * Updates trip metadata and constraints atomically under a single
     * optimistic-lock version bump. If either the metadata write or the
     * constraint write fails, the whole transaction rolls back so the trip can
     * never observe a half-applied configuration. Replanning stays a separate
     * operation; the current itinerary is implicitly stale until a replan
     * completes against the new version.
     */
    @Transactional
    public TripResponse updateConfiguration(UUID ownerId, UUID tripId, UpdateConfigurationRequest request) {
        TripRecord trip = findOwned(ownerId, tripId);
        validator.validateDateRange(request.startDate(), request.endDate());
        validator.validateSchedules(request.constraints().fixedSchedules(), request.startDate(), request.endDate());
        validator.validateContext(request.constraints(), request.destination(), request.startDate(), request.endDate());
        if (tripMapper.updateConfigurationMetadata(
                tripId, ownerId, request.version(),
                request.title().trim(), request.destination().trim(),
                request.startDate(), request.endDate()) != 1) {
            throw new ApiException(HttpStatus.CONFLICT, "TRIP_VERSION_CONFLICT",
                    "Trip was updated by another request; reload it before retrying");
        }
        tripMapper.updateConstraint(toRecord(tripId, request.constraints()));
        return get(ownerId, tripId);
    }

    @Transactional
    public void archive(UUID ownerId, UUID tripId) {
        findOwned(ownerId, tripId);
        tripMapper.archiveOwned(tripId, ownerId);
    }

    @Transactional
    public void restore(UUID ownerId, UUID tripId) {
        findOwned(ownerId, tripId);
        tripMapper.restoreOwned(tripId, ownerId);
    }

    private TripRecord findOwned(UUID ownerId, UUID tripId) {
        return tripMapper.findOwnedById(tripId, ownerId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "TRIP_NOT_FOUND", "Trip was not found"));
    }

    private TripConstraintRecord toRecord(UUID tripId, ConstraintInput input) {
        return new TripConstraintRecord(
                tripId, input.budgetAmount(), input.travelers(), input.travelerType(), input.pace(),
                writeJson(input.preferences()), writeJson(input.fixedSchedules()),
                writeNullableJson(input.arrival()), writeNullableJson(input.departure()),
                writeNullableJson(normalizeAccommodation(input.accommodation())),
                writeJson(input.mustVisitPlaces()),
                writeJson(input.avoidPlaces()), writeJson(input.mealWindows()),
                input.mobilityLevel(), 2, null
        );
    }

    private static Accommodation normalizeAccommodation(Accommodation accommodation) {
        if (accommodation == null) {
            return null;
        }
        if (accommodation.poi() == null) {
            return accommodation;
        }
        // Always persist a display name so legacy consumers (which only know
        // placeName) still see something readable.
        String effectiveName = accommodation.placeName() != null
                && !accommodation.placeName().isBlank()
                ? accommodation.placeName() : accommodation.poi().name();
        return new Accommodation(effectiveName, accommodation.poi());
    }

    private TripResponse toResponse(TripRecord trip) {
        TripConstraintRecord constraint = tripMapper.findConstraint(trip.id())
                .orElseThrow(() -> new IllegalStateException("Trip constraint is missing for " + trip.id()));
        ConstraintResponse constraintResponse = new ConstraintResponse(
                constraint.budgetAmount(), constraint.travelers(), constraint.travelerType(), constraint.pace(),
                readJson(constraint.preferencesJson(), STRING_LIST),
                readJson(constraint.fixedSchedulesJson(), SCHEDULE_LIST),
                readNullableJson(constraint.arrivalJson(), TravelAnchor.class),
                readNullableJson(constraint.departureJson(), TravelAnchor.class),
                readNullableJson(constraint.accommodationJson(), Accommodation.class),
                readJson(constraint.mustVisitPlacesJson(), STRING_LIST),
                readJson(constraint.avoidPlacesJson(), STRING_LIST),
                effectiveMealWindows(readJson(constraint.mealWindowsJson(), MEAL_WINDOW_LIST)),
                constraint.mobilityLevel(),
                constraint.schemaVersion()
        );
        return new TripResponse(
                trip.id(), trip.title(), trip.destination(), trip.startDate(), trip.endDate(),
                trip.status(), trip.version(), constraintResponse, trip.createdAt(), trip.updatedAt(),
                trip.archivedAt()
        );
    }

    private TripResponse toResponse(TripSnapshotRecord snapshot) {
        ConstraintResponse constraintResponse = new ConstraintResponse(
                snapshot.budgetAmount(), snapshot.travelers(), snapshot.travelerType(), snapshot.pace(),
                readJson(snapshot.preferencesJson(), STRING_LIST),
                readJson(snapshot.fixedSchedulesJson(), SCHEDULE_LIST),
                readNullableJson(snapshot.arrivalJson(), TravelAnchor.class),
                readNullableJson(snapshot.departureJson(), TravelAnchor.class),
                readNullableJson(snapshot.accommodationJson(), Accommodation.class),
                readJson(snapshot.mustVisitPlacesJson(), STRING_LIST),
                readJson(snapshot.avoidPlacesJson(), STRING_LIST),
                effectiveMealWindows(readJson(snapshot.mealWindowsJson(), MEAL_WINDOW_LIST)),
                snapshot.mobilityLevel(),
                snapshot.schemaVersion()
        );
        return new TripResponse(
                snapshot.id(), snapshot.title(), snapshot.destination(),
                snapshot.startDate(), snapshot.endDate(), snapshot.status(), snapshot.version(),
                constraintResponse, snapshot.createdAt(), snapshot.updatedAt(), snapshot.archivedAt()
        );
    }

    /**
     * Returns the effective meal windows for display: trips created before
     * defaults were normalized get the system defaults; legacy windows without
     * an explicit source are treated as user-set.
     */
    private static List<MealWindow> effectiveMealWindows(List<MealWindow> stored) {
        if (stored == null || stored.isEmpty()) {
            return TripRequests.DEFAULT_MEAL_WINDOWS;
        }
        return stored.stream()
                .map(window -> window.source() == null
                        ? new MealWindow(window.mealType(), window.startTime(), window.endTime(), "USER_SET")
                        : window)
                .toList();
    }

    private TripSearch normalizeSearch(TripSearch search) {
        if (search == null || search.page() < 0 || search.size() < 1 || search.size() > 100) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "TRIP_SEARCH_INVALID",
                    "Page must be non-negative and page size must be between 1 and 100");
        }
        if (search.startDate() != null && search.endDate() != null
                && search.startDate().isAfter(search.endDate())) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "TRIP_SEARCH_INVALID",
                    "Search start date must be before search end date");
        }
        return new TripSearch(
                search.destination() == null || search.destination().isBlank()
                        ? null : search.destination().trim(),
                search.status() == null || search.status().isBlank() ? null : search.status().trim(),
                search.startDate(), search.endDate(), search.includeArchived(), search.page(), search.size()
        );
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Could not serialize trip constraints", exception);
        }
    }

    private String writeNullableJson(Object value) {
        return value == null ? null : writeJson(value);
    }

    private <T> T readJson(String value, TypeReference<T> type) {
        try {
            return objectMapper.readValue(value, type);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Could not deserialize trip constraints", exception);
        }
    }

    private <T> T readNullableJson(String value, Class<T> type) {
        if (value == null) {
            return null;
        }
        try {
            return objectMapper.readValue(value, type);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Could not deserialize trip constraints", exception);
        }
    }

    public record TripResponse(
            UUID id,
            String title,
            String destination,
            LocalDate startDate,
            LocalDate endDate,
            String status,
            int version,
            ConstraintResponse constraints,
            java.time.Instant createdAt,
            java.time.Instant updatedAt,
            java.time.Instant archivedAt
    ) {
    }

    public record TripSearch(
            String destination,
            String status,
            LocalDate startDate,
            LocalDate endDate,
            boolean includeArchived,
            int page,
            int size
    ) {
    }

    public record TripPage(
            List<TripResponse> items,
            int page,
            int size,
            long totalElements,
            int totalPages
    ) {
    }

    public record ConstraintResponse(
            BigDecimal budgetAmount,
            int travelers,
            String travelerType,
            String pace,
            List<String> preferences,
            List<FixedSchedule> fixedSchedules,
            TravelAnchor arrival,
            TravelAnchor departure,
            Accommodation accommodation,
            List<String> mustVisitPlaces,
            List<String> avoidPlaces,
            List<MealWindow> mealWindows,
            String mobilityLevel,
            int schemaVersion
    ) {
    }
}
