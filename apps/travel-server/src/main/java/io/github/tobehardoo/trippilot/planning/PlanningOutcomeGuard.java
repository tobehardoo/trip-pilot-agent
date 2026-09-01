package io.github.tobehardoo.trippilot.planning;

import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.UUID;

import io.github.tobehardoo.trippilot.common.EventRejectedException;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningCompletedEvent;

/**
 * Guards shared by the completion and review outcome paths.
 *
 * Identity (tripId/traceId), candidate date coverage and trip/replan baseline
 * checks are identical for PLANNING_COMPLETED and PLANNING_REVIEW_REQUIRED, so
 * they live here instead of drifting apart in two services.
 */
public final class PlanningOutcomeGuard {

    private static final ZoneOffset TRIP_ZONE = ZoneOffset.ofHours(8);

    public void validateIdentity(UUID tripId, UUID traceId,
                                 PlanningTaskCompletionRecord task,
                                 String eventLabel) {
        if (!tripId.equals(task.tripId()) || !traceId.equals(task.traceId())) {
            throw new EventRejectedException(
                    eventLabel + " does not match its planning task");
        }
    }

    public void validateDates(List<PlanningCompletedEvent.Day> days,
                              PlanningTaskCompletionRecord task) {
        long expectedDayCount = ChronoUnit.DAYS.between(task.tripStartDate(), task.tripEndDate()) + 1;
        if (days.size() != expectedDayCount) {
            throw new EventRejectedException(
                    "Outcome itinerary must contain every trip date exactly once");
        }
        for (int dayIndex = 0; dayIndex < days.size(); dayIndex++) {
            PlanningCompletedEvent.Day day = days.get(dayIndex);
            LocalDate expectedDate = task.tripStartDate().plusDays(dayIndex);
            if (!expectedDate.equals(day.date())) {
                throw new EventRejectedException(
                        "Outcome itinerary dates must be ordered within the trip range");
            }
            for (PlanningCompletedEvent.Activity activity : day.activities()) {
                if (!day.date().equals(activity.startTime()
                        .withOffsetSameInstant(TRIP_ZONE).toLocalDate())
                        || !day.date().equals(activity.endTime()
                        .withOffsetSameInstant(TRIP_ZONE).toLocalDate())) {
                    throw new EventRejectedException(
                            "Activities must remain within their itinerary day");
                }
            }
        }
    }

    public boolean isStaleTripBaseline(PlanningTaskCompletionRecord task) {
        return task.baselineTripVersion() != task.currentTripVersion();
    }

    /**
     * Fail-closed replan baseline check: a REPLAN task must prove its baseline
     * itinerary version is still current.  A null baseline or null current
     * version is an inconsistent task state and must be treated as stale
     * rather than being silently routed against whatever happens to be
     * current.
     */
    public boolean isStaleReplanBaseline(PlanningTaskCompletionRecord task,
                                         UUID currentVersionId) {
        return task.baselineItineraryVersionId() == null
                || currentVersionId == null
                || !task.baselineItineraryVersionId().equals(currentVersionId);
    }
}
