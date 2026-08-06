package io.github.tobehardoo.trippilot.places;

import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Restricted structured place search. Authenticated so the AMap key is never
 * exposed to anonymous callers; the search is scoped to the destination city
 * passed by the trip form.
 */
@RestController
@RequestMapping("/api/places")
public class PlaceSearchController {

    private final PlaceSearchService placeSearchService;

    public PlaceSearchController(PlaceSearchService placeSearchService) {
        this.placeSearchService = placeSearchService;
    }

    @GetMapping("/search")
    PlaceSearchResponse search(
            @AuthenticationPrincipal Jwt jwt,
            @RequestParam String keyword,
            @RequestParam String city
    ) {
        return placeSearchService.search(keyword, city);
    }
}
