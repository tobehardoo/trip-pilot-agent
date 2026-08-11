package io.github.tobehardoo.trippilot.itinerary;

import java.util.Map;
import java.util.UUID;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class FeasibilityEntityRefMapperTest {

    private static final UUID TEMP_ACTIVITY =
            UUID.fromString("10000000-0000-4000-8000-000000000031");
    private static final UUID PERSISTED_ACTIVITY =
            UUID.fromString("20000000-0000-4000-8000-000000000031");
    private static final UUID TEMP_TRANSIT =
            UUID.fromString("10000000-0000-4000-8000-000000000041");
    private static final UUID PERSISTED_TRANSIT =
            UUID.fromString("20000000-0000-4000-8000-000000000041");

    private final FeasibilityEntityRefMapper mapper = new FeasibilityEntityRefMapper();

    @Test
    void mapsTemporaryActivityAndTransitReferencesInRuleResults() {
        String report = """
                {
                  "ruleResults": [
                    {
                      "ruleId": "DUPLICATE_POI",
                      "affectedEntityRefs": [
                        "%s",
                        "%s",
                        "POI-123",
                        "hotel-456"
                      ]
                    }
                  ],
                  "repairAttempts": []
                }
                """.formatted(TEMP_ACTIVITY, TEMP_TRANSIT);

        String remapped = mapper.remap(
                report,
                Map.of(TEMP_ACTIVITY, PERSISTED_ACTIVITY),
                Map.of(TEMP_TRANSIT, PERSISTED_TRANSIT));

        assertThat(remapped)
                .contains(PERSISTED_ACTIVITY.toString())
                .contains(PERSISTED_TRANSIT.toString())
                .contains("POI-123")
                .contains("hotel-456")
                .doesNotContain(TEMP_ACTIVITY.toString())
                .doesNotContain(TEMP_TRANSIT.toString());
    }

    @Test
    void mapsRepairAttemptEntityRefsToo() {
        String report = """
                {
                  "ruleResults": [],
                  "repairAttempts": [
                    {
                      "attemptIndex": 1,
                      "affectedEntityRefs": ["%s"]
                    }
                  ]
                }
                """.formatted(TEMP_ACTIVITY);

        String remapped = mapper.remap(
                report,
                Map.of(TEMP_ACTIVITY, PERSISTED_ACTIVITY),
                Map.of());

        assertThat(remapped)
                .contains(PERSISTED_ACTIVITY.toString())
                .doesNotContain(TEMP_ACTIVITY.toString());
    }

    @Test
    void keepsNonUuidTextReferencesUnchanged() {
        String report = """
                {
                  "ruleResults": [
                    {
                      "ruleId": "OPENING_HOURS",
                      "affectedEntityRefs": ["POI-123", "hotel-456", "area-estimated"]
                    }
                  ],
                  "repairAttempts": []
                }
                """;

        String remapped = mapper.remap(report, Map.of(), Map.of());

        assertThat(remapped)
                .contains("POI-123")
                .contains("hotel-456")
                .contains("area-estimated");
    }

    @Test
    void keepsUnknownUuidReferencesUnchangedWhenZeroMatches() {
        String unknown = UUID.randomUUID().toString();
        String report = """
                {
                  "ruleResults": [
                    {"ruleId": "X", "affectedEntityRefs": ["%s"]}
                  ],
                  "repairAttempts": []
                }
                """.formatted(unknown);

        String remapped = mapper.remap(report, Map.of(), Map.of());

        assertThat(remapped).contains(unknown);
    }

    @Test
    void uuidLookingPoiReferenceIsMappedWhenItCollidesWithATemporaryId() {
        // Characterization of the current contract: affectedEntityRefs is an
        // untyped string list.  A provider POI id that is itself a UUID and
        // happens to equal a temporary activity id is indistinguishable and
        // gets mapped.  This is a known residual risk (B6J.1 F5), not a fix;
        // typed entity refs would be needed to disambiguate.
        String report = """
                {
                  "ruleResults": [
                    {"ruleId": "X", "affectedEntityRefs": ["%s"]}
                  ],
                  "repairAttempts": []
                }
                """.formatted(TEMP_ACTIVITY);

        String remapped = mapper.remap(
                report, Map.of(TEMP_ACTIVITY, PERSISTED_ACTIVITY), Map.of());

        assertThat(remapped).contains(PERSISTED_ACTIVITY.toString());
    }

    @Test
    void failsClosedWhenAReferenceIsAmbiguousAcrossActivityAndTransit() {
        String report = """
                {
                  "ruleResults": [
                    {"ruleId": "X", "affectedEntityRefs": ["%s"]}
                  ],
                  "repairAttempts": []
                }
                """.formatted(TEMP_ACTIVITY);

        assertThatThrownBy(() -> mapper.remap(
                report,
                Map.of(TEMP_ACTIVITY, PERSISTED_ACTIVITY),
                Map.of(TEMP_ACTIVITY, PERSISTED_TRANSIT)))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("ambiguous");
    }
}
