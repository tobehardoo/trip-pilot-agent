from trip_agent.planning.candidates import CandidateRanker
from trip_agent.providers.map import Coordinates, Poi


def poi(
    provider_id: str,
    name: str,
    *,
    city: str = "广州市",
    address: str = "广州市越秀区",
    longitude: float = 113.2644,
    latitude: float = 23.1291,
    type_name: str = "风景名胜",
) -> Poi:
    return Poi(
        provider_id=provider_id,
        name=name,
        coordinates=Coordinates(longitude=longitude, latitude=latitude),
        type_name=type_name,
        type_code="110000",
        province="广东省",
        city=city,
        district="越秀区",
        address=address,
    )


def test_ranker_scores_preferences_and_returns_stable_explanations() -> None:
    result = CandidateRanker().rank(
        (
            poi("park", "越秀公园", type_name="公园广场"),
            poi("museum", "广州博物馆", type_name="科教文化服务"),
            poi("tower", "广州塔"),
        ),
        destination="广州",
        preferences=("博物馆", "岭南文化"),
        traveler_type="FAMILY",
        limit=2,
    )

    assert [item.poi.provider_id for item in result.selected] == ["museum", "park"]
    assert "PREFERENCE_MATCH:博物馆" in result.selected[0].reasons
    assert "FAMILY_FRIENDLY" in result.selected[1].reasons
    assert [(item.poi.provider_id, item.reason) for item in result.rejected] == [
        ("tower", "BELOW_SELECTION_CUTOFF")
    ]


def test_ranker_rejects_invalid_city_empty_address_and_duplicate_places() -> None:
    result = CandidateRanker().rank(
        (
            poi("valid", "陈家祠"),
            poi("duplicate-id", "陈家祠", longitude=113.26441, latitude=23.12909),
            poi("empty-address", "沙面", address=" "),
            poi("wrong-city", "西湖", city="杭州市"),
            poi("valid", "重复 ID"),
        ),
        destination="广州",
        preferences=(),
        traveler_type="FRIENDS",
        limit=5,
    )

    assert [item.poi.provider_id for item in result.selected] == ["valid"]
    assert {item.reason for item in result.rejected} == {
        "DUPLICATE_PLACE",
        "EMPTY_ADDRESS",
        "CITY_MISMATCH",
        "DUPLICATE_PROVIDER_ID",
    }
