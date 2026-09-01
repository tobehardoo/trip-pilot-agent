package io.github.tobehardoo.trippilot.feasibility;

import java.util.UUID;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * B6J.2 R1: typed entity reference codec shared with Python.
 *
 * Grammar: activity:/transit: must be canonical lowercase UUIDs; poi:/text:
 * values may contain colons but must be non-blank; whole ref ≤200 chars;
 * control chars forbidden; unknown kinds / bare UUIDs / unprefixed strings
 * fail closed.
 */
class FeasibilityEntityReferenceCodecTest {

    private static final UUID ACTIVITY_ID =
            UUID.fromString("10000000-0000-4000-8000-000000000031");
    private static final UUID TRANSIT_ID =
            UUID.fromString("10000000-0000-4000-8000-000000000041");

    @Test
    void encodesAndDecodesActivityRef() {
        String ref = FeasibilityEntityReferenceCodec.encodeActivityRef(ACTIVITY_ID);
        assertThat(ref).isEqualTo("activity:10000000-0000-4000-8000-000000000031");
        FeasibilityEntityReferenceCodec.ParsedRef parsed =
                FeasibilityEntityReferenceCodec.parse(ref);
        assertThat(parsed.kind()).isEqualTo(FeasibilityEntityReferenceCodec.Kind.ACTIVITY);
        assertThat(parsed.value()).isEqualTo(ACTIVITY_ID.toString());
    }

    @Test
    void encodesAndDecodesTransitRef() {
        String ref = FeasibilityEntityReferenceCodec.encodeTransitRef(TRANSIT_ID);
        assertThat(ref).isEqualTo("transit:10000000-0000-4000-8000-000000000041");
        FeasibilityEntityReferenceCodec.ParsedRef parsed =
                FeasibilityEntityReferenceCodec.parse(ref);
        assertThat(parsed.kind()).isEqualTo(FeasibilityEntityReferenceCodec.Kind.TRANSIT);
    }

    @Test
    void poiValueMayContainColons() {
        String ref = FeasibilityEntityReferenceCodec.encodePoiRef("a:b:c");
        assertThat(ref).isEqualTo("poi:a:b:c");
        FeasibilityEntityReferenceCodec.ParsedRef parsed =
                FeasibilityEntityReferenceCodec.parse(ref);
        assertThat(parsed.kind()).isEqualTo(FeasibilityEntityReferenceCodec.Kind.POI);
        assertThat(parsed.value()).isEqualTo("a:b:c");
    }

    @Test
    void uuidLookingPoiStaysPoi() {
        String poi = ACTIVITY_ID.toString();
        String ref = FeasibilityEntityReferenceCodec.encodePoiRef(poi);
        assertThat(ref).isEqualTo("poi:" + poi);
        FeasibilityEntityReferenceCodec.ParsedRef parsed =
                FeasibilityEntityReferenceCodec.parse(ref);
        assertThat(parsed.kind()).isEqualTo(FeasibilityEntityReferenceCodec.Kind.POI);
        assertThat(parsed.value()).isEqualTo(poi);
    }

    @Test
    void encodesTextRef() {
        String ref = FeasibilityEntityReferenceCodec.encodeTextRef("广州塔");
        assertThat(ref).isEqualTo("text:广州塔");
        assertThat(FeasibilityEntityReferenceCodec.parse(ref).kind())
                .isEqualTo(FeasibilityEntityReferenceCodec.Kind.TEXT);
    }

    @Test
    void rejectsInvalidRefs() {
        for (String bad : new String[]{
                "activity", "activity:", "transit:", "poi:", "text:",
                "unknown:x", "unknown:", "10000000-0000-4000-8000-000000000031",
                "no-prefix-value", "ACTIVITY:x", "activity:ABC",
                "activity:10000000-0000-4000-8000-00000000003G",
                "activity:\n10000000-0000-4000-8000-000000000031",
        }) {
            assertThat(FeasibilityEntityReferenceCodec.validate(bad))
                    .as("expected invalid: %s", bad)
                    .isFalse();
            assertThatThrownBy(() -> FeasibilityEntityReferenceCodec.parse(bad))
                    .isInstanceOf(IllegalArgumentException.class);
        }
    }

    @Test
    void rejectsUppercaseUuidForActivity() {
        assertThat(FeasibilityEntityReferenceCodec.validate(
                "activity:10000000-0000-4000-8000-AABBCCDDEEFF")).isFalse();
    }

    @Test
    void rejectsRefLongerThan200Chars() {
        String ref = FeasibilityEntityReferenceCodec.encodePoiRef("x".repeat(200));
        assertThat(ref.length()).isGreaterThan(200);
        assertThat(FeasibilityEntityReferenceCodec.validate(ref)).isFalse();
    }

    @Test
    void rejectsControlCharacters() {
        assertThat(FeasibilityEntityReferenceCodec.validate("poi:has\tcontrol")).isFalse();
    }

    @Test
    void validatesKnownGoodRefs() {
        assertThat(FeasibilityEntityReferenceCodec.validate(
                FeasibilityEntityReferenceCodec.encodeActivityRef(ACTIVITY_ID))).isTrue();
        assertThat(FeasibilityEntityReferenceCodec.validate(
                FeasibilityEntityReferenceCodec.encodeTransitRef(TRANSIT_ID))).isTrue();
        assertThat(FeasibilityEntityReferenceCodec.validate(
                FeasibilityEntityReferenceCodec.encodePoiRef("POI-1"))).isTrue();
        assertThat(FeasibilityEntityReferenceCodec.validate(
                FeasibilityEntityReferenceCodec.encodeTextRef("some text"))).isTrue();
    }
}
