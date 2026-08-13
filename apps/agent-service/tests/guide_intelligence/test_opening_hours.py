"""B1 — opening-hours parsing matrix (pure functions, no I/O)."""

from datetime import time

from trip_agent.guide_intelligence.opening_hours import (
    TimeInterval,
    WeekdayRule,
    opening_normalized_value,
    parse_opening_text,
    parse_opening_value,
)


def _hm(hour: int, minute: int = 0) -> time:
    return time(hour, minute)


# ── parse_opening_text ─────────────────────────────────────────────────────


def test_parses_single_interval() -> None:
    parsed = parse_opening_text("营业时间：09:00-17:00")
    assert parsed is not None
    assert parsed.scope == "DAILY"
    assert parsed.intervals == (TimeInterval(_hm(9), _hm(17)),)
    assert parsed.closed is False
    assert parsed.all_day is False


def test_parses_multi_interval_with_last_entry() -> None:
    parsed = parse_opening_text(
        "开放时间：09:00-12:00；14:00-17:00，16:30停止入场"
    )
    assert parsed is not None
    assert parsed.intervals == (
        TimeInterval(_hm(9), _hm(12)),
        TimeInterval(_hm(14), _hm(17)),
    )
    assert parsed.last_entry == _hm(16, 30)


def test_parses_last_entry_without_intervals_effect() -> None:
    parsed = parse_opening_text("09:00-17:00；16:30 停止入场")
    assert parsed is not None
    assert parsed.last_entry == _hm(16, 30)
    assert parsed.intervals == (TimeInterval(_hm(9), _hm(17)),)


def test_parses_closed_weekday_only_statement() -> None:
    parsed = parse_opening_text("每周一闭馆")
    assert parsed is not None
    assert parsed.scope == "WEEKLY"
    assert parsed.closed_weekdays == frozenset({0})
    assert parsed.intervals == ()


def test_parses_weekday_range_with_intervals() -> None:
    parsed = parse_opening_text("周一至周五09:00-17:00")
    assert parsed is not None
    assert parsed.scope == "WEEKLY"
    assert parsed.weekday_rules == (
        WeekdayRule(
            weekdays=frozenset({0, 1, 2, 3, 4}),
            intervals=(TimeInterval(_hm(9), _hm(17)),),
        ),
    )
    # no DAILY intervals leaked from the weekday-bound pair
    assert parsed.intervals == ()


def test_parses_all_day() -> None:
    parsed = parse_opening_text("全天开放")
    assert parsed is not None
    assert parsed.all_day is True
    assert parsed.intervals == ()


def test_parses_24_hours() -> None:
    parsed = parse_opening_text("24小时开放")
    assert parsed is not None
    assert parsed.all_day is True


def test_parses_cross_midnight_with_day_offset() -> None:
    parsed = parse_opening_text("开放时间：20:00-02:00")
    assert parsed is not None
    assert parsed.intervals == (
        TimeInterval(_hm(20), _hm(2), close_day_offset=1),
    )


def test_parses_bare_rest_as_closed() -> None:
    parsed = parse_opening_text("休息")
    assert parsed is not None
    assert parsed.closed is True
    assert parsed.intervals == ()


def test_conditional_seasonal_text_yields_none() -> None:
    assert parse_opening_text("旺季8:00-18:00，淡季9:00-17:00") is None
    assert parse_opening_text("节假日另行通知") is None
    assert parse_opening_text("夜场开放19:00-22:00") is None


def test_empty_or_garbage_text_yields_none() -> None:
    assert parse_opening_text("") is None
    assert parse_opening_text("   ") is None
    assert parse_opening_text("地址：广州市越秀区") is None


def test_today_scope_rejects_weekday_rules() -> None:
    assert parse_opening_text("周一至周五09:00-17:00", scope="TODAY") is None
    assert parse_opening_text("每周一闭馆", scope="TODAY") is None


def test_today_scope_accepts_plain_window() -> None:
    parsed = parse_opening_text("09:00-17:00", scope="TODAY")
    assert parsed is not None
    assert parsed.scope == "TODAY"
    assert parsed.intervals == (TimeInterval(_hm(9), _hm(17)),)


