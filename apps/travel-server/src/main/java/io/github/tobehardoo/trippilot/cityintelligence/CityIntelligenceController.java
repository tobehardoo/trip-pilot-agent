package io.github.tobehardoo.trippilot.cityintelligence;

import java.util.UUID;

import io.github.tobehardoo.trippilot.cityintelligence.CityIntelligenceStatusService.CityIntelligenceStatusResponse;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/trips/{tripId}/city-intelligence")
public class CityIntelligenceController {

    private final CityIntelligenceStatusService statusService;

    public CityIntelligenceController(CityIntelligenceStatusService statusService) {
        this.statusService = statusService;
    }

    @GetMapping
    CityIntelligenceStatusResponse get(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId
    ) {
        return statusService.get(UUID.fromString(jwt.getSubject()), tripId);
    }

    @PostMapping("/refreshes")
    @ResponseStatus(HttpStatus.ACCEPTED)
    CityIntelligenceStatusResponse refresh(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId,
            @RequestHeader("Idempotency-Key") UUID idempotencyKey
    ) {
        return statusService.refresh(
                UUID.fromString(jwt.getSubject()),
                tripId,
                idempotencyKey
        );
    }
}
