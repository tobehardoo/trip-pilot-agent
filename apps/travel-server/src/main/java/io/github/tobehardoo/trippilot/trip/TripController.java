package io.github.tobehardoo.trippilot.trip;

import java.util.List;
import java.util.UUID;

import io.github.tobehardoo.trippilot.trip.TripRequests.CreateTripRequest;
import io.github.tobehardoo.trippilot.trip.TripRequests.UpdateConstraintRequest;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/trips")
public class TripController {

    private final TripService tripService;

    public TripController(TripService tripService) {
        this.tripService = tripService;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    TripService.TripResponse create(@AuthenticationPrincipal Jwt jwt,
                                    @Valid @RequestBody CreateTripRequest request) {
        return tripService.create(userId(jwt), request);
    }

    @GetMapping
    List<TripService.TripResponse> list(@AuthenticationPrincipal Jwt jwt) {
        return tripService.list(userId(jwt));
    }

    @GetMapping("/{tripId}")
    TripService.TripResponse get(@AuthenticationPrincipal Jwt jwt, @PathVariable UUID tripId) {
        return tripService.get(userId(jwt), tripId);
    }

    @PutMapping("/{tripId}/constraints")
    TripService.TripResponse updateConstraints(@AuthenticationPrincipal Jwt jwt, @PathVariable UUID tripId,
                                               @Valid @RequestBody UpdateConstraintRequest request) {
        return tripService.updateConstraints(userId(jwt), tripId, request);
    }

    private UUID userId(Jwt jwt) {
        return UUID.fromString(jwt.getSubject());
    }
}
