package io.github.tobehardoo.trippilot.planning;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

import io.github.tobehardoo.trippilot.common.ApiException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class InternalPlanningDiagnosticsService {

    private final PlanningTaskMapper planningTaskMapper;
    private final PlanningTaskService planningTaskService;

    public InternalPlanningDiagnosticsService(
            PlanningTaskMapper planningTaskMapper,
            PlanningTaskService planningTaskService
    ) {
        this.planningTaskMapper = planningTaskMapper;
        this.planningTaskService = planningTaskService;
    }

    @Transactional(readOnly = true)
    public PlanningFailurePage recentFailures(int limit) {
        if (limit < 1 || limit > 100) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "DIAGNOSTICS_LIMIT_INVALID",
                    "Diagnostics limit must be between 1 and 100");
        }
        List<PlanningFailure> items = planningTaskMapper.findRecentFailures(limit).stream()
                .map(record -> new PlanningFailure(
                        record.taskId(), record.tripId(), record.taskType(), record.status(),
                        record.lastStage(), record.errorCode(), record.errorMessage(),
                        record.retryCount(), record.traceId(), record.updatedAt()
                ))
                .toList();
        return new PlanningFailurePage(items);
    }

    public PlanningTaskService.PlanningTaskResponse retryFailedCreate(UUID taskId, UUID idempotencyKey) {
        PlanningTaskMapper.RetryableFailedTask task = planningTaskMapper.findRetryableFailedCreate(taskId)
                .orElseThrow(() -> new ApiException(HttpStatus.CONFLICT, "PLANNING_RETRY_UNAVAILABLE",
                        "Only failed full-planning tasks can be retried from diagnostics"));
        return planningTaskService.create(task.ownerId(), task.tripId(), idempotencyKey);
    }

    public record PlanningFailurePage(List<PlanningFailure> items) {
    }

    public record PlanningFailure(
            UUID taskId,
            UUID tripId,
            String taskType,
            String status,
            String lastStage,
            String errorCode,
            String errorMessage,
            int retryCount,
            UUID traceId,
            Instant failedAt
    ) {
    }
}
