package io.github.tobehardoo.trippilot.planning;

import org.slf4j.MDC;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Thread-local structured-logging context for the planning pipeline.
 *
 * <p>Key boundaries open a scope, add the correlation fields they own, log,
 * and close the scope in a {@code finally} (or try-with-resources).  Each
 * scope snapshots the managed keys at open and restores them at close, so
 * nested scopes are safe (a service scope never wipes a listener's fields)
 * and a reused listener thread can never leak a previous task's
 * {@code taskId}/{@code traceId}.
 *
 * <p>This is the only MDC touchpoint for the planning pipeline; there is no
 * global mutable context and no second trace system.
 */
public final class PlanningLogContext implements AutoCloseable {

    public static final String TRACE_ID = "traceId";
    public static final String EVENT_ID = "eventId";
    public static final String TASK_ID = "taskId";
    public static final String TRIP_ID = "tripId";
    public static final String RUN_ID = "runId";
    public static final String TASK_TYPE = "taskType";
    public static final String CANDIDATE_TYPE = "candidateType";
    public static final String SCHEMA_VERSION = "schemaVersion";
    public static final String EVENT_TYPE = "eventType";
    public static final String OUTCOME_STATUS = "outcomeStatus";
    public static final String ATTEMPT_INDEX = "attemptIndex";
    public static final String PROVIDER = "provider";
    public static final String OPERATION = "operation";
    public static final String RETRYABLE = "retryable";
    public static final String FALLBACK_ATTEMPTED = "fallbackAttempted";
    public static final String FALLBACK_SUCCEEDED = "fallbackSucceeded";
    public static final String RETRY_COUNT = "retryCount";

    private static final List<String> MANAGED_KEYS = List.of(
            TRACE_ID, EVENT_ID, TASK_ID, TRIP_ID, RUN_ID, TASK_TYPE, CANDIDATE_TYPE,
            SCHEMA_VERSION, EVENT_TYPE, OUTCOME_STATUS, ATTEMPT_INDEX, PROVIDER,
            OPERATION, RETRYABLE, FALLBACK_ATTEMPTED, FALLBACK_SUCCEEDED, RETRY_COUNT
    );

    private final Map<String, String> previous = new HashMap<>();

    private PlanningLogContext() {
        for (String key : MANAGED_KEYS) {
            previous.put(key, MDC.get(key));
        }
    }

    public static PlanningLogContext open() {
        return new PlanningLogContext();
    }

    /** Adds a key with a non-null value and returns this scope for chaining. */
    public PlanningLogContext put(String key, String value) {
        if (value != null && !value.isBlank()) {
            MDC.put(key, value);
        }
        return this;
    }

    /** Restores every managed key to its pre-open value (or removes it). */
    @Override
    public void close() {
        for (Map.Entry<String, String> entry : previous.entrySet()) {
            String prior = entry.getValue();
            if (prior == null) {
                MDC.remove(entry.getKey());
            } else {
                MDC.put(entry.getKey(), prior);
            }
        }
    }
}
