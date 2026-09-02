package io.github.tobehardoo.trippilot.agentdialog;

import java.util.UUID;

import io.github.tobehardoo.trippilot.trip.TripService;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * P2.8a: the agent-path trigger endpoints.  Commands are queued through the
 * transactional outbox; the dialog events stream back over
 * {@code GET /agent-dialogue/events}.
 *
 * The trip entity's destination/dates are injected into the AGENT_START payload
 * as read-only TRIP facts so the worker doesn't re-ask what the user already set.
 */
@RestController
@RequestMapping("/api/trips/{tripId}/agent-dialogue")
public class AgentDialogRunController {

    private final AgentDialogCommandService commandService;
    private final TripService tripService;

    public AgentDialogRunController(
            AgentDialogCommandService commandService,
            TripService tripService
    ) {
        this.commandService = commandService;
        this.tripService = tripService;
    }

    public record StartRunRequest(String message) {
    }

    public record AnswerRequest(String answer) {
    }

    public record QueuedReply(UUID eventId, String status) {
    }

    @PostMapping("/runs")
    ResponseEntity<QueuedReply> startRun(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId,
            @RequestHeader(value = "Idempotency-Key", required = false) UUID idempotencyKey,
            @RequestBody StartRunRequest request
    ) {
        UUID ownerId = UUID.fromString(jwt.getSubject());
        UUID eventId = idempotencyKey == null ? UUID.randomUUID() : idempotencyKey;
        // Fetch the trip entity to seed the dialog with read-only TRIP facts.
        TripService.TripResponse trip = tripService.get(ownerId, tripId);
        HttpAgentDialogClient.TripContext tripContext = new HttpAgentDialogClient.TripContext(
                trip.destination(),
                String.valueOf(trip.startDate()),
                String.valueOf(trip.endDate())
        );
        AgentDialogCommandService.CommandQueued queued = commandService.startRun(
                ownerId, tripId, eventId, request.message(), tripContext
        );
        return ResponseEntity.status(HttpStatus.ACCEPTED)
                .body(new QueuedReply(queued.eventId(), queued.status()));
    }

    @PostMapping("/runs/{runId}/answers")
    ResponseEntity<QueuedReply> answer(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId,
            @PathVariable UUID runId,
            @RequestHeader(value = "Idempotency-Key", required = false) UUID idempotencyKey,
            @RequestBody AnswerRequest request
    ) {
        UUID eventId = idempotencyKey == null ? UUID.randomUUID() : idempotencyKey;
        AgentDialogCommandService.CommandQueued queued = commandService.resumeRun(
                UUID.fromString(jwt.getSubject()), tripId, runId, eventId, request.answer()
        );
        return ResponseEntity.status(HttpStatus.ACCEPTED)
                .body(new QueuedReply(queued.eventId(), queued.status()));
    }
}
