package io.github.tobehardoo.trippilot.planning;

import java.util.Set;
import java.util.UUID;

import io.github.tobehardoo.trippilot.common.ApiException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@Service
public class PlanningTaskEventStreamService {

    private static final Set<String> TERMINAL_STATUSES = Set.of("SUCCEEDED", "FAILED", "CANCELLED");

    private final PlanningTaskMapper taskMapper;
    private final PlanningTaskEventHub eventHub;

    public PlanningTaskEventStreamService(PlanningTaskMapper taskMapper,
                                          PlanningTaskEventHub eventHub) {
        this.taskMapper = taskMapper;
        this.eventHub = eventHub;
    }

    @Transactional(readOnly = true)
    public SseEmitter subscribe(UUID ownerId, UUID taskId, Long lastEventId) {
        PlanningTaskRecord task = taskMapper.findOwnedById(taskId, ownerId)
                .orElseThrow(() -> new ApiException(
                        HttpStatus.NOT_FOUND, "PLANNING_TASK_NOT_FOUND", "Planning task was not found"
                ));
        long afterEventId = lastEventId == null ? 0 : Math.max(0, lastEventId);
        return eventHub.subscribe(taskId, afterEventId, TERMINAL_STATUSES.contains(task.status()));
    }
}
