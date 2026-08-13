package io.github.tobehardoo.trippilot.planning;

import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.ApiException;
import org.springframework.http.HttpStatus;

final class PlanningTaskIdempotency {

    private static final String CREATE_TASK_TYPE = "CREATE";
    private static final String REPLAN_TASK_TYPE = "REPLAN";

    private PlanningTaskIdempotency() {
    }

    static void requireCreateMatch(PlanningTaskRecord existing) {
        if (!CREATE_TASK_TYPE.equals(existing.taskType())) {
            throw reusedKey();
        }
    }

    static void requireReplanMatch(
            PlanningTaskRecord existing,
            PlanningTaskService.LocalReplanRequest request,
            ObjectMapper objectMapper
    ) {
        if (!REPLAN_TASK_TYPE.equals(existing.taskType())
                || request == null
                || request.baseVersionId() == null
                || !request.baseVersionId().equals(existing.baselineItineraryVersionId())
                || !canonicalDates(request.dates()).equals(
                        storedDates(existing.impactedDatesJson(), objectMapper)
                )) {
            throw reusedKey();
        }
    }

    static void requireCandidateMatch(
            PlanningTaskRecord existing,
            String candidateType,
            UUID baselineVersionId,
            UUID sourceVersionId,
            String requestHash,
            List<LocalDate> changedDates,
            List<LocalDate> impactedDates,
            ObjectMapper objectMapper
    ) {
        if (!(candidateType + "_VALIDATE").equals(existing.taskType())
                || !candidateType.equals(existing.candidateType())
                || !baselineVersionId.equals(existing.baselineItineraryVersionId())
                || !sourceVersionId.equals(existing.candidateSourceVersionId())
                || !requestHash.equals(existing.candidateRequestHash())
                || !canonicalDates(changedDates).equals(
                        storedDates(existing.changedDatesJson(), objectMapper))
                || !canonicalDates(impactedDates).equals(
                        storedDates(existing.impactedDatesJson(), objectMapper))) {
            throw reusedKey();
        }
    }

    private static List<LocalDate> storedDates(String value, ObjectMapper objectMapper) {
        if (value == null) {
            throw new IllegalStateException("REPLAN task is missing impacted dates");
        }
        try {
            List<LocalDate> dates = objectMapper.readValue(
                    value, new TypeReference<List<LocalDate>>() { }
            );
            return canonicalDates(dates);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Could not deserialize REPLAN impacted dates", exception);
        }
    }

    private static List<LocalDate> canonicalDates(List<LocalDate> dates) {
        if (dates == null || dates.isEmpty() || dates.stream().anyMatch(java.util.Objects::isNull)) {
            throw reusedKey();
        }
        List<LocalDate> canonical = dates.stream().distinct().sorted().toList();
        if (canonical.size() != dates.size()) {
            throw reusedKey();
        }
        return canonical;
    }

    private static ApiException reusedKey() {
        return new ApiException(
                HttpStatus.CONFLICT,
                "IDEMPOTENCY_KEY_REUSED",
                "The Idempotency-Key was already used for a different planning request"
        );
    }
}
