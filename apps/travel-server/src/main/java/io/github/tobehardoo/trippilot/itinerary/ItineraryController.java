package io.github.tobehardoo.trippilot.itinerary;

import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.ApiException;
import org.springframework.http.HttpStatus;
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
    private final ItineraryEditRoutingCoordinator editRoutingCoordinator;
    private final ObjectMapper objectMapper;
    private final EditRequestFingerprint editRequestFingerprint;

    public ItineraryController(
            ItineraryService itineraryService,
            ItineraryVersionService versionService,
            ItineraryEditRoutingCoordinator editRoutingCoordinator,
            ObjectMapper objectMapper,
            EditRequestFingerprint editRequestFingerprint
    ) {
        this.itineraryService = itineraryService;
        this.versionService = versionService;
        this.editRoutingCoordinator = editRoutingCoordinator;
        this.objectMapper = objectMapper;
        this.editRequestFingerprint = editRequestFingerprint;
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
    @org.springframework.web.bind.annotation.ResponseStatus(HttpStatus.ACCEPTED)
    io.github.tobehardoo.trippilot.planning.PlanningTaskService.PlanningTaskResponse rollback(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId,
            @RequestHeader("Idempotency-Key") UUID idempotencyKey,
            @RequestBody ItineraryVersionService.RollbackRequest request
    ) {
        JsonNode tree = objectMapper.valueToTree(request);
        return versionService.validateRollback(
                UUID.fromString(jwt.getSubject()), tripId, idempotencyKey,
                request, editRequestFingerprint.forRollback(tree));
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
    @org.springframework.web.bind.annotation.ResponseStatus(HttpStatus.ACCEPTED)
    io.github.tobehardoo.trippilot.planning.PlanningTaskService.PlanningTaskResponse applyEdit(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId,
            @RequestHeader("Idempotency-Key") UUID idempotencyKey,
            @RequestBody JsonNode request) {
        return editRoutingCoordinator.validateEditCandidate(
                UUID.fromString(jwt.getSubject()), tripId, idempotencyKey,
                read(request, ItineraryService.ItineraryEditRequest.class),
                editRequestFingerprint.forEdit(request));
    }

    @PostMapping("/edits/commit")
    @org.springframework.web.bind.annotation.ResponseStatus(HttpStatus.ACCEPTED)
    io.github.tobehardoo.trippilot.planning.PlanningTaskService.PlanningTaskResponse commitEdits(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId,
            @RequestHeader("Idempotency-Key") UUID idempotencyKey,
            @RequestBody JsonNode request) {
        return editRoutingCoordinator.validateEditCandidates(
                UUID.fromString(jwt.getSubject()), tripId, idempotencyKey,
                read(request, ItineraryService.ItineraryBatchEditRequest.class),
                editRequestFingerprint.forBatch(request));
    }

    private <T> T read(JsonNode request, Class<T> type) {
        try {
            return objectMapper.treeToValue(request, type);
        } catch (JsonProcessingException exception) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "INVALID_REQUEST", "Request body is invalid");
        }
    }
}
