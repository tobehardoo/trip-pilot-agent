package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.io.IOException;
import java.math.BigDecimal;
import java.net.URI;
import java.util.HashSet;
import java.util.Set;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectReader;
import io.github.tobehardoo.trippilot.feasibility.ItineraryFingerprintVerifier;
import org.springframework.stereotype.Component;

/**
 * Parses and validates PLANNING_REVIEW_REQUIRED events (schema v1).
 *
 * Review events share the v9 itinerary/knowledge/provenance structure but
 * never carry an evaluation, their payload status must be WAITING_USER and
 * the feasibility report must be UNVERIFIED or NEEDS_REPAIR.  The itinerary
 * fingerprint must match the report, same as v9 completions.
 */
@Component
public class PlanningReviewRequiredEventParser {

    private static final Set<String> DAY_TYPES = Set.of(
            "ARRIVAL_DAY", "FULL_DAY", "DEPARTURE_DAY", "SPECIAL_ACTIVITY_DAY"
    );
    private static final Set<String> ACTIVITY_KINDS = Set.of(
            "ATTRACTION", "EXPERIENCE", "MEAL", "ACCOMMODATION", "ARRIVAL", "DEPARTURE"
    );
    private static final BigDecimal MAX_PERSISTED_MONEY = new BigDecimal("9999999999.99");

    private final ObjectReader reader;
    private final ObjectMapper objectMapper;

    public PlanningReviewRequiredEventParser(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
        this.reader = objectMapper.readerFor(PlanningReviewRequiredEvent.class)
                .with(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);
    }

    public PlanningReviewRequiredEvent parse(byte[] body) {
        try {
            JsonNode tree = objectMapper.readTree(body);
            if (tree == null) {
                throw invalid("event body must contain a JSON object");
            }
            validateJsonTypes(tree);
            PlanningReviewRequiredEvent event =
                    reader.readValue(tree.traverse(objectMapper));
            validate(event);
            return withValidatedItinerary(event, tree.at("/payload/itinerary"));
        } catch (IOException exception) {
            throw new PlanningEventContractException(
                    "Invalid PLANNING_REVIEW_REQUIRED event", exception);
        }
    }

    /**
     * Rebuilds the parsed event with the validated raw itinerary snapshot.
     *
     * The snapshot is a defensive deep copy of the wire itinerary tree that
     * already passed schema, type, semantic and fingerprint validation.  The
     * review service persists this exact tree as candidateItinerary so the
     * Task API read model can re-verify the report fingerprint against a
     * byte-identical candidate (no typed-DTO re-serialisation drift).  The
     * field is {@code @JsonIgnore} internal metadata and never appears on
     * the wire.
     */
    private PlanningReviewRequiredEvent withValidatedItinerary(
            PlanningReviewRequiredEvent event, JsonNode wireItinerary
    ) {
        PlanningReviewRequiredEvent.Payload payload = event.payload();
        return new PlanningReviewRequiredEvent(
                event.eventType(), event.schemaVersion(), event.eventId(), event.traceId(),
                event.taskId(), event.tripId(), event.runId(), event.occurredAt(),
                new PlanningReviewRequiredEvent.Payload(
                        payload.status(), payload.provider(), payload.itinerary(),
                        payload.knowledge(), payload.factImpacts(),
                        payload.providerProvenance(), payload.feasibilityReport(),
                        wireItinerary.deepCopy()
                )
        );
    }

