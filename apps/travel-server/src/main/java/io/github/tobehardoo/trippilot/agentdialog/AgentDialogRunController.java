package io.github.tobehardoo.trippilot.agentdialog;

import java.util.UUID;

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
 */
@RestController
@RequestMapping("/api/trips/{tripId}/agent-dialogue")
public class AgentDialogRunController {

    private final AgentDialogCommandService commandService;

    public AgentDialogRunController(AgentDialogCommandService commandService) {
        this.commandService = commandService;
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
        UUID eventId = idempotencyKey == null ? UUID.randomUUID() : idempotencyKey;
        AgentDialogCommandService.CommandQueued queued = commandService.startRun(
                UUID.fromString(jwt.getSubject()), tripId, eventId, request.message()
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
