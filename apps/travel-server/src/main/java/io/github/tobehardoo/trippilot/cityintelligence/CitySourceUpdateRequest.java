package io.github.tobehardoo.trippilot.cityintelligence;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

public record CitySourceUpdateRequest(
        @NotNull Boolean enabled,
        @NotBlank String reviewStatus,
        @Size(max = 1000) String reviewNote,
        @Min(0) @Max(Integer.MAX_VALUE) int expectedVersion
) {
}
