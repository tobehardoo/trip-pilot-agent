package io.github.tobehardoo.trippilot.trip;

import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.trip.TripRequests.ConstraintInput;
import io.github.tobehardoo.trippilot.trip.TripRequests.FixedSchedule;
import io.github.tobehardoo.trippilot.trip.TripRequests.MealWindow;
import io.github.tobehardoo.trippilot.trip.TripRequests.StructuredPoi;
import io.github.tobehardoo.trippilot.trip.TripRequests.TravelAnchor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

/**
 * Pure domain validation for trip constraints.
 *
 * Extracted from {@link TripService} so that validation rules can be
 * tested independently and reused by other services without pulling in
 * the full service dependency.
 */
@Component
public class TripConstraintValidator {

    private static final ZoneOffset CHINA_OFFSET = ZoneOffset.ofHours(8);
    private static final long MAX_TRIP_DAYS = 7;

    // --- public API ---------------------------------------------------------

    public void validateDateRange(LocalDate startDate, LocalDate endDate) {
        if (endDate.isBefore(startDate)) {
            throw failure("endDate must not be before startDate");
        }
        if (ChronoUnit.DAYS.between(startDate, endDate) + 1 > MAX_TRIP_DAYS) {
            throw failure("Trip duration must not exceed 7 days");
        }
    }

    public void validateSchedules(
            List<FixedSchedule> schedules,
            LocalDate startDate,
            LocalDate endDate
    ) {
        for (FixedSchedule schedule : schedules) {
            if (!schedule.endTime().isAfter(schedule.startTime())
                    || schedule.startTime().withOffsetSameInstant(CHINA_OFFSET)
                            .toLocalDate().isBefore(startDate)
                    || schedule.endTime().withOffsetSameInstant(CHINA_OFFSET)
                            .toLocalDate().isAfter(endDate)) {
                throw failure(
                        "Fixed schedules must be ordered and fall within the trip dates"
                );
            }
        }
    }

    public void validateContext(
            ConstraintInput input,
            String destination,
            LocalDate startDate,
            LocalDate endDate
    ) {
        validateAnchor(input.arrival(), startDate, endDate);
        validateAnchor(input.departure(), startDate, endDate);
        validatePoi(input.arrival() == null ? null : input.arrival().poi(), destination, "TRANSPORT");
        validatePoi(input.departure() == null ? null : input.departure().poi(), destination, "TRANSPORT");
        if (input.accommodation() != null) {
            validatePoi(input.accommodation().poi(), destination, "HOTEL");
        }
        if (input.arrival() != null && input.departure() != null
                && !input.departure().time().isAfter(input.arrival().time())) {
            throw failure("Departure time must be after arrival time");
        }
        Set<String> mustVisit = normalized(input.mustVisitPlaces());
        Set<String> avoided = normalized(input.avoidPlaces());
        mustVisit.retainAll(avoided);
        if (!mustVisit.isEmpty()) {
            throw failure("Must-visit and avoided places must not overlap");
        }
        Set<String> mealTypes = new HashSet<>();
        List<MealWindow> orderedMeals = new ArrayList<>(input.mealWindows());
        orderedMeals.sort(Comparator.comparing(MealWindow::startTime));
        for (MealWindow window : input.mealWindows()) {
            if (!window.endTime().isAfter(window.startTime())
                    || !mealTypes.add(window.mealType())) {
                throw failure(
                        "Meal windows must be ordered and use unique meal types"
                );
            }
        }
        for (int index = 1; index < orderedMeals.size(); index++) {
            if (orderedMeals.get(index).startTime()
                    .isBefore(orderedMeals.get(index - 1).endTime())) {
                throw failure("Meal windows must not overlap");
            }
        }
    }

    // --- internal helpers ---------------------------------------------------

    /**
     * Structured POIs are the only trusted coordinate anchors. A POI must
     * carry a provider, both coordinates, an address, and a city that matches
     * the trip destination; its category code must fit the scene (transport for
     * arrival/departure, lodging for the hotel). Anything else fails closed
     * with a clear 400 instead of silently degrading to free text.
     */
    private void validatePoi(StructuredPoi poi, String destination, String scene) {
        if (poi == null) {
            return;
        }
        if (poi.provider() == null || poi.provider().isBlank()) {
            throw failure("Structured POI must include a provider");
        }
        if ((poi.longitude() == null) != (poi.latitude() == null)) {
            throw failure("Structured POI longitude and latitude must be provided together");
        }
        if (poi.fullAddress() == null || poi.fullAddress().isBlank()) {
            throw failure("Structured POI must include a full address");
        }
        if (poi.city() == null || poi.city().isBlank()) {
            throw failure("Structured POI must include a city");
        }
        if (!sameCity(destination, poi.city())) {
            throw failure("Structured POI city must match the trip destination");
        }
        if (poi.categoryCode() == null || poi.categoryCode().isBlank()) {
            throw failure("Structured POI must include a category code");
        }
        if (!belongsToScene(poi.categoryCode(), scene)) {
            throw failure(poi.categoryCode() + " is not a valid "
                    + ("HOTEL".equals(scene) ? "lodging" : "transport") + " category for this place");
        }
    }

    /**
     * AMap type-code allowlists, aligned with the category filters the search
     * client applies per scene so a saved anchor can never come from outside
     * its scene. Transport covers railway (1503), bus (1504), port (1505),
     * metro (1506), light rail (1507), and airport (1508); lodging starts at 12.
     */
    private static boolean belongsToScene(String categoryCode, String scene) {
        if ("HOTEL".equals(scene)) {
            return categoryCode.startsWith("12");
        }
        return categoryCode.startsWith("1503")
                || categoryCode.startsWith("1504")
                || categoryCode.startsWith("1505")
                || categoryCode.startsWith("1506")
                || categoryCode.startsWith("1507")
                || categoryCode.startsWith("1508");
    }

    private static boolean sameCity(String destination, String poiCity) {
        return normalizeCity(destination).equals(normalizeCity(poiCity));
    }

    private static String normalizeCity(String value) {
        if (value == null) {
            return "";
        }
        return value.trim().replaceAll("[市]$", "").toLowerCase(Locale.ROOT);
    }

    private void validateAnchor(
            TravelAnchor anchor,
            LocalDate startDate,
            LocalDate endDate
    ) {
        if (anchor == null) {
            return;
        }
        LocalDate anchorDate =
                anchor.time().withOffsetSameInstant(CHINA_OFFSET).toLocalDate();
        if (anchorDate.isBefore(startDate) || anchorDate.isAfter(endDate)) {
            throw failure("Travel anchor times must fall within the trip dates");
        }
    }

    private static Set<String> normalized(List<String> values) {
        Set<String> result = new HashSet<>();
        for (String value : values) {
            result.add(value.trim().toLowerCase(Locale.ROOT));
        }
        return result;
    }

    private static ApiException failure(String message) {
        return new ApiException(
                HttpStatus.BAD_REQUEST, "VALIDATION_FAILED", message
        );
    }
}
