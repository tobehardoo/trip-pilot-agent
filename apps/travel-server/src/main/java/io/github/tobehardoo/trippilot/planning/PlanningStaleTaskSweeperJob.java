package io.github.tobehardoo.trippilot.planning;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;

import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningFailedEvent;

/**
 * Reaps planning tasks stuck in an active state (QUEUED / RUNNING) well past
 * any legitimate planning duration.
 *
 * <p>Recovery division of labour: a worker that dies mid-command gets its MQ
 * delivery redelivered and the task reprocessed from scratch (completion
 * idempotency prevents duplicate versions).  What redelivery cannot fix is a
 * command that was acked but whose completion event never landed, or a
 * message lost to the dead-letter path — those tasks stay active forever and,
 * through the one-active-task-per-trip index, permanently lock the trip out
 * of planning.  This sweeper closes that hole: past the configured timeout it
 * fails the task through the regular {@link PlanningFailureService} path, so
 * the terminal event, trip phase rollback, SSE closure and metrics are
 * exactly the ones a worker-reported failure would produce.
 *
 * <p>Deliberately out of scope (三问纪律): stage-level checkpointing of the
 * planning pipeline (reprocessing from scratch is cheap and Redis-cached),
 * RETRYING tasks (owned by the worker retry/DLX path), and WAITING_USER
 * tasks (a long review is a legitimate user decision, not a stall).
 */
public class PlanningStaleTaskSweeperJob {

    private static final Logger log = LoggerFactory.getLogger(PlanningStaleTaskSweeperJob.class);

    static final String STALE_TASK_ERROR_CODE = "STALE_TASK_REAPED";

    private final PlanningTaskMapper taskMapper;
    private final PlanningFailureService failureService;
    private final Clock clock;
    private final Duration staleTimeout;
    private final int batchSize;

    public PlanningStaleTaskSweeperJob(
            PlanningTaskMapper taskMapper,
            PlanningFailureService failureService,
            Clock clock,
            @Value("${app.planning.stale-task-timeout-minutes:30}") long staleTimeoutMinutes,
            @Value("${app.planning.stale-task-batch-size:20}") int batchSize
    ) {
        this.taskMapper = taskMapper;
        this.failureService = failureService;
        this.clock = clock;
        this.staleTimeout = Duration.ofMinutes(staleTimeoutMinutes);
        this.batchSize = batchSize;
    }

    @Scheduled(fixedDelayString = "${app.planning.stale-task-sweeper-delay-ms:60000}")
    public void reapStaleTasks() {
        Instant threshold = clock.instant().minus(staleTimeout);
        List<UUID> staleIds = taskMapper.findStaleActiveTaskIds(threshold, batchSize);
        for (UUID taskId : staleIds) {
            try {
                failureService.handle(syntheticFailure(taskId));
                log.warn("reaped stale planning task: taskId={} timeoutMinutes={}",
                        taskId, staleTimeout.toMinutes());
            } catch (Exception exception) {
                // The task may have completed between the scan and the reap;
                // the failure service's status guard rejects those.  Nothing
                // to roll back — skip and let the rest of the batch proceed.
                log.info("stale reaper skipped task {}: {}", taskId, exception.getMessage());
            }
        }
    }

    private PlanningFailedEvent syntheticFailure(UUID taskId) {
        PlanningTaskMapper.PlanningTaskRef ref = taskMapper.findTaskRef(taskId)
                .orElseThrow(() -> new IllegalStateException("Stale task disappeared: " + taskId));
        PlanningFailedEvent.Payload payload = new PlanningFailedEvent.Payload(
                "FAILED",
                STALE_TASK_ERROR_CODE,
                "Planning stopped responding and was recovered; start a new plan to retry",
                List.of(),
                List.of()
        );
        return new PlanningFailedEvent(
                "PLANNING_FAILED",
                2,
                UUID.randomUUID(),
                ref.traceId(),
                ref.id(),
                ref.tripId(),
                null,
                OffsetDateTime.ofInstant(clock.instant(), ZoneOffset.UTC),
                payload
        );
    }
}
