package io.github.tobehardoo.trippilot.place;

import java.util.UUID;

import io.github.tobehardoo.trippilot.place.PlaceSearchDtos.PlaceSearchRequest;
import io.github.tobehardoo.trippilot.place.PlaceSearchDtos.PlaceSearchResponse;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Owner-authenticated place search proxy (B13-D).
 *
 * The browser never contacts a map provider: this endpoint forwards the
 * search to the agent service behind the internal token and returns
 * candidate places with explicit demo/estimated flags.  B13_FIX R5: each
 * candidate additionally carries an owner-scoped selection token.
 */
@RestController
@RequestMapping("/api/trips")
public class PlaceSuggestionController {

    private final PlaceSuggestionService placeSuggestionService;

    public PlaceSuggestionController(PlaceSuggestionService placeSuggestionService) {
        this.placeSuggestionService = placeSuggestionService;
    }

    @PostMapping("/places/search")
    PlaceSearchResponse search(
            @AuthenticationPrincipal Jwt jwt,
            @RequestBody PlaceSearchRequest request
    ) {
        return placeSuggestionService.search(UUID.fromString(jwt.getSubject()), request);
    }
}
