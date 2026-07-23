package io.github.tobehardoo.trippilot.messaging;

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
            List<Relaxation> relaxationSuggestions
    ) {
        public Payload {
            conflicts = conflicts == null ? List.of() : List.copyOf(conflicts);
            relaxationSuggestions = relaxationSuggestions == null
                    ? List.of() : List.copyOf(relaxationSuggestions);
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
