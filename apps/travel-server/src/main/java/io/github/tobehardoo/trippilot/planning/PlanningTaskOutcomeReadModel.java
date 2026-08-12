package io.github.tobehardoo.trippilot.planning;

import java.util.List;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.feasibility.FeasibilityReport;
import io.github.tobehardoo.trippilot.feasibility.FeasibilityReportValidator;
import io.github.tobehardoo.trippilot.feasibility.FeasibilityStatus;
import io.github.tobehardoo.trippilot.feasibility.ItineraryFingerprintVerifier;
import io.github.tobehardoo.trippilot.infrastructure.mq.PlanningCompletedEvent.PlanEvaluation;
import org.springframework.stereotype.Component;

/**
 * B6J.2.1 F3: eventType-aware read model for the latest planning-task
 * outcome.
 *
 * The outcome is derived from the task status AND the latest outcome event
 * type together; the payload is never passed through blindly:
 *
 * <ul>
 *   <li>PLANNING_COMPLETED requires task.status SUCCEEDED, a valid report
 *       with status VERIFIED and a non-null evaluation; candidateItinerary
 *       must be absent.</li>
 *   <li>PLANNING_REVIEW_REQUIRED requires task.status WAITING_USER, a valid
 *       report with status UNVERIFIED/NEEDS_REPAIR, a non-null candidate
 *       whose fingerprint matches the report, and no evaluation.</li>
 *   <li>PLANNING_FAILED requires task.status FAILED; PLANNING_CANCELLED
 *       requires task.status CANCELLED; neither may carry report, candidate
 *       or evaluation.</li>
 * </ul>
 *
 * QUEUED/RUNNING tasks have no outcome event and are handled by the caller
 * (no outcome fields).  Any contradictory combination or malformed payload
 * fails closed with {@link IllegalStateException}.
 */
@Component
public class PlanningTaskOutcomeReadModel {

    private final ObjectMapper objectMapper;

