package io.github.tobehardoo.trippilot.guide;

import java.util.List;
import java.util.UUID;

import io.github.tobehardoo.trippilot.guide.GuideImportService.GuideImportResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
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
@RequestMapping("/api/trips/{tripId}/guide-imports")
public class GuideImportController {

    private final GuideImportService guideImportService;

    public GuideImportController(GuideImportService guideImportService) {
        this.guideImportService = guideImportService;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    GuideImportResponse create(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId,
            @Valid @RequestBody GuideImportRequest request
    ) {
        return guideImportService.create(userId(jwt), tripId, request);
    }

    @GetMapping
    List<GuideImportResponse> list(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId
    ) {
        return guideImportService.list(userId(jwt), tripId);
    }

    @PutMapping("/{guideImportId}")
    GuideImportResponse setEnabled(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable UUID tripId,
            @PathVariable UUID guideImportId,
            @Valid @RequestBody GuideImportStatusRequest request
    ) {
        return guideImportService.setEnabled(
                userId(jwt), tripId, guideImportId, request.enabled()
        );
    }

    private UUID userId(Jwt jwt) {
        return UUID.fromString(jwt.getSubject());
    }

    private record GuideImportStatusRequest(@NotNull Boolean enabled) {
    }
}
