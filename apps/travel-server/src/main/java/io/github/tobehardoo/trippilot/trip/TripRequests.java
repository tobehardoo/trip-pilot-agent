package io.github.tobehardoo.trippilot.trip;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.OffsetDateTime;
import java.util.List;

import jakarta.validation.Valid;
import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Digits;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

final class TripRequests {

    private TripRequests() {
    }

    record CreateTripRequest(
            @Size(max = 120) String title,
            @NotBlank @Size(max = 120) String destination,
            @Valid RegionRefInput region,
            LocalDate startDate,
            LocalDate endDate,
            OffsetDateTime arrivalAt,
            OffsetDateTime departureAt,
            @NotNull @Valid ConstraintInput constraints
    ) {
    }

    record UpdateTripMetadataRequest(
            @NotNull @Min(0) Integer expectedVersion,
            @Size(max = 120) String title
    ) {
    }

    record RegionRefInput(
            @NotNull @Pattern(regexp = "\\d{6}") String provinceCode,
            @NotNull @Pattern(regexp = "\\d{6}") String cityCode,
            @NotNull @Size(max = 100) List<@NotNull @Pattern(regexp = "\\d{6}") String> districtCodes,
            @NotBlank @Size(max = 80) String provinceName,
            @NotBlank @Size(max = 80) String cityName,
            @NotNull @Size(max = 100) List<@NotBlank @Size(max = 80) String> districtNames,
            @NotBlank @Pattern(regexp = "\\d{4}-\\d{2}-\\d{2}") String datasetVersion
    ) {
        RegionRefInput {
            districtCodes = districtCodes == null ? List.of() : List.copyOf(districtCodes);
            districtNames = districtNames == null ? List.of() : List.copyOf(districtNames);
        }
    }

    record UpdateConstraintRequest(
            @NotNull @Min(0) Integer version,
            @DecimalMin("0.0") @Digits(integer = 10, fraction = 2) BigDecimal budgetAmount,
            @Min(1) @Max(50) int travelers,
            @NotNull @Pattern(regexp = "SOLO|COUPLE|FAMILY|FRIENDS|BUSINESS") String travelerType,
            @NotNull @Pattern(regexp = "RELAXED|BALANCED|INTENSIVE") String pace,
            @NotNull @Size(max = 30) List<@NotBlank @Size(max = 60) String> preferences,
            @NotNull @Size(max = 30) List<@NotNull @Valid FixedSchedule> fixedSchedules,
            @Valid TravelAnchor arrival,
            @Valid TravelAnchor departure,
            @Valid PlaceAnchor accommodation,
            @Size(max = 30) List<@NotBlank @Size(max = 120) String> mustVisitPlaces,
            @Size(max = 30) List<@NotBlank @Size(max = 120) String> avoidPlaces,
            @Size(max = 30) List<@NotNull @Valid PlaceRefInput> mustVisitPlaceRefs,
            @Size(max = 30) List<@NotNull @Valid PlaceRefInput> avoidPlaceRefs,
            @Size(max = 3) List<@NotNull @Valid MealWindow> mealWindows,
            @Pattern(regexp = "STANDARD|REDUCED|STEP_FREE") String mobilityLevel
    ) {
        ConstraintInput asConstraintInput() {
            return new ConstraintInput(
                    budgetAmount, travelers, travelerType, pace, preferences, fixedSchedules,
                    arrival, departure, accommodation, mustVisitPlaces, avoidPlaces,
                    mustVisitPlaceRefs, avoidPlaceRefs, mealWindows, mobilityLevel
            );
        }
    }

