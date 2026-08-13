"""B9.2 — opening-aware active placement."""

from datetime import date, time

from trip_agent.planning.daily_schedule import (
    CandidateActivity,
    OpeningAvailability,
    _earliest_opening_placement,
    opening_availability_from_resolved,
    plan_day,
)


class _Resolved:
    def __init__(
        self,
        *,
        state: str,
        eligible: bool,
        windows: tuple[object, ...] = (),
        last_entry: time | None = None,
    ) -> None:
        self.state = state
        self.hard_constraint_eligible = eligible
        self.windows = windows
        self.last_entry = last_entry


class _Interval:
    def __init__(self, open: time, close: time, offset: int = 0) -> None:
        self.open = open
        self.close = close
        self.close_day_offset = offset


def _candidate(
    *,
    poi_id: str = "poi-1",
    title: str = "museum",
    must_include: bool = False,
    opening: OpeningAvailability | None = None,
) -> CandidateActivity:
    return CandidateActivity(
        poi_id=poi_id,
        title=title,
        magnitude="LIGHT",
        coordinates=(113.26, 23.13),
        must_include=must_include,
        opening=opening,
    )


def _windowed(open: time, close: time, last_entry: time | None = None) -> OpeningAvailability:
    return OpeningAvailability(
        kind="VERIFIED_WINDOW",
        windows=((open.hour * 60 + open.minute, close.hour * 60 + close.minute),),
        last_entry_minute=(
            last_entry.hour * 60 + last_entry.minute if last_entry is not None else None
        ),
    )


def test_resolved_mapping_only_eligible_verified_constrains() -> None:
    windowed = opening_availability_from_resolved(
        _Resolved(
            state="VERIFIED_WINDOW",
            eligible=True,
            windows=(_Interval(time(9, 0), time(17, 0)),),
            last_entry=time(16, 30),
        )
    )
    assert windowed.kind == "VERIFIED_WINDOW"
    assert windowed.windows == ((540, 1020),)
    assert windowed.last_entry_minute == 990

    closed = opening_availability_from_resolved(_Resolved(state="VERIFIED_CLOSED", eligible=True))
    assert closed.kind == "VERIFIED_CLOSED"

    # Ineligible evidence, UNKNOWN/STALE/CONFLICTING: never constrains.
    for state in ("VERIFIED_WINDOW", "VERIFIED_CLOSED"):
        assert (
            opening_availability_from_resolved(_Resolved(state=state, eligible=False)).kind
            == "UNKNOWN"
        )
    for state in ("UNKNOWN", "STALE", "CONFLICTING"):
        assert (
            opening_availability_from_resolved(_Resolved(state=state, eligible=True)).kind
            == "UNKNOWN"
        )


def test_earliest_opening_placement_obeys_window_and_last_entry() -> None:
    availability = _windowed(time(10, 0), time(18, 0), last_entry=time(16, 30))
    activity = _candidate(opening=availability)
    # slot 08:00-22:00, cursor 08:00: earliest start inside 10:00 window.
    start = _earliest_opening_placement(activity, 480, 1320, 480, 120, 0)
    assert start == 600
    # Cursor past last-entry: no legal start.
    assert _earliest_opening_placement(activity, 480, 1320, 1000, 120, 0) is None


def test_earliest_opening_placement_picks_first_multi_window() -> None:
    availability = OpeningAvailability(
        kind="VERIFIED_WINDOW",
        windows=((840, 900), (600, 660), (720, 780)),
        last_entry_minute=None,
    )
    activity = _candidate(opening=availability)
    start = _earliest_opening_placement(activity, 480, 1320, 480, 30, 0)
    # Windows are considered sorted; the earliest window containing a legal
    # 30-minute placement wins: 600.
    assert start == 600


def test_verified_closed_candidate_is_excluded_from_placement() -> None:
    closed = OpeningAvailability(kind="VERIFIED_CLOSED")
    candidates = (
        _candidate(poi_id="closed", title="closed-place", opening=closed),
        _candidate(poi_id="open", title="open-place"),
    )
    plan = plan_day(
        trip_date=date(2026, 8, 1),
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 1),
        arrival=None,
        departure=None,
        accommodation_known=False,
        candidates=candidates,
    )
    placed_titles = {item.title for item in plan.items}
    assert "closed-place" not in placed_titles
    assert "open-place" in placed_titles


def test_verified_closed_must_visit_is_flagged_not_swapped() -> None:
    closed = OpeningAvailability(kind="VERIFIED_CLOSED")
    candidates = (
        _candidate(
            poi_id="must-closed",
            title="must-see",
            must_include=True,
            opening=closed,
        ),
        _candidate(poi_id="other", title="other"),
    )
    plan = plan_day(
        trip_date=date(2026, 8, 1),
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 1),
        arrival=None,
        departure=None,
        accommodation_known=False,
        candidates=candidates,
    )
    assert any(warning.startswith("MUST_VISIT_CLOSED:must-see") for warning in plan.warnings)


def test_unknown_opening_never_constrains_placement() -> None:
    unknown = OpeningAvailability(kind="UNKNOWN")
    candidates = (_candidate(poi_id="unknown-open", title="unknown-open", opening=unknown),)
    plan = plan_day(
        trip_date=date(2026, 8, 1),
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 1),
        arrival=None,
        departure=None,
        accommodation_known=False,
        candidates=candidates,
    )
    assert any(item.title == "unknown-open" for item in plan.items)


def test_cross_midnight_window_keeps_close_past_1440() -> None:
    resolved = opening_availability_from_resolved(
        _Resolved(
            state="VERIFIED_WINDOW",
            eligible=True,
            windows=(_Interval(time(20, 0), time(2, 0), offset=1),),
        )
    )
    assert resolved.windows == ((1200, 1560),)
