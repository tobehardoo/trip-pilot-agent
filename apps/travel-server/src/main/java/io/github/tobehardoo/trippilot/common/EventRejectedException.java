package io.github.tobehardoo.trippilot.common;

/**
 * A domain event that must not be retried (identity or state mismatch).
 * Shared by the agent-dialog and planning domains, which historically each
 * owned an identical copy.
 */
public class EventRejectedException extends RuntimeException {

    public EventRejectedException(String message) {
        super(message);
    }
}
