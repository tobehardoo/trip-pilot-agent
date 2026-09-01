package io.github.tobehardoo.trippilot.planning;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.UUID;

import io.github.tobehardoo.trippilot.common.ApiException;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/internal/diagnostics")
public class InternalPlanningDiagnosticsController {

    private final InternalDiagnosticsProperties properties;
    private final InternalPlanningDiagnosticsService diagnosticsService;

    public InternalPlanningDiagnosticsController(
            InternalDiagnosticsProperties properties,
            InternalPlanningDiagnosticsService diagnosticsService
    ) {
        this.properties = properties;
        this.diagnosticsService = diagnosticsService;
    }

    @GetMapping("/planning-failures")
    InternalPlanningDiagnosticsService.PlanningFailurePage recentFailures(
            @RequestHeader(value = "X-Internal-Token", required = false) String internalToken,
            @RequestParam(defaultValue = "20") int limit
    ) {
        requireInternalToken(internalToken);
        return diagnosticsService.recentFailures(limit);
    }

    @PostMapping("/planning-tasks/{taskId}/retries")
    @ResponseStatus(HttpStatus.ACCEPTED)
    PlanningTaskService.PlanningTaskResponse retryFailedCreate(
            @RequestHeader(value = "X-Internal-Token", required = false) String internalToken,
            @RequestHeader("Idempotency-Key") UUID idempotencyKey,
            @PathVariable UUID taskId
    ) {
        requireInternalToken(internalToken);
        return diagnosticsService.retryFailedCreate(taskId, idempotencyKey);
    }

    private void requireInternalToken(String suppliedToken) {
        byte[] expected = properties.internalToken().getBytes(StandardCharsets.UTF_8);
        byte[] supplied = suppliedToken == null ? new byte[expected.length]
                : suppliedToken.getBytes(StandardCharsets.UTF_8);
        if (!MessageDigest.isEqual(expected, supplied)) {
            throw new ApiException(HttpStatus.FORBIDDEN, "INTERNAL_ACCESS_DENIED",
                    "Internal diagnostics access was denied");
        }
    }
}
