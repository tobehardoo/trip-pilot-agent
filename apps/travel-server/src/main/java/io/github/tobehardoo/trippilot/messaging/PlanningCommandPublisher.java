package io.github.tobehardoo.trippilot.messaging;

@FunctionalInterface
public interface PlanningCommandPublisher {

    void publish(OutboxEventRecord event);
}
