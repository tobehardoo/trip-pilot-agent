"""B13-F — meal window source contract (DEFAULT | USER | DISABLED).

The source field is additive: historical payloads without a source parse as
USER so their hard-constraint semantics are never downgraded.
"""

import pytest
from plan_evaluation_support import make_command
from pydantic import ValidationError

from trip_agent.worker.contracts import MealWindow


def test_meal_window_source_defaults_to_user() -> None:
    window = MealWindow.model_validate(
        {"mealType": "LUNCH", "startTime": "12:00", "endTime": "13:00"}
    )
    assert window.source == "USER"


def test_all_three_sources_parse() -> None:
    for source in ("DEFAULT", "USER", "DISABLED"):
        window = MealWindow.model_validate(
            {
                "mealType": "DINNER",
                "startTime": "18:00",
                "endTime": "19:00",
                "source": source,
            }
        )
        assert window.source == source


def test_unknown_source_is_rejected() -> None:
    with pytest.raises(ValidationError):
        MealWindow.model_validate(
            {
                "mealType": "DINNER",
                "startTime": "18:00",
                "endTime": "19:00",
                "source": "HARD",
            }
        )


def test_create_command_accepts_source_without_new_schema_version() -> None:
    command = make_command(
        meal_windows=(
            {"mealType": "LUNCH", "startTime": "12:00", "endTime": "13:00", "source": "DEFAULT"},
            {"mealType": "DINNER", "startTime": "18:00", "endTime": "19:00", "source": "DISABLED"},
        )
    )
    windows = command.payload.trip.constraints.meal_windows
    assert [window.source for window in windows] == ["DEFAULT", "DISABLED"]


def test_source_less_command_windows_are_user() -> None:
    command = make_command(
        meal_windows=({"mealType": "LUNCH", "startTime": "12:00", "endTime": "13:00"},)
    )
    window = command.payload.trip.constraints.meal_windows[0]
    assert window.source == "USER"
