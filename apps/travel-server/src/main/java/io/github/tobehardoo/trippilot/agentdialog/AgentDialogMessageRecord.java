package io.github.tobehardoo.trippilot.agentdialog;

import java.time.Instant;
import java.util.UUID;

public record AgentDialogMessageRecord(
        Long id,
        UUID eventId,
        UUID tripId,
        UUID runId,
        String eventType,
        int schemaVersion,
        String payloadJson,
        Instant createdAt
) {
}
