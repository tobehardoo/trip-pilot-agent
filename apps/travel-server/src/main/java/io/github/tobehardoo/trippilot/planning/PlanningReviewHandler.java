package io.github.tobehardoo.trippilot.planning;

import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningReviewRequiredEvent;

/**
 * Handles a validated PLANNING_REVIEW_REQUIRED event.
 *
 * Implementations transition the referenced planning task into the
 * WAITING_USER state without creating an itinerary version or touching the
 * trip's current version.
 */
@FunctionalInterface
public interface PlanningReviewHandler {

    void handle(PlanningReviewRequiredEvent event);
}
