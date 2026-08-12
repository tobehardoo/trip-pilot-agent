"""Typed entity references for feasibility reports (hard-validator-v4).

Grammar (single colon separates kind/value):

- ``activity:<canonical-lowercase-uuid>``
- ``transit:<canonical-lowercase-uuid>``
- ``poi:<nonblank-opaque-value>``    (value may contain further colons)
- ``text:<nonblank-opaque-value>``

Rules:

- only the first colon separates kind and value;
- activity/transit values must be canonical lowercase UUIDs;
- poi/text values must be non-blank (may contain colons);
- the full string must fit the 200-char entity-ref bound;
- control characters are forbidden;
- unknown kinds, empty values, bare UUIDs and unprefixed strings fail closed.

v3 historical reports used raw UUIDs/POI ids; v4 reports always use these
typed refs.  Python and Java must share this grammar exactly.
"""

from __future__ import annotations

import re
import uuid
from enum import Enum
from typing import NamedTuple

MAX_ENTITY_REF_LENGTH = 200
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class EntityReferenceKind(str, Enum):
    ACTIVITY = "activity"
    TRANSIT = "transit"
    POI = "poi"
    TEXT = "text"


class ParsedEntityRef(NamedTuple):
    kind: EntityReferenceKind
    value: str


def encode_activity_ref(activity_id: uuid.UUID | str) -> str:
    return f"{EntityReferenceKind.ACTIVITY.value}:{_canonical_uuid(activity_id)}"


def encode_transit_ref(transit_id: uuid.UUID | str) -> str:
    return f"{EntityReferenceKind.TRANSIT.value}:{_canonical_uuid(transit_id)}"


def encode_poi_ref(poi_id: str) -> str:
    return f"{EntityReferenceKind.POI.value}:{poi_id}"


def encode_text_ref(value: str) -> str:
    return f"{EntityReferenceKind.TEXT.value}:{value}"


def _canonical_uuid(value: uuid.UUID | str) -> str:
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(uuid.UUID(value)).lower()


def parse_entity_ref(ref: str) -> ParsedEntityRef:
    """Strict parse; raises ValueError on any grammar violation."""
    if not isinstance(ref, str) or not ref:
        raise ValueError("entity reference must be a non-empty string")
    if len(ref) > MAX_ENTITY_REF_LENGTH:
        raise ValueError("entity reference exceeds 200 characters")
    if _CONTROL_CHARS.search(ref):
        raise ValueError("entity reference must not contain control characters")
    kind_text, sep, value = ref.partition(":")
    if not sep or not value:
        raise ValueError("entity reference must be kind:value")
    try:
        kind = EntityReferenceKind(kind_text)
    except ValueError:
        raise ValueError(f"unknown entity reference kind: {kind_text!r}") from None
    if kind is EntityReferenceKind.ACTIVITY or kind is EntityReferenceKind.TRANSIT:
        try:
            parsed = uuid.UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"{kind.value} reference must be a UUID") from exc
        if str(parsed) != value:
            raise ValueError(f"{kind.value} reference must be canonical lowercase UUID")
    return ParsedEntityRef(kind, value)


def validate_entity_ref(ref: str) -> bool:
    try:
        parse_entity_ref(ref)
        return True
    except ValueError:
        return False


def decode_entity_ref(ref: str) -> ParsedEntityRef:
    """Parse for remapping; raises ValueError on grammar violation."""
    return parse_entity_ref(ref)
