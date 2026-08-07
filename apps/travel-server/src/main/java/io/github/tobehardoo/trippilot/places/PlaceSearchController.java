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
    private final PlaceSuggestService placeSuggestService;

    public PlaceSearchController(PlaceSearchService placeSearchService, PlaceSuggestService placeSuggestService) {
        this.placeSearchService = placeSearchService;
        this.placeSuggestService = placeSuggestService;
    }

    @GetMapping("/search")
    PlaceSearchResponse search(
            @AuthenticationPrincipal Jwt jwt,
            @RequestParam String keyword,
            @RequestParam String city
    ) {
        return placeSearchService.search(keyword, city);
    }

    /** 混合联想：真实 POI + 行政区 REGION，用于 ARRIVAL/DEPARTURE/HOTEL 字段。 */
    @GetMapping("/suggest")
    PlaceSuggestResponse suggest(
            @AuthenticationPrincipal Jwt jwt,
            @RequestParam String keyword,
            @RequestParam String cityCode,
            @RequestParam(defaultValue = "ARRIVAL") String scene
    ) {
        return placeSuggestService.suggest(keyword, cityCode, scene);
    }
}