    private void validateJsonTypes(JsonNode event) {
        if (!event.isObject() || !event.path("eventType").isTextual()
                || !event.path("schemaVersion").isIntegralNumber()
                || !event.path("occurredAt").isTextual()) {
            throw invalid("event field types do not match the JSON Schema");
        }
        for (String idField : new String[]{"eventId", "traceId", "taskId", "tripId", "runId"}) {
            if (!event.path(idField).isTextual()) {
                throw invalid("event field types do not match the JSON Schema");
            }
        }
        int schemaVersion = event.path("schemaVersion").asInt();
        if (schemaVersion != 1) {
            throw invalid("unsupported eventType or schemaVersion");
        }
        JsonNode payload = event.path("payload");
        JsonNode itinerary = payload.path("itinerary");
        JsonNode days = itinerary.path("days");
        if (!payload.isObject() || !payload.path("status").isTextual()
                || !payload.path("provider").isTextual()
                || !itinerary.isObject() || !itinerary.path("title").isTextual()
                || !itinerary.path("estimatedTotalCost").isNumber() || !days.isArray()) {
            throw invalid("payload field types do not match the JSON Schema");
        }
        if (payload.has("evaluation") && !payload.get("evaluation").isNull()) {
            throw invalid("evaluation is not allowed in schema review v1");
        }
        validateKnowledgeTypes(payload);
        validateFactImpactTypes(payload);
        validateFeasibilityReportTypes(payload, itinerary);
        for (JsonNode day : days) {
            JsonNode activities = day.path("activities");
            if (!day.isObject() || !day.path("date").isTextual() || !activities.isArray()) {
                throw invalid("day field types do not match the JSON Schema");
            }
            if (day.has("dayType") && !day.path("dayType").isNull()
                    && !day.path("dayType").isTextual()) {
                throw invalid("dayType must be a string");
            }
            for (JsonNode activity : activities) {
                if (!activity.isObject() || !activity.path("title").isTextual()
                        || !activity.path("startTime").isTextual()
                        || !activity.path("endTime").isTextual()
                        || !activity.path("estimatedCost").isNumber()
                        || !activity.path("source").isTextual()) {
                    throw invalid("activity field types do not match the JSON Schema");
                }
                if (activity.has("kind") && !activity.path("kind").isNull()
                        && !activity.path("kind").isTextual()) {
                    throw invalid("activity kind must be a string");
                }
                if (activity.has("timeFixed") && !activity.path("timeFixed").isNull()
                        && !activity.path("timeFixed").isBoolean()) {
                    throw invalid("activity timeFixed must be a boolean");
                }
                validateActivityMetadataTypes(activity);
                if (activity.has("activityId") && !activity.path("activityId").isTextual()) {
                    throw invalid("activityId must be a UUID string");
                }
            }
            validateTransitLegTypes(day);
        }
    }

    private void validateKnowledgeTypes(JsonNode payload) {
        JsonNode knowledge = payload.path("knowledge");
        if (knowledge.isNull() || knowledge.isMissingNode()) {
            return;
        }
        JsonNode citations = knowledge.path("citations");
        JsonNode freshness = knowledge.path("freshness");
        if (!knowledge.isObject() || !knowledge.path("status").isTextual()
                || !knowledge.path("query").isTextual() || !citations.isArray()
                || !freshness.isObject() || !freshness.path("status").isTextual()) {
            throw invalid("knowledge evidence field types do not match the JSON Schema");
        }
        if (knowledge.has("message") && !knowledge.path("message").isNull()
                && !knowledge.path("message").isTextual()) {
            throw invalid("knowledge message must be text");
        }
        if (freshness.has("checkedAt") && !freshness.path("checkedAt").isNull()
                && !freshness.path("checkedAt").isTextual()) {
            throw invalid("knowledge checkedAt must be text");
        }
        if (freshness.has("staleReason") && !freshness.path("staleReason").isNull()
                && !freshness.path("staleReason").isTextual()) {
            throw invalid("knowledge staleReason must be text");
        }
        for (JsonNode citation : citations) {
            if (!citation.isObject() || !citation.path("documentId").isTextual()
                    || !citation.path("documentVersion").isIntegralNumber()
                    || !citation.path("chunkId").isTextual()
                    || !citation.path("chunkIndex").isIntegralNumber()
                    || !citation.path("title").isTextual()
                    || !citation.path("sourceUrl").isTextual()
                    || !citation.path("sourceName").isTextual()
                    || !citation.path("collectedAt").isTextual()
                    || !citation.path("reliabilityLevel").isTextual()
                    || !citation.path("similarity").isNumber()) {
                throw invalid("knowledge citation field types do not match the JSON Schema");
            }
        }
    }

