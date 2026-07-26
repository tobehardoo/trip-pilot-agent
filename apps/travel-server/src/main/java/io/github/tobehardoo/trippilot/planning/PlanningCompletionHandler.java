package io.github.tobehardoo.trippilot.planning;

import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningCompletedEvent;

@FunctionalInterface
public interface PlanningCompletionHandler {

    void handle(PlanningCompletedEvent event);
}
