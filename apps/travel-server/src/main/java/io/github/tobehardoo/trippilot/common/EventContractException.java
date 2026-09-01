package io.github.tobehardoo.trippilot.common;

/**
 * A message that violates its wire contract and must be rejected by the
 * consumer instead of retried.  Shared by the agent and planning event
 * parsers, which historically each owned an identical copy.
 */
public class EventContractException extends RuntimeException {

    public EventContractException(String message) {
        super(message);
    }

    public EventContractException(String message, Throwable cause) {
        super(message, cause);
    }
}