    record ConstraintInput(
            @DecimalMin("0.0") @Digits(integer = 10, fraction = 2) BigDecimal budgetAmount,
            @Min(1) @Max(50) int travelers,
            @NotNull @Pattern(regexp = "SOLO|COUPLE|FAMILY|FRIENDS|BUSINESS") String travelerType,
            @NotNull @Pattern(regexp = "RELAXED|BALANCED|INTENSIVE") String pace,
            @NotNull @Size(max = 30) List<@NotBlank @Size(max = 60) String> preferences,
            @NotNull @Size(max = 30) List<@NotNull @Valid FixedSchedule> fixedSchedules,
            @Valid TravelAnchor arrival,
            @Valid TravelAnchor departure,
            @Valid PlaceAnchor accommodation,
            @Size(max = 30) List<@NotBlank @Size(max = 120) String> mustVisitPlaces,
            @Size(max = 30) List<@NotBlank @Size(max = 120) String> avoidPlaces,
            @Size(max = 30) List<@NotNull @Valid PlaceRefInput> mustVisitPlaceRefs,
            @Size(max = 30) List<@NotNull @Valid PlaceRefInput> avoidPlaceRefs,
            @Size(max = 3) List<@NotNull @Valid MealWindow> mealWindows,
            @Pattern(regexp = "STANDARD|REDUCED|STEP_FREE") String mobilityLevel
    ) {
        ConstraintInput {
            mustVisitPlaces = mustVisitPlaces == null ? List.of() : List.copyOf(mustVisitPlaces);
            avoidPlaces = avoidPlaces == null ? List.of() : List.copyOf(avoidPlaces);
            mustVisitPlaceRefs = mustVisitPlaceRefs == null
                    ? List.of() : List.copyOf(mustVisitPlaceRefs);
            avoidPlaceRefs = avoidPlaceRefs == null
                    ? List.of() : List.copyOf(avoidPlaceRefs);
            mealWindows = mealWindows == null ? List.of() : List.copyOf(mealWindows);
            mobilityLevel = mobilityLevel == null ? "STANDARD" : mobilityLevel;
        }
    }

    record FixedSchedule(
            @NotBlank @Size(max = 120) String placeName,
            @NotNull OffsetDateTime startTime,
            @NotNull OffsetDateTime endTime
    ) {
    }

    record PlaceAnchor(
            @NotBlank @Size(max = 120) String placeName,
            @Valid PlaceRefInput placeRef
    ) {
    }

    record TravelAnchor(
            @NotBlank @Size(max = 120) String placeName,
            @NotNull OffsetDateTime time,
            @Valid PlaceRefInput placeRef
    ) {
    }

    /**
     * B13-D: structured place reference captured from a real search
     * candidate.  Legacy free text never produces one; candidates are
     * provenance data, never verification evidence.
     *
     * B13_FIX R5 (P1-2): request DTO carries the optional owner-scoped
     * selection token issued by the place-search endpoint.  The server
     * canonicalizes the ref from the cached candidate and never persists
     * the token itself.
     */
    record PlaceRefInput(
            @NotNull @Pattern(regexp = "AMAP|DEMO") String provider,
            @NotBlank @Size(max = 100) String providerPoiId,
            @NotBlank @Size(max = 120) String name,
            @Size(max = 200) String address,
            @Size(max = 80) String province,
            @Size(max = 80) String city,
            @Size(max = 80) String district,
            @NotNull @DecimalMin("-180") @DecimalMax("180") BigDecimal longitude,
            @NotNull @DecimalMin("-90") @DecimalMax("90") BigDecimal latitude,
            // Never serialized once canonicalized: the token must not reach
            // the web response, the outbox command or the Python planner.
            @com.fasterxml.jackson.annotation.JsonInclude(
                    com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
            @Size(max = 100) String selectionToken
    ) {
        PlaceRefInput {
            address = address == null ? "" : address;
            province = province == null ? "" : province;
            city = city == null ? "" : city;
            district = district == null ? "" : district;
        }
    }

    record MealWindow(
            @NotNull @Pattern(regexp = "BREAKFAST|LUNCH|DINNER") String mealType,
            @NotNull LocalTime startTime,
            @NotNull LocalTime endTime,
            // B13-F: DEFAULT is a soft suggestion (never a hard MEAL_WINDOW
            // FAIL), USER is a hard constraint, DISABLED is not projected.
            // Historical rows without a source keep USER semantics (never
            // downgraded); validation runs after this normalization.
            @Pattern(regexp = "DEFAULT|USER|DISABLED") String source
    ) {
        MealWindow {
            source = source == null ? "USER" : source;
        }
    }
}
