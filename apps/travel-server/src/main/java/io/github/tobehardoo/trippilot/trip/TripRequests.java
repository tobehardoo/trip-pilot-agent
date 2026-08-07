package io.github.tobehardoo.trippilot.trip;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.OffsetDateTime;
import java.util.List;

import jakarta.validation.Valid;
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

    /**
     * Structured destination region (province / city / districts). Codes are
     * AMap adcodes and must match the static {@link RegionCatalog}; a plain
     * {@code destination} string remains the backward-compatible fallback for
     * legacy trips and cities without catalogued codes.
     */
    record DestinationRegion(
            @NotBlank @Size(max = 12) String provinceCode,
            @NotBlank @Size(max = 30) String provinceName,
            @NotBlank @Size(max = 12) String cityCode,
            @NotBlank @Size(max = 30) String cityName,
            @Size(max = 10) List<DistrictRef> districts
    ) {
        DestinationRegion {
            districts = districts == null ? List.of() : List.copyOf(districts);
        }

        record DistrictRef(
                @NotBlank @Size(max = 12) String districtCode,
                @NotBlank @Size(max = 30) String districtName
        ) {
        }
    }

    record CreateTripRequest(
            @NotBlank @Size(max = 120) String title,
            @NotBlank @Size(max = 120) String destination,
            @NotNull LocalDate startDate,
            @NotNull LocalDate endDate,
            @NotNull @Valid ConstraintInput constraints,
            @Valid DestinationRegion destinationRegion
    ) {
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
            @Valid Accommodation accommodation,
            @Size(max = 30) List<@NotBlank @Size(max = 120) String> mustVisitPlaces,
            @Size(max = 30) List<@NotBlank @Size(max = 120) String> avoidPlaces,
            @Size(max = 3) List<@NotNull @Valid MealWindow> mealWindows,
            @Pattern(regexp = "STANDARD|REDUCED|STEP_FREE") String mobilityLevel
    ) {
        ConstraintInput asConstraintInput() {
            return new ConstraintInput(
                    budgetAmount, travelers, travelerType, pace, preferences, fixedSchedules,
                    arrival, departure, accommodation, mustVisitPlaces, avoidPlaces,
                    mealWindows, mobilityLevel
            );
        }
    }

    /**
     * Unified configuration update: trip metadata plus constraints are changed
     * atomically under one optimistic-lock version bump. Replanning stays a
     * separate operation.
     */
    record UpdateConfigurationRequest(
            @NotNull @Min(0) Integer version,
            @NotBlank @Size(max = 120) String title,
            @NotBlank @Size(max = 120) String destination,
            @NotNull LocalDate startDate,
            @NotNull LocalDate endDate,
            @NotNull @Valid ConstraintInput constraints,
            @Valid DestinationRegion destinationRegion
    ) {
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
            @Valid Accommodation accommodation,
            @Size(max = 30) List<@NotBlank @Size(max = 120) String> mustVisitPlaces,
            @Size(max = 30) List<@NotBlank @Size(max = 120) String> avoidPlaces,
            @Size(max = 3) List<@NotNull @Valid MealWindow> mealWindows,
            @Pattern(regexp = "STANDARD|REDUCED|STEP_FREE") String mobilityLevel
    ) {
        ConstraintInput {
            mustVisitPlaces = mustVisitPlaces == null ? List.of() : List.copyOf(mustVisitPlaces);
            avoidPlaces = avoidPlaces == null ? List.of() : List.copyOf(avoidPlaces);
            mobilityLevel = mobilityLevel == null ? "STANDARD" : mobilityLevel;
            mealWindows = normalizeMealWindows(mealWindows);
        }
    }

    record FixedSchedule(
            @NotBlank @Size(max = 120) String placeName,
            @NotNull OffsetDateTime startTime,
            @NotNull OffsetDateTime endTime
    ) {
    }

    /**
     * A trusted POI anchor chosen from the structured search list. The backend
     * re-validates the scene category and the city binding instead of trusting
     * the client; a POI without a provider id is never accepted as an anchor.
     */
    record StructuredPoi(
            @NotBlank @Size(max = 200) String name,
            @NotBlank @Size(max = 100) String providerPoiId,
            @Size(max = 300) String fullAddress,
            BigDecimal longitude,
            BigDecimal latitude,
            @Size(max = 60) String city,
            @Size(max = 60) String district,
            @Pattern(regexp = "AMAP|DEMO") @Size(max = 20) String provider,
            @Size(max = 60) String category,
            @Size(max = 20) String categoryCode,
            @Size(max = 12) String provinceCode,
            @Size(max = 12) String cityCode,
            @Size(max = 12) String districtCode
    ) {
    }

    record Accommodation(
            @Size(max = 120) String placeName,
            @Valid StructuredPoi poi
    ) {
    }

    record TravelAnchor(
            @NotBlank @Size(max = 120) String placeName,
            @NotNull OffsetDateTime time,
            @Valid StructuredPoi poi
    ) {
    }

    record MealWindow(
            @NotNull @Pattern(regexp = "BREAKFAST|LUNCH|DINNER") String mealType,
            @NotNull LocalTime startTime,
            @NotNull LocalTime endTime,
            @Pattern(regexp = "SYSTEM_DEFAULT|USER_SET") String source
    ) {
    }

    /** Default meal windows used when a trip does not supply any. */
    static final List<MealWindow> DEFAULT_MEAL_WINDOWS = List.of(
            new MealWindow("BREAKFAST", LocalTime.of(8, 0), LocalTime.of(9, 0), "SYSTEM_DEFAULT"),
            new MealWindow("LUNCH", LocalTime.of(12, 0), LocalTime.of(13, 0), "SYSTEM_DEFAULT"),
            new MealWindow("DINNER", LocalTime.of(18, 0), LocalTime.of(19, 0), "SYSTEM_DEFAULT")
    );

    static List<MealWindow> normalizeMealWindows(List<MealWindow> input) {
        if (input == null || input.isEmpty()) {
            return DEFAULT_MEAL_WINDOWS;
        }
        // Explicitly supplied windows are user-set unless the caller preserves
        // the SYSTEM_DEFAULT marker; a missing source means the user set it.
        return List.copyOf(input).stream()
                .map(window -> window.source() == null
                        ? new MealWindow(window.mealType(), window.startTime(), window.endTime(), "USER_SET")
                        : window)
                .toList();
    }
}
