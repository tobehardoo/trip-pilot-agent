package io.github.tobehardoo.trippilot.planning;

import io.github.tobehardoo.trippilot.common.EventRejectedException;

/**
 * Shared planning-domain support for the four planning event services.
 *
 * {@link PersistenceSupport} owns the generic JSON-write and single-row
 * assertion primitives; this class only carries the planning-specific event
 * rejection exception factory.
 */
final class PlanningEventSupport {

    private PlanningEventSupport() {
    }

    static EventRejectedException rejected(String message) {
        return new EventRejectedException(message);
    }
}
