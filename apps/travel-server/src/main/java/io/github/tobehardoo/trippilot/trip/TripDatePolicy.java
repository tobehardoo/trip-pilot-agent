package io.github.tobehardoo.trippilot.trip;

import java.time.Clock;
import java.time.LocalDate;
import java.time.ZoneId;

import io.github.tobehardoo.trippilot.common.ApiException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

/**
 * Business date policy for trips.
 *
 * All user-facing trip dates are interpreted in the business time zone
 * (Asia/Shanghai) regardless of the browser or server default time zone.
 * The underlying {@link Clock} is injectable so tests can fix "today".
 */
@Component
public class TripDatePolicy {

    public static final ZoneId BUSINESS_ZONE = ZoneId.of("Asia/Shanghai");

    private final Clock clock;

    public TripDatePolicy(Clock clock) {
        this.clock = clock;
    }

    /** Today's date in the business time zone. */
    public LocalDate today() {
        return LocalDate.now(clock.withZone(BUSINESS_ZONE));
    }

    public String timeZone() {
        return BUSINESS_ZONE.getId();
    }

    /**
     * Rejects a new trip whose start date is already in the past in the
     * business time zone. Historical trips are never re-validated: this check
     * runs only on creation.
     */
    public void validateNewTripStartDate(LocalDate startDate) {
        if (startDate.isBefore(today())) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "TRIP_START_DATE_IN_PAST",
                    "Trip start date must be today or later (Asia/Shanghai)"
            );
        }
    }
}
