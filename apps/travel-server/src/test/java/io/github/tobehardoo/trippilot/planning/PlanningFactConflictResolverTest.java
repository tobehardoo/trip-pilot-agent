package io.github.tobehardoo.trippilot.planning;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.guide.TrustedGuideRecords.TrustedFactRecord;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class PlanningFactConflictResolverTest {

    private static final Instant NOW = Instant.parse("2026-07-26T08:00:00Z");

    @Test
    void reviewedOfficialFactWinsAcrossImportsAndKeepsConflictEvidence() {
        TrustedFactRecord community = fact(
                "community",
                "{\"required\":false,\"poiName\":\"故宫博物院\"}",
                "COMMUNITY",
                false,
                NOW.plusSeconds(60)
        );
        TrustedFactRecord official = fact(
                "official",
                "{\"required\":true,\"poiName\":\"故宫博物院\"}",
                "OFFICIAL_ATTRACTION",
                true,
                NOW
        );

        PlanningFactConflictResolver.Resolution result =
                new PlanningFactConflictResolver(new ObjectMapper())
                        .resolve(List.of(community, official), NOW);

        assertThat(result.selectedFacts())
                .extracting(TrustedFactRecord::factId)
                .containsExactly("official");
        assertThat(result.conflicts()).singleElement().satisfies(conflict -> {
            assertThat(conflict.selectedFactId()).isEqualTo("official");
            assertThat(conflict.conflictFactIds()).containsExactly("community");
            assertThat(conflict.downgradedFactIds()).containsExactly("community");
            assertThat(conflict.reason()).contains("reviewed official");
            assertThat(conflict.needsManualReview()).isFalse();
        });
    }

    @Test
    void differentPoisAndEffectiveDatesAreNotMerged() {
        TrustedFactRecord palaceToday = fact(
                "palace-today",
                "{\"closed\":true,\"poiName\":\"故宫博物院\"}",
                "OFFICIAL_ATTRACTION",
                true,
                NOW
        );
        TrustedFactRecord palaceTomorrow = new TrustedFactRecord(
                palaceToday.guideImportId(),
                "palace-tomorrow",
                palaceToday.documentId(),
                palaceToday.city(),
                palaceToday.category(),
                palaceToday.statement(),
                palaceToday.normalizedValueJson(),
                palaceToday.evidence(),
                palaceToday.evidenceStart(),
                palaceToday.evidenceEnd(),
                palaceToday.confidence(),
                LocalDate.of(2026, 8, 2),
                palaceToday.checkedAt(),
                palaceToday.expiresAt(),
                palaceToday.sourceType(),
                palaceToday.sourceName(),
                palaceToday.sourceUrl(),
                palaceToday.reliabilityLevel(),
                palaceToday.sourceReviewed(),
                palaceToday.hardConstraintEligible()
        );
        TrustedFactRecord temple = fact(
                "temple",
                "{\"closed\":true,\"poiName\":\"天坛\"}",
                "OFFICIAL_ATTRACTION",
                true,
                NOW
        );

        PlanningFactConflictResolver.Resolution result =
                new PlanningFactConflictResolver(new ObjectMapper())
                        .resolve(List.of(palaceToday, palaceTomorrow, temple), NOW);

        assertThat(result.selectedFacts()).hasSize(3);
        assertThat(result.conflicts()).isEmpty();
    }

    private TrustedFactRecord fact(
            String id,
            String value,
            String reliability,
            boolean reviewed,
            Instant checkedAt
    ) {
        return new TrustedFactRecord(
                UUID.randomUUID(),
                id,
                "doc_" + "a".repeat(32),
                "北京",
                id.startsWith("community") || id.startsWith("official")
                        ? "RESERVATION_REQUIREMENT"
                        : "TEMPORARY_CLOSURE",
                "故宫博物院参观须提前预约",
                value,
                "故宫博物院参观须提前预约",
                0,
                13,
                0.9,
                LocalDate.of(2026, 8, 1),
                checkedAt,
                checkedAt.plusSeconds(86_400),
                reviewed ? "OFFICIAL_ATTRACTION" : "PASTED_TEXT",
                reviewed ? "故宫博物院" : "用户攻略",
                reviewed ? "https://www.dpm.org.cn/Visit.html" : null,
                reliability,
                reviewed,
                reviewed
        );
    }
}
