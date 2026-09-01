package io.github.tobehardoo.trippilot.infrastructure.mq;

import io.github.tobehardoo.trippilot.common.EventContractException;
import java.io.IOException;
import java.util.Set;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectReader;
import org.springframework.stereotype.Component;

@Component
public class CityIntelligenceRefreshCommandParser {

    private static final Set<String> ALLOWED_CATEGORIES = Set.of(
            "CURRENT_WEATHER",
            "DAILY_FORECAST",
            "ATTRACTION_DETAILS",
            "OPENING_HOURS",
            "TICKET_PRICE",
            "RESERVATION_REQUIREMENT",
            "TEMPORARY_CLOSURE"
    );

    private final ObjectReader reader;

    public CityIntelligenceRefreshCommandParser(ObjectMapper objectMapper) {
        reader = objectMapper.readerFor(CityIntelligenceRefreshCommand.class)
                .with(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);
    }

    public CityIntelligenceRefreshCommand parse(byte[] body) {
        try {
            CityIntelligenceRefreshCommand command = reader.readValue(body);
            validate(command);
            return command;
        } catch (IOException exception) {
            throw new EventContractException(
                    "Invalid CITY_INTELLIGENCE_REFRESH_REQUESTED command",
                    exception
            );
        }
    }

    private void validate(CityIntelligenceRefreshCommand command) {
        if (command == null
                || !"CITY_INTELLIGENCE_REFRESH_REQUESTED".equals(command.eventType())
                || command.schemaVersion() != 1
                || command.eventId() == null
                || command.refreshId() == null
                || command.tripId() == null
                || command.occurredAt() == null
                || command.payload() == null) {
            throw invalid("command envelope is incomplete");
        }
        CityIntelligenceRefreshCommand.Payload payload = command.payload();
        if (!bounded(payload.city(), 120)
                || payload.cityCode() == null
                || !payload.cityCode().matches("[A-Z0-9-]{2,32}")
                || payload.startDate() == null
                || payload.endDate() == null
                || payload.endDate().isBefore(payload.startDate())
                || payload.sourceIds().size() > 20
                || payload.sourceIds().stream().anyMatch(id -> id == null)
                || payload.requiredCategories().isEmpty()
                || payload.requiredCategories().size() > 20
                || !ALLOWED_CATEGORIES.containsAll(payload.requiredCategories())
                || payload.idempotencyKey() == null) {
            throw invalid("command payload is invalid");
        }
    }

    private boolean bounded(String value, int maximumLength) {
        return value != null && !value.isBlank() && value.length() <= maximumLength;
    }

    private EventContractException invalid(String message) {
        return new EventContractException(
                "Invalid CITY_INTELLIGENCE_REFRESH_REQUESTED command: " + message
        );
    }
}
