package io.github.tobehardoo.trippilot.itinerary;

import java.util.Map;
import java.util.UUID;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * B6J.2 R1: v4 typed entity ref remapping dispatched by validatorVersion.
 */
class FeasibilityEntityRefMapperV4Test {

    private static final UUID TEMP_ACTIVITY =
            UUID.fromString("10000000-0000-4000-8000-000000000031");
    private static final UUID PERSISTED_ACTIVITY =
            UUID.fromString("20000000-0000-4000-8000-000000000031");
    private static final UUID TEMP_TRANSIT =
            UUID.fromString("10000000-0000-4000-8000-000000000041");
    private static final UUID PERSISTED_TRANSIT =
            UUID.fromString("20000000-0000-4000-8000-000000000041");

    private final FeasibilityEntityRefMapper mapper = new FeasibilityEntityRefMapper();

    private String report(String validatorVersion, String refsJson) {
        return """
                {
                  "schemaVersion": 1,
                  "validatorVersion": "%s",
                  "ruleResults": [
                    {"ruleId": "X", "affectedEntityRefs": %s}
                  ],
                  "repairAttempts": []
                }
                """.formatted(validatorVersion, refsJson);
    }

    @Test
    void v4ActivityRefIsStrictlyRemapped() {
        String input = report("hard-validator-v4",
                "[\"activity:" + TEMP_ACTIVITY + "\"]");
        String out = mapper.remap(
                input,
                Map.of(TEMP_ACTIVITY, PERSISTED_ACTIVITY),
                Map.of());
        assertThat(out).contains("activity:" + PERSISTED_ACTIVITY);
        assertThat(out).doesNotContain(TEMP_ACTIVITY.toString());
    }

    @Test
    void v4TransitRefIsStrictlyRemapped() {
        String input = report("hard-validator-v4",
                "[\"transit:" + TEMP_TRANSIT + "\"]");
        String out = mapper.remap(
                input, Map.of(), Map.of(TEMP_TRANSIT, PERSISTED_TRANSIT));
        assertThat(out).contains("transit:" + PERSISTED_TRANSIT);
    }

    @Test
    void v4PoiUuidCollisionIsPreserved() {
        // F5 core: a poi: ref whose value equals a temp activity UUID must
        // NOT be remapped.
        String input = report("hard-validator-v4",
                "[\"poi:" + TEMP_ACTIVITY + "\"]");
        String out = mapper.remap(
                input, Map.of(TEMP_ACTIVITY, PERSISTED_ACTIVITY), Map.of());
        assertThat(out).contains("poi:" + TEMP_ACTIVITY);
        assertThat(out).doesNotContain(PERSISTED_ACTIVITY.toString());
    }

    @Test
    void v4TextRefIsPreserved() {
        String input = report("hard-validator-v4",
                "[\"text:some place\"]");
        String out = mapper.remap(input, Map.of(), Map.of());
        assertThat(out).contains("text:some place");
    }

    @Test
    void v4ActivityWithoutUniqueMappingFailsClosed() {
        String input = report("hard-validator-v4",
                "[\"activity:" + TEMP_ACTIVITY + "\"]");
        assertThatThrownBy(() -> mapper.remap(input, Map.of(), Map.of()))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("activity");
    }

    @Test
    void v4BareUuidFailsClosed() {
        String input = report("hard-validator-v4", "[\"" + TEMP_ACTIVITY + "\"]");
        assertThatThrownBy(() -> mapper.remap(input, Map.of(), Map.of()))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    void v4UnknownKindFailsClosed() {
        String input = report("hard-validator-v4", "[\"unknown:x\"]");
        assertThatThrownBy(() -> mapper.remap(input, Map.of(), Map.of()))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    void unknownValidatorVersionFailsClosed() {
        String input = report("hard-validator-unknown", "[\"poi:POI-1\"]");
        assertThatThrownBy(() -> mapper.remap(input, Map.of(), Map.of()))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    void v3LegacyHeuristicIsPreserved() {
        String input = report("hard-validator-v3", "[\"" + TEMP_ACTIVITY + "\"]");
        String out = mapper.remap(
                input, Map.of(TEMP_ACTIVITY, PERSISTED_ACTIVITY), Map.of());
        assertThat(out).contains(PERSISTED_ACTIVITY.toString());
    }

    @Test
    void v4RepairAttemptRefsAreRemapped() {
        String input = """
                {
                  "schemaVersion": 1,
                  "validatorVersion": "hard-validator-v4",
                  "ruleResults": [],
                  "repairAttempts": [
                    {"attemptIndex": 1, "affectedEntityRefs": ["activity:%s"]}
                  ]
                }
                """.formatted(TEMP_ACTIVITY);
        String out = mapper.remap(
                input, Map.of(TEMP_ACTIVITY, PERSISTED_ACTIVITY), Map.of());
        assertThat(out).contains("activity:" + PERSISTED_ACTIVITY);
    }

    @Test
    void v5RepairAttemptRefsUseTheSameTypedRemapping() {
        String input = """
                {
                  "schemaVersion": 1,
                  "validatorVersion": "hard-validator-v5",
                  "ruleResults": [],
                  "repairAttempts": [
                    {"attemptIndex": 1, "affectedEntityRefs": ["activity:%s"]}
                  ]
                }
                """.formatted(TEMP_ACTIVITY);

        String out = mapper.remap(
                input, Map.of(TEMP_ACTIVITY, PERSISTED_ACTIVITY), Map.of());

        assertThat(out).contains("activity:" + PERSISTED_ACTIVITY);
    }
}