# ── parse_opening_value (dual format) ──────────────────────────────────────


def test_reads_new_opening_windows_format() -> None:
    value = {
        "scope": "WEEKLY",
        "openingWindows": [
            {"open": "09:00", "close": "12:00", "closeDayOffset": 0},
            {"open": "14:00", "close": "02:00", "closeDayOffset": 1},
        ],
        "closedWeekdays": [0],
        "lastEntry": "16:00",
        "raw": "原始文本",
    }
    parsed = parse_opening_value(value)
    assert parsed is not None
    assert parsed.scope == "WEEKLY"
    assert parsed.intervals == (
        TimeInterval(_hm(9), _hm(12)),
        TimeInterval(_hm(14), _hm(2), close_day_offset=1),
    )
    assert parsed.closed_weekdays == frozenset({0})
    assert parsed.last_entry == _hm(16)
    assert parsed.raw == "原始文本"


def test_reads_legacy_open_time_close_time_format() -> None:
    parsed = parse_opening_value({"openTime": "09:00", "closeTime": "17:30"})
    assert parsed is not None
    assert parsed.scope == "DAILY"
    assert parsed.intervals == (TimeInterval(_hm(9), _hm(17, 30)),)


def test_legacy_reversed_pair_is_invalid_not_cross_midnight() -> None:
    assert parse_opening_value({"openTime": "17:00", "closeTime": "09:00"}) is None


def test_unparsed_marker_yields_none() -> None:
    assert parse_opening_value({"raw": "旺季8:00-18:00", "unparsed": True}) is None


def test_weekday_rules_roundtrip() -> None:
    parsed = parse_opening_text("周一至周五09:00-17:00")
    assert parsed is not None
    value = opening_normalized_value(parsed, "周一至周五09:00-17:00")
    again = parse_opening_value(value)
    assert again is not None
    assert again.scope == "WEEKLY"
    assert again.weekday_rules == parsed.weekday_rules
    assert again.intervals == ()


# ── opening_normalized_value ───────────────────────────────────────────────


def test_normalized_value_keeps_legacy_keys_for_single_same_day_interval() -> None:
    parsed = parse_opening_text("营业时间：09:00-17:00")
    assert parsed is not None
    value = opening_normalized_value(parsed, "营业时间：09:00-17:00")
    assert value["openTime"] == "09:00"
    assert value["closeTime"] == "17:00"
    assert value["openingWindows"] == [
        {"open": "09:00", "close": "17:00", "closeDayOffset": 0}
    ]
    assert value["scope"] == "DAILY"
    assert value["raw"] == "营业时间：09:00-17:00"


def test_normalized_value_omits_legacy_keys_for_cross_midnight() -> None:
    parsed = parse_opening_text("开放时间：20:00-02:00")
    assert parsed is not None
    value = opening_normalized_value(parsed, "开放时间：20:00-02:00")
    assert "openTime" not in value
    assert "closeTime" not in value
    assert value["openingWindows"] == [
        {"open": "20:00", "close": "02:00", "closeDayOffset": 1}
    ]


def test_normalized_value_preserves_unparsed_raw() -> None:
    value = opening_normalized_value(None, "旺季8:00-18:00")
    assert value == {"raw": "旺季8:00-18:00", "unparsed": True}


def test_normalized_value_keeps_closed_weekday_structure() -> None:
    parsed = parse_opening_text("每周一闭馆")
    assert parsed is not None
    value = opening_normalized_value(parsed, "每周一闭馆")
    assert value["scope"] == "WEEKLY"
    assert value["closedWeekdays"] == [0]
    assert "openTime" not in value


def test_all_day_never_combines_with_intervals() -> None:
    parsed = parse_opening_text("全天开放")
    assert parsed is not None
    assert parsed.all_day is True
    assert parsed.intervals == ()
    value = opening_normalized_value(parsed, "全天开放")
    assert value["allDay"] is True
    assert "openingWindows" not in value
