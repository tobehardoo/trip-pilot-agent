package io.github.tobehardoo.trippilot.trip;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.trip.TripRequests.ConstraintInput;
import io.github.tobehardoo.trippilot.trip.TripRequests.CreateTripRequest;
import io.github.tobehardoo.trippilot.trip.TripRequests.FixedSchedule;
import io.github.tobehardoo.trippilot.trip.TripRequests.MealWindow;
import io.github.tobehardoo.trippilot.trip.TripRequests.PlaceAnchor;
import io.github.tobehardoo.trippilot.trip.TripRequests.TravelAnchor;
import io.github.tobehardoo.trippilot.trip.TripRequests.UpdateConstraintRequest;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class TripService {

    private static final ZoneOffset CHINA_OFFSET = ZoneOffset.ofHours(8);
    private static final long MAX_TRIP_DAYS = 7;
    private static final TypeReference<List<String>> STRING_LIST = new TypeReference<>() { };
    private static final TypeReference<List<FixedSchedule>> SCHEDULE_LIST = new TypeReference<>() { };
    private static final TypeReference<List<MealWindow>> MEAL_WINDOW_LIST = new TypeReference<>() { };

    private final TripMapper tripMapper;
    private final ObjectMapper objectMapper;

    public TripService(TripMapper tripMapper, ObjectMapper objectMapper) {
        this.tripMapper = tripMapper;
        this.objectMapper = objectMapper;
    }

    @Transactional
    public TripResponse create(UUID ownerId, CreateTripRequest request) {
        validateDateRange(request.startDate(), request.endDate());
        validateSchedules(request.constraints().fixedSchedules(), request.startDate(), request.endDate());
        validateContext(request.constraints(), request.startDate(), request.endDate());
        UUID tripId = UUID.randomUUID();
        TripRecord trip = new TripRecord(
                tripId, ownerId, request.title().trim(), request.destination().trim(),
                request.startDate(), request.endDate(), "DRAFT", 0, null, null
        );
        tripMapper.insertTrip(trip);
        tripMapper.insertConstraint(toRecord(tripId, request.constraints()));
        return get(ownerId, tripId);
    }

    @Transactional(readOnly = true)
    public List<TripResponse> list(UUID ownerId) {
        return tripMapper.findAllOwned(ownerId).stream().map(this::toResponse).toList();
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
        validateSchedules(request.fixedSchedules(), trip.startDate(), trip.endDate());
        validateContext(request.asConstraintInput(), trip.startDate(), trip.endDate());
        if (tripMapper.incrementVersion(tripId, ownerId, request.version()) != 1) {
            throw new ApiException(HttpStatus.CONFLICT, "TRIP_VERSION_CONFLICT",
                    "Trip was updated by another request; reload it before retrying");
        }
        tripMapper.updateConstraint(toRecord(tripId, request.asConstraintInput()));
        return get(ownerId, tripId);
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
                writeNullableJson(input.accommodation()), writeJson(input.mustVisitPlaces()),
                writeJson(input.avoidPlaces()), writeJson(input.mealWindows()),
                input.mobilityLevel(), 2, null
        );
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
                readNullableJson(constraint.accommodationJson(), PlaceAnchor.class),
                readJson(constraint.mustVisitPlacesJson(), STRING_LIST),
                readJson(constraint.avoidPlacesJson(), STRING_LIST),
                readJson(constraint.mealWindowsJson(), MEAL_WINDOW_LIST),
                constraint.mobilityLevel(),
                constraint.schemaVersion()
        );
        return new TripResponse(
                trip.id(), trip.title(), trip.destination(), trip.startDate(), trip.endDate(),
                trip.status(), trip.version(), constraintResponse, trip.createdAt(), trip.updatedAt()
        );
    }

    private TripResponse toResponse(TripSnapshotRecord snapshot) {
        ConstraintResponse constraintResponse = new ConstraintResponse(
                snapshot.budgetAmount(), snapshot.travelers(), snapshot.travelerType(), snapshot.pace(),
                readJson(snapshot.preferencesJson(), STRING_LIST),
                readJson(snapshot.fixedSchedulesJson(), SCHEDULE_LIST),
                readNullableJson(snapshot.arrivalJson(), TravelAnchor.class),
                readNullableJson(snapshot.departureJson(), TravelAnchor.class),
                readNullableJson(snapshot.accommodationJson(), PlaceAnchor.class),
                readJson(snapshot.mustVisitPlacesJson(), STRING_LIST),
                readJson(snapshot.avoidPlacesJson(), STRING_LIST),
                readJson(snapshot.mealWindowsJson(), MEAL_WINDOW_LIST),
                snapshot.mobilityLevel(),
                snapshot.schemaVersion()
        );
        return new TripResponse(
                snapshot.id(), snapshot.title(), snapshot.destination(),
                snapshot.startDate(), snapshot.endDate(), snapshot.status(), snapshot.version(),
                constraintResponse, snapshot.createdAt(), snapshot.updatedAt()
        );
    }

    private void validateDateRange(LocalDate startDate, LocalDate endDate) {
        if (endDate.isBefore(startDate)) {
            throw validationFailure("endDate must not be before startDate");
        }
        if (ChronoUnit.DAYS.between(startDate, endDate) + 1 > MAX_TRIP_DAYS) {
            throw validationFailure("Trip duration must not exceed 7 days");
        }
    }

    private void validateSchedules(List<FixedSchedule> schedules, LocalDate startDate, LocalDate endDate) {
        for (FixedSchedule schedule : schedules) {
            if (!schedule.endTime().isAfter(schedule.startTime())
                    || schedule.startTime().withOffsetSameInstant(CHINA_OFFSET)
                            .toLocalDate().isBefore(startDate)
                    || schedule.endTime().withOffsetSameInstant(CHINA_OFFSET)
                            .toLocalDate().isAfter(endDate)) {
                throw validationFailure("Fixed schedules must be ordered and fall within the trip dates");
            }
        }
    }

    private void validateContext(ConstraintInput input, LocalDate startDate, LocalDate endDate) {
        validateAnchor(input.arrival(), startDate, endDate);
        validateAnchor(input.departure(), startDate, endDate);
        if (input.arrival() != null && input.departure() != null
                && !input.departure().time().isAfter(input.arrival().time())) {
            throw validationFailure("Departure time must be after arrival time");
        }
        Set<String> mustVisit = normalized(input.mustVisitPlaces());
        Set<String> avoided = normalized(input.avoidPlaces());
        mustVisit.retainAll(avoided);
        if (!mustVisit.isEmpty()) {
            throw validationFailure("Must-visit and avoided places must not overlap");
        }
        Set<String> mealTypes = new HashSet<>();
        List<MealWindow> orderedMeals = new ArrayList<>(input.mealWindows());
        orderedMeals.sort(Comparator.comparing(MealWindow::startTime));
        for (MealWindow window : input.mealWindows()) {
            if (!window.endTime().isAfter(window.startTime())
                    || !mealTypes.add(window.mealType())) {
                throw validationFailure("Meal windows must be ordered and use unique meal types");
            }
        }
        for (int index = 1; index < orderedMeals.size(); index++) {
            if (orderedMeals.get(index).startTime()
                    .isBefore(orderedMeals.get(index - 1).endTime())) {
                throw validationFailure("Meal windows must not overlap");
            }
        }
    }

    private void validateAnchor(TravelAnchor anchor, LocalDate startDate, LocalDate endDate) {
        if (anchor == null) {
            return;
        }
        LocalDate anchorDate = anchor.time().withOffsetSameInstant(CHINA_OFFSET).toLocalDate();
        if (anchorDate.isBefore(startDate) || anchorDate.isAfter(endDate)) {
            throw validationFailure("Travel anchor times must fall within the trip dates");
        }
    }

    private Set<String> normalized(List<String> values) {
        Set<String> result = new HashSet<>();
        for (String value : values) {
            result.add(value.trim().toLowerCase(Locale.ROOT));
        }
        return result;
    }

    private ApiException validationFailure(String message) {
        return new ApiException(HttpStatus.BAD_REQUEST, "VALIDATION_FAILED", message);
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
            java.time.Instant updatedAt
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
            PlaceAnchor accommodation,
            List<String> mustVisitPlaces,
            List<String> avoidPlaces,
            List<MealWindow> mealWindows,
            String mobilityLevel,
            int schemaVersion
    ) {
    }
}
