package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

public record PlanningFailedEvent(
        String eventType,
        int schemaVersion,
        UUID eventId,
        UUID traceId,
        UUID taskId,
        UUID tripId,
        UUID runId,
        OffsetDateTime occurredAt,
        Payload payload
) {
    public record Payload(
            String status,
            String errorCode,
            String message,
            List<Conflict> conflicts,
            List<Relaxation> relaxationSuggestions,
            String errorCategory,
            String provider,
            String operation,
            boolean retryable,
            int retryCount,
            boolean fallbackAttempted,
            boolean fallbackSucceeded,
            String safeMessage,
            String safeProviderCode,
            String causeType
    ) {
        public Payload(
                String status,
                String errorCode,
                String message,
                List<Conflict> conflicts,
                List<Relaxation> relaxationSuggestions
        ) {
            this(
                    status, errorCode, message, conflicts, relaxationSuggestions,
                    null, null, null, false, 0, false, false,
                    null, null, null
            );
        }

        public Payload {
            conflicts = conflicts == null ? List.of() : List.copyOf(conflicts);
            relaxationSuggestions = relaxationSuggestions == null
                    ? List.of() : List.copyOf(relaxationSuggestions);
        }

        public String displayMessage() {
            return safeMessage == null ? message : safeMessage;
        }
    }

    public record Conflict(String code, String message, List<String> affected) {
        public Conflict {
            affected = affected == null ? List.of() : List.copyOf(affected);
        }
    }

    public record Relaxation(String code, String message) {
    }
}
