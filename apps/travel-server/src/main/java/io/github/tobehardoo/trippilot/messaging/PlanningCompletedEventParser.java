package io.github.tobehardoo.trippilot.messaging;

import java.io.IOException;
import java.math.BigDecimal;
import java.net.URI;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectReader;
import org.springframework.stereotype.Component;

@Component
public class PlanningCompletedEventParser {

    private static final BigDecimal MAX_PERSISTED_MONEY = new BigDecimal("9999999999.99");
    private static final BigDecimal MIN_LONGITUDE = new BigDecimal("-180");
    private static final BigDecimal MAX_LONGITUDE = new BigDecimal("180");
    private static final BigDecimal MIN_LATITUDE = new BigDecimal("-90");
    private static final BigDecimal MAX_LATITUDE = new BigDecimal("90");
    private static final int MAX_ROUTE_DISTANCE_METERS = 40_100_000;
    private static final int MAX_ROUTE_DURATION_SECONDS = 31_536_000;
    private static final int MAX_POLYLINE_POINTS = 5_000;

    private final ObjectReader reader;
    private final ObjectMapper objectMapper;

    public PlanningCompletedEventParser(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
        this.reader = objectMapper.readerFor(PlanningCompletedEvent.class)
                .with(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);
    }

    public PlanningCompletedEvent parse(byte[] body) {
        try {
            JsonNode tree = objectMapper.readTree(body);
            if (tree == null) {
                throw invalid("event body must contain a JSON object");
            }
            validateJsonTypes(tree);
            PlanningCompletedEvent event = reader.readValue(tree.traverse(objectMapper));
            validate(event);
            return event;
        } catch (IOException exception) {
            throw new PlanningEventContractException("Invalid PLANNING_COMPLETED event", exception);
        }
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
        JsonNode payload = event.path("payload");
        JsonNode itinerary = payload.path("itinerary");
        JsonNode days = itinerary.path("days");
        int schemaVersion = event.path("schemaVersion").asInt();
        if (!payload.isObject() || !payload.path("provider").isTextual()
                || !itinerary.isObject() || !itinerary.path("title").isTextual()
                || !itinerary.path("estimatedTotalCost").isNumber() || !days.isArray()) {
            throw invalid("payload field types do not match the JSON Schema");
        }
        validateKnowledgeTypes(payload, schemaVersion);
        for (JsonNode day : days) {
            JsonNode activities = day.path("activities");
            if (!day.isObject() || !day.path("date").isTextual() || !activities.isArray()) {
                throw invalid("day field types do not match the JSON Schema");
            }
            for (JsonNode activity : activities) {
                if (!activity.isObject() || !activity.path("title").isTextual()
                        || !activity.path("startTime").isTextual()
                        || !activity.path("endTime").isTextual()
                        || !activity.path("estimatedCost").isNumber()
                        || !activity.path("source").isTextual()) {
                    throw invalid("activity field types do not match the JSON Schema");
                }
                validateActivityMetadataTypes(activity);
            }
            validateTransitLegTypes(day, schemaVersion);
        }
    }

