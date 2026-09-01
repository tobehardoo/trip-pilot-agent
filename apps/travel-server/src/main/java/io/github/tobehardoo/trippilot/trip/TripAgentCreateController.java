package io.github.tobehardoo.trippilot.trip;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.ZoneId;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import io.github.tobehardoo.trippilot.agentdialog.HttpAgentDialogClient;
import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.place.PlaceSearchDtos.PlaceCandidate;
import io.github.tobehardoo.trippilot.place.PlaceSearchDtos.PlaceSearchRequest;
import io.github.tobehardoo.trippilot.place.PlaceSearchDtos.PlaceSearchResponse;
import io.github.tobehardoo.trippilot.place.PlaceSuggestionService;
import io.github.tobehardoo.trippilot.trip.TripRequests.ConstraintInput;
import io.github.tobehardoo.trippilot.trip.TripRequests.CreateTripRequest;
import io.github.tobehardoo.trippilot.trip.TripRequests.PlaceAnchor;
import io.github.tobehardoo.trippilot.trip.TripRequests.PlaceRefInput;
import io.github.tobehardoo.trippilot.trip.TripRequests.TravelAnchor;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

/**
 * Plan C: agent-driven trip creation.  The web client runs a trip-less
 * dialog under a client-generated sessionId; on "create", the confirmed
 * slots are re-fetched server-side (the dialog service owns their truth —
 * only CONFIRMED values ever reach {@link TripService#create}) and the
 * itinerary is created through the same versioned path as the form.
 *
 * Spoken place names (must-visit, accommodation, arrival/departure) are
 * grounded into structured refs through the owner-scoped search, which also
 * issues the selection tokens the create validator requires.
 */
@RestController
@RequestMapping("/api/agent")
public class TripAgentCreateController {

    private static final ZoneId CHINA_ZONE = ZoneId.of("Asia/Shanghai");

    private final TripService tripService;
    private final HttpAgentDialogClient client;
    private final PlaceSuggestionService placeSearch;

    public TripAgentCreateController(
            TripService tripService,
            HttpAgentDialogClient client,
            PlaceSuggestionService placeSearch
    ) {
        this.tripService = tripService;
        this.client = client;
        this.placeSearch = placeSearch;
    }

    @PostMapping("/dialogue")
    HttpAgentDialogClient.AgentDialogReply dialogue(
            @AuthenticationPrincipal Jwt jwt,
            @Valid @RequestBody CreateDialogRequest request
    ) {
        return client.createDialogue(new HttpAgentDialogClient.AgentCreateDialogCommand(
                request.sessionId(),
                request.message(),
                request.option(),
                Boolean.TRUE.equals(request.reset())
        ));
    }

