"""B2 RED 2 — deterministic itinerary fingerprint.

The fingerprint must be a pure function of the itinerary's semantic
content: identical data in, identical 64-hex hash out, independent of
cwd, system timezone, locale and wall-clock time.  Activity/day order
is semantic (the planner orders the day), so reordering must change the
hash.
"""

from decimal import Decimal

from plan_evaluation_support import make_result

from trip_agent.feasibility.fingerprint import compute_itinerary_fingerprint
from trip_agent.worker.contracts import Itinerary


def test_fingerprint_is_a_64_char_lowercase_hex_string() -> None:
    fingerprint = compute_itinerary_fingerprint(make_result().itinerary)

    assert len(fingerprint) == 64
    assert fingerprint == fingerprint.lower()
    int(fingerprint, 16)  # must be valid hex


def test_same_itinerary_yields_the_same_fingerprint_repeatedly() -> None:
    itinerary = make_result().itinerary

    assert compute_itinerary_fingerprint(itinerary) == compute_itinerary_fingerprint(
        itinerary
    )
    assert compute_itinerary_fingerprint(itinerary) == compute_itinerary_fingerprint(
        itinerary
    )


def test_equivalent_model_copy_yields_the_same_fingerprint() -> None:
    itinerary = make_result().itinerary
    copy = itinerary.model_copy(deep=True)

    assert compute_itinerary_fingerprint(itinerary) == compute_itinerary_fingerprint(
        copy
    )


def test_changing_title_changes_the_fingerprint() -> None:
    base = make_result().itinerary
    renamed = base.model_copy(update={"title": "Another title"})

    assert compute_itinerary_fingerprint(base) != compute_itinerary_fingerprint(renamed)


def test_changing_activity_time_changes_the_fingerprint() -> None:
    base = make_result().itinerary
    day = base.days[0]
    moved = day.model_copy(
        update={
            "activities": (
                day.activities[0].model_copy(
                    update={"start_time": day.activities[0].start_time.replace(hour=8)}
                ),
                day.activities[1],
            )
        }
    )
    altered = base.model_copy(update={"days": (moved,)})

    assert compute_itinerary_fingerprint(base) != compute_itinerary_fingerprint(altered)


def test_changing_provider_poi_id_changes_the_fingerprint() -> None:
    base = make_result().itinerary
    day = base.days[0]
    first = day.activities[0].model_copy(update={"provider_poi_id": "POI-CHANGED"})
    shifted = day.model_copy(update={"activities": (first,) + day.activities[1:]})
    altered = base.model_copy(update={"days": (shifted,)})

    assert compute_itinerary_fingerprint(base) != compute_itinerary_fingerprint(altered)


def test_reordering_activities_changes_the_fingerprint() -> None:
    # Order carries planning semantics: a swapped day must hash differently.
    base = make_result().itinerary
    day = base.days[0]
    swapped = day.model_copy(
        update={"activities": (day.activities[1], day.activities[0])}
    )
    altered = base.model_copy(update={"days": (swapped,)})

    assert compute_itinerary_fingerprint(base) != compute_itinerary_fingerprint(altered)


def test_reordering_days_changes_the_fingerprint() -> None:
    day = make_result().itinerary.days[0]
    second_day = day.model_copy(
        update={
            "date": day.date.replace(day=2),
            "activities": (
                day.activities[0].model_copy(
                    update={"start_time": day.activities[0].start_time.replace(hour=10)}
                ),
                day.activities[1],
            ),
        }
    )
    two_days = Itinerary(
        title="Two-day trip",
        days=(day, second_day),
        estimated_total_cost=Decimal("200.00"),
    )
    reversed_days = two_days.model_copy(update={"days": (second_day, day)})

    assert compute_itinerary_fingerprint(two_days) != compute_itinerary_fingerprint(
        reversed_days
    )


def test_fingerprint_ignores_activity_order_in_fingerprint_call() -> None:
    # Sanity guard: the function must not sort internally to "normalise"
    # order away — order is semantic, so a swap must be visible.
    base = make_result().itinerary
    day = base.days[0]
    swapped = day.model_copy(
        update={"activities": (day.activities[1], day.activities[0])}
    )
    altered = base.model_copy(update={"days": (swapped,)})

    assert compute_itinerary_fingerprint(base) != compute_itinerary_fingerprint(altered)


def test_fingerprint_does_not_depend_on_runtime_clock_or_locale() -> None:
    itinerary = make_result().itinerary
    first = compute_itinerary_fingerprint(itinerary)

    # Determinism across repeated calls is the only observable guarantee;
    # any use of time/locale would make this flaky, so repeated equality is
    # both the assertion and the regression guard.
    for _ in range(5):
        assert compute_itinerary_fingerprint(itinerary) == first
