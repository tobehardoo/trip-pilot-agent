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
import io.github.tobehardoo.trippilot.trip.TripRequests.ConstraintInput;
import io.github.tobehardoo.trippilot.trip.TripRequests.CreateTripRequest;
import io.github.tobehardoo.trippilot.trip.TripRequests.FixedSchedule;
import io.github.tobehardoo.trippilot.trip.TripRequests.MealWindow;
import io.github.tobehardoo.trippilot.trip.TripRequests.PlaceAnchor;
import io.github.tobehardoo.trippilot.trip.TripRequests.TravelAnchor;
import io.github.tobehardoo.trippilot.trip.TripRequests.UpdateConstraintRequest;
import io.github.tobehardoo.trippilot.trip.TripRequests.RegionRefInput;
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
    private final CityIntelligencePrewarmService cityIntelligencePrewarmService;

    public TripService(
            TripMapper tripMapper,
            ObjectMapper objectMapper,
            TripConstraintValidator validator,
            CityIntelligencePrewarmService cityIntelligencePrewarmService
    ) {
        this.tripMapper = tripMapper;
        this.objectMapper = objectMapper;
        this.validator = validator;
        this.cityIntelligencePrewarmService = cityIntelligencePrewarmService;
    }

    @Transactional
    public TripResponse create(UUID ownerId, CreateTripRequest request) {
        validator.validateDateRange(request.startDate(), request.endDate());
        validator.validateSchedules(request.constraints().fixedSchedules(), request.startDate(), request.endDate());
        validator.validateContext(request.constraints(), request.startDate(), request.endDate());
        validateRegion(request.region());
        UUID tripId = UUID.randomUUID();
        TripRecord trip = new TripRecord(
                tripId, ownerId, request.title().trim(), request.destination().trim(),
                request.startDate(), request.endDate(), "DRAFT", 0, null, null, null,
                writeNullableJson(request.region())
        );
        tripMapper.insertTrip(trip);
        tripMapper.insertConstraint(toRecord(tripId, request.constraints()));
        if (request.region() == null) {
            cityIntelligencePrewarmService.request(tripId, trip.destination(), trip.startDate(), trip.endDate());
        } else {
            cityIntelligencePrewarmService.request(
                    tripId, trip.destination(), request.region().cityCode(),
                    trip.startDate(), trip.endDate()
            );
        }
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
        validator.validateContext(request.asConstraintInput(), trip.startDate(), trip.endDate());
        if (tripMapper.incrementVersion(tripId, ownerId, request.version()) != 1) {
            throw new ApiException(HttpStatus.CONFLICT, "TRIP_VERSION_CONFLICT",
                    "Trip was updated by another request; reload it before retrying");
        }
        tripMapper.updateConstraint(toRecord(tripId, request.asConstraintInput()));
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
                trip.status(), trip.version(), constraintResponse, trip.createdAt(), trip.updatedAt(),
                trip.archivedAt(), readNullableJson(trip.regionRefJson(), RegionRef.class),
                planningCoverage(trip.regionRefJson(), trip.destination())
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
                constraintResponse, snapshot.createdAt(), snapshot.updatedAt(), snapshot.archivedAt(),
                readNullableJson(snapshot.regionRefJson(), RegionRef.class),
                planningCoverage(snapshot.regionRefJson(), snapshot.destination())
        );
    }

    private void validateRegion(RegionRefInput region) {
        if (region == null) return;
        String province = region.provinceCode();
        String city = region.cityCode();
        if (!province.endsWith("0000") || city.equals(province)
                || !city.startsWith(province.substring(0, 2))) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "TRIP_REGION_INVALID", "Region city must belong to its province");
        }
        String cityPrefix = city.substring(0, 4);
        boolean municipality = city.substring(2, 4).equals("00");
        for (String district : region.districtCodes()) {
            boolean belongs = !district.equals(city) && !district.endsWith("00")
                    && (municipality ? district.startsWith(province.substring(0, 2)) : district.startsWith(cityPrefix));
            if (!belongs) {
                throw new ApiException(HttpStatus.BAD_REQUEST, "TRIP_REGION_INVALID", "Region district must belong to its city");
            }
        }
    }

    private String planningCoverage(String regionJson, String destination) {
        if (regionJson == null) {
            return CityIntelligencePrewarmService.cityCode(destination).equals("UNREGISTERED") ? "BASIC" : "FULL";
        }
        RegionRef region = readNullableJson(regionJson, RegionRef.class);
        return List.of("110000", "310000", "440100").contains(region.cityCode()) ? "FULL" : "BASIC";
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
            java.time.Instant archivedAt,
            RegionRef region,
            String planningCoverage
    ) {
        public TripResponse(
                UUID id, String title, String destination, LocalDate startDate, LocalDate endDate,
                String status, int version, ConstraintResponse constraints,
                java.time.Instant createdAt, java.time.Instant updatedAt, java.time.Instant archivedAt
        ) {
            this(id, title, destination, startDate, endDate, status, version, constraints,
                    createdAt, updatedAt, archivedAt, null, "BASIC");
        }
    }

    public record RegionRef(
            String provinceCode, String cityCode, List<String> districtCodes,
            String provinceName, String cityName, List<String> districtNames,
            String datasetVersion
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
            PlaceAnchor accommodation,
            List<String> mustVisitPlaces,
            List<String> avoidPlaces,
            List<MealWindow> mealWindows,
            String mobilityLevel,
            int schemaVersion
    ) {
    }
}
