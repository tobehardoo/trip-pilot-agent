package io.github.tobehardoo.trippilot.itinerary;

import java.util.Map;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * Remaps temporary activity/transit UUIDs inside a persisted feasibility
 * report to the persisted node ids.
 *
 * RuleResult.affectedEntityRefs and RepairAttempt.affectedEntityRefs may
 * reference the wire itinerary's temporary activity/transit ids.  After the
 * itinerary version is persisted these must point at the real rows so API
 * consumers can locate the affected nodes.  Provider POI ids, hotel POI ids
 * and plain text references are never UUID-mapped and pass through unchanged.
 * A UUID that matches both maps is ambiguous and fails closed instead of
 * guessing.
 */
public final class FeasibilityEntityRefMapper {

    private final ObjectMapper objectMapper = new ObjectMapper();

    public String remap(String reportJson,
                        Map<UUID, UUID> activityRefs,
                        Map<UUID, UUID> transitRefs) {
        try {
            ObjectNode report = (ObjectNode) objectMapper.readTree(reportJson);
            remapArray(report.path("ruleResults"), activityRefs, transitRefs, "affectedEntityRefs");
            remapArray(report.path("repairAttempts"), activityRefs, transitRefs, "affectedEntityRefs");
            return objectMapper.writeValueAsString(report);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Could not remap feasibility entity references",
                    exception);
        }
    }

    private void remapArray(JsonNode containers,
                            Map<UUID, UUID> activityRefs,
                            Map<UUID, UUID> transitRefs,
                            String field) {
        if (!containers.isArray()) {
            return;
        }
        for (JsonNode container : containers) {
            if (!container.isObject()) {
                continue;
            }
            JsonNode refs = container.path(field);
            if (!refs.isArray()) {
                continue;
            }
            for (int index = 0; index < refs.size(); index++) {
                JsonNode ref = refs.get(index);
                if (!ref.isTextual()) {
                    continue;
                }
                String remapped = remapOne(ref.asText(), activityRefs, transitRefs);
                if (remapped != null) {
                    ((ArrayNode) refs).set(index, objectMapper.getNodeFactory()
                            .textNode(remapped));
                }
            }
        }
    }

    private String remapOne(String reference,
                            Map<UUID, UUID> activityRefs,
                            Map<UUID, UUID> transitRefs) {
        UUID uuid;
        try {
            uuid = UUID.fromString(reference);
        } catch (IllegalArgumentException exception) {
            return null;
        }
        UUID activityTarget = activityRefs.get(uuid);
        UUID transitTarget = transitRefs.get(uuid);
        if (activityTarget != null && transitTarget != null) {
            throw new IllegalStateException(
                    "Entity reference " + reference + " is ambiguous across activity and transit");
        }
        if (activityTarget != null) {
            return activityTarget.toString();
        }
        if (transitTarget != null) {
            return transitTarget.toString();
        }
        return null;
    }
}
