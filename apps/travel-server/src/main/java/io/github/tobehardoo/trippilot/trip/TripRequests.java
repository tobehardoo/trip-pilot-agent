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

    record CreateTripRequest(
            @NotBlank @Size(max = 120) String title,
            @NotBlank @Size(max = 120) String destination,
            @NotNull LocalDate startDate,
            @NotNull LocalDate endDate,
            @NotNull @Valid ConstraintInput constraints
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
            @Valid PlaceAnchor accommodation,
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
            @Size(max = 3) List<@NotNull @Valid MealWindow> mealWindows,
            @Pattern(regexp = "STANDARD|REDUCED|STEP_FREE") String mobilityLevel
    ) {
        ConstraintInput {
            mustVisitPlaces = mustVisitPlaces == null ? List.of() : List.copyOf(mustVisitPlaces);
            avoidPlaces = avoidPlaces == null ? List.of() : List.copyOf(avoidPlaces);
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
            @NotBlank @Size(max = 120) String placeName
    ) {
    }

    record TravelAnchor(
            @NotBlank @Size(max = 120) String placeName,
            @NotNull OffsetDateTime time
    ) {
    }

    record MealWindow(
            @NotNull @Pattern(regexp = "BREAKFAST|LUNCH|DINNER") String mealType,
            @NotNull LocalTime startTime,
            @NotNull LocalTime endTime
    ) {
    }
}
