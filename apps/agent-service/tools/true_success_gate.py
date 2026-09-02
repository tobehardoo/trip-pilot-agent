"""TRUE_SUCCESS_GATE —— 统一的真实成功验收闸（M0 新增）。

任何「规划完成」都不能仅凭 COMPLETED 状态宣布成功；必须同时满足：

  1. status == COMPLETED
  2. itinerary exists（persisted 读取成功）
  3. days > 0
  4. days == expected_days（= end_date - start_date + 1）
  5. every day has >= 1 activity
  6. every activity has a valid POI（title 非空 + 有坐标/可定位）
  7. persisted itinerary 非空（后端落库的证据）
  8. frontend itinerary rendered（前端拿到的行程非空）
  9. map markers > 0（地图有定位点）
 10. required user-facing result 非空（预算/攻略/日期等关键展示）

输出只能是 TRUE_SUCCESS 或 FALSE_SUCCESS，并列出全部缺失项。

可作库函数（gate 返回条目级结果）也可作 CLI：
  python tools/true_success_gate.py --itinerary-json out.json ...
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GateItem:
    id: str
    label: str
    passed: bool
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.passed


@dataclass
class GateResult:
    items: list[GateItem] = field(default_factory=list)

    @property
    def all_pass(self) -> bool:
        return all(item.ok for item in self.items)

    def verdict(self) -> str:
        return "TRUE_SUCCESS" if self.all_pass else "FALSE_SUCCESS"

    def failures(self) -> list[GateItem]:
        return [item for item in self.items if not item.ok]


def expected_days(start_date: str, end_date: str) -> int:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    return (end - start).days + 1


def run_gate(
    *,
    status: str,
    itinerary: dict[str, Any] | None,
    start_date: str,
    end_date: str,
    map_markers: int,
    frontend_rendered: bool,
    user_facing_non_empty: bool,
) -> GateResult:
    result = GateResult()

    # 1. 状态
    result.items.append(
        GateItem("status", "status == COMPLETED", str(status).lower() == "completed",
                 f"actual={status}")
    )
    # 2. itinerary 存在
    result.items.append(
        GateItem("itinerary", "itinerary exists", itinerary is not None,
                 "itinerary is None" if itinerary is None else "")
    )
    # 3/4/5/6. 结构
    if itinerary is None:
        for item_id, label in (
            ("days", "days > 0"),
            ("day_match", "days == expected"),
            ("activities", "every day >= 1 activity"),
            ("poi", "every activity valid POI"),
        ):
            result.items.append(GateItem(item_id, label, False, "itinerary missing"))
    else:
        days = itinerary.get("days") or []
        has_days = len(days) > 0
        result.items.append(GateItem("days", "days > 0", has_days, f"days={len(days)}"))
        exp = expected_days(start_date, end_date)
        result.items.append(
            GateItem("day_match", "days == expected", has_days and len(days) == exp,
                     f"days={len(days)} expected={exp}")
        )
        every_day_has_activity = has_days and all(
            bool(day.get("activities")) for day in days
        )
        result.items.append(
            GateItem("activities", "every day >= 1 activity", every_day_has_activity,
                     "" if every_day_has_activity else "some day has 0 activities")
        )
        valid_pois = has_days and all(
            bool(act.get("title"))
            and (act.get("coordinates") or act.get("providerPoiId") or act.get("latitude"))
            for day in days
            for act in (day.get("activities") or [])
        )
        result.items.append(
            GateItem("poi", "every activity valid POI", valid_pois,
                     "" if valid_pois else "some activity lacks POI/location")
        )
    # 7. persisted（由调用方给出：后端读取到的行程非空即视为已落库）
    result.items.append(
        GateItem("persisted", "persisted itinerary non-empty",
                 itinerary is not None and bool(itinerary.get("days")),
                 "" if itinerary and itinerary.get("days") else "no persisted days")
    )
    # 8. frontend rendered
    result.items.append(
        GateItem("frontend", "frontend itinerary rendered", frontend_rendered,
                 f"rendered={frontend_rendered}")
    )
    # 9. map markers
    result.items.append(
        GateItem("map", "map markers > 0", map_markers > 0, f"markers={map_markers}")
    )
    # 10. user-facing result non-empty
    result.items.append(
        GateItem("user_facing", "required user-facing result non-empty",
                 user_facing_non_empty, f"non_empty={user_facing_non_empty}")
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="TRUE_SUCCESS_GATE")
    parser.add_argument("--status", required=True)
    parser.add_argument("--itinerary-json", required=True, help="persisted itinerary JSON file")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--map-markers", type=int, default=0)
    parser.add_argument("--frontend-rendered", action="store_true", default=False)
    parser.add_argument("--user-facing", action="store_true", default=False)
    args = parser.parse_args()

    itinerary = json.loads(Path(args.itinerary_json).read_text(encoding="utf-8"))
    result = run_gate(
        status=args.status,
        itinerary=itinerary,
        start_date=args.start_date,
        end_date=args.end_date,
        map_markers=args.map_markers,
        frontend_rendered=args.frontend_rendered,
        user_facing_non_empty=args.user_facing,
    )
    print(result.verdict())
    for item in result.items:
        flag = "PASS" if item.ok else "FAIL"
        print(f"  [{flag}] {item.label} {('(' + item.detail + ')') if item.detail else ''}")
    return 0 if result.all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
