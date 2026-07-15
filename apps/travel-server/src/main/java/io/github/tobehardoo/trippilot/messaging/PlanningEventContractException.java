package io.github.tobehardoo.trippilot.messaging;

public class PlanningEventContractException extends RuntimeException {

    public PlanningEventContractException(String message) {
        super(message);
    }

    public PlanningEventContractException(String message, Throwable cause) {
        super(message, cause);
    }
}