    private void validateFactImpactTypes(JsonNode payload) {
        JsonNode impacts = payload.path("factImpacts");
        if (impacts.isMissingNode()) {
            return;
        }
        if (!impacts.isArray()) {
            throw invalid("factImpacts must be an array");
        }
    }

    private void validateActivityMetadataTypes(JsonNode activity) {
        if (activity.has("providerPoiId") && !activity.path("providerPoiId").isNull()
                && !activity.path("providerPoiId").isTextual()) {
            throw invalid("activity metadata types do not match the JSON Schema");
        }
        if (activity.has("address") && !activity.path("address").isNull()
                && !activity.path("address").isTextual()) {
            throw invalid("activity metadata types do not match the JSON Schema");
        }
        if (activity.has("coordinates")) {
            JsonNode coordinates = activity.path("coordinates");
            if (!coordinates.isNull() && (!coordinates.isObject()
                    || !coordinates.path("longitude").isNumber()
                    || !coordinates.path("latitude").isNumber())) {
                throw invalid("activity metadata types do not match the JSON Schema");
            }
        }
    }

    private void validateTransitLegTypes(JsonNode day) {
        JsonNode transitLegs = day.path("transitLegs");
        if (!transitLegs.isArray()) {
            throw invalid("day transitLegs must be an array");
        }
        for (JsonNode leg : transitLegs) {
            if (!leg.isObject()
                    || !leg.path("fromActivityIndex").isIntegralNumber()
                    || !leg.path("toActivityIndex").isIntegralNumber()
                    || !leg.path("mode").isTextual()
                    || !leg.path("distanceMeters").isIntegralNumber()
                    || !leg.path("durationSeconds").isIntegralNumber()
                    || !leg.path("provider").isTextual()
                    || !leg.path("estimated").isBoolean()
                    || !leg.path("polyline").isArray()) {
                throw invalid("transit leg field types do not match the JSON Schema");
            }
            if (leg.has("transitId") && !leg.path("transitId").isNull()
                    && !leg.path("transitId").isTextual()) {
                throw invalid("transitId must be a UUID string");
            }
        }
    }

    private void validateFeasibilityReportTypes(JsonNode payload, JsonNode itinerary) {
        JsonNode report = payload.path("feasibilityReport");
        if (!report.isObject()
                || !report.path("schemaVersion").isInt()
                || !report.path("reportId").isTextual()
                || !report.path("validatorVersion").isTextual()
                || !report.path("itineraryFingerprint").isTextual()
                || !report.path("status").isTextual()
                || !report.path("validatedAt").isTextual()
                || !report.path("requiredRuleIds").isArray()
                || !report.path("missingRequiredRuleIds").isArray()
                || !report.path("summary").isObject()
                || !report.path("ruleResults").isArray()
                || !report.path("repairAttempts").isArray()) {
            throw invalid("feasibilityReport field types do not match the JSON Schema");
        }
        if (!report.path("itineraryFingerprint").asText().matches("^[0-9a-f]{64}$")) {
            throw invalid("feasibilityReport itineraryFingerprint must be a 64-char lowercase hex");
        }
        if (!ItineraryFingerprintVerifier.matches(
                itinerary, report.path("itineraryFingerprint").asText())) {
            throw invalid("feasibilityReport itineraryFingerprint does not match the itinerary");
        }
    }

