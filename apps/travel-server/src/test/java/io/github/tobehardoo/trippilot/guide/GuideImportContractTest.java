package io.github.tobehardoo.trippilot.guide;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;

import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.List;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.ClassPathResource;

/**
 * B14_FIX R1 RED — the REAL agent CITY_INTELLIGENCE response (captured from the
 * isolated stack) must satisfy the Java contract.  The response is parsed by
 * the real Jackson path (the same object mapping HttpGuideIntelligenceClient
 * uses) and validated by GuideImportService's real validation method.  The
 * current implementation rejects it (502 GUIDE_SERVICE_INVALID_RESPONSE), so
 * these tests are RED until the producer output satisfies the contract.
 */
class GuideImportContractTest {

    private static String fixture() throws Exception {
        return new String(
                new ClassPathResource("fixtures/guide-city-intelligence-real-response.json")
                        .getInputStream().readAllBytes(),
                StandardCharsets.UTF_8
        );
    }

    private static void validateFetchedGuide(GuideIntelligenceClient.FetchedGuide guide)
            throws Exception {
        Method method = GuideImportService.class.getDeclaredMethod(
                "validateFetchedGuide", GuideIntelligenceClient.FetchedGuide.class
        );
        method.setAccessible(true);
        method.invoke(new GuideImportService(null, null, null, null, null), guide);
    }

    @Test
    void realResponsePassesTheJavaContractValidation() throws Exception {
        GuideIntelligenceClient.FetchedGuide guide =
                new ObjectMapper().registerModule(new JavaTimeModule()).readValue(fixture(), GuideIntelligenceClient.FetchedGuide.class);
        // RED: the real response currently fails validateFetchedGuide (ApiException);
        // GREEN: the validation passes without throwing.
        assertThatCode(() -> validateFetchedGuide(guide)).doesNotThrowAnyException();
    }

    @Test
    void responseHasNoMergeDecisionReferencesOutsideTheTrustedFactSet() throws Exception {
        GuideIntelligenceClient.FetchedGuide guide =
                new ObjectMapper().registerModule(new JavaTimeModule()).readValue(fixture(), GuideIntelligenceClient.FetchedGuide.class);
        java.util.Set<String> trustedIds = guide.trustedFacts().stream()
                .map(GuideIntelligenceClient.FetchedTrustedFact::factId)
                .collect(java.util.stream.Collectors.toSet());
        boolean dangling = guide.factMergeDecisions().stream().anyMatch(decision ->
                !trustedIds.contains(decision.selectedFactId())
                        || !trustedIds.containsAll(decision.conflictFactIds())
                        || !trustedIds.containsAll(decision.downgradedFactIds()));
        // RED: the real response currently carries dangling decision references.
        assertThat(dangling).isFalse();
    }

    @Test
    void guideImportRequestAcceptsCityIntelligenceShape() {
        GuideImportRequest request = new GuideImportRequest(
                null, "CITY_INTELLIGENCE", null, null, "广州",
                java.time.LocalDate.of(2026, 11, 20), java.time.LocalDate.of(2026, 11, 21),
                null
        );
        assertThat(request.normalizedSourceType()).isEqualTo("CITY_INTELLIGENCE");
    }

    @Test
    void guideImportRequestAcceptsImageOcrShapeWithBase64PayloadsOnly() {
        GuideImportRequest request = GuideImportRequestContract.imageOcrRequest();

        assertThat(request.normalizedSourceType()).isEqualTo("IMAGE_OCR");
        assertThat(request.isValidSource()).isTrue();
    }

    @Test
    void imageOcrRequestsRejectMixedChannelsAndMissingImages() {
        GuideImportRequest withoutImages = new GuideImportRequest(
                null, "IMAGE_OCR", null, null, null, null, null, List.of()
        );
        GuideImportRequest mixedWithTitle = new GuideImportRequest(
                null,
                "IMAGE_OCR",
                "标题",
                null,
                null,
                null,
                null,
                GuideImportRequestContract.imageOcrRequest().images()
        );
        GuideImportRequest textWithImages = new GuideImportRequest(
                null,
                "PASTED_TEXT",
                "标题",
                "正文",
                null,
                null,
                null,
                GuideImportRequestContract.imageOcrRequest().images()
        );

        assertThat(withoutImages.isValidSource()).isFalse();
        assertThat(mixedWithTitle.isValidSource()).isFalse();
        assertThat(textWithImages.isValidSource()).isFalse();
    }

    @Test
    void legacyTextAndUrlRequestsRemainValidWithoutImages() {
        assertThat(new GuideImportRequest(
                "https://example.com/guide", "PUBLIC_GUIDE_URL",
                null, null, null, null, null, null
        ).isValidSource()).isTrue();
        assertThat(new GuideImportRequest(
                null, "XIAOHONGSHU_SHARED_TEXT", "标题", "正文",
                null, null, null, null
        ).isValidSource()).isTrue();
    }

    @Test
    void fetchedGuideValidationAcceptsImageOcrSourceType() throws Exception {
        Instant fetchedAt = Instant.parse("2026-08-01T08:00:00Z");
        GuideIntelligenceClient.FetchedGuide guide = new GuideIntelligenceClient.FetchedGuide(
                "IMAGE_OCR",
                "https://user-content.trippilot.invalid/image-ocr/test",
                "https://user-content.trippilot.invalid/image-ocr/test",
                "用户图片截图",
                "图片攻略",
                "陈家祠地址：中山七路。",
                "a".repeat(64),
                fetchedAt,
                List.of()
        );

        assertThatCode(() -> validateFetchedGuide(guide)).doesNotThrowAnyException();
    }
}
