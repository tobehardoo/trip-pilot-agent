package io.github.tobehardoo.trippilot.planning;

import java.util.UUID;

/**
 * Supplies the trip's current itinerary version id for the replan baseline
 * check.  Kept behind an interface so review/completion services share the
 * same stale-baseline semantics without coupling the unit tests to the full
 * ItineraryService graph.
 */
@FunctionalInterface
public interface ItineraryCurrentVersionProvider {

    UUID currentVersionId(UUID tripId);
}
