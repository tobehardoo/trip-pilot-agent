"""Structured opening-hours parsing and normalization (pure, deterministic).

No I/O and no provider access.  Parses free-text opening-hour statements into
a typed, scope-aware structure (:class:`ParsedOpeningHours`) and converts both
legacy and new ``normalized_value`` shapes into the same structure.

Scope semantics
---------------
* ``DAILY``  — applies to every trip date (no weekday rules, no date).
* ``WEEKLY`` — weekday rules / closed weekdays only; the resolver decides per
  trip date whether the day is open, closed, or unknown.
* ``TODAY``  — applies only to ``effective_date`` (set by the AMap adapter
  from the provider fetch time); never inferred from free text.

Cross-midnight rule
-------------------
A cross-midnight window is expressed **only** with the new
``openingWindows`` format and ``closeDayOffset=1``.  The legacy
``{openTime, closeTime}`` pair with ``close <= open`` stays invalid
(``OPENING_HOURS_REVERSED``) and is never auto-guessed as cross-midnight.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time
from typing import Literal

type OpeningScope = Literal["DAILY", "WEEKLY", "TODAY"]

_TIME_PAIR = re.compile(
    r"(?P<open>\d{1,2}:\d{2})\s*[-—–至到~～]\s*(?P<close>\d{1,2}:\d{2})"
)
_LAST_ENTRY = re.compile(
    r"(?:"
    r"(?P<lead>\d{1,2}:\d{2})\s*(?:停止入场|停止入园|停止检票|最后入场|截止入场)"
    r"|"
    r"(?:停止入场|停止入园|停止检票|最后入场|截止入场)"
    r"\s*(?:时间)?\s*[:：为]?\s*(?P<trail>\d{1,2}:\d{2})"
    r")"
)
_CLOSED_DAY = re.compile(
    r"(?:每周|每)?(?:周|星期|礼拜)(?P<day>[一二三四五六日天])闭馆?"
)
_CLOSED_DAY_RANGE = re.compile(
    r"(?:周|星期|礼拜)(?P<from>[一二三四五六日天])"
    r"(?:至|到|—|-)(?:周|星期|礼拜)?(?P<to>[一二三四五六日天])闭馆?"
)
_REST_DAY = re.compile(
    r"(?:周|星期|礼拜)(?P<day>[一二三四五六日天])休息"
)
_WEEKDAY_RANGE = re.compile(
    r"(?:周|星期|礼拜)(?P<from>[一二三四五六日天])"
    r"(?:至|到|—|-)(?:周|星期|礼拜)?(?P<to>[一二三四五六日天])"
)
# AMap ``opentime_week`` shape: weekday list, pipe, time windows, e.g.
# ``一,二,三,四,五,六,日|09:00-17:00``.  The weekday list must be parsed
# explicitly; a week schedule that cannot be bound to weekdays is UNKNOWN.
_AMAP_WEEK_SCHEDULE = re.compile(
    r"^\s*(?P<days>[一二三四五六日天](?:[、,，\s]*[一二三四五六日天])*)"
    r"\s*[|｜]\s*(?P<time>.+?)\s*$"
)
_AMAP_WEEKDAYS = re.compile(r"[一二三四五六日天]")

_ALL_DAY_TERMS = ("全天开放", "全天", "24小时", "二十四小时", "全天候")
_CLOSED_TERMS = ("闭馆", "闭园", "暂停开放", "停止开放", "不开放")
# Conditional text that cannot be reliably bound to a trip date.  Even when a
# local time pair is extractable, no actionable DAILY window may be produced.
_CONDITIONAL_TERMS = (
    "旺季", "淡季", "节假日", "另行通知", "冬季", "夏季", "秋季", "春季",
    "夜场", "分时段", "特定日期", "视情况",
)

_WEEKDAY_MAP: dict[str, int] = {
    "一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6,
}


@dataclass(frozen=True, slots=True)
class TimeInterval:
    """An open/close window inside one day.

    ``close_day_offset`` is 0 when the window closes on the same calendar day
    and 1 when it closes on the following day (cross-midnight, e.g.
    ``20:00-02:00``).  ``time(24, 0)`` is never used.
    """

    open: time
    close: time
    close_day_offset: int = 0


@dataclass(frozen=True, slots=True)
class WeekdayRule:
    """A positive opening rule bound to a set of weekdays (0=Monday..6=Sunday)."""

    weekdays: frozenset[int]
    intervals: tuple[TimeInterval, ...]


@dataclass(frozen=True, slots=True)
class ParsedOpeningHours:
    """The structured result of parsing one opening-hours statement."""

    scope: OpeningScope
    intervals: tuple[TimeInterval, ...] = ()
    all_day: bool = False
    closed: bool = False
    closed_weekdays: frozenset[int] = frozenset()
    weekday_rules: tuple[WeekdayRule, ...] = ()
    last_entry: time | None = None
    note: str | None = None
    raw: str = ""


def parse_opening_text(
    text: str, *, scope: OpeningScope | None = None
) -> ParsedOpeningHours | None:
    """Parse free-text opening hours into a structured form.

    Returns ``None`` when the text cannot be reliably structured — either
    because it carries conditional/seasonal terms that cannot be bound to a
    trip date, or because it contains no usable opening information.  The
    caller keeps the raw text for evidence/UNKNOWN purposes.
    """
    if not text or not text.strip():
        return None
    raw = text.strip()
    if any(term in raw for term in _CONDITIONAL_TERMS):
        return None

    closed_weekdays = _closed_weekdays(raw)
    weekday_rules = _weekday_rules(raw)

    chosen = scope or (
        "WEEKLY" if (closed_weekdays or weekday_rules) else "DAILY"
    )
    if chosen == "TODAY":
        # TODAY is the caller's forced semantic for same-day data.  Weekday
        # rules cannot be bound to a single date, so reject them instead of
        # misreading a weekday schedule as the day's own window.
        if closed_weekdays or weekday_rules:
            return None
        closed_weekdays, weekday_rules = frozenset(), ()

    all_day = any(term in raw for term in _ALL_DAY_TERMS)

    intervals: tuple[TimeInterval, ...] = ()
    if not all_day and not weekday_rules:
        intervals = tuple(
            TimeInterval(
                open=open_at,
                close=close_at,
                close_day_offset=1 if close_at <= open_at else 0,
            )
            for open_at, close_at in _time_pairs(raw)
        )

    last_entry = _last_entry_time(raw)
    closed = bool(
        not all_day
        and not intervals
        and not closed_weekdays
        and not weekday_rules
        and (
            any(term in raw for term in _CLOSED_TERMS)
            or raw in {"休息", "休息日"}
        )
    )

    if not intervals and not all_day and not closed and not closed_weekdays and not weekday_rules:
        return None

    return ParsedOpeningHours(
        scope=chosen,
        intervals=intervals,
        all_day=all_day,
        closed=closed,
        closed_weekdays=closed_weekdays,
        weekday_rules=weekday_rules,
        last_entry=last_entry,
        note=None,
        raw=raw,
    )


def parse_amap_week_schedule(text: str) -> ParsedOpeningHours | None:
    """Parse an AMap ``opentime_week`` weekday-list schedule.

    Expected shape: ``一,二,三,四,五,六,日|09:00-17:00``.  Returns a WEEKLY
    :class:`ParsedOpeningHours` with a positive weekday rule, or ``None``
    when the schedule cannot be bound to weekdays — the caller keeps the raw
    text and the resolver marks the fact UNKNOWN instead of guessing.
    """
    if not text or not text.strip():
        return None
    raw = text.strip()
    if any(term in raw for term in _CONDITIONAL_TERMS):
        return None
    match = _AMAP_WEEK_SCHEDULE.fullmatch(raw)
    if match is None:
        return None
    days = tuple(_AMAP_WEEKDAYS.findall(match.group("days")))
    if not days or any(day not in _WEEKDAY_MAP for day in days):
        return None
    pairs = tuple(
        TimeInterval(
            open=open_at, close=close_at,
            close_day_offset=1 if close_at <= open_at else 0,
        )
        for open_at, close_at in _time_pairs(match.group("time"))
    )
    if not pairs:
        return None
    return ParsedOpeningHours(
        scope="WEEKLY",
        weekday_rules=(
            WeekdayRule(
                weekdays=frozenset(_WEEKDAY_MAP[day] for day in days),
                intervals=pairs,
            ),
        ),
        raw=raw,
    )


def parse_opening_value(value: Mapping[str, object]) -> ParsedOpeningHours | None:
    """Read either the new ``openingWindows`` shape or the legacy
    ``{openTime, closeTime}`` shape from a ``normalized_value`` mapping.

    Legacy pairs with ``close <= open`` are invalid (never auto-guessed as
    cross-midnight) and yield ``None``.
    """
    if not isinstance(value, Mapping):
        return None
    if value.get("unparsed"):
        return None

    windows = value.get("openingWindows")
    intervals: tuple[TimeInterval, ...] = ()
    if isinstance(windows, list) and windows:
        parsed_intervals = _intervals_from_windows(windows)
        if parsed_intervals is None:
            return None
        intervals = parsed_intervals
    elif "openTime" in value and "closeTime" in value:
        open_at = _time_from(value.get("openTime"))
        close_at = _time_from(value.get("closeTime"))
        if open_at is None or close_at is None:
            return None
        if close_at <= open_at:
            return None
        intervals = (TimeInterval(open=open_at, close=close_at),)

    scope_value = value.get("scope", "DAILY")
    scope: OpeningScope = (
        scope_value if scope_value in {"DAILY", "WEEKLY", "TODAY"} else "DAILY"
    )

    return ParsedOpeningHours(
        scope=scope,
        intervals=intervals,
        all_day=bool(value.get("allDay", False)),
        closed=bool(value.get("closed", False)),
        closed_weekdays=_weekday_set(value.get("closedWeekdays")),
        weekday_rules=_weekday_rules_from_value(value.get("weekdayRules")),
        last_entry=_time_from(value.get("lastEntry")),
        note=str(value["note"]) if value.get("note") else None,
        raw=str(value.get("raw", "")),
    )


def opening_normalized_value(
    parsed: ParsedOpeningHours | None, sentence: str
) -> dict[str, object]:
    """Build the ``normalized_value`` payload for a parsed statement.

    Legacy ``openTime``/``closeTime`` keys are written only when they can
    express the result exactly (single, same-day interval); otherwise the new
    ``openingWindows`` shape is the source of truth.  When parsing failed the
    payload keeps ``{"raw": ..., "unparsed": true}`` so evidence is preserved
    and the resolver can mark the fact UNKNOWN instead of guessing.
    """
    if parsed is None:
        return {"raw": sentence, "unparsed": True}

    result: dict[str, object] = {"scope": parsed.scope, "raw": parsed.raw or sentence}
    if parsed.all_day:
        result["allDay"] = True
    if parsed.closed:
        result["closed"] = True
    if parsed.closed_weekdays:
        result["closedWeekdays"] = sorted(parsed.closed_weekdays)
    if parsed.weekday_rules:
        result["weekdayRules"] = [
            {
                "weekdays": sorted(rule.weekdays),
                "intervals": _windows_payload(rule.intervals),
            }
            for rule in parsed.weekday_rules
        ]
    if parsed.last_entry is not None:
        result["lastEntry"] = _hhmm(parsed.last_entry)
    if parsed.note is not None:
        result["note"] = parsed.note
    if parsed.intervals:
        result["openingWindows"] = _windows_payload(parsed.intervals)
        if len(parsed.intervals) == 1 and parsed.intervals[0].close_day_offset == 0:
            single = parsed.intervals[0]
            result["openTime"] = _hhmm(single.open)
            result["closeTime"] = _hhmm(single.close)
    return result


def _time_pairs(raw: str) -> tuple[tuple[time, time], ...]:
    pairs: list[tuple[time, time]] = []
    for match in _TIME_PAIR.finditer(raw):
        open_at = _time_from(match.group("open"))
        close_at = _time_from(match.group("close"))
        if open_at is not None and close_at is not None:
            pairs.append((open_at, close_at))
    return tuple(pairs)


def _last_entry_time(raw: str) -> time | None:
    match = _LAST_ENTRY.search(raw)
    if match is None:
        return None
    return _time_from(match.group("lead") or match.group("trail"))


def _closed_weekdays(raw: str) -> frozenset[int]:
    days: set[int] = set()
    for match in _CLOSED_DAY.finditer(raw):
        days.add(_WEEKDAY_MAP[match.group("day")])
    for match in _CLOSED_DAY_RANGE.finditer(raw):
        days.update(_weekday_span(match.group("from"), match.group("to")))
    for match in _REST_DAY.finditer(raw):
        days.add(_WEEKDAY_MAP[match.group("day")])
    return frozenset(days)


def _weekday_rules(raw: str) -> tuple[WeekdayRule, ...]:
    rules: list[WeekdayRule] = []
    for match in _WEEKDAY_RANGE.finditer(raw):
        weekdays = _weekday_span(match.group("from"), match.group("to"))
        tail = raw[match.end() : match.end() + 40]
        pairs = tuple(
            TimeInterval(
                open=open_at, close=close_at,
                close_day_offset=1 if close_at <= open_at else 0,
            )
            for open_at, close_at in _time_pairs(tail)
        )
        if pairs:
            rules.append(WeekdayRule(weekdays=weekdays, intervals=pairs))
    return tuple(rules)


def _weekday_span(from_day: str, to_day: str) -> frozenset[int]:
    start = _WEEKDAY_MAP[from_day]
    end = _WEEKDAY_MAP[to_day]
    if end >= start:
        return frozenset(range(start, end + 1))
    return frozenset(range(start, 7)) | frozenset(range(0, end + 1))


def _intervals_from_windows(windows: object) -> tuple[TimeInterval, ...] | None:
    if not isinstance(windows, list):
        return None
    intervals: list[TimeInterval] = []
    for window in windows:
        if not isinstance(window, Mapping):
            return None
        open_at = _time_from(window.get("open"))
        close_at = _time_from(window.get("close"))
        offset = window.get("closeDayOffset", 0)
        if open_at is None or close_at is None or not isinstance(offset, int) or offset < 0:
            return None
        intervals.append(
            TimeInterval(open=open_at, close=close_at, close_day_offset=offset)
        )
    return tuple(intervals)


def _weekday_rules_from_value(value: object) -> tuple[WeekdayRule, ...]:
    if not isinstance(value, list):
        return ()
    rules: list[WeekdayRule] = []
    for rule in value:
        if not isinstance(rule, Mapping):
            continue
        weekdays = _weekday_set(rule.get("weekdays"))
        intervals = _intervals_from_windows(rule.get("intervals"))
        if weekdays and intervals is not None and intervals:
            rules.append(WeekdayRule(weekdays=weekdays, intervals=intervals))
    return tuple(rules)


def _weekday_set(value: object) -> frozenset[int]:
    if not isinstance(value, list | tuple | set | frozenset):
        return frozenset()
    return frozenset(
        int(day) for day in value if isinstance(day, int) and 0 <= day <= 6
    )


def _time_from(value: object) -> time | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return time.fromisoformat(value.strip())
    except ValueError:
        return None


def _windows_payload(intervals: tuple[TimeInterval, ...]) -> list[dict[str, object]]:
    return [
        {
            "open": _hhmm(interval.open),
            "close": _hhmm(interval.close),
            "closeDayOffset": interval.close_day_offset,
        }
        for interval in intervals
    ]


def _hhmm(value: time) -> str:
    """Format a time as ``HH:MM`` (no seconds, no 24:00)."""
    return f"{value.hour:02d}:{value.minute:02d}"
