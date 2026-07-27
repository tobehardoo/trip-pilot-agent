package io.github.tobehardoo.trippilot.share;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping
public class ItineraryShareController {

    private final ItineraryShareService shareService;

    public ItineraryShareController(ItineraryShareService shareService) {
        this.shareService = shareService;
    }

    @PostMapping("/api/trips/{tripId}/itinerary/shares")
    @ResponseStatus(HttpStatus.CREATED)
    ItineraryShareService.CreatedShare create(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId,
            @Valid @RequestBody CreateShareRequest request
    ) {
        return shareService.create(userId(jwt), tripId, request.versionId(), request.expiresAt());
    }

    @GetMapping("/api/trips/{tripId}/itinerary/shares")
    List<ItineraryShareService.ShareStatus> list(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId
    ) {
        return shareService.list(userId(jwt), tripId);
    }

    @DeleteMapping("/api/trips/{tripId}/itinerary/shares/{shareId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    void revoke(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId,
            @PathVariable UUID shareId
    ) {
        shareService.revoke(userId(jwt), tripId, shareId);
    }

    @GetMapping("/api/shares/{shareToken}")
    ItineraryShareService.PublicItinerary resolve(
            @PathVariable String shareToken,
            HttpServletRequest request
    ) {
        return shareService.resolvePublic(shareToken, clientAddress(request));
    }

    static String clientAddress(HttpServletRequest request) {
        String forwardedFor = request.getHeader("X-Forwarded-For");
        if (forwardedFor != null && !forwardedFor.isBlank()) {
            return forwardedFor.split(",", 2)[0].trim();
        }
        return request.getRemoteAddr();
    }

    private UUID userId(Jwt jwt) {
        return UUID.fromString(jwt.getSubject());
    }

    record CreateShareRequest(@NotNull UUID versionId, Instant expiresAt) {
    }
}
