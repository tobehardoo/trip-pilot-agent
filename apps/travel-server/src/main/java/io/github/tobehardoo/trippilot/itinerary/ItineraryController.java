package io.github.tobehardoo.trippilot.itinerary;

import java.util.UUID;

import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/trips/{tripId}/itinerary")
public class ItineraryController {

    private final ItineraryService itineraryService;
    private final ItineraryVersionService versionService;

    public ItineraryController(
            ItineraryService itineraryService,
            ItineraryVersionService versionService
    ) {
        this.itineraryService = itineraryService;
        this.versionService = versionService;
    }

    @GetMapping("/versions")
    java.util.List<ItineraryVersionService.VersionSummary> versions(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId
    ) {
        return versionService.list(UUID.fromString(jwt.getSubject()), tripId);
    }

    @GetMapping("/versions/diff")
    ItineraryVersionService.VersionDiff diff(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId,
            @RequestParam("from") UUID fromVersionId,
            @RequestParam("to") UUID toVersionId
    ) {
        return versionService.diff(
                UUID.fromString(jwt.getSubject()),
                tripId,
                fromVersionId,
                toVersionId
        );
    }

    @GetMapping("/versions/{versionId}")
    ItineraryService.ItineraryResponse version(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId,
            @PathVariable UUID versionId
    ) {
        return itineraryService.getVersion(
                UUID.fromString(jwt.getSubject()), tripId, versionId
        );
    }

    @PostMapping("/rollbacks")
    ItineraryService.ItineraryResponse rollback(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId,
            @RequestHeader("Idempotency-Key") UUID idempotencyKey,
            @RequestBody ItineraryVersionService.RollbackRequest request
    ) {
        return versionService.rollback(
                UUID.fromString(jwt.getSubject()),
                tripId,
                idempotencyKey,
                request
        );
    }

    @GetMapping
    ItineraryService.ItineraryResponse getCurrent(
            @AuthenticationPrincipal Jwt jwt, @PathVariable UUID tripId) {
        return itineraryService.getCurrent(UUID.fromString(jwt.getSubject()), tripId);
    }

    @PostMapping("/edits/preview")
    ItineraryService.ItineraryEditPreviewResponse previewEdit(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId,
            @RequestBody ItineraryService.ItineraryEditRequest request) {
        return itineraryService.previewEdit(UUID.fromString(jwt.getSubject()), tripId, request);
    }

    @PostMapping("/edits")
    ItineraryService.ItineraryResponse applyEdit(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId,
            @RequestHeader("Idempotency-Key") UUID idempotencyKey,
            @RequestBody ItineraryService.ItineraryEditRequest request) {
        return itineraryService.applyEdit(
                UUID.fromString(jwt.getSubject()), tripId, idempotencyKey, request);
    }
}