    private void validate(PlanningReviewRequiredEvent event) {
        if (!"PLANNING_REVIEW_REQUIRED".equals(event.eventType())
                || event.schemaVersion() != 1) {
            throw invalid("unsupported eventType or schemaVersion");
        }
        if (event.eventId() == null || event.traceId() == null || event.taskId() == null
                || event.tripId() == null || event.runId() == null
                || event.occurredAt() == null) {
            throw invalid("event envelope fields are required");
        }
        PlanningReviewRequiredEvent.Payload payload = event.payload();
        if (payload == null || payload.itinerary() == null
                || !supportedProvider(payload.provider())) {
            throw invalid("supported payload is required");
        }
        if (!"WAITING_USER".equals(payload.status())) {
            throw invalid("review payload status must be WAITING_USER");
        }
        PlanningCompletedEvent.Itinerary itinerary = payload.itinerary();
        if (!validText(itinerary.title(), 200)) {
            throw invalid("itinerary title must contain 1 to 200 characters");
        }
        if (itinerary.days() == null || itinerary.days().isEmpty()) {
            throw invalid("itinerary days must not be empty");
        }
        if (!isPersistableMoney(itinerary.estimatedTotalCost())) {
            throw invalid("estimatedTotalCost must fit NUMERIC(12,2)");
        }
        for (PlanningCompletedEvent.Day day : itinerary.days()) {
            validateDay(day, payload.provider());
        }
        validateKnowledge(payload.knowledge());
        validateFeasibilityReport(payload.feasibilityReport());
    }

    private void validateDay(PlanningCompletedEvent.Day day, String provider) {
        if (day == null || day.date() == null || day.activities() == null
                || day.activities().isEmpty()) {
            throw invalid("each itinerary day requires activities");
        }
        if (day.dayType() != null && !DAY_TYPES.contains(day.dayType())) {
            throw invalid("dayType is not a supported value");
        }
        java.time.OffsetDateTime previousEnd = null;
        for (PlanningCompletedEvent.Activity activity : day.activities()) {
            if (activity == null || !validText(activity.title(), 200)
                    || activity.startTime() == null || activity.endTime() == null
                    || !isPersistableMoney(activity.estimatedCost())
                    || !supportedProvider(activity.source())) {
                throw invalid("activity fields are invalid");
            }
            if (activity.kind() != null && !ACTIVITY_KINDS.contains(activity.kind())) {
                throw invalid("activity kind is not a supported value");
            }
            if (!provider.equals(activity.source())) {
                throw invalid("activity source must match payload provider");
            }
            if (!activity.endTime().isAfter(activity.startTime())) {
                throw invalid("activity endTime must be after startTime");
            }
            if (previousEnd != null && activity.startTime().isBefore(previousEnd)) {
                throw invalid("activities must be ordered without overlap");
            }
            previousEnd = activity.endTime();
        }
        if (day.transitLegs() != null) {
            if (day.transitLegs().size() > day.activities().size() - 1) {
                throw invalid("transit legs cannot exceed adjacent activity pairs");
            }
            Set<String> endpoints = new HashSet<>();
            for (PlanningCompletedEvent.TransitLeg leg : day.transitLegs()) {
                int fromIndex = leg.fromActivityIndex();
                int toIndex = leg.toActivityIndex();
                if (fromIndex < 0 || toIndex != fromIndex + 1
                        || toIndex >= day.activities().size()) {
                    throw invalid("transit legs must connect adjacent activities in order");
                }
                if (!endpoints.add(fromIndex + ":" + toIndex)) {
                    throw invalid("transit legs must use unique adjacent activity endpoints");
                }
                boolean sourceMatchesEstimate = ("AMAP".equals(leg.provider()) && !leg.estimated())
                        || ("DEMO".equals(leg.provider()) && leg.estimated());
                if (!("WALKING".equals(leg.mode()) || "DRIVING".equals(leg.mode()))
                        || !sourceMatchesEstimate
                        || leg.distanceMeters() < 0 || leg.durationSeconds() < 0) {
                    throw invalid("transit leg fields are invalid");
                }
                PlanningCompletedEvent.Activity origin = day.activities().get(fromIndex);
                PlanningCompletedEvent.Activity destination = day.activities().get(toIndex);
                if (origin.endTime().plusSeconds(leg.durationSeconds())
                        .isAfter(destination.startTime())) {
                    throw invalid("transit leg travel time must fit between activities");
                }
            }
        }
    }

