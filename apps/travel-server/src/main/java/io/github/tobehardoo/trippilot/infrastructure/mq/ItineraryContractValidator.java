package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.math.BigDecimal;
import java.net.URI;
import java.util.Set;

/**
 * Shared contract primitives for the planning event parsers.
 *
 * Both {@link PlanningCompletedEventParser} and {@link PlanningReviewRequiredEventParser}
 * historically carried private copies of these predicates.  The two money
 * copies had diverged: the review parser let negative amounts through while
 * the completion parser rejected them.  The completion semantics are the
 * canonical contract (money persisted to NUMERIC(12,2) must be non-negative),
 * so the shared validator keeps that behaviour.
 */
final class ItineraryContractValidator {

    static final BigDecimal MAX_PERSISTED_MONEY = new BigDecimal("9999999999.99");

    static final Set<String> DAY_TYPES = Set.of(
            "ARRIVAL_DAY", "FULL_DAY", "DEPARTURE_DAY", "SPECIAL_ACTIVITY_DAY"
    );

    static final Set<String> ACTIVITY_KINDS = Set.of(
            "ATTRACTION", "EXPERIENCE", "MEAL", "ACCOMMODATION", "ARRIVAL", "DEPARTURE"
    );

    private ItineraryContractValidator() {
    }

    static boolean isPersistableMoney(BigDecimal value) {
        return value != null
                && value.signum() >= 0
                && value.compareTo(MAX_PERSISTED_MONEY) <= 0
                && value.stripTrailingZeros().scale() <= 2;
    }

    static boolean validText(String value, int maxLength) {
        return value != null && !value.isBlank() && value.length() <= maxLength;
    }

    static boolean validHttpUrl(String value) {
        if (!validText(value, 2_048)) {
            return false;
        }
        try {
            URI uri = URI.create(value);
            return ("https".equalsIgnoreCase(uri.getScheme())
                    || "http".equalsIgnoreCase(uri.getScheme()))
                    && uri.getHost() != null;
        } catch (IllegalArgumentException exception) {
            return false;
        }
    }

    static boolean supportedProvider(String provider) {
        return "DEMO".equals(provider) || "AMAP".equals(provider);
    }
}
