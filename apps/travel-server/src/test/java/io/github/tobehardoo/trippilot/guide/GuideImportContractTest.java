package io.github.tobehardoo.trippilot.guide;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;

import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;

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
                java.time.LocalDate.of(2026, 11, 20), java.time.LocalDate.of(2026, 11, 21)
        );
        assertThat(request.normalizedSourceType()).isEqualTo("CITY_INTELLIGENCE");
    }
}
