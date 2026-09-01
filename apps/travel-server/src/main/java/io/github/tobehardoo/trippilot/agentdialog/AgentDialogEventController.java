package io.github.tobehardoo.trippilot.agentdialog;

import java.util.UUID;

import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
@RequestMapping("/api/trips/{tripId}/agent-dialogue")
public class AgentDialogEventController {

    private final AgentDialogEventStreamService streamService;

    public AgentDialogEventController(AgentDialogEventStreamService streamService) {
        this.streamService = streamService;
    }

    @GetMapping(value = "/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    ResponseEntity<SseEmitter> stream(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId,
            @RequestHeader(value = "Last-Event-ID", required = false) Long lastMessageId) {
        SseEmitter emitter = streamService.subscribe(
                UUID.fromString(jwt.getSubject()), tripId, lastMessageId
        );
        return ResponseEntity.ok().contentType(MediaType.TEXT_EVENT_STREAM).body(emitter);
    }
}
