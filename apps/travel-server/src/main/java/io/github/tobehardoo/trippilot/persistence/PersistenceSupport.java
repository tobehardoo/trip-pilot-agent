package io.github.tobehardoo.trippilot.persistence;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Shared persistence primitives for services that write JSON columns and
 * assert single-row writes.
 *
 * Historically every service that stored a JSON payload carried its own
 * private {@code writeJson}/{@code requireOne} pair.  Both helpers are
 * behaviour-identical across callers; the write subject is parameterised so
 * the failure message stays specific to each caller.
 */
public final class PersistenceSupport {

    private PersistenceSupport() {
    }

    public static void requireOne(int rows, String operation) {
        if (rows != 1) {
            throw new IllegalStateException("Could not persist " + operation);
        }
    }

    public static String writeJson(ObjectMapper objectMapper, Object value, String subject) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Could not serialize " + subject, exception);
        }
    }
}
