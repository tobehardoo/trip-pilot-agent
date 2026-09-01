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
 * Dispatches on the report's validatorVersion:
 *
 * - v4/v5 (hard-validator-v4/hard-validator-v5): refs must be typed strings
 *   (activity:/transit:/poi:/text:) per {@code FeasibilityEntityReferenceCodec}.
 *   activity/transit refs are remapped strictly (missing or ambiguous mapping
 *   fails closed); poi:/text: pass through unchanged even when their value
 *   looks like a temporary UUID (F5).
 * - v3 and older: the legacy heuristic maps any UUID-looking ref that matches
 *   a temporary activity/transit id, and leaves POI/plain text untouched.
 * - any other validatorVersion fails closed: a report that cannot prove it
 *   is legacy must not silently accept untyped refs.
 */
public final class FeasibilityEntityRefMapper {

    private final ObjectMapper objectMapper = new ObjectMapper();

    public String remap(String reportJson,
                        Map<UUID, UUID> activityRefs,
                        Map<UUID, UUID> transitRefs) {
        try {
            ObjectNode report = (ObjectNode) objectMapper.readTree(reportJson);
            String validatorVersion = report.path("validatorVersion").asText(null);
            if (validatorVersion == null || validatorVersion.isBlank()) {
                throw new IllegalStateException(
                        "feasibility report is missing validatorVersion");
            }
            if (isTyped(validatorVersion)) {
                remapArrayV4(report.path("ruleResults"), activityRefs, transitRefs,
                        "affectedEntityRefs");
                remapArrayV4(report.path("repairAttempts"), activityRefs, transitRefs,
                        "affectedEntityRefs");
            } else if (isLegacy(validatorVersion)) {
                remapArrayLegacy(report.path("ruleResults"), activityRefs, transitRefs,
                        "affectedEntityRefs");
                remapArrayLegacy(report.path("repairAttempts"), activityRefs, transitRefs,
                        "affectedEntityRefs");
            } else {
                throw new IllegalStateException(
                        "unknown feasibility validatorVersion: " + validatorVersion);
            }
            return objectMapper.writeValueAsString(report);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Could not remap feasibility entity references",
                    exception);
        }
    }

    private boolean isLegacy(String validatorVersion) {
        return "hard-validator-v1".equals(validatorVersion)
                || "hard-validator-v2".equals(validatorVersion)
                || "hard-validator-v3".equals(validatorVersion);
    }

    private boolean isTyped(String validatorVersion) {
        return "hard-validator-v4".equals(validatorVersion)
                || "hard-validator-v5".equals(validatorVersion);
    }

    private void remapArrayLegacy(JsonNode containers,
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
                String remapped = remapOneLegacy(ref.asText(), activityRefs, transitRefs);
                if (remapped != null) {
                    ((ArrayNode) refs).set(index, objectMapper.getNodeFactory()
                            .textNode(remapped));
                }
            }
        }
    }

    private void remapArrayV4(JsonNode containers,
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
                String remapped = remapOneV4(ref.asText(), activityRefs, transitRefs);
                if (remapped != null) {
                    ((ArrayNode) refs).set(index, objectMapper.getNodeFactory()
                            .textNode(remapped));
                }
            }
        }
    }

    private String remapOneLegacy(String reference,
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

    private String remapOneV4(String reference,
                              Map<UUID, UUID> activityRefs,
                              Map<UUID, UUID> transitRefs) {
        io.github.tobehardoo.trippilot.feasibility.FeasibilityEntityReferenceCodec.ParsedRef parsed;
        try {
            parsed = io.github.tobehardoo.trippilot.feasibility.FeasibilityEntityReferenceCodec
                    .parse(reference);
        } catch (IllegalArgumentException exception) {
            throw new IllegalStateException(
                    "typed entity reference is invalid: " + reference, exception);
        }
        switch (parsed.kind()) {
            case POI, TEXT -> {
                return null;
            }
            case ACTIVITY -> {
                UUID target = activityRefs.get(UUID.fromString(parsed.value()));
                if (target == null) {
                    throw new IllegalStateException(
                            "v4 activity reference has no persisted mapping: " + reference);
                }
                return io.github.tobehardoo.trippilot.feasibility.FeasibilityEntityReferenceCodec
                        .encodeActivityRef(target);
            }
            case TRANSIT -> {
                UUID target = transitRefs.get(UUID.fromString(parsed.value()));
                if (target == null) {
                    throw new IllegalStateException(
                            "v4 transit reference has no persisted mapping: " + reference);
                }
                return io.github.tobehardoo.trippilot.feasibility.FeasibilityEntityReferenceCodec
                        .encodeTransitRef(target);
            }
            default -> throw new IllegalStateException(
                    "v4 entity reference has unknown kind: " + reference);
        }
    }
}
