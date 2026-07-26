package io.github.tobehardoo.trippilot.infrastructure.mq;

public class PlanningEventContractException extends RuntimeException {

    public PlanningEventContractException(String message) {
        super(message);
    }

    public PlanningEventContractException(String message, Throwable cause) {
        super(message, cause);
    }
}
