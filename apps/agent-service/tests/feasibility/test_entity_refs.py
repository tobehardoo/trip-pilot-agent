"""B6J.2 R1: typed entity reference encoding/validation (hard-validator-v4).

Grammar (single colon separates kind/value):

- activity:<canonical-lowercase-uuid>
- transit:<canonical-lowercase-uuid>
- poi:<nonblank-opaque-value>      (value may contain further colons)
- text:<nonblank-opaque-value>

Unknown kinds, empty values, bare UUIDs and unprefixed strings fail closed.
"""

import uuid

import pytest

from trip_agent.feasibility.entity_refs import (
    EntityReferenceKind,
    decode_entity_ref,
    encode_activity_ref,
    encode_poi_ref,
    encode_text_ref,
    encode_transit_ref,
    parse_entity_ref,
    validate_entity_ref,
)

ACTIVITY_ID = uuid.UUID("10000000-0000-4000-8000-000000000031")
TRANSIT_ID = uuid.UUID("10000000-0000-4000-8000-000000000041")
POI_ID = "POI-123"
TEXT = "广州塔"


class TestEncode:
    def test_activity_encode(self) -> None:
        assert encode_activity_ref(ACTIVITY_ID) == (f"activity:{ACTIVITY_ID}")

    def test_transit_encode(self) -> None:
        assert encode_transit_ref(TRANSIT_ID) == (f"transit:{TRANSIT_ID}")

    def test_poi_encode_preserves_opaque_value(self) -> None:
        assert encode_poi_ref(POI_ID) == f"poi:{POI_ID}"

    def test_poi_encode_allows_colons_in_value(self) -> None:
        assert encode_poi_ref("a:b:c") == "poi:a:b:c"

    def test_text_encode(self) -> None:
        assert encode_text_ref(TEXT) == f"text:{TEXT}"

    def test_uuid_like_poi_stays_poi(self) -> None:
        # F5 core case: a UUID-looking POI is encoded as poi:, never activity:.
        assert encode_poi_ref(str(ACTIVITY_ID)) == f"poi:{ACTIVITY_ID}"


class TestParseAndValidate:
    def test_roundtrip_activity(self) -> None:
        ref = encode_activity_ref(ACTIVITY_ID)
        kind, value = parse_entity_ref(ref)
        assert kind is EntityReferenceKind.ACTIVITY
        assert value == str(ACTIVITY_ID)
        assert validate_entity_ref(ref) is True

    def test_roundtrip_transit(self) -> None:
        ref = encode_transit_ref(TRANSIT_ID)
        kind, value = parse_entity_ref(ref)
        assert kind is EntityReferenceKind.TRANSIT
        assert value == str(TRANSIT_ID)

    def test_roundtrip_poi_with_colons(self) -> None:
        ref = encode_poi_ref("a:b:c")
        kind, value = parse_entity_ref(ref)
        assert kind is EntityReferenceKind.POI
        assert value == "a:b:c"

    def test_roundtrip_text(self) -> None:
        ref = encode_text_ref(TEXT)
        kind, value = parse_entity_ref(ref)
        assert kind is EntityReferenceKind.TEXT
        assert value == TEXT

    @pytest.mark.parametrize(
        "bad",
        [
            "activity",  # no colon
            "activity:",  # empty value
            "transit:",  # empty value
            "poi:",  # empty value
            "text:",  # empty value
            "unknown:x",  # unknown kind
            "unknown:",  # unknown kind empty
            str(ACTIVITY_ID),  # bare UUID
            "no-prefix-value",  # unprefixed string
            "ACTIVITY:x",  # uppercase kind
            "activity:ABC",  # non-canonical uuid
            "activity:10000000-0000-4000-8000-000000000031-extra",  # uuid + junk
            "activity:10000000-0000-4000-8000-00000000003G",  # invalid uuid char
            "activity:\n10000000-0000-4000-8000-000000000031",  # control char
            "poi:has\tcontrol",  # control char in value
            "activity:" + "a" * 200,  # too long after prefix (uuid parse fails anyway)
        ],
    )
    def test_invalid_refs_fail_closed(self, bad: str) -> None:
        assert validate_entity_ref(bad) is False
        with pytest.raises(ValueError):
            decode_entity_ref(bad)

    def test_uppercase_uuid_rejected_for_activity(self) -> None:
        ref = "activity:10000000-0000-4000-8000-AABBCCDDEEFF"
        assert validate_entity_ref(ref) is False

    def test_length_bound_includes_prefix(self) -> None:
        long_value = "x" * 200
        ref = f"poi:{long_value}"
        assert len(ref) > 200
        assert validate_entity_ref(ref) is False


class TestDecode:
    def test_decode_activity(self) -> None:
        kind, value = decode_entity_ref(f"activity:{ACTIVITY_ID}")
        assert kind is EntityReferenceKind.ACTIVITY
        assert value == str(ACTIVITY_ID)

    def test_decode_poi_uuid_like_keeps_poi_kind(self) -> None:
        # F5: even when the POI value looks like a UUID it must decode as POI.
        kind, value = decode_entity_ref(encode_poi_ref(str(ACTIVITY_ID)))
        assert kind is EntityReferenceKind.POI
        assert value == str(ACTIVITY_ID)
