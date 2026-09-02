package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.time.OffsetDateTime;
import java.util.UUID;

import com.fasterxml.jackson.databind.JsonNode;

public record AgentCompletedEvent(
        String eventType,
        int schemaVersion,
        UUID eventId,
        UUID traceId,
        UUID tripId,
        UUID runId,
        OffsetDateTime occurredAt,
        Payload payload
) {
    // AUDIT-01（归边 A）：Agent 对话框链不再携带完整 itinerary ——
    // 权威行程由 Planner 管线生成并通过 PLANNING_COMPLETED 落库。
    public record Payload(String summary, JsonNode slots) {
    }
}
