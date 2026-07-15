package io.github.tobehardoo.trippilot.itinerary;

import java.util.UUID;

import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/trips/{tripId}/itinerary")
public class ItineraryController {

    private final ItineraryService itineraryService;

    public ItineraryController(ItineraryService itineraryService) {
        this.itineraryService = itineraryService;
    }

    @GetMapping
    ItineraryService.ItineraryResponse getCurrent(
            @AuthenticationPrincipal Jwt jwt, @PathVariable UUID tripId) {
        return itineraryService.getCurrent(UUID.fromString(jwt.getSubject()), tripId);
    }
}
