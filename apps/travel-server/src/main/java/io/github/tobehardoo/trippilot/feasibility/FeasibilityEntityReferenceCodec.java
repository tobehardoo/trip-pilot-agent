package io.github.tobehardoo.trippilot.feasibility;

import java.util.UUID;

/**
 * Typed entity references for feasibility reports (hard-validator-v4+),
 * grammar-identical to the Python {@code trip_agent.feasibility.entity_refs}
 * module.
 *
 * <pre>
 * activity:&lt;canonical-lowercase-uuid&gt;
 * transit:&lt;canonical-lowercase-uuid&gt;
 * poi:&lt;nonblank-opaque-value&gt;    (value may contain further colons)
 * text:&lt;nonblank-opaque-value&gt;
 * </pre>
 *
 * Unknown kinds, empty values, bare UUIDs and unprefixed strings fail
 * closed.  The whole reference is bounded to 200 chars and must not contain
 * control characters.
 */
public final class FeasibilityEntityReferenceCodec {

    public static final int MAX_ENTITY_REF_LENGTH = 200;

    public enum Kind {
        ACTIVITY("activity"),
        TRANSIT("transit"),
        POI("poi"),
        TEXT("text");

        private final String prefix;

        Kind(String prefix) {
            this.prefix = prefix;
        }

        public String prefix() {
            return prefix;
        }

        static Kind fromPrefix(String prefix) {
            for (Kind kind : values()) {
                if (kind.prefix.equals(prefix)) {
                    return kind;
                }
            }
            throw new IllegalArgumentException("unknown entity reference kind: " + prefix);
        }
    }

    public record ParsedRef(Kind kind, String value) {
    }

    private FeasibilityEntityReferenceCodec() {
    }

    public static String encodeActivityRef(UUID activityId) {
        return Kind.ACTIVITY.prefix + ":" + canonicalUuid(activityId);
    }

    public static String encodeTransitRef(UUID transitId) {
        return Kind.TRANSIT.prefix + ":" + canonicalUuid(transitId);
    }

    public static String encodePoiRef(String poiId) {
        return Kind.POI.prefix + ":" + poiId;
    }

    public static String encodeTextRef(String value) {
        return Kind.TEXT.prefix + ":" + value;
    }

    private static String canonicalUuid(UUID id) {
        return id.toString().toLowerCase(java.util.Locale.ROOT);
    }

    public static ParsedRef parse(String ref) {
        if (ref == null || ref.isEmpty()) {
            throw new IllegalArgumentException("entity reference must be a non-empty string");
        }
        if (ref.length() > MAX_ENTITY_REF_LENGTH) {
            throw new IllegalArgumentException("entity reference exceeds 200 characters");
        }
        if (containsControlCharacter(ref)) {
            throw new IllegalArgumentException(
                    "entity reference must not contain control characters");
        }
        int colon = ref.indexOf(':');
        if (colon <= 0 || colon == ref.length() - 1) {
            throw new IllegalArgumentException("entity reference must be kind:value");
        }
        String kindText = ref.substring(0, colon);
        String value = ref.substring(colon + 1);
        Kind kind = Kind.fromPrefix(kindText);
        if (kind == Kind.ACTIVITY || kind == Kind.TRANSIT) {
            UUID parsed;
            try {
                parsed = UUID.fromString(value);
            } catch (IllegalArgumentException exception) {
                throw new IllegalArgumentException(
                        kind.prefix + " reference must be a UUID", exception);
            }
            if (!parsed.toString().equals(value)) {
                throw new IllegalArgumentException(
                        kind.prefix + " reference must be canonical lowercase UUID");
            }
        }
        return new ParsedRef(kind, value);
    }

    public static boolean validate(String ref) {
        try {
            parse(ref);
            return true;
        } catch (IllegalArgumentException exception) {
            return false;
        }
    }

    private static boolean containsControlCharacter(String value) {
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (c < 0x20 || c == 0x7f) {
                return true;
            }
        }
        return false;
    }
}
