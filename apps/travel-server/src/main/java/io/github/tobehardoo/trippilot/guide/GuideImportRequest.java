package io.github.tobehardoo.trippilot.guide;

import java.time.LocalDate;

import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public record GuideImportRequest(
        @Size(max = 2048) String sourceUrl,
        @Pattern(
                regexp = "PUBLIC_GUIDE_URL|PASTED_TEXT|TEXT_FILE|"
                        + "XIAOHONGSHU_SHARED_TEXT|CITY_INTELLIGENCE"
        ) String sourceType,
        @Size(max = 300) String title,
        @Size(max = 100_000) String content,
        @Size(max = 60) String city,
        LocalDate startDate,
        LocalDate endDate
) {
    @AssertTrue(message = "provide either a public URL or titled text content")
    public boolean isValidSource() {
        boolean hasUrl = hasText(sourceUrl);
        boolean hasContent = hasText(content);
        boolean hasCity = hasText(city);
        if ((hasUrl ? 1 : 0) + (hasContent ? 1 : 0) + (hasCity ? 1 : 0) != 1) {
            return false;
        }
        String type = normalizedSourceType();
        if (hasUrl) {
            return "PUBLIC_GUIDE_URL".equals(type);
        }
        if (hasCity) {
            return "CITY_INTELLIGENCE".equals(type)
                    && startDate != null
                    && endDate != null
                    && !endDate.isBefore(startDate);
        }
        return !"PUBLIC_GUIDE_URL".equals(type)
                && !"CITY_INTELLIGENCE".equals(type)
                && hasText(title);
    }

    public String normalizedSourceType() {
        return hasText(sourceType) ? sourceType.trim() : "PUBLIC_GUIDE_URL";
    }

    private static boolean hasText(String value) {
        return value != null && !value.isBlank();
    }
}
