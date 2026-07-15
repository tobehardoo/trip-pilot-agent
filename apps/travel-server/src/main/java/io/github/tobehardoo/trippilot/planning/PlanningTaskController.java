package io.github.tobehardoo.trippilot.planning;

import java.util.UUID;

import org.springframework.http.HttpStatus;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class PlanningTaskController {

    private final PlanningTaskService planningTaskService;

    public PlanningTaskController(PlanningTaskService planningTaskService) {
        this.planningTaskService = planningTaskService;
    }

    @PostMapping("/api/trips/{tripId}/planning-tasks")
    @ResponseStatus(HttpStatus.ACCEPTED)
    PlanningTaskService.PlanningTaskResponse create(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId,
            @RequestHeader("Idempotency-Key") UUID idempotencyKey) {
        return planningTaskService.create(UUID.fromString(jwt.getSubject()), tripId, idempotencyKey);
    }
}
