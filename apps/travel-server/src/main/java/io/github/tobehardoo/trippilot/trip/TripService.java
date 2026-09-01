package io.github.tobehardoo.trippilot.trip;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.cityintelligence.CityIntelligencePrewarmService;
import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.persistence.PersistenceSupport;
import io.github.tobehardoo.trippilot.trip.TripRequests.ConstraintInput;
import io.github.tobehardoo.trippilot.trip.TripRequests.CreateTripRequest;
import io.github.tobehardoo.trippilot.trip.TripRequests.FixedSchedule;
import io.github.tobehardoo.trippilot.trip.TripRequests.MealWindow;
import io.github.tobehardoo.trippilot.trip.TripRequests.PlaceAnchor;
import io.github.tobehardoo.trippilot.trip.TripRequests.PlaceRefInput;
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
    private static final TypeReference<List<PlaceRefInput>> PLACE_REF_LIST =
            new TypeReference<>() { };

    private final TripMapper tripMapper;
    private final ObjectMapper objectMapper;
    private final TripConstraintValidator validator;
    private final CityIntelligencePrewarmService cityIntelligencePrewarmService;
    private final PlaceRefCanonicalizer placeRefCanonicalizer;

    public TripService(
            TripMapper tripMapper,
            ObjectMapper objectMapper,
            TripConstraintValidator validator,
            CityIntelligencePrewarmService cityIntelligencePrewarmService,
            PlaceRefCanonicalizer placeRefCanonicalizer
    ) {
        this.tripMapper = tripMapper;
        this.objectMapper = objectMapper;
        this.validator = validator;
        this.cityIntelligencePrewarmService = cityIntelligencePrewarmService;
        this.placeRefCanonicalizer = placeRefCanonicalizer;
    }

    @Transactional
    public TripResponse create(UUID ownerId, CreateTripRequest request) {
        ResolvedBoundaries boundaries = resolveBoundaries(request);
        validator.validateDateRange(boundaries.startDate(), boundaries.endDate());
        validator.validateSchedules(request.constraints().fixedSchedules(), boundaries.startDate(), boundaries.endDate());
        validator.validateContext(request.constraints(), boundaries.startDate(), boundaries.endDate());
        validateRegion(request.region());
        // B13_FIX R5 (P1-2): new refs must be canonicalized from server-issued
        // selection tokens; no persisted refs exist on create.
        ConstraintInput canonicalConstraints = canonicalizeRefs(
                ownerId, request.constraints(), List.of(),
                authoritativeCityName(request.region(), request.destination()));
        // B13_FIX.1 R2: a new trip must not persist free-text anchors or
        // free-text must/avoid entries — non-empty place fields require a
        // selected candidate with a valid PlaceRef.
        validateCreatePlaceRefs(canonicalConstraints);
        String title = (request.title() == null || request.title().isBlank())
                ? TripTitleGenerator.generate(request.destination(), boundaries.startDate(), boundaries.endDate())
                : request.title().trim();
        UUID tripId = UUID.randomUUID();
        TripRecord trip = new TripRecord(
                tripId, ownerId, title, request.destination().trim(),
                boundaries.startDate(), boundaries.endDate(), "DRAFT", 0, null, null, null,
                writeNullableJson(request.region()), boundaries.arrivalAt(), boundaries.departureAt()
        );
        tripMapper.insertTrip(trip);
        tripMapper.insertConstraint(toRecord(tripId, canonicalConstraints));
        if (request.region() == null) {
            cityIntelligencePrewarmService.request(tripId, trip.destination(), boundaries.startDate(), boundaries.endDate());
        } else {
            cityIntelligencePrewarmService.request(
                    tripId, trip.destination(), request.region().cityCode(),
                    boundaries.startDate(), boundaries.endDate()
            );
        }
        return get(ownerId, tripId);
    }

    /**
     * B13-E: arrivalAt/departureAt are the primary boundary inputs and the
     * date projections are derived in Asia/Shanghai.  Legacy clients that
     * still send startDate/endDate remain supported; a legacy trip never
     * fabricates specific boundary times.
     */
    private ResolvedBoundaries resolveBoundaries(CreateTripRequest request) {
        boolean hasDatetimeBoundaries = request.arrivalAt() != null || request.departureAt() != null;
        if (hasDatetimeBoundaries) {
            if (request.arrivalAt() == null || request.departureAt() == null) {
                throw new ApiException(HttpStatus.BAD_REQUEST, "TRIP_BOUNDARIES_INVALID",
                        "arrivalAt and departureAt must be provided together");
            }
            if (!request.arrivalAt().isBefore(request.departureAt())) {
                throw new ApiException(HttpStatus.BAD_REQUEST, "TRIP_BOUNDARIES_INVALID",
                        "arrivalAt must be before departureAt");
            }
            LocalDate start = request.arrivalAt().atZoneSameInstant(TripTitleGenerator.CHINA_ZONE).toLocalDate();
            LocalDate end = request.departureAt().atZoneSameInstant(TripTitleGenerator.CHINA_ZONE).toLocalDate();
            return new ResolvedBoundaries(start, end, request.arrivalAt(), request.departureAt());
        }
        if (request.startDate() == null || request.endDate() == null) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "TRIP_BOUNDARIES_INVALID",
                    "Either arrivalAt/departureAt or startDate/endDate is required");
        }
        return new ResolvedBoundaries(request.startDate(), request.endDate(), null, null);
    }

    private record ResolvedBoundaries(
            LocalDate startDate, LocalDate endDate,
            OffsetDateTime arrivalAt, OffsetDateTime departureAt
    ) {
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
        // B13_FIX R5 (P1-2): unchanged persisted refs may be saved without a
        // token; new/changed refs must carry a valid selection token.
        List<PlaceRefInput> persistedRefs = readPersistedRefs(tripId);
        TripConstraintRecord persisted = tripMapper.findConstraint(tripId)
                .orElseThrow(() -> new IllegalStateException("Trip constraint is missing for " + tripId));
        // B13_FIX.1 R2: the server decides "unchanged" from the database value,
        // never from a client claim.  New or changed non-empty anchors and
        // must/avoid entries require a candidate-selected PlaceRef.
        validateUpdatePlaceRefs(request.asConstraintInput(), persisted);
        ConstraintInput canonical = canonicalizeRefs(
                ownerId, request.asConstraintInput(), persistedRefs,
                authoritativeCityName(readNullableJson(trip.regionRefJson(), RegionRef.class), trip.destination()));
        if (tripMapper.incrementVersion(tripId, ownerId, request.version()) != 1) {
            throw new ApiException(HttpStatus.CONFLICT, "TRIP_VERSION_CONFLICT",
                    "Trip was updated by another request; reload it before retrying");
        }
        tripMapper.updateConstraint(toRecord(tripId, canonical));
        return get(ownerId, tripId);
    }

    /**
     * B13-C: owner-scoped, version-aware title rename.  A blank title falls
     * back to the deterministic default title derived from the trip's own
     * destination and boundaries — an empty string is never persisted.
     */
    @Transactional
    public TripResponse updateMetadata(UUID ownerId, UUID tripId, TripRequests.UpdateTripMetadataRequest request) {
        TripRecord trip = findOwned(ownerId, tripId);
        String title = (request.title() == null || request.title().isBlank())
                ? TripTitleGenerator.generate(trip.destination(), trip.startDate(), trip.endDate())
                : request.title().trim();
        if (tripMapper.updateTitleOwned(tripId, ownerId, request.expectedVersion(), title) != 1) {
            throw new ApiException(HttpStatus.CONFLICT, "TRIP_VERSION_CONFLICT",
                    "Trip was updated by another request; reload it before retrying");
        }
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
        boolean hasPlaceRefs = !input.mustVisitPlaceRefs().isEmpty()
                || !input.avoidPlaceRefs().isEmpty()
                || hasAnchorPlaceRef(input.arrival())
                || hasAnchorPlaceRef(input.departure())
                || hasAnchorPlaceRef(input.accommodation());
        return new TripConstraintRecord(
                tripId, input.budgetAmount(), input.travelers(), input.travelerType(), input.pace(),
                writeJson(input.preferences()), writeJson(input.fixedSchedules()),
                writeNullableJson(input.arrival()), writeNullableJson(input.departure()),
                writeNullableJson(input.accommodation()), writeJson(input.mustVisitPlaces()),
                writeJson(input.avoidPlaces()), writeJson(input.mustVisitPlaceRefs()),
                writeJson(input.avoidPlaceRefs()), writeJson(input.mealWindows()),
                input.mobilityLevel(), hasPlaceRefs ? 3 : 2, null
        );
    }

    /** B13_FIX R5 (P1-2): canonicalize every ref in the constraint input. */

    /**
     * B14_FIX.1 R1: the authoritative city for PlaceRef validation is the
     * official RegionRef cityName (e.g. 大理白族自治州), never the display
     * destination shorthand (大理).  Legacy trips without a region fall back
     * to the destination — conservative and fail-closed if ambiguous.
     */
    private static String authoritativeCityName(RegionRefInput region, String destination) {
        return authoritativeCityName(region == null ? null : region.cityName(), destination);
    }

    private static String authoritativeCityName(RegionRef region, String destination) {
        return authoritativeCityName(region == null ? null : region.cityName(), destination);
    }

    private static String authoritativeCityName(String cityName, String destination) {
        if (cityName != null && !cityName.isBlank()) {
            return cityName.trim();
        }
        return destination;
    }

    private ConstraintInput canonicalizeRefs(
            UUID ownerId,
            ConstraintInput input,
            List<PlaceRefInput> persistedRefs,
            String authoritativeCityName
    ) {
        List<PlaceRefInput> mustRefs = placeRefCanonicalizer.canonicalize(
                ownerId, input.mustVisitPlaceRefs(), persistedRefs, authoritativeCityName);
        List<PlaceRefInput> avoidRefs = placeRefCanonicalizer.canonicalize(
                ownerId, input.avoidPlaceRefs(), persistedRefs, authoritativeCityName);
        TravelAnchor arrival = canonicalizeAnchor(ownerId, input.arrival(), persistedRefs, authoritativeCityName);
        TravelAnchor departure = canonicalizeAnchor(ownerId, input.departure(), persistedRefs, authoritativeCityName);
        PlaceAnchor accommodation = canonicalizeAnchor(ownerId, input.accommodation(), persistedRefs, authoritativeCityName);
        return new ConstraintInput(
                input.budgetAmount(), input.travelers(), input.travelerType(), input.pace(),
                input.preferences(), input.fixedSchedules(), arrival, departure, accommodation,
                input.mustVisitPlaces(), input.avoidPlaces(), mustRefs, avoidRefs,
                input.mealWindows(), input.mobilityLevel()
        );
    }

    /**
     * B13_FIX.1 R2: on create there is no persisted legacy value, so every
     * non-empty place field must come from a selected candidate (a PlaceRef).
     */
    private void validateCreatePlaceRefs(ConstraintInput input) {
        requirePlaceRef("arrival", input.arrival());
        requirePlaceRef("departure", input.departure());
        requirePlaceRef("accommodation", input.accommodation());
        if (!input.mustVisitPlaces().isEmpty() && input.mustVisitPlaceRefs().size() != input.mustVisitPlaces().size()) {
            throw placeRefRequired("must-visit places require a selected candidate");
        }
        if (!input.avoidPlaces().isEmpty() && input.avoidPlaceRefs().size() != input.avoidPlaces().size()) {
            throw placeRefRequired("avoid places require a selected candidate");
        }
    }

    /**
     * B13_FIX.1 R2: on update the server compares against the persisted
     * database value.  An untouched legacy free-text anchor stays allowed;
     * any new or changed non-empty place field needs a candidate PlaceRef.
     */
    private void validateUpdatePlaceRefs(ConstraintInput input, TripConstraintRecord persisted) {
        TravelAnchor persistedArrival = readNullableJson(persisted.arrivalJson(), TravelAnchor.class);
        TravelAnchor persistedDeparture = readNullableJson(persisted.departureJson(), TravelAnchor.class);
        PlaceAnchor persistedAccommodation = readNullableJson(persisted.accommodationJson(), PlaceAnchor.class);
        validateAnchorAgainstPersisted("arrival", input.arrival(), persistedArrival);
        validateAnchorAgainstPersisted("departure", input.departure(), persistedDeparture);
        validateAnchorAgainstPersisted("accommodation", input.accommodation(), persistedAccommodation);
        // must/avoid: persisted legacy names may stay; newly added names
        // without a matching ref are rejected.  The parallel-count check is
        // already enforced by the schema validator when refs are present;
        // here we additionally reject a non-empty name list with zero refs
        // when the persisted list had none for a NEW entry.
        validateListAgainstPersisted(
                "must-visit", input.mustVisitPlaces(), input.mustVisitPlaceRefs(),
                readJson(persisted.mustVisitPlacesJson(), STRING_LIST),
                readPlaceRefs(persisted.mustVisitPlaceRefsJson()));
        validateListAgainstPersisted(
                "avoid", input.avoidPlaces(), input.avoidPlaceRefs(),
                readJson(persisted.avoidPlacesJson(), STRING_LIST),
                readPlaceRefs(persisted.avoidPlaceRefsJson()));
    }

    private void requirePlaceRef(String label, TripRequests.TravelAnchor anchor) {
        if (anchor != null && anchor.placeRef() == null) {
            throw placeRefRequired(label + " requires a selected candidate");
        }
    }

    private void requirePlaceRef(String label, TripRequests.PlaceAnchor anchor) {
        if (anchor != null && anchor.placeRef() == null) {
            throw placeRefRequired(label + " requires a selected candidate");
        }
    }

    private void validateAnchorAgainstPersisted(
            String label,
            TripRequests.TravelAnchor input,
            TravelAnchor persisted
    ) {
        if (input == null) return; // cleared optional field is allowed
        if (input.placeRef() != null) return; // candidate-selected is always allowed
        boolean unchangedLegacy = persisted != null
                && persisted.placeRef() == null
                && input.placeName().equals(persisted.placeName());
        if (!unchangedLegacy) {
            throw placeRefRequired(label + " requires a selected candidate");
        }
    }

    private void validateAnchorAgainstPersisted(
            String label,
            TripRequests.PlaceAnchor input,
            PlaceAnchor persisted
    ) {
        if (input == null) return;
        if (input.placeRef() != null) return;
        boolean unchangedLegacy = persisted != null
                && persisted.placeRef() == null
                && input.placeName().equals(persisted.placeName());
        if (!unchangedLegacy) {
            throw placeRefRequired(label + " requires a selected candidate");
        }
    }

    private void validateListAgainstPersisted(
            String label,
            List<String> names,
            List<PlaceRefInput> refs,
            List<String> persistedNames,
            List<PlaceRefInput> persistedRefs
    ) {
        if (names.isEmpty()) return;
        if (refs.size() == names.size()) return; // fully structured
        // Every entry must be either unchanged-legacy or have a ref.
        for (int index = 0; index < names.size(); index++) {
            String name = names.get(index);
            boolean hasRef = index < refs.size() && refs.get(index) != null;
            if (hasRef) continue;
            boolean unchangedLegacy = index < persistedNames.size()
                    && name.equals(persistedNames.get(index))
                    && index >= persistedRefs.size();
            if (!unchangedLegacy) {
                throw placeRefRequired(label + " entry requires a selected candidate");
            }
        }
    }

    private ApiException placeRefRequired(String message) {
        return new ApiException(HttpStatus.BAD_REQUEST, "PLACE_REF_REQUIRED", message);
    }

    private TravelAnchor canonicalizeAnchor(
            UUID ownerId,
            TravelAnchor anchor,
            List<PlaceRefInput> persistedRefs,
            String authoritativeCityName
    ) {
        if (anchor == null || anchor.placeRef() == null) {
            return anchor;
        }
        PlaceRefInput ref = placeRefCanonicalizer.canonicalize(
                ownerId, List.of(anchor.placeRef()), persistedRefs, authoritativeCityName).get(0);
        return new TravelAnchor(anchor.placeName(), anchor.time(), ref);
    }

    private PlaceAnchor canonicalizeAnchor(
            UUID ownerId,
            PlaceAnchor anchor,
            List<PlaceRefInput> persistedRefs,
            String authoritativeCityName
    ) {
        if (anchor == null || anchor.placeRef() == null) {
            return anchor;
        }
        PlaceRefInput ref = placeRefCanonicalizer.canonicalize(
                ownerId, List.of(anchor.placeRef()), persistedRefs, authoritativeCityName).get(0);
        return new PlaceAnchor(anchor.placeName(), ref);
    }

    /** B13_FIX R5: refs currently persisted for the trip (token-free). */
    private List<PlaceRefInput> readPersistedRefs(UUID tripId) {
        TripConstraintRecord constraint = tripMapper.findConstraint(tripId)
                .orElseThrow(() -> new IllegalStateException("Trip constraint is missing for " + tripId));
        List<PlaceRefInput> refs = new java.util.ArrayList<>();
        refs.addAll(readPlaceRefs(constraint.mustVisitPlaceRefsJson()));
        refs.addAll(readPlaceRefs(constraint.avoidPlaceRefsJson()));
        if (constraint.arrivalJson() != null) {
            TravelAnchor anchor = readNullableJson(constraint.arrivalJson(), TravelAnchor.class);
            if (anchor != null && anchor.placeRef() != null) {
                refs.add(anchor.placeRef());
            }
        }
        if (constraint.departureJson() != null) {
            TravelAnchor anchor = readNullableJson(constraint.departureJson(), TravelAnchor.class);
            if (anchor != null && anchor.placeRef() != null) {
                refs.add(anchor.placeRef());
            }
        }
        if (constraint.accommodationJson() != null) {
            PlaceAnchor anchor = readNullableJson(constraint.accommodationJson(), PlaceAnchor.class);
            if (anchor != null && anchor.placeRef() != null) {
                refs.add(anchor.placeRef());
            }
        }
        return List.copyOf(refs);
    }

    private static boolean hasAnchorPlaceRef(TripRequests.PlaceAnchor anchor) {
        return anchor != null && anchor.placeRef() != null;
    }

    private static boolean hasAnchorPlaceRef(TripRequests.TravelAnchor anchor) {
        return anchor != null && anchor.placeRef() != null;
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
                readPlaceRefs(constraint.mustVisitPlaceRefsJson()),
                readPlaceRefs(constraint.avoidPlaceRefsJson()),
                readJson(constraint.mealWindowsJson(), MEAL_WINDOW_LIST),
                constraint.mobilityLevel(),
                constraint.schemaVersion()
        );
        return new TripResponse(
                trip.id(), trip.title(), trip.destination(), trip.startDate(), trip.endDate(),
                trip.status(), trip.version(), constraintResponse, trip.createdAt(), trip.updatedAt(),
                trip.archivedAt(), readNullableJson(trip.regionRefJson(), RegionRef.class),
                planningCoverage(trip.regionRefJson(), trip.destination()),
                trip.arrivalAt(), trip.departureAt()
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
                readPlaceRefs(snapshot.mustVisitPlaceRefsJson()),
                readPlaceRefs(snapshot.avoidPlaceRefsJson()),
                readJson(snapshot.mealWindowsJson(), MEAL_WINDOW_LIST),
                snapshot.mobilityLevel(),
                snapshot.schemaVersion()
        );
        return new TripResponse(
                snapshot.id(), snapshot.title(), snapshot.destination(),
                snapshot.startDate(), snapshot.endDate(), snapshot.status(), snapshot.version(),
                constraintResponse, snapshot.createdAt(), snapshot.updatedAt(), snapshot.archivedAt(),
                readNullableJson(snapshot.regionRefJson(), RegionRef.class),
                planningCoverage(snapshot.regionRefJson(), snapshot.destination()),
                snapshot.arrivalAt(), snapshot.departureAt()
        );
    }

    // B13_FIX R4 (P1-1): 直辖市明确模型。仅这 4 个省级行政区允许
    // provinceCode == cityCode（受控同码组合），且城市名必须与代码一致。
    private static final java.util.Set<String> MUNICIPALITY_CODES = java.util.Set.of(
            "110000", // 北京
            "120000", // 天津
            "310000", // 上海
            "500000"  // 重庆
    );

    private void validateRegion(RegionRefInput region) {
        if (region == null) return;
        String province = region.provinceCode();
        String city = region.cityCode();
        if (!province.endsWith("0000")) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "TRIP_REGION_INVALID",
                    "Region province code must be a province-level code");
        }
        if (MUNICIPALITY_CODES.contains(province)) {
            if (!city.equals(province)) {
                throw new ApiException(HttpStatus.BAD_REQUEST, "TRIP_REGION_INVALID",
                        "Municipality city code must equal its province code");
            }
            if (!municipalityCityNameMatches(province, region.cityName())) {
                throw new ApiException(HttpStatus.BAD_REQUEST, "TRIP_REGION_INVALID",
                        "Municipality city name must match its administrative code");
            }
        } else if (city.equals(province) || !city.startsWith(province.substring(0, 2))) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "TRIP_REGION_INVALID",
                    "Region city must belong to its province");
        }
        String cityPrefix = city.substring(0, 4);
        boolean municipality = MUNICIPALITY_CODES.contains(province)
                || city.substring(2, 4).equals("00");
        for (String district : region.districtCodes()) {
            boolean belongs = !district.equals(city) && !district.endsWith("00")
                    && (municipality ? district.startsWith(province.substring(0, 2))
                            : district.startsWith(cityPrefix));
            if (!belongs) {
                throw new ApiException(HttpStatus.BAD_REQUEST, "TRIP_REGION_INVALID",
                        "Region district must belong to its city");
            }
        }
    }

    private static boolean municipalityCityNameMatches(String provinceCode, String cityName) {
        String expected = switch (provinceCode) {
            case "110000" -> "北京";
            case "120000" -> "天津";
            case "310000" -> "上海";
            case "500000" -> "重庆";
            default -> null;
        };
        return expected != null
                && (cityName.equals(expected) || cityName.equals(expected + "市"));
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
        return PersistenceSupport.writeJson(objectMapper, value, "trip constraints");
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

    /** Legacy rows store NULL in the ref columns; treat that as no refs. */
    private List<TripRequests.PlaceRefInput> readPlaceRefs(String value) {
        if (value == null) {
            return List.of();
        }
        return readJson(value, PLACE_REF_LIST);
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
            String planningCoverage,
            OffsetDateTime arrivalAt,
            OffsetDateTime departureAt
    ) {
        public TripResponse(
                UUID id, String title, String destination, LocalDate startDate, LocalDate endDate,
                String status, int version, ConstraintResponse constraints,
                java.time.Instant createdAt, java.time.Instant updatedAt, java.time.Instant archivedAt
        ) {
            this(id, title, destination, startDate, endDate, status, version, constraints,
                    createdAt, updatedAt, archivedAt, null, "BASIC", null, null);
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
            List<TripRequests.PlaceRefInput> mustVisitPlaceRefs,
            List<TripRequests.PlaceRefInput> avoidPlaceRefs,
            List<MealWindow> mealWindows,
            String mobilityLevel,
            int schemaVersion
    ) {
    }
}
