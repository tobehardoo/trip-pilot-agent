package io.github.tobehardoo.trippilot.system;

import java.time.LocalDate;

import io.github.tobehardoo.trippilot.trip.TripDatePolicy;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Lightweight endpoint the web client uses before authentication to anchor
 * date pickers to the server's Beijing-time calendar. Unauthenticated on
 * purpose.
 */
@RestController
@RequestMapping("/api/system")
public class SystemTimeController {

    private final TripDatePolicy datePolicy;

    public SystemTimeController(TripDatePolicy datePolicy) {
        this.datePolicy = datePolicy;
    }

    @GetMapping("/time")
    public SystemTimeResponse time() {
        return new SystemTimeResponse(datePolicy.today(), datePolicy.timeZone());
    }

    public record SystemTimeResponse(LocalDate serverDate, String timeZone) {
    }
}
