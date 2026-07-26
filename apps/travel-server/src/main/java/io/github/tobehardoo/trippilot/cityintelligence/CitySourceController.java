package io.github.tobehardoo.trippilot.cityintelligence;

import java.util.List;
import java.util.UUID;

import io.github.tobehardoo.trippilot.cityintelligence.CitySourceService.CitySourceResponse;
import jakarta.validation.Valid;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/city-sources")
public class CitySourceController {

    private final CitySourceService citySourceService;

    public CitySourceController(CitySourceService citySourceService) {
        this.citySourceService = citySourceService;
    }

    @GetMapping
    List<CitySourceResponse> list(
            @RequestParam(required = false) String cityCode,
            @RequestParam(required = false) Boolean enabled,
            @RequestParam(required = false) String reviewStatus
    ) {
        return citySourceService.list(cityCode, enabled, reviewStatus);
    }

    @PutMapping("/{sourceId}")
    CitySourceResponse update(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID sourceId,
            @Valid @RequestBody CitySourceUpdateRequest request
    ) {
        return citySourceService.update(UUID.fromString(jwt.getSubject()), sourceId, request);
    }
}
