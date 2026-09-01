from datetime import UTC, datetime, timedelta

import pytest

from trip_agent.guide_intelligence.travel_entities import (
    FactProvenance,
    FactValue,
    TravelEntityLocation,
    attraction_cache_key,
    build_attraction,
)


def test_expired_fact_is_unknown_instead_of_being_used_as_current_truth() -> None:
    checked_at = datetime(2026, 8, 1, 8, tzinfo=UTC)
    provenance = FactProvenance(
        source="official-attraction",
        source_type="OFFICIAL",
        fetched_at=checked_at - timedelta(days=2),
        valid_until=checked_at - timedelta(minutes=1),
        confidence=0.99,
    )
    fact = FactValue.known("09:00-17:00", provenance)

    current = fact.at(checked_at)

    assert current.status == "UNKNOWN"
    assert current.value is None
    assert current.provenance is None


def test_attraction_preserves_provenance_for_slow_and_fast_facts() -> None:
    checked_at = datetime(2026, 8, 1, 8, tzinfo=UTC)
    provenance = FactProvenance(
        source="amap",
        source_type="PROVIDER",
        fetched_at=checked_at,
        valid_until=checked_at + timedelta(hours=6),
        confidence=0.8,
    )
    attraction = build_attraction(
        city_adcode="540100",
        provider_poi_id="B0001",
        name="布达拉宫",
        category="HISTORIC_SITE",
        location=TravelEntityLocation(91.1172, 29.6548, "拉萨市城关区"),
        opening_hours=FactValue.known("09:00-16:00", provenance),
    )

    assert attraction.city_adcode == "540100"
    assert attraction.opening_hours.value == "09:00-16:00"
    assert attraction.ticket_price.status == "UNKNOWN"


def test_attraction_cache_key_is_scoped_by_city_entity_provider_query_and_date() -> None:
    first = attraction_cache_key(
        city_adcode="540100",
        provider="AMAP",
        query="museum",
        as_of="2026-08-01",
    )
    second = attraction_cache_key(
        city_adcode="440100",
        provider="AMAP",
        query="museum",
        as_of="2026-08-01",
    )

    assert first.startswith("travel-intel:v1:attraction:540100:AMAP:")
    assert first != second


@pytest.mark.parametrize("city_adcode", ["54010", "5401000", "Lhasa!"])
def test_city_adcode_must_be_a_six_digit_administrative_code(city_adcode: str) -> None:
    with pytest.raises(ValueError, match="city_adcode"):
        build_attraction(
            city_adcode=city_adcode,
            provider_poi_id="B0001",
            name="景点",
            category="ATTRACTION",
            location=TravelEntityLocation(91.0, 29.0, "拉萨"),
        )
