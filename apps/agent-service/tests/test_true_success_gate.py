"""TRUE_SUCCESS_GATE 防回归：只有完整行程才算真实成功。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_GATE_PATH = Path(__file__).resolve().parents[1] / "tools" / "true_success_gate.py"
_spec = importlib.util.spec_from_file_location("true_success_gate", _GATE_PATH)
gate = importlib.util.module_from_spec(_spec)
sys.modules["true_success_gate"] = gate  # dataclass 需要模块在 sys.modules 中
_spec.loader.exec_module(gate)


def _itinerary(days: int, activities_per_day: int = 1, with_poi: bool = True) -> dict:
    def _activity(i: int) -> dict:
        return {
            "title": f"POI-{i}",
            "providerPoiId": f"poi-{i}" if with_poi else None,
            "coordinates": {"longitude": 104.06, "latitude": 30.57} if with_poi else None,
        }

    return {
        "title": "成都四日",
        "days": [
            {
                "date": f"2026-09-{5 + i:02d}",
                "activities": [_activity(i) for i in range(activities_per_day)],
            }
            for i in range(days)
        ],
    }


def test_empty_completed_is_false_success() -> None:
    result = gate.run_gate(
        status="COMPLETED",
        itinerary={"title": "x", "days": []},
        start_date="2026-09-05",
        end_date="2026-09-08",
        map_markers=0,
        frontend_rendered=True,
        user_facing_non_empty=False,
    )
    assert result.verdict() == "FALSE_SUCCESS"
    assert {"days", "day_match", "activities", "persisted", "map", "user_facing"} <= {
        item.id for item in result.failures()
    }
    # status 是 COMPLETED → 单独通过，但结构/持久化/展示仍失败，故为 FALSE_SUCCESS。
    assert "status" not in {item.id for item in result.failures()}


def test_partial_day_count_is_false_success() -> None:
    result = gate.run_gate(
        status="COMPLETED",
        itinerary=_itinerary(days=1),
        start_date="2026-09-05",
        end_date="2026-09-08",
        map_markers=3,
        frontend_rendered=True,
        user_facing_non_empty=True,
    )
    assert result.verdict() == "FALSE_SUCCESS"
    assert "day_match" in {item.id for item in result.failures()}


def test_full_valid_trip_is_true_success() -> None:
    result = gate.run_gate(
        status="COMPLETED",
        itinerary=_itinerary(days=4),
        start_date="2026-09-05",
        end_date="2026-09-08",
        map_markers=12,
        frontend_rendered=True,
        user_facing_non_empty=True,
    )
    assert result.verdict() == "TRUE_SUCCESS"


def test_activity_without_poi_is_false_success() -> None:
    result = gate.run_gate(
        status="COMPLETED",
        itinerary=_itinerary(days=4, with_poi=False),
        start_date="2026-09-05",
        end_date="2026-09-08",
        map_markers=0,
        frontend_rendered=True,
        user_facing_non_empty=True,
    )
    assert result.verdict() == "FALSE_SUCCESS"
    assert "poi" in {item.id for item in result.failures()}