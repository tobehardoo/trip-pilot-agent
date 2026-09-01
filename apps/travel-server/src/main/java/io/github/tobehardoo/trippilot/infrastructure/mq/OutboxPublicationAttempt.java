package io.github.tobehardoo.trippilot.infrastructure.mq;

@FunctionalInterface
public interface OutboxPublicationAttempt {

    boolean publishNext();
}
