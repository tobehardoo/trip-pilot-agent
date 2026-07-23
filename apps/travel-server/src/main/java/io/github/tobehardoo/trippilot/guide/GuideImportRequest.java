package io.github.tobehardoo.trippilot.guide;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public record GuideImportRequest(
        @NotBlank @Size(max = 2048) String sourceUrl
) {
}
