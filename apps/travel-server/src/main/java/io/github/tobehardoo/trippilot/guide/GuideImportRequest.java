package io.github.tobehardoo.trippilot.guide;

import java.time.LocalDate;
import java.util.List;

import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public record GuideImportRequest(
        @Size(max = 2048) String sourceUrl,
        @Pattern(
                regexp = "PUBLIC_GUIDE_URL|PASTED_TEXT|TEXT_FILE|"
                        + "XIAOHONGSHU_SHARED_TEXT|IMAGE_OCR|CITY_INTELLIGENCE"
        ) String sourceType,
        @Size(max = 300) String title,
        @Size(max = 100_000) String content,
        @Size(max = 60) String city,
        LocalDate startDate,
        LocalDate endDate,
        @Size(max = 5, message = "at most five images can be imported at once")
        List<GuideImagePayload> images
) {
    @AssertTrue(message = "provide a public URL, titled text content, or image payloads")
    public boolean isValidSource() {
        boolean hasUrl = hasText(sourceUrl);
        boolean hasContent = hasText(content);
        boolean hasCity = hasText(city);
        boolean hasImages = images != null && !images.isEmpty();
        int providedChannels =
                (hasUrl ? 1 : 0)
                        + (hasContent ? 1 : 0)
                        + (hasCity ? 1 : 0)
                        + (hasImages ? 1 : 0);
        if (providedChannels != 1) {
            return false;
        }
        String type = normalizedSourceType();
        if (hasUrl) {
            return "PUBLIC_GUIDE_URL".equals(type);
        }
        if (hasImages) {
            return "IMAGE_OCR".equals(type)
                    && !hasText(title)
                    && startDate == null
                    && endDate == null;
        }
        if (hasCity) {
            return "CITY_INTELLIGENCE".equals(type)
                    && startDate != null
                    && endDate != null
                    && !endDate.isBefore(startDate);
        }
        return !"PUBLIC_GUIDE_URL".equals(type)
                && !"CITY_INTELLIGENCE".equals(type)
                && !"IMAGE_OCR".equals(type)
                && hasText(title);
    }

    public String normalizedSourceType() {
        return hasText(sourceType) ? sourceType.trim() : "PUBLIC_GUIDE_URL";
    }

    private static boolean hasText(String value) {
        return value != null && !value.isBlank();
    }
}