    private void validateKnowledge(PlanningCompletedEvent.KnowledgeEvidence knowledge) {
        if (knowledge == null) {
            return;
        }
        if (!validText(knowledge.query(), 200)
                || knowledge.freshness() == null || knowledge.citations().size() > 20) {
            throw invalid("knowledge evidence is invalid");
        }
        boolean real = "REAL".equals(knowledge.status());
        if (real) {
            if (knowledge.citations().isEmpty() || knowledge.message() != null
                    || "UNAVAILABLE".equals(knowledge.freshness().status())) {
                throw invalid("real knowledge evidence requires citations and freshness");
            }
        } else if (!("DEMO".equals(knowledge.status())
                || "UNAVAILABLE".equals(knowledge.status()))
                || !knowledge.citations().isEmpty()
                || !validText(knowledge.message(), 300)
                || !"UNAVAILABLE".equals(knowledge.freshness().status())) {
            throw invalid("non-real knowledge evidence must be explicitly unavailable");
        }
        boolean unavailable = "UNAVAILABLE".equals(knowledge.freshness().status());
        if (!("FRESH".equals(knowledge.freshness().status())
                || "STALE".equals(knowledge.freshness().status()) || unavailable)
                || (!unavailable && knowledge.freshness().checkedAt() == null)
                || (unavailable && (knowledge.freshness().checkedAt() != null
                || knowledge.freshness().staleReason() != null))
                || ("FRESH".equals(knowledge.freshness().status())
                && knowledge.freshness().staleReason() != null)
                || (knowledge.freshness().staleReason() != null
                && !validText(knowledge.freshness().staleReason(), 60))) {
            throw invalid("knowledge freshness is invalid");
        }
        for (PlanningCompletedEvent.KnowledgeCitation citation : knowledge.citations()) {
            if (citation == null || !validText(citation.documentId(), 200)
                    || citation.documentVersion() < 1
                    || !validText(citation.chunkId(), 200)
                    || citation.chunkIndex() < 0
                    || !validText(citation.title(), 200)
                    || !validHttpUrl(citation.sourceUrl())
                    || !validText(citation.sourceName(), 120)
                    || citation.collectedAt() == null
                    || !validText(citation.reliabilityLevel(), 60)
                    || !Double.isFinite(citation.similarity())
                    || citation.similarity() < -1 || citation.similarity() > 1) {
                throw invalid("knowledge citation is invalid");
            }
        }
    }

    private void validateFeasibilityReport(
            io.github.tobehardoo.trippilot.feasibility.FeasibilityReport report
    ) {
        if (report == null) {
            throw invalid("feasibilityReport is required in schema review v1");
        }
        try {
            io.github.tobehardoo.trippilot.feasibility.FeasibilityReportValidator.validate(report);
        } catch (IllegalArgumentException exception) {
            throw invalid("feasibilityReport is invalid: " + exception.getMessage());
        }
        if (report.status() == io.github.tobehardoo.trippilot.feasibility.FeasibilityStatus.VERIFIED) {
            throw invalid("feasibilityReport status must be UNVERIFIED or NEEDS_REPAIR");
        }
    }

    private boolean validText(String value, int maxLength) {
        return value != null && !value.isBlank() && value.length() <= maxLength;
    }

    private boolean validHttpUrl(String value) {
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

    private boolean isPersistableMoney(BigDecimal value) {
        return value != null
                && value.compareTo(MAX_PERSISTED_MONEY) <= 0
                && value.scale() <= 2;
    }

    private boolean supportedProvider(String provider) {
        return "AMAP".equals(provider) || "DEMO".equals(provider);
    }

    private PlanningEventContractException invalid(String message) {
        return new PlanningEventContractException(
                "Invalid PLANNING_REVIEW_REQUIRED event: " + message);
    }
}
