package io.github.tobehardoo.trippilot.planning;

import java.util.UUID;

import io.github.tobehardoo.trippilot.common.ApiException;
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
@RequestMapping("/api/planning-tasks/{taskId}/events")
public class PlanningTaskEventController {

    private final PlanningTaskEventStreamService streamService;

    public PlanningTaskEventController(PlanningTaskEventStreamService streamService) {
        this.streamService = streamService;
    }

    @GetMapping(produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    ResponseEntity<SseEmitter> stream(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID taskId,
            @RequestHeader(value = "Last-Event-ID", required = false) Long lastEventId) {
        try {
            SseEmitter emitter = streamService.subscribe(
                    UUID.fromString(jwt.getSubject()), taskId, lastEventId
            );
            return ResponseEntity.ok().contentType(MediaType.TEXT_EVENT_STREAM).body(emitter);
        } catch (ApiException exception) {
            return ResponseEntity.status(exception.status()).build();
        }
    }
}
