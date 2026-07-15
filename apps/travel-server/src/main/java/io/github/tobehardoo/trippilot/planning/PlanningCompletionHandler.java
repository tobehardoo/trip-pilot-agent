package io.github.tobehardoo.trippilot.planning;

import io.github.tobehardoo.trippilot.messaging.PlanningCompletedEvent;

@FunctionalInterface
public interface PlanningCompletionHandler {

    void handle(PlanningCompletedEvent event);
}
