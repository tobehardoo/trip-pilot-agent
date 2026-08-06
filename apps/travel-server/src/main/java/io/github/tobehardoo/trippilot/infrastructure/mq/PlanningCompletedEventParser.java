package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.io.IOException;
import java.math.BigDecimal;
import java.net.URI;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

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
    private static final Set<String> EVALUATION_WARNING_CODES = Set.of(
            "TIGHT_TRANSFER", "HIGH_DAILY_LOAD", "BUDGET_NEAR_LIMIT",
            "LONG_WALKING", "LATE_DAY_END", "LOW_INTEREST_MATCH",
            "PROVIDER_FALLBACK_USED", "ESTIMATED_TRANSIT", "LOW_TIME_BUFFER"
    );
    private static final Set<String> EVALUATION_SEVERITIES = Set.of(
            "INFO", "WARNING", "CRITICAL"
    );
    private static final Set<String> EVALUATION_ENTITY_TYPES = Set.of(
            "PLAN", "DAY", "ACTIVITY", "TRANSIT"
    );
    private static final Set<String> EVALUATION_REASON_CODES = Set.of(
            "FIXED_APPOINTMENT", "NEARBY_CLUSTER", "MUST_VISIT",
            "TRANSIT_MODE", "SHORTEST_ROUTE", "PROVIDER_CONSTRAINT",
            "TIME_OPTIMIZATION", "BUDGET_CONSTRAINT", "REGIONAL_GROUPING"
    );
    private static final Set<String> DAY_TYPES = Set.of(
            "ARRIVAL_DAY", "FULL_DAY", "DEPARTURE_DAY", "SPECIAL_ACTIVITY_DAY"
    );
    private static final Set<String> ACTIVITY_KINDS = Set.of(
            "ATTRACTION", "EXPERIENCE", "MEAL", "ACCOMMODATION", "ARRIVAL", "DEPARTURE"
    );
    private static final Set<String> STRUCTURAL_KINDS = Set.of(
            "MEAL", "ACCOMMODATION", "ARRIVAL", "DEPARTURE"
    );

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
        // Java accepts v1-v6 (historical/current) and v8 (candidate); v7 is
        // ABANDONED and stays rejected.
        if (schemaVersion < 1 || schemaVersion > 8 || schemaVersion == 7) {
            throw invalid("unsupported eventType or schemaVersion");
        }
        if (!payload.isObject() || !payload.path("provider").isTextual()
                || !itinerary.isObject() || !itinerary.path("title").isTextual()
                || !itinerary.path("estimatedTotalCost").isNumber() || !days.isArray()) {
            throw invalid("payload field types do not match the JSON Schema");
        }
        validateKnowledgeTypes(payload, schemaVersion);
        validateFactImpactTypes(payload, schemaVersion);
        validateProviderProvenanceTypes(payload, schemaVersion);
        validateEvaluationTypes(payload, schemaVersion);
        for (JsonNode day : days) {
            JsonNode activities = day.path("activities");
            if (!day.isObject() || !day.path("date").isTextual() || !activities.isArray()) {
                throw invalid("day field types do not match the JSON Schema");
            }
            if (day.has("dayType") && !day.path("dayType").isTextual()) {
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
                if (activity.has("kind") && !activity.path("kind").isTextual()) {
                    throw invalid("activity kind must be a string");
                }
                if (activity.has("timeFixed") && !activity.path("timeFixed").isBoolean()) {
                    throw invalid("activity timeFixed must be a boolean");
                }
                validateActivityMetadataTypes(activity);
                if (activity.has("activityId")
                        && ((schemaVersion != 6 && schemaVersion != 8)
                        || !activity.path("activityId").isTextual())) {
                    throw invalid("activityId is only supported as a UUID string in schema v6/v8");
                }
            }
            validateTransitLegTypes(day, schemaVersion);
        }
    }

    private void validateFactImpactTypes(JsonNode payload, int schemaVersion) {
        if (schemaVersion < 6) {
            if (payload.has("factImpacts")) {
                throw invalid("fact impacts are only supported in schema v6");
            }
            return;
        }
        JsonNode impacts = payload.path("factImpacts");
        if (!impacts.isArray() || impacts.size() > 500) {
            throw invalid("v6 factImpacts must be a bounded array");
        }
        for (JsonNode impact : impacts) {
            if (!impact.isObject()
                    || !impact.path("factId").isTextual()
                    || !impact.path("category").isTextual()
                    || !impact.path("effect").isTextual()
                    || !impact.path("reason").isTextual()
                    || !impact.path("sourceName").isTextual()
                    || !impact.path("sourceType").isTextual()
                    || !impact.path("reliabilityLevel").isTextual()
                    || !impact.path("checkedAt").isTextual()
                    || !impact.path("evidence").isTextual()
                    || !impact.path("stale").isBoolean()
                    || !impact.path("conflicted").isBoolean()
                    || !impact.path("refreshFailed").isBoolean()
                    || impact.has("date") && !impact.path("date").isTextual()
                    || impact.has("targetPoiId")
                        && !impact.path("targetPoiId").isTextual()
                    || impact.has("targetName")
                        && !impact.path("targetName").isTextual()
                    || impact.has("sourceUrl")
                        && !impact.path("sourceUrl").isTextual()) {
                throw invalid("fact impact field types do not match the JSON Schema");
            }
        }
    }

    private void validateProviderProvenanceTypes(JsonNode payload, int schemaVersion) {
        if (!payload.has("providerProvenance")) {
            return;
        }
        if (schemaVersion != 6 && schemaVersion != 8) {
            throw invalid("provider provenance is only supported in schema v6/v8");
        }
        JsonNode provenance = payload.path("providerProvenance");
        JsonNode actualProviders = provenance.path("actualProviders");
        JsonNode operations = provenance.path("fallbackOperations");
        if (!provenance.isObject()
                || !provenance.path("requestedProviderMode").isTextual()
                || !provenance.path("primaryProvider").isTextual()
                || !actualProviders.isArray()
                || !provenance.path("fallbackAttempted").isBoolean()
                || !provenance.path("fallbackSucceeded").isBoolean()
                || !operations.isArray()
                || provenance.has("fallbackReason")
                    && !provenance.path("fallbackReason").isNull()
                    && !provenance.path("fallbackReason").isTextual()) {
            throw invalid("provider provenance field types do not match the JSON Schema");
        }
        actualProviders.forEach(provider -> {
            if (!provider.isTextual()) {
                throw invalid("actualProviders must contain provider names");
            }
        });
        for (JsonNode operation : operations) {
            if (!operation.isObject()
                    || !operation.path("operation").isTextual()
                    || !nullableText(operation, "transitId")
                    || !nullableText(operation, "fromActivityId")
                    || !nullableText(operation, "toActivityId")
                    || !operation.path("requestedMode").isTextual()
                    || !operation.path("actualProvider").isTextual()
                    || !operation.path("errorCategory").isTextual()
                    || !operation.path("errorCode").isTextual()
                    || !operation.path("retryCount").isIntegralNumber()) {
                throw invalid("fallback operation field types do not match the JSON Schema");
            }
        }
    }

    private boolean nullableText(JsonNode object, String field) {
        JsonNode value = object.get(field);
        return value != null && (value.isNull() || value.isTextual());
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
            if (leg.has("transitId")
                    && ((schemaVersion != 6 && schemaVersion != 8)
                    || !leg.path("transitId").isTextual())) {
                throw invalid("transitId is only supported as a UUID string in schema v6/v8");
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
                && event.schemaVersion() != 5
                && event.schemaVersion() != 6
                && event.schemaVersion() != 8)) {
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
        validateFactImpacts(event.schemaVersion(), event.payload().factImpacts());
        validateProviderProvenance(event);
        validateEvaluation(event);
    }

    private void validateEvaluationTypes(JsonNode payload, int schemaVersion) {
        if (!payload.has("evaluation") || payload.get("evaluation").isNull()) {
            return;
        }
        if (schemaVersion != 6 && schemaVersion != 8) {
            throw invalid("evaluation is only supported in schema v6/v8");
        }
        JsonNode evaluation = payload.path("evaluation");
        if (!evaluation.isObject()
                || !evaluation.path("schemaVersion").isInt()
                || !evaluation.path("evaluatorVersion").isTextual()
                || !evaluation.path("feasible").isBoolean()
                || !evaluation.path("overallScore").isInt()
                || !evaluation.path("dimensions").isObject()
                || !evaluation.path("warnings").isArray()
                || !evaluation.path("decisions").isArray()
                || !evaluation.path("summary").isTextual()
                || !evaluation.path("evaluatedAt").isTextual()) {
            throw invalid("evaluation field types do not match the JSON Schema");
        }
    }

    private void validateEvaluation(PlanningCompletedEvent event) {
        PlanningCompletedEvent.PlanEvaluation evaluation = event.payload().evaluation();
        if (evaluation == null) {
            return;
        }
        if ((event.schemaVersion() != 6 && event.schemaVersion() != 8)
                || evaluation.schemaVersion() != 1) {
            throw invalid("evaluation schemaVersion must be 1");
        }
        if (evaluation.evaluatorVersion() == null
                || !evaluation.evaluatorVersion().matches("^rule-v\\d+$")) {
            throw invalid("evaluation evaluatorVersion is invalid");
        }
        if (!evaluation.feasible()) {
            throw invalid("evaluation feasible must be true in completion");
        }
        if (evaluation.overallScore() < 0 || evaluation.overallScore() > 100) {
            throw invalid("evaluation overallScore must be 0-100");
        }
        if (!validText(evaluation.summary(), 1_000)
                || evaluation.evaluatedAt() == null) {
            throw invalid("evaluation summary or evaluatedAt is invalid");
        }
        PlanningCompletedEvent.EvaluationDimensions dims = evaluation.dimensions();
        if (dims == null
                || dims.constraintSatisfaction() < 0 || dims.constraintSatisfaction() > 100
                || dims.timeFeasibility() < 0 || dims.timeFeasibility() > 100
                || dims.budgetFit() < 0 || dims.budgetFit() > 100
                || dims.routeEfficiency() < 0 || dims.routeEfficiency() > 100
                || dims.interestMatch() < 0 || dims.interestMatch() > 100) {
            throw invalid("evaluation dimension scores must be 0-100");
        }
        int expectedOverall = (int) Math.round(
                dims.constraintSatisfaction() * 0.30
                + dims.timeFeasibility() * 0.25
                + dims.budgetFit() * 0.15
                + dims.routeEfficiency() * 0.15
                + dims.interestMatch() * 0.15
        );
        if (evaluation.overallScore() != expectedOverall) {
            throw invalid("evaluation overallScore must match weighted dimensions");
        }
        if (evaluation.warnings() != null) {
            for (PlanningCompletedEvent.EvaluationWarning w : evaluation.warnings()) {
                if (w == null
                        || !EVALUATION_WARNING_CODES.contains(w.code())
                        || !EVALUATION_SEVERITIES.contains(w.severity())
                        || !validText(w.message(), 300)
                        || !EVALUATION_ENTITY_TYPES.contains(w.entityType())) {
                    throw invalid("evaluation warning is invalid");
                }
            }
        }
        if (evaluation.decisions() != null) {
            java.util.Set<String> seen = new java.util.HashSet<>();
            for (PlanningCompletedEvent.DecisionExplanation d : evaluation.decisions()) {
                if (d == null
                        || !EVALUATION_ENTITY_TYPES.contains(d.subjectType())
                        || !validText(d.summary(), 300)
                        || d.reasonCodes() == null || d.reasonCodes().isEmpty()
                        || !EVALUATION_REASON_CODES.containsAll(d.reasonCodes())
                        || d.reasons() == null || d.reasons().isEmpty()
                        || d.reasonCodes().size() != d.reasons().size()
                        || d.reasons().stream().anyMatch(reason -> !validText(reason, 300))
                        || d.evidence().stream().anyMatch(evidence -> evidence == null
                                || !validText(evidence.key(), 60)
                                || !validText(evidence.label(), 300)
                                || !validText(evidence.value(), 200))) {
                    throw invalid("evaluation decision is invalid");
                }
                if (!seen.add(d.subjectType() + "|" + d.subjectId() + "|" + d.summary())) {
                    throw invalid("evaluation decisions must contain unique entries");
                }
            }
        }
    }

    private void validateProviderProvenance(PlanningCompletedEvent event) {
        PlanningCompletedEvent.ProviderProvenance provenance =
                event.payload().providerProvenance();
        if (provenance == null) {
            return;
        }
        if ((event.schemaVersion() != 6 && event.schemaVersion() != 8)
                || provenance.requestedProviderMode() == null
                || provenance.primaryProvider() == null
                || provenance.actualProviders().isEmpty()
                || provenance.actualProviders().size() > 2
                || new HashSet<>(provenance.actualProviders()).size()
                    != provenance.actualProviders().size()
                || provenance.fallbackOperations().size() > 100) {
            throw invalid("provider provenance is invalid");
        }

        Set<PlanningCompletedEvent.ProviderSource> observedProviders = new HashSet<>();
        event.payload().itinerary().days().forEach(day -> {
            day.activities().forEach(activity -> observedProviders.add(
                    PlanningCompletedEvent.ProviderSource.valueOf(activity.source())
            ));
            day.transitLegs().forEach(leg -> observedProviders.add(
                    PlanningCompletedEvent.ProviderSource.valueOf(leg.provider())
            ));
        });
        List<PlanningCompletedEvent.ProviderSource> canonicalProviders =
                observedProviders.stream().sorted().toList();
        if (!provenance.actualProviders().equals(canonicalProviders)) {
            throw invalid("actualProviders must exactly match final activity and transit sources");
        }
        if (provenance.fallbackAttempted() != provenance.fallbackSucceeded()) {
            throw invalid("successful completion cannot contain a failed fallback");
        }
        if (provenance.fallbackAttempted()) {
            if (!validCode(provenance.fallbackReason())
                    || provenance.fallbackOperations().isEmpty()) {
                throw invalid("successful fallback requires reason and operation evidence");
            }
        } else if (provenance.fallbackReason() != null
                || !provenance.fallbackOperations().isEmpty()) {
            throw invalid("non-fallback completion must not contain fallback evidence");
        }

        switch (provenance.requestedProviderMode()) {
            case DEMO_ONLY -> {
                if (provenance.primaryProvider() != PlanningCompletedEvent.ProviderSource.DEMO
                        || !provenance.actualProviders().equals(
                                List.of(PlanningCompletedEvent.ProviderSource.DEMO))
                        || provenance.fallbackAttempted()) {
                    throw invalid("DEMO_ONLY completion must only contain DEMO evidence");
                }
            }
            case REAL_ONLY -> {
                if (provenance.primaryProvider() != PlanningCompletedEvent.ProviderSource.AMAP
                        || !provenance.actualProviders().equals(
                                List.of(PlanningCompletedEvent.ProviderSource.AMAP))
                        || provenance.fallbackAttempted()) {
                    throw invalid("REAL_ONLY completion must only contain AMAP evidence");
                }
            }
            case REAL_WITH_EXPLICIT_FALLBACK -> {
                if (provenance.primaryProvider() != PlanningCompletedEvent.ProviderSource.AMAP
                        || provenance.fallbackAttempted()
                            && !provenance.actualProviders().contains(
                                    PlanningCompletedEvent.ProviderSource.DEMO)
                        || !provenance.fallbackAttempted()
                            && !provenance.actualProviders().equals(
                                    List.of(PlanningCompletedEvent.ProviderSource.AMAP))) {
                    throw invalid("explicit fallback completion has inconsistent provider evidence");
                }
            }
        }
        validateFallbackOperations(event, provenance);
    }

    private void validateFallbackOperations(
            PlanningCompletedEvent event,
            PlanningCompletedEvent.ProviderProvenance provenance
    ) {
        Set<PlanningCompletedEvent.FallbackOperation> uniqueOperations = new HashSet<>();
        for (PlanningCompletedEvent.FallbackOperation operation
                : provenance.fallbackOperations()) {
            if (operation == null
                    || !uniqueOperations.add(operation)
                    || operation.requestedMode() != provenance.requestedProviderMode()
                    || operation.actualProvider() != PlanningCompletedEvent.ProviderSource.DEMO
                    || operation.errorCategory() == null
                    || !validCode(operation.errorCode())
                    || operation.retryCount() < 0 || operation.retryCount() > 10) {
                throw invalid("fallback operation evidence is invalid");
            }
            if (operation.operation() != PlanningCompletedEvent.ProviderOperation.ROUTE) {
                if (operation.transitId() != null || operation.fromActivityId() != null
                        || operation.toActivityId() != null) {
                    throw invalid("whole-plan fallback must not claim a transit identity");
                }
                continue;
            }
            validateRouteFallbackIdentity(event, operation);
        }
    }

    private void validateRouteFallbackIdentity(
            PlanningCompletedEvent event,
            PlanningCompletedEvent.FallbackOperation operation
    ) {
        int matches = 0;
        for (PlanningCompletedEvent.Day day : event.payload().itinerary().days()) {
            for (PlanningCompletedEvent.TransitLeg leg : day.transitLegs()) {
                if (!java.util.Objects.equals(operation.transitId(), leg.transitId())) {
                    continue;
                }
                PlanningCompletedEvent.Activity origin =
                        day.activities().get(leg.fromActivityIndex());
                PlanningCompletedEvent.Activity destination =
                        day.activities().get(leg.toActivityIndex());
                if (!java.util.Objects.equals(operation.fromActivityId(), origin.activityId())
                        || !java.util.Objects.equals(operation.toActivityId(), destination.activityId())
                        || !"DEMO".equals(leg.provider()) || !leg.estimated()) {
                    throw invalid("fallback operation must match one transit identity");
                }
                matches++;
            }
        }
        if (matches != 1) {
            throw invalid("fallback operation must match one transit identity");
        }
    }

    private boolean validCode(String value) {
        return validText(value, 60) && value.matches("[A-Z0-9_]+");
    }

    private void validateFactImpacts(
            int schemaVersion,
            List<PlanningCompletedEvent.FactImpact> impacts
    ) {
        if (schemaVersion < 6) {
            if (!impacts.isEmpty()) {
                throw invalid("older schemas must not contain fact impacts");
            }
            return;
        }
        if (impacts.size() > 500) {
            throw invalid("fact impacts exceed the supported limit");
        }
        for (PlanningCompletedEvent.FactImpact impact : impacts) {
            if (impact == null
                    || !validText(impact.factId(), 80)
                    || !validText(impact.category(), 60)
                    || !validText(impact.effect(), 60)
                    || !validText(impact.reason(), 300)
                    || !validText(impact.sourceName(), 120)
                    || !validText(impact.sourceType(), 60)
                    || impact.sourceUrl() != null
                        && !validHttpUrl(impact.sourceUrl())
                    || !validText(impact.reliabilityLevel(), 60)
                    || impact.checkedAt() == null
                    || !validText(impact.evidence(), 2000)
                    || impact.date() != null && schemaVersion < 6
                    || impact.targetPoiId() != null
                        && !validText(impact.targetPoiId(), 100)
                    || impact.targetName() != null
                        && !validText(impact.targetName(), 120)) {
                throw invalid("fact impact is invalid");
            }
        }
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
        // Gaps between adjacent activities are allowed only in v8 (unresolved
        // structural nodes such as a meal without a bound restaurant have no
        // transit leg). Older producers always emit one leg per adjacent pair.
        boolean strictAdjacency = schemaVersion != 8;
        if (strictAdjacency
                && day.transitLegs().size() != day.activities().size() - 1) {
            throw invalid("transit legs must connect every adjacent activity");
        }
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
            if (!validTransitLeg(leg, schemaVersion)) {
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
        if (!"AMAP".equals(activity.source())) {
            throw invalid("AMAP activity requires valid provider metadata");
        }
        boolean structural = activity.kind() != null
                && STRUCTURAL_KINDS.contains(activity.kind());
        if (structural && !hasProviderMetadata) {
            // A structural node without a resolved POI is allowed (e.g. an
            // unresolved meal slot); it carries no fake provider metadata.
            return;
        }
        if (!validText(activity.providerPoiId(), 100)
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
