package io.github.tobehardoo.trippilot.messaging;

import java.io.IOException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectReader;
import org.springframework.stereotype.Component;

@Component
public class PlanningFailedEventParser {

    private final ObjectReader reader;

    public PlanningFailedEventParser(ObjectMapper objectMapper) {
        this.reader = objectMapper.readerFor(PlanningFailedEvent.class)
                .with(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);
    }

    public PlanningFailedEvent parse(byte[] body) {
        try {
            PlanningFailedEvent event = reader.readValue(body);
            validate(event);
            return event;
        } catch (IOException exception) {
            throw new PlanningEventContractException("Invalid PLANNING_FAILED event", exception);
        }
    }

    private void validate(PlanningFailedEvent event) {
        if (event == null || !"PLANNING_FAILED".equals(event.eventType())
                || event.schemaVersion() != 1 || event.eventId() == null
                || event.traceId() == null || event.taskId() == null || event.tripId() == null
                || event.runId() == null || event.occurredAt() == null || event.payload() == null) {
            throw invalid("failure envelope is incomplete");
        }
        PlanningFailedEvent.Payload payload = event.payload();
        if (!"FAILED".equals(payload.status())
                || !"NO_FEASIBLE_ITINERARY".equals(payload.errorCode())
                || !bounded(payload.message(), 300)
                || payload.conflicts().isEmpty() || payload.conflicts().size() > 20
                || payload.relaxationSuggestions().size() > 20) {
            throw invalid("failure payload is invalid");
        }
        for (PlanningFailedEvent.Conflict conflict : payload.conflicts()) {
            if (conflict == null || !bounded(conflict.code(), 60)
                    || !bounded(conflict.message(), 300)
                    || conflict.affected().isEmpty() || conflict.affected().size() > 30
                    || conflict.affected().stream().anyMatch(value -> !bounded(value, 120))) {
                throw invalid("failure conflict is invalid");
            }
        }
        for (PlanningFailedEvent.Relaxation relaxation : payload.relaxationSuggestions()) {
            if (relaxation == null || !bounded(relaxation.code(), 60)
                    || !bounded(relaxation.message(), 300)) {
                throw invalid("failure relaxation is invalid");
            }
        }
    }

    private boolean bounded(String value, int maxLength) {
        return value != null && !value.isBlank() && value.length() <= maxLength;
    }

    private PlanningEventContractException invalid(String message) {
        return new PlanningEventContractException("Invalid PLANNING_FAILED event: " + message);
    }
}