    public PlanningTaskOutcomeReadModel(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public Outcome read(PlanningTaskRecord task, PlanningTaskEventRecord event) {
        JsonNode payload;
        try {
            payload = objectMapper.readTree(event.payloadJson());
        } catch (JsonProcessingException exception) {
            throw invalid(event);
        }
        if (!payload.isObject()) {
            throw invalid(event);
        }
        switch (event.eventType()) {
            case "PLANNING_COMPLETED":
                return readCompleted(task, event, payload);
            case "PLANNING_REVIEW_REQUIRED":
                return readReview(task, event, payload);
            case "PLANNING_FAILED":
                return readFailed(task, event, payload);
            case "PLANNING_CANCELLED":
                return readCancelled(task, event, payload);
            default:
                throw invalid(event);
        }
    }

    private Outcome readCompleted(PlanningTaskRecord task, PlanningTaskEventRecord event,
                                  JsonNode payload) {
        requireStatus(task, "SUCCEEDED", event);
        FeasibilityReport report = parseReport(payload);
        if (report.status() != FeasibilityStatus.VERIFIED) {
            throw invalid(event);
        }
        PlanEvaluation evaluation = parseEvaluation(payload, event);
        if (evaluation == null) {
            throw invalid(event);
        }
        if (payload.has("candidateItinerary") && !payload.path("candidateItinerary").isNull()) {
            throw invalid(event);
        }
        return new Outcome(
                null, null, text(payload, "provider"), text(payload, "operation"),
                optionalBoolean(payload, "retryable"), optionalInteger(payload, "retryCount"),
                optionalBoolean(payload, "fallbackAttempted"),
                optionalBoolean(payload, "fallbackSucceeded"),
                null, null,
                text(payload, "requestedProviderMode"), text(payload, "primaryProvider"),
                nullableStringList(payload, "actualProviders"),
                text(payload, "fallbackReason"),
                fallbackOperationList(payload, "fallbackOperations"),
                evaluation, report,
                payload.has("candidateItinerary")
                        ? payload.get("candidateItinerary") : null
        );
    }

    private Outcome readReview(PlanningTaskRecord task, PlanningTaskEventRecord event,
                               JsonNode payload) {
        requireStatus(task, "WAITING_USER", event);
        FeasibilityReport report = parseReport(payload);
        if (report.status() == FeasibilityStatus.VERIFIED) {
            throw invalid(event);
        }
        JsonNode candidate = payload.get("candidateItinerary");
        if (candidate == null || candidate.isNull() || !candidate.isObject()) {
            throw invalid(event);
        }
        if (!isValidCandidate(candidate)) {
            throw invalid(event);
        }
        // The stored candidate is the parser-validated raw wire itinerary
        // (persisted losslessly by the review service), so the report
        // fingerprint must recompute exactly against it.  A tampered
        // candidate or a tampered fingerprint fails closed instead of being
        // passed through.
        if (!ItineraryFingerprintVerifier.matches(candidate, report.itineraryFingerprint())) {
            throw invalid(event);
        }
        if (payload.has("evaluation") && !payload.path("evaluation").isNull()) {
            throw invalid(event);
        }
        return new Outcome(
                null, null, text(payload, "provider"), text(payload, "operation"),
                optionalBoolean(payload, "retryable"), optionalInteger(payload, "retryCount"),
                optionalBoolean(payload, "fallbackAttempted"),
                optionalBoolean(payload, "fallbackSucceeded"),
                null, null,
                text(payload, "requestedProviderMode"), text(payload, "primaryProvider"),
                nullableStringList(payload, "actualProviders"),
                text(payload, "fallbackReason"),
                fallbackOperationList(payload, "fallbackOperations"),
                null, report, candidate
        );
    }

    /**
     * Structural validation of a stored candidate itinerary: it must carry a
     * title, a non-empty days array, and each day must have a non-empty
     * activities array with the mandatory activity fields.  This protects the
     * API from malformed candidates without requiring byte-identical
     * fingerprint recomputation (impossible for typed-DTO storage).
     */
    private boolean isValidCandidate(JsonNode candidate) {
        if (!candidate.path("title").isTextual()
                || candidate.path("title").asText().isBlank()) {
            return false;
        }
        if (!candidate.path("days").isArray() || candidate.path("days").isEmpty()) {
            return false;
        }
        for (JsonNode day : candidate.path("days")) {
            if (!day.isObject() || !day.path("date").isTextual()
                    || !day.path("activities").isArray()
                    || day.path("activities").isEmpty()) {
                return false;
            }
            for (JsonNode activity : day.path("activities")) {
                if (!activity.isObject()
                        || !activity.path("title").isTextual()
                        || activity.path("title").asText().isBlank()
                        || !activity.path("startTime").isTextual()
                        || !activity.path("endTime").isTextual()) {
                    return false;
                }
            }
        }
        return true;
    }

    private Outcome readFailed(PlanningTaskRecord task, PlanningTaskEventRecord event,
                               JsonNode payload) {
        requireStatus(task, "FAILED", event);
        rejectOutcomeFields(payload, event);
        return new Outcome(
                text(payload, "errorCode", task.errorCode()),
                text(payload, "errorCategory"),
                text(payload, "provider"), text(payload, "operation"),
                optionalBoolean(payload, "retryable"), optionalInteger(payload, "retryCount"),
                optionalBoolean(payload, "fallbackAttempted"),
                optionalBoolean(payload, "fallbackSucceeded"),
                text(payload, "safeMessage", text(payload, "message", task.errorMessage())),
                text(payload, "safeProviderCode"),
                text(payload, "requestedProviderMode"), text(payload, "primaryProvider"),
                nullableStringList(payload, "actualProviders"),
                text(payload, "fallbackReason"),
                fallbackOperationList(payload, "fallbackOperations"),
                null, null, null
        );
    }

    private Outcome readCancelled(PlanningTaskRecord task, PlanningTaskEventRecord event,
                                  JsonNode payload) {
        requireStatus(task, "CANCELLED", event);
        rejectOutcomeFields(payload, event);
        return new Outcome(
                null, null, text(payload, "provider"), text(payload, "operation"),
                optionalBoolean(payload, "retryable"), optionalInteger(payload, "retryCount"),
                optionalBoolean(payload, "fallbackAttempted"),
                optionalBoolean(payload, "fallbackSucceeded"),
                text(payload, "safeMessage", text(payload, "message", task.errorMessage())),
                text(payload, "safeProviderCode"),
                text(payload, "requestedProviderMode"), text(payload, "primaryProvider"),
                nullableStringList(payload, "actualProviders"),
                text(payload, "fallbackReason"),
                fallbackOperationList(payload, "fallbackOperations"),
                null, null, null
        );
    }

    private void rejectOutcomeFields(JsonNode payload, PlanningTaskEventRecord event) {
        for (String field : new String[]{"feasibilityReport", "candidateItinerary", "evaluation"}) {
            if (payload.has(field) && !payload.path(field).isNull()) {
                throw invalid(event);
            }
        }
    }

    private void requireStatus(PlanningTaskRecord task, String expected,
                               PlanningTaskEventRecord event) {
        if (!expected.equals(task.status())) {
            throw invalid(event);
        }
    }

    private FeasibilityReport parseReport(JsonNode payload) {
        JsonNode reportNode = payload.get("feasibilityReport");
        if (reportNode == null || reportNode.isNull() || !reportNode.isObject()) {
            throw invalid(payload);
        }
        try {
            FeasibilityReport report = objectMapper.treeToValue(reportNode, FeasibilityReport.class);
            FeasibilityReportValidator.validate(report);
            return report;
        } catch (JsonProcessingException | IllegalArgumentException exception) {
            throw invalid(payload);
        }
    }

    private PlanEvaluation parseEvaluation(JsonNode payload, PlanningTaskEventRecord event) {
        JsonNode evalNode = payload.get("evaluation");
        if (evalNode == null || evalNode.isNull()) {
            return null;
        }
        try {
            return objectMapper.treeToValue(evalNode, PlanEvaluation.class);
        } catch (JsonProcessingException e) {
            throw invalid(event);
        }
    }

    private String text(JsonNode payload, String field) {
        return text(payload, field, null);
    }

    private String text(JsonNode payload, String field, String fallback) {
        JsonNode value = payload.get(field);
        return value == null || value.isNull() ? fallback : value.asText();
    }

    private Boolean optionalBoolean(JsonNode payload, String field) {
        JsonNode value = payload.get(field);
        return value == null || value.isNull() ? null : value.asBoolean();
    }

    private Integer optionalInteger(JsonNode payload, String field) {
        JsonNode value = payload.get(field);
        return value == null || value.isNull() ? null : value.asInt();
    }

    private List<String> nullableStringList(JsonNode payload, String field) {
        JsonNode value = payload.get(field);
        if (value == null || value.isNull()) {
            return null;
        }
        if (!value.isArray()) {
            throw invalid(payload);
        }
        java.util.ArrayList<String> result = new java.util.ArrayList<>();
        value.forEach(item -> result.add(item.asText()));
        return List.copyOf(result);
    }

    private List<PlanningTaskService.FallbackOperationResponse> fallbackOperationList(
            JsonNode payload, String field) {
        JsonNode value = payload.get(field);
        if (value == null || value.isNull()) {
            return null;
        }
        if (!value.isArray()) {
            throw invalid(payload);
        }
        java.util.ArrayList<PlanningTaskService.FallbackOperationResponse> result =
                new java.util.ArrayList<>();
        value.forEach(item -> result.add(new PlanningTaskService.FallbackOperationResponse(
                text(item, "operation", null), optionalUuid(item, "transitId"),
                optionalUuid(item, "fromActivityId"), optionalUuid(item, "toActivityId"),
                text(item, "requestedMode", null), text(item, "actualProvider", null),
                text(item, "errorCategory", null), text(item, "errorCode", null),
                item.path("retryCount").asInt()
        )));
        return List.copyOf(result);
    }

    private UUID optionalUuid(JsonNode payload, String field) {
        JsonNode value = payload.get(field);
        return value == null || value.isNull() ? null : UUID.fromString(value.asText());
    }

    private IllegalStateException invalid(PlanningTaskEventRecord event) {
        return new IllegalStateException(
                "Planning task terminal event is invalid: " + event.eventType());
    }

    private IllegalStateException invalid(JsonNode payload) {
        return new IllegalStateException("Planning task terminal event is invalid");
    }

    public record Outcome(
            String errorCode,
            String errorCategory,
            String provider,
            String operation,
            Boolean retryable,
            Integer retryCount,
            Boolean fallbackAttempted,
            Boolean fallbackSucceeded,
            String safeMessage,
            String safeProviderCode,
            String requestedProviderMode,
            String primaryProvider,
            List<String> actualProviders,
            String fallbackReason,
            List<PlanningTaskService.FallbackOperationResponse> fallbackOperations,
            PlanEvaluation evaluation,
            FeasibilityReport feasibilityReport,
            JsonNode candidateItinerary
    ) {
    }
}
