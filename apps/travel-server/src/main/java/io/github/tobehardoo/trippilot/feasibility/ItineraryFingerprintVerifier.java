package io.github.tobehardoo.trippilot.feasibility;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.List;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * Cross-language itinerary fingerprint verification.
 *
 * The algorithm must match the Python producer exactly:
 * {@code itinerary.model_dump(mode="json", by_alias=True, exclude_none=False)}
 * with recursively sorted keys, compact separators, UTF-8 and SHA-256 lower
 * hex.  The producer serialises v9 completion and review-required outcomes
 * with explicit nulls (exclude_none=False), so the wire tree is complete:
 * this verifier hashes the raw itinerary JsonNode as received and never
 * restores or invents missing fields.
 */
public final class ItineraryFingerprintVerifier {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private ItineraryFingerprintVerifier() {
    }

    public static String compute(JsonNode itinerary) {
        JsonNode canonical = canonicalise(itinerary);
        byte[] bytes = canonical.toString().getBytes(StandardCharsets.UTF_8);
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(bytes));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 unavailable", exception);
        }
    }

    public static boolean matches(JsonNode itinerary, String expectedFingerprint) {
        if (expectedFingerprint == null || !expectedFingerprint.matches("^[0-9a-f]{64}$")) {
            return false;
        }
        return compute(itinerary).equals(expectedFingerprint);
    }

    private static JsonNode canonicalise(JsonNode node) {
        if (node.isObject()) {
            ObjectNode result = MAPPER.createObjectNode();
            List<String> names = new ArrayList<>();
            node.fieldNames().forEachRemaining(names::add);
            names.sort(Comparator.naturalOrder());
            for (String name : names) {
                result.set(name, canonicalise(node.get(name)));
            }
            return result;
        }
        if (node.isArray()) {
            ArrayNode result = MAPPER.createArrayNode();
            for (JsonNode item : node) {
                result.add(canonicalise(item));
            }
            return result;
        }
        return node;
    }
}
