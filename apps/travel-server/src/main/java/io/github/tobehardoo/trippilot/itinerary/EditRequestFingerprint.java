package io.github.tobehardoo.trippilot.itinerary;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.List;
import org.springframework.stereotype.Component;

/** Creates a stable SHA-256 fingerprint from edit fields that affect business behavior. */
@Component
final class EditRequestFingerprint {

    private static final List<String> EDIT_FIELDS = List.of(
            "baseVersionId", "operation", "activityId", "transitLegId", "targetDate",
            "targetOrder", "targetStartTime", "targetEndTime", "transitMode", "transitLocked"
    );

    private final ObjectMapper objectMapper;

    EditRequestFingerprint(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    String forEdit(JsonNode request) {
        ObjectNode canonical = objectMapper.createObjectNode();
        canonical.put("requestType", "ITINERARY_EDIT");
        canonical.set("edit", canonicalEdit(request));
        return sha256(canonical);
    }

    String forBatch(JsonNode request) {
        ObjectNode canonical = objectMapper.createObjectNode();
        canonical.put("requestType", "ITINERARY_BATCH_EDIT");
        canonical.set("baseVersionId", fieldState(request, "baseVersionId"));
        canonical.set("edits", batchEdits(request));
        return sha256(canonical);
    }

    private ObjectNode canonicalEdit(JsonNode request) {
        ObjectNode canonical = objectMapper.createObjectNode();
        for (String field : EDIT_FIELDS) {
            canonical.set(field, fieldState(request, field));
        }
        return canonical;
    }

    private ObjectNode batchEdits(JsonNode request) {
        ObjectNode canonical = objectMapper.createObjectNode();
        if (request == null || !request.has("edits")) {
            canonical.put("state", "ABSENT");
            return canonical;
        }
        if (request.get("edits").isNull()) {
            canonical.put("state", "NULL");
            return canonical;
        }
        canonical.put("state", "VALUE");
        if (!request.get("edits").isArray()) {
            canonical.set("value", request.get("edits"));
            return canonical;
        }
        ArrayNode edits = canonical.putArray("value");
        for (JsonNode edit : request.get("edits")) {
            edits.add(canonicalEdit(edit));
        }
        return canonical;
    }

    private ObjectNode fieldState(JsonNode request, String field) {
        ObjectNode canonical = objectMapper.createObjectNode();
        if (request == null || !request.has(field)) {
            canonical.put("state", "ABSENT");
        } else if (request.get(field).isNull()) {
            canonical.put("state", "NULL");
        } else {
            canonical.put("state", "VALUE");
            canonical.set("value", request.get(field));
        }
        return canonical;
    }

    private String sha256(JsonNode canonical) {
        try {
            byte[] bytes = objectMapper.writeValueAsBytes(canonical);
            return java.util.HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256").digest(bytes)
            );
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Unable to canonicalize itinerary edit request", exception);
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }
}
