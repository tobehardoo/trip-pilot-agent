package io.github.tobehardoo.trippilot.export;

import java.nio.charset.StandardCharsets;
import java.util.UUID;

import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/trips/{tripId}/itinerary/exports")
public class ItineraryExportController {

    private final ItineraryExportService exportService;

    public ItineraryExportController(ItineraryExportService exportService) {
        this.exportService = exportService;
    }

    @GetMapping("/ics")
    ResponseEntity<byte[]> calendar(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId,
            @RequestParam(required = false) UUID versionId
    ) {
        ItineraryExportService.ExportedItinerary export = exportService.calendar(userId(jwt), tripId, versionId);
        return attachment(export, "ics", MediaType.parseMediaType("text/calendar; charset=UTF-8"));
    }

    @GetMapping("/pdf")
    ResponseEntity<byte[]> pdf(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId,
            @RequestParam(required = false) UUID versionId
    ) {
        ItineraryExportService.ExportedItinerary export = exportService.pdf(userId(jwt), tripId, versionId);
        return attachment(export, "pdf", MediaType.APPLICATION_PDF);
    }

    private ResponseEntity<byte[]> attachment(
            ItineraryExportService.ExportedItinerary export,
            String extension,
            MediaType contentType
    ) {
        String filename = "trip-pilot-itinerary-v" + export.versionNumber() + "." + extension;
        return ResponseEntity.ok()
                .contentType(contentType)
                .header(HttpHeaders.CONTENT_DISPOSITION, ContentDisposition.attachment()
                        .filename(filename, StandardCharsets.UTF_8).build().toString())
                .body(export.content());
    }

    private UUID userId(Jwt jwt) {
        return UUID.fromString(jwt.getSubject());
    }
}
