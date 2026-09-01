package io.github.tobehardoo.trippilot.planning;

import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningProgressEvent;

@FunctionalInterface
public interface PlanningProgressHandler {

    void handle(PlanningProgressEvent event);
}