    @PostMapping("/trips")
    @ResponseStatus(HttpStatus.CREATED)
    TripService.TripResponse createTrip(
            @AuthenticationPrincipal Jwt jwt,
            @Valid @RequestBody AgentTripRequest request
    ) {
        UUID ownerId = userId(jwt);
        HttpAgentDialogClient.AgentConfirmedSlots slots = client.confirmedCreation(request.sessionId());
        Map<String, Object> confirmed = slots.confirmed();
        String destination = text(confirmed.get("destination"));
        String startDate = text(confirmed.get("start_date"));
        String endDate = text(confirmed.get("end_date"));
        if (destination == null || startDate == null || endDate == null) {
            throw new ApiException(
                    HttpStatus.UNPROCESSABLE_ENTITY,
                    "AGENT_TRIP_INCOMPLETE",
                    "对话还没确认目的地和日期，先在助手里完成确认再创建行程。"
            );
        }
        int travelers = number(confirmed.get("travelers"), 2);
        BigDecimal budget = number(confirmed.get("budget"), 0) > 0
                ? BigDecimal.valueOf(number(confirmed.get("budget"), 0))
                : null;
        String pace = text(confirmed.get("pace"));
        if (!"RELAXED".equals(pace) && !"INTENSIVE".equals(pace)) {
            pace = "BALANCED";
        }
        String travelerType = travelers == 1 ? "SOLO" : travelers == 2 ? "COUPLE" : "FRIENDS";
        List<String> preferences = stringList(confirmed.get("preferences"));
        String mobility = text(confirmed.get("mobility"));

        List<String> unresolved = new ArrayList<>();
        List<String> resolvedNames = new ArrayList<>();
        List<PlaceRefInput> mustVisitRefs = new ArrayList<>();
        for (String name : stringList(confirmed.get("must_visit"))) {
            PlaceRefInput ref = resolvePlaceRef(ownerId, destination, name, unresolved);
            if (ref != null) {
                resolvedNames.add(ref.name());
                mustVisitRefs.add(ref);
            }
        }

        PlaceAnchor accommodation = null;
        String accommodationName = text(confirmed.get("accommodation"));
        if (accommodationName != null) {
            PlaceRefInput ref = resolvePlaceRef(ownerId, destination, accommodationName, unresolved);
            if (ref != null) {
                accommodation = new PlaceAnchor(ref.name(), ref);
            }
        }

        TravelAnchor arrival = anchor(confirmed.get("arrival"), startDate, ownerId, destination, unresolved);
        TravelAnchor departure = anchor(confirmed.get("departure"), endDate, ownerId, destination, unresolved);

        if (!unresolved.isEmpty()) {
            throw new ApiException(
                    HttpStatus.UNPROCESSABLE_ENTITY,
                    "AGENT_TRIP_PLACE_UNRESOLVED",
                    "以下地点没有匹配到真实地点：" + String.join("、", unresolved)
                            + "。请换个说法重试，或创建后到详情页手动添加。"
            );
        }

        String title = (destination + " · AI 行程");
        try {
            return tripService.create(ownerId, new CreateTripRequest(
                    title,
                    destination,
                    null,
                    LocalDate.parse(startDate),
                    LocalDate.parse(endDate),
                    null,
                    null,
                    new ConstraintInput(
                            budget,
                            travelers,
                            travelerType,
                            pace,
                            preferences,
                            List.of(),
                            arrival,
                            departure,
                            accommodation,
                            resolvedNames.isEmpty() ? null : resolvedNames,
                            null,
                            mustVisitRefs.isEmpty() ? null : mustVisitRefs,
                            null,
                            null,
                            mobility
                    )
            ));
        } catch (DateTimeParseException exception) {
            throw new ApiException(
                    HttpStatus.UNPROCESSABLE_ENTITY,
                    "AGENT_TRIP_INCOMPLETE",
                    "日期解析失败，请重新确认行程日期。"
            );
        }
    }

    /** Ground one spoken place name into a canonical ref (or collect the miss). */
    private PlaceRefInput resolvePlaceRef(
            UUID ownerId, String city, String name, List<String> unresolved
    ) {
        PlaceSearchResponse search =
                placeSearch.search(ownerId, new PlaceSearchRequest(city, name, 3));
        if (search.candidates().isEmpty()) {
            unresolved.add(name);
            return null;
        }
        return toRef(search.candidates().get(0));
    }

    /** Build a travel anchor from a {place, time} slot onto the given date. */
    private TravelAnchor anchor(
            Object slot, String dateText, UUID ownerId, String destination, List<String> unresolved
    ) {
        if (!(slot instanceof Map<?, ?> raw)) {
            return null;
        }
        String place = raw.get("place") instanceof String placeText && !placeText.isBlank()
                ? placeText : null;
        String timeText = raw.get("time") instanceof String time && !time.isBlank() ? time : null;
        if (place == null || timeText == null) {
            return null;
        }
        PlaceRefInput ref = resolvePlaceRef(ownerId, destination, place, unresolved);
        if (ref == null) {
            return null;
        }
        try {
            var time = LocalDate.parse(dateText).atTime(LocalTime.parse(timeText))
                    .atZone(CHINA_ZONE).toOffsetDateTime();
            return new TravelAnchor(ref.name(), time, ref);
        } catch (DateTimeParseException exception) {
            unresolved.add(place + "（时间无法识别）");
            return null;
        }
    }

    private PlaceRefInput toRef(PlaceCandidate candidate) {
        return new PlaceRefInput(
                candidate.provider(),
                candidate.providerPoiId(),
                candidate.name(),
                candidate.address(),
                candidate.province(),
                candidate.city(),
                candidate.district(),
                BigDecimal.valueOf(candidate.longitude()),
                BigDecimal.valueOf(candidate.latitude()),
                candidate.selectionToken()
        );
    }

    private String text(Object value) {
        return value instanceof String textValue && !textValue.isBlank() ? textValue : null;
    }

    private int number(Object value, int fallback) {
        return value instanceof Number number ? number.intValue() : fallback;
    }

    private List<String> stringList(Object value) {
        return value instanceof List<?> items
                ? items.stream().map(String::valueOf).toList()
                : List.of();
    }

    private UUID userId(Jwt jwt) {
        return UUID.fromString(jwt.getSubject());
    }

    record CreateDialogRequest(
            @NotBlank String sessionId,
            String message,
            HttpAgentDialogClient.CardOption option,
            Boolean reset
    ) {
    }

    record AgentTripRequest(@NotBlank String sessionId) {
    }
}
