package io.github.tobehardoo.trippilot.infrastructure.mq;

@FunctionalInterface
public interface PlanningCommandPublisher {

    void publish(OutboxEventRecord event);
}
