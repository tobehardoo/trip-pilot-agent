"""Tests for the consolidated domain utilities in domain/shared.py."""

from datetime import UTC, date, datetime, timedelta

import pytest

from trip_agent.domain.shared import (
    CHINA_TIME_ZONE,
    available_minutes,
    coordinate_decimal,
    minute_datetime,
    normalize_text,
    normalize_trip_date,
    text_matches,
)


class TestChinaTimeZone:
    def test_is_utc_plus_8(self) -> None:
        assert CHINA_TIME_ZONE.utcoffset(None) == timedelta(hours=8)

    def test_name_is_asia_shanghai(self) -> None:
        assert str(CHINA_TIME_ZONE) == "Asia/Shanghai"


class TestTextMatches:
    def test_exact_match(self) -> None:
        assert text_matches("hello", "hello")

    def test_case_insensitive(self) -> None:
        assert text_matches("Hello", "HELLO")

    def test_ignores_non_alnum(self) -> None:
        assert text_matches("hello world", "hello-world!")

    def test_substring_match(self) -> None:
        assert text_matches("hello", "hello world")

    def test_reverse_substring(self) -> None:
        assert text_matches("hello world", "hello")

    def test_no_match(self) -> None:
        assert not text_matches("hello", "goodbye")

    def test_empty_expected_returns_false(self) -> None:
        assert not text_matches("", "hello")

    def test_empty_actual_still_matches_expected(self) -> None:
        # empty string is trivially a substring of any non-empty key
        assert text_matches("hello", "")

    def test_chinese_characters(self) -> None:
        assert text_matches("广州塔", "广州塔")

    def test_chinese_with_punctuation(self) -> None:
        assert text_matches("广州塔", "广州塔（景点）")


class TestNormalizeText:
    def test_strips_non_alnum(self) -> None:
        assert normalize_text("hello world!") == "helloworld"

    def test_casefold(self) -> None:
        assert normalize_text("HELLO") == "hello"

    def test_chinese_preserved(self) -> None:
        assert normalize_text("广州塔-123") == "广州塔123"


class TestAvailableMinutes:
    def test_default_window(self) -> None:
        start, end = available_minutes(
            date(2026, 7, 20),
            date(2026, 7, 20),
            date(2026, 7, 22),
            None,
            None,
        )
        assert start == 9 * 60
        assert end == 18 * 60

    def test_first_day_with_arrival(self) -> None:
        arrival = datetime(2026, 7, 20, 11, 30, tzinfo=CHINA_TIME_ZONE)
        start, end = available_minutes(
            date(2026, 7, 20),
            date(2026, 7, 20),
            date(2026, 7, 22),
            arrival,
            None,
        )
        assert start == 11 * 60 + 30
        assert end == 18 * 60

    def test_last_day_with_departure(self) -> None:
        departure = datetime(2026, 7, 22, 16, 0, tzinfo=CHINA_TIME_ZONE)
        start, end = available_minutes(
            date(2026, 7, 22),
            date(2026, 7, 20),
            date(2026, 7, 22),
            None,
            departure,
        )
        assert start == 9 * 60
        assert end == 16 * 60

    def test_middle_day_ignores_anchors(self) -> None:
        arrival = datetime(2026, 7, 20, 11, 0, tzinfo=CHINA_TIME_ZONE)
        departure = datetime(2026, 7, 22, 16, 0, tzinfo=CHINA_TIME_ZONE)
        start, end = available_minutes(
            date(2026, 7, 21),
            date(2026, 7, 20),
            date(2026, 7, 22),
            arrival,
            departure,
        )
        assert start == 9 * 60
        assert end == 18 * 60

    def test_arrival_later_than_default(self) -> None:
        arrival = datetime(2026, 7, 20, 14, 0, tzinfo=CHINA_TIME_ZONE)
        start, _ = available_minutes(
            date(2026, 7, 20),
            date(2026, 7, 20),
            date(2026, 7, 22),
            arrival,
            None,
        )
        assert start == 14 * 60


class TestMinuteDatetime:
    def test_midnight_plus_offset(self) -> None:
        result = minute_datetime(date(2026, 7, 20), 600)
        assert result == datetime(2026, 7, 20, 10, 0, tzinfo=CHINA_TIME_ZONE)

    def test_has_correct_timezone(self) -> None:
        result = minute_datetime(date(2026, 7, 20), 0)
        assert result.tzinfo is not None
        assert result.utcoffset() == timedelta(hours=8)


class TestCoordinateDecimal:
    def test_positive_value(self) -> None:
        result = coordinate_decimal(113.264385)
        assert float(result) == pytest.approx(113.264385)

    def test_rounds_to_scale(self) -> None:
        result = coordinate_decimal(113.264385123456)
        # quantized to 7 decimal places (COORDINATE_SCALE = 0.0000001)
        assert result.as_tuple().exponent == -7

    def test_negative_value(self) -> None:
        result = coordinate_decimal(-23.12911)
        assert float(result) == pytest.approx(-23.12911)


class TestNormalizeTripDate:
    """F-2b — the single date normalizer for agent + dialog."""

    def test_iso_separators(self) -> None:
        assert normalize_trip_date("2026-10-01") == date(2026, 10, 1)
        assert normalize_trip_date("2026/10/01") == date(2026, 10, 1)
        assert normalize_trip_date("2026.10.1") == date(2026, 10, 1)
        assert normalize_trip_date("2026年10月1日") == date(2026, 10, 1)

    def test_chinese_month_day_this_year_when_future(self) -> None:
        today = date(2026, 9, 1)
        assert normalize_trip_date("10月1日", today=today) == date(2026, 10, 1)

    def test_chinese_month_day_rolls_to_next_year_once_passed(self) -> None:
        today = date(2026, 12, 1)
        assert normalize_trip_date("1月1日", today=today) == date(2027, 1, 1)

    def test_chinese_month_day_extracted_from_surrounding_text(self) -> None:
        """The dialog scan passes fragments like '…2个人，10月1日'; the
        Chinese form is search-based while ISO stays whole-value."""
        today = date(2026, 9, 1)
        fragment = "想去成都玩，预算5000，2个人，10月1日"
        assert normalize_trip_date(fragment, today=today) == date(2026, 10, 1)

    def test_chinese_month_day_with_前后_suffix(self) -> None:
        today = date(2026, 9, 1)
        assert normalize_trip_date("10月1日前后", today=today) == date(2026, 10, 1)

    def test_datetime_and_date_pass_through(self) -> None:
        moment = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
        assert normalize_trip_date(moment) == date(2026, 10, 1)
        assert normalize_trip_date(date(2026, 10, 1)) == date(2026, 10, 1)

    def test_unrecognizable_values_return_none(self) -> None:
        assert normalize_trip_date(None) is None
        assert normalize_trip_date("明年春天") is None
        assert normalize_trip_date("下周三") is None
        assert normalize_trip_date("2月30日") is None
