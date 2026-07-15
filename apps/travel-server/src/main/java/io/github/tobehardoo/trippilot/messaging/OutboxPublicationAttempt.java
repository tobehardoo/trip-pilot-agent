package io.github.tobehardoo.trippilot.messaging;

@FunctionalInterface
public interface OutboxPublicationAttempt {

    boolean publishNext();
}
