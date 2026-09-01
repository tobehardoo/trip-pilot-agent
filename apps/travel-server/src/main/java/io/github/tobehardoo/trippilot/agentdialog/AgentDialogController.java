package io.github.tobehardoo.trippilot.agentdialog;

import java.util.UUID;

import io.github.tobehardoo.trippilot.trip.TripService;
import jakarta.validation.Valid;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Chat entry for the agent dialog (Plan B v0.1).  Ownership is enforced via
 * {@link TripService#get}; the reply is a pure pass-through of the
 * agent-service response.
 */
@RestController
@RequestMapping("/api/trips/{tripId}/agent-dialogue")
public class AgentDialogController {

    private final TripService tripService;
    private final HttpAgentDialogClient client;

    public AgentDialogController(TripService tripService, HttpAgentDialogClient client) {
        this.tripService = tripService;
        this.client = client;
    }

    @PostMapping
    HttpAgentDialogClient.AgentDialogReply dialogue(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId,
            @Valid @RequestBody AgentDialogRequest request
    ) {
        TripService.TripResponse trip = tripService.get(userId(jwt), tripId);
        return client.dialogue(new HttpAgentDialogClient.AgentDialogCommand(
                tripId.toString(),
                request.message(),
                request.option(),
                Boolean.TRUE.equals(request.reset()),
                new HttpAgentDialogClient.TripContext(
                        trip.destination(),
                        String.valueOf(trip.startDate()),
                        String.valueOf(trip.endDate())
                )
        ));
    }

    private UUID userId(Jwt jwt) {
        return UUID.fromString(jwt.getSubject());
    }

    record AgentDialogRequest(String message, HttpAgentDialogClient.CardOption option, Boolean reset) {
    }
}
