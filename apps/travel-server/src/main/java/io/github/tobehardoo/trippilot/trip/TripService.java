package io.github.tobehardoo.trippilot.trip;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.trip.TripRequests.ConstraintInput;
import io.github.tobehardoo.trippilot.trip.TripRequests.CreateTripRequest;
import io.github.tobehardoo.trippilot.trip.TripRequests.FixedSchedule;
import io.github.tobehardoo.trippilot.trip.TripRequests.UpdateConstraintRequest;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class TripService {

    private static final TypeReference<List<String>> STRING_LIST = new TypeReference<>() { };
    private static final TypeReference<List<FixedSchedule>> SCHEDULE_LIST = new TypeReference<>() { };

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
                writeJson(input.preferences()), writeJson(input.fixedSchedules()), 1, null
        );
    }

    private TripResponse toResponse(TripRecord trip) {
        TripConstraintRecord constraint = tripMapper.findConstraint(trip.id())
                .orElseThrow(() -> new IllegalStateException("Trip constraint is missing for " + trip.id()));
        ConstraintResponse constraintResponse = new ConstraintResponse(
                constraint.budgetAmount(), constraint.travelers(), constraint.travelerType(), constraint.pace(),
                readJson(constraint.preferencesJson(), STRING_LIST),
                readJson(constraint.fixedSchedulesJson(), SCHEDULE_LIST),
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
    }

    private void validateSchedules(List<FixedSchedule> schedules, LocalDate startDate, LocalDate endDate) {
        for (FixedSchedule schedule : schedules) {
            if (!schedule.endTime().isAfter(schedule.startTime())
                    || schedule.startTime().toLocalDate().isBefore(startDate)
                    || schedule.endTime().toLocalDate().isAfter(endDate)) {
                throw validationFailure("Fixed schedules must be ordered and fall within the trip dates");
            }
        }
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

    private <T> T readJson(String value, TypeReference<T> type) {
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
            int schemaVersion
    ) {
    }
}