    private void validateKnowledgeTypes(JsonNode payload, int schemaVersion) {
        if (schemaVersion < 4) {
            if (payload.has("knowledge")) {
                throw invalid("knowledge evidence is only supported in schema v4");
            }
            return;
        }
        JsonNode knowledge = payload.path("knowledge");
        JsonNode citations = knowledge.path("citations");
        JsonNode freshness = knowledge.path("freshness");
        if (!knowledge.isObject() || !knowledge.path("status").isTextual()
                || !knowledge.path("query").isTextual() || !citations.isArray()
                || !freshness.isObject() || !freshness.path("status").isTextual()) {
            throw invalid("knowledge evidence field types do not match the JSON Schema");
        }
        if (knowledge.has("message") && !knowledge.path("message").isTextual()) {
            throw invalid("knowledge message must be text");
        }
        if (freshness.has("checkedAt") && !freshness.path("checkedAt").isTextual()) {
            throw invalid("knowledge checkedAt must be text");
        }
        if (freshness.has("staleReason") && !freshness.path("staleReason").isTextual()) {
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

    private void validateTransitLegTypes(JsonNode day, int schemaVersion) {
        if (schemaVersion < 3) {
            if (day.has("transitLegs")) {
                throw invalid("transitLegs are only supported in schema v3");
            }
            return;
        }
        JsonNode transitLegs = day.path("transitLegs");
        if (!transitLegs.isArray()) {
            throw invalid("v3 day transitLegs must be an array");
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
            for (JsonNode point : leg.path("polyline")) {
                if (!point.isObject() || !point.path("longitude").isNumber()
                        || !point.path("latitude").isNumber()) {
                    throw invalid("transit leg field types do not match the JSON Schema");
                }
            }
        }
    }

    private void validateActivityMetadataTypes(JsonNode activity) {
        if (activity.has("providerPoiId") && !activity.path("providerPoiId").isTextual()) {
            throw invalid("activity metadata types do not match the JSON Schema");
        }
        if (activity.has("address") && !activity.path("address").isTextual()) {
            throw invalid("activity metadata types do not match the JSON Schema");
        }
        if (activity.has("coordinates")) {
            JsonNode coordinates = activity.path("coordinates");
            if (!coordinates.isObject() || !coordinates.path("longitude").isNumber()
                    || !coordinates.path("latitude").isNumber()) {
                throw invalid("activity metadata types do not match the JSON Schema");
            }
        }
    }

    private void validate(PlanningCompletedEvent event) {
        if (!"PLANNING_COMPLETED".equals(event.eventType())
                || (event.schemaVersion() != 1
                && event.schemaVersion() != 2
                && event.schemaVersion() != 3
                && event.schemaVersion() != 4
                && event.schemaVersion() != 5)) {
            throw invalid("unsupported eventType or schemaVersion");
        }
        if (event.eventId() == null || event.traceId() == null || event.taskId() == null
                || event.tripId() == null || event.runId() == null || event.occurredAt() == null) {
            throw invalid("event envelope fields are required");
        }
        if (event.payload() == null || event.payload().itinerary() == null
                || !supportedProvider(event.payload().provider())) {
            throw invalid("supported payload is required");
        }
        if (event.schemaVersion() == 1 && !"DEMO".equals(event.payload().provider())) {
            throw invalid("v1 only supports DEMO payloads");
        }
        PlanningCompletedEvent.Itinerary itinerary = event.payload().itinerary();
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
            validateDay(day, event.schemaVersion(), event.payload().provider());
        }
        validateKnowledge(event.schemaVersion(), event.payload().knowledge());
    }

    private void validateKnowledge(int schemaVersion,
                                   PlanningCompletedEvent.KnowledgeEvidence knowledge) {
        if (schemaVersion < 4) {
            if (knowledge != null) {
                throw invalid("older schemas must not contain knowledge evidence");
            }
            return;
        }
        if (knowledge == null || !validText(knowledge.query(), 200)
                || knowledge.freshness() == null || knowledge.citations().size() > 20) {
            throw invalid("v4 knowledge evidence is invalid");
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
        validateFreshness(knowledge.freshness());
        for (PlanningCompletedEvent.KnowledgeCitation citation : knowledge.citations()) {
            if (!validCitation(citation)) {
                throw invalid("knowledge citation is invalid");
            }
        }
    }

    private void validateFreshness(PlanningCompletedEvent.KnowledgeFreshness freshness) {
        if ("UNAVAILABLE".equals(freshness.status())) {
            if (freshness.checkedAt() != null || freshness.staleReason() != null) {
                throw invalid("unavailable freshness cannot contain verification details");
            }
            return;
        }
        if (!("FRESH".equals(freshness.status()) || "STALE".equals(freshness.status()))
                || freshness.checkedAt() == null
                || ("FRESH".equals(freshness.status()) && freshness.staleReason() != null)
                || (freshness.staleReason() != null && !validText(freshness.staleReason(), 60))) {
            throw invalid("knowledge freshness is invalid");
        }
    }

    private boolean validCitation(PlanningCompletedEvent.KnowledgeCitation citation) {
        return citation != null
                && validText(citation.documentId(), 200)
                && citation.documentVersion() >= 1
                && validText(citation.chunkId(), 200)
                && citation.chunkIndex() >= 0
                && validText(citation.title(), 200)
                && validHttpUrl(citation.sourceUrl())
                && validText(citation.sourceName(), 120)
                && citation.collectedAt() != null
                && validText(citation.reliabilityLevel(), 60)
                && Double.isFinite(citation.similarity())
                && citation.similarity() >= -1
                && citation.similarity() <= 1;
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

    private void validateDay(PlanningCompletedEvent.Day day, int schemaVersion, String provider) {
        if (day == null || day.date() == null || day.activities() == null
                || day.activities().isEmpty()) {
            throw invalid("each itinerary day requires activities");
        }
        java.time.OffsetDateTime previousEnd = null;
        for (PlanningCompletedEvent.Activity activity : day.activities()) {
            if (activity == null || !validText(activity.title(), 200)
                    || activity.startTime() == null || activity.endTime() == null
                    || !isPersistableMoney(activity.estimatedCost())
                    || !supportedProvider(activity.source())) {
                throw invalid("activity fields are invalid");
            }
            if (!provider.equals(activity.source())) {
                throw invalid("activity source must match payload provider");
            }
            if (schemaVersion == 1 && (!"DEMO".equals(activity.source())
                    || activity.providerPoiId() != null
                    || activity.coordinates() != null || activity.address() != null)) {
                throw invalid("v1 activity source is invalid");
            }
            if (schemaVersion >= 2) {
                validateV2ActivitySource(activity);
            }
            if (!activity.endTime().isAfter(activity.startTime())) {
                throw invalid("activity endTime must be after startTime");
            }
            if (previousEnd != null && activity.startTime().isBefore(previousEnd)) {
                throw invalid("activities must be ordered without overlap");
            }
            previousEnd = activity.endTime();
        }
        validateTransitLegs(day, schemaVersion);
    }

    private void validateTransitLegs(PlanningCompletedEvent.Day day, int schemaVersion) {
        if (schemaVersion < 3) {
            if (!day.transitLegs().isEmpty()) {
                throw invalid("older schemas must not contain transit legs");
            }
            return;
        }
        int expectedCount = day.activities().size() - 1;
        if (day.transitLegs().size() != expectedCount) {
            throw invalid("transit legs must connect every adjacent activity");
        }
        for (int index = 0; index < day.transitLegs().size(); index++) {
            PlanningCompletedEvent.TransitLeg leg = day.transitLegs().get(index);
            if (leg.fromActivityIndex() != index || leg.toActivityIndex() != index + 1) {
                throw invalid("transit legs must connect adjacent activities in order");
            }
            if (!validTransitLeg(leg, schemaVersion)) {
                throw invalid("transit leg fields are invalid");
            }
            PlanningCompletedEvent.Activity origin = day.activities().get(index);
            PlanningCompletedEvent.Activity destination = day.activities().get(index + 1);
            if (origin.endTime().plusSeconds(leg.durationSeconds())
                    .isAfter(destination.startTime())) {
                throw invalid("transit leg travel time must fit between activities");
            }
        }
    }

    private boolean validTransitLeg(PlanningCompletedEvent.TransitLeg leg, int schemaVersion) {
        boolean sourceMatchesEstimate = ("AMAP".equals(leg.provider()) && !leg.estimated())
                || ("DEMO".equals(leg.provider()) && leg.estimated());
        boolean supportedMode = "WALKING".equals(leg.mode())
                || (schemaVersion >= 5 && "DRIVING".equals(leg.mode()));
        return supportedMode
                && leg.distanceMeters() >= 0
                && leg.distanceMeters() <= MAX_ROUTE_DISTANCE_METERS
                && leg.durationSeconds() >= 0
                && leg.durationSeconds() <= MAX_ROUTE_DURATION_SECONDS
                && sourceMatchesEstimate
                && !leg.polyline().isEmpty()
                && leg.polyline().size() <= MAX_POLYLINE_POINTS
                && leg.polyline().stream().allMatch(this::validCoordinates);
    }

    private void validateV2ActivitySource(PlanningCompletedEvent.Activity activity) {
        boolean hasProviderMetadata = activity.providerPoiId() != null
                || activity.coordinates() != null || activity.address() != null;
        if ("DEMO".equals(activity.source())) {
            if (hasProviderMetadata) {
                throw invalid("DEMO activity must not contain provider metadata");
            }
            return;
        }
        if (!"AMAP".equals(activity.source())
                || !validText(activity.providerPoiId(), 100)
                || !validText(activity.address(), 300)
                || !validCoordinates(activity.coordinates())) {
            throw invalid("AMAP activity requires valid provider metadata");
        }
    }

    private boolean validCoordinates(PlanningCompletedEvent.Coordinates coordinates) {
        return coordinates != null
                && coordinates.longitude() != null
                && coordinates.latitude() != null
                && coordinates.longitude().compareTo(MIN_LONGITUDE) >= 0
                && coordinates.longitude().compareTo(MAX_LONGITUDE) <= 0
                && coordinates.latitude().compareTo(MIN_LATITUDE) >= 0
                && coordinates.latitude().compareTo(MAX_LATITUDE) <= 0;
    }

    private boolean supportedProvider(String provider) {
        return "DEMO".equals(provider) || "AMAP".equals(provider);
    }

    private boolean validText(String value, int maxLength) {
        return value != null && !value.isBlank() && value.length() <= maxLength;
    }

    private boolean isPersistableMoney(BigDecimal value) {
        return value != null
                && value.signum() >= 0
                && value.compareTo(MAX_PERSISTED_MONEY) <= 0
                && value.stripTrailingZeros().scale() <= 2;
    }

    private PlanningEventContractException invalid(String detail) {
        return new PlanningEventContractException("Invalid PLANNING_COMPLETED event: " + detail);
    }
}
