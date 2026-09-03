"""B8-5 / AUDIT-R6: run the four golden scenarios as real HTTP trips against the stack.

Verifies day-type semantics and must-visit coverage of the daily-skeleton
path end-to-end.  AUDIT-R6 repair (2026-09-03): payloads follow the current
contract — must-visit entries are canonicalized through the owner-authenticated
place search (``mustVisitPlaceRefs`` + selection token), future travel dates,
and the no-fake-hotel check accepts structural "待确认" placeholders instead
of asserting the absence of ACCOMMODATION nodes.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
import uuid

BASE = os.environ.get("TRIPPILOT_BASE", "http://127.0.0.1:8081")

SCENARIOS = [
    {
        "name": "1-广州下午到达/离开",
        "trip": {
            "destination": "广州", "startDate": "2026-10-16", "endDate": "2026-10-18",
            "title": "广州三日",
            "constraints": {
                "budgetAmount": 3000, "preferences": ["历史文化", "美食"],
                "mustVisitPlaces": ["陈家祠"], "fixedSchedules": [],
                "travelers": 1, "pace": "BALANCED", "travelerType": "SOLO",
                "arrival": {"placeName": "广州站", "time": "2026-10-16T14:00:00+08:00"},
                "departure": {"placeName": "广州南站", "time": "2026-10-18T16:00:00+08:00"},
            },
        },
        "expect_day_types": ["ARRIVAL_DAY", "FULL_DAY", "DEPARTURE_DAY"],
    },
    {
        "name": "2-泰安含泰山",
        "trip": {
            "destination": "泰安", "startDate": "2026-10-16", "endDate": "2026-10-18",
            "title": "泰安三日",
            "constraints": {
                "budgetAmount": 3000, "preferences": ["自然", "历史文化"],
                "mustVisitPlaces": ["泰山"], "fixedSchedules": [],
                "travelers": 1, "pace": "BALANCED", "travelerType": "SOLO",
            },
        },
        "expect_experience": "泰山",
    },
    {
        "name": "3-上海含迪士尼",
        "trip": {
            "destination": "上海", "startDate": "2026-10-17", "endDate": "2026-10-18",
            "title": "上海两日",
            "constraints": {
                "budgetAmount": 3000, "preferences": ["娱乐"],
                "mustVisitPlaces": ["上海迪士尼乐园"], "fixedSchedules": [],
                "travelers": 1, "pace": "BALANCED", "travelerType": "SOLO",
            },
        },
        "expect_experience": "迪士尼",
    },
    {
        "name": "4-老人轻游无锚点",
        "trip": {
            "destination": "广州", "startDate": "2026-10-17", "endDate": "2026-10-18",
            "title": "老人轻游",
            "constraints": {
                "budgetAmount": 3000, "preferences": [],
                "mustVisitPlaces": [], "fixedSchedules": [],
                "travelers": 3, "pace": "RELAXED", "travelerType": "FAMILY",
            },
        },
        "expect_no_fake_hotel": True,
    },
]


def api(method, path, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"raw": e.read().decode()[:200]}


def _ref_from_candidate(candidate):
    return {
        key: candidate[key]
        for key in (
            "provider", "providerPoiId", "name", "address", "province",
            "city", "district", "longitude", "latitude", "selectionToken",
        )
        if candidate.get(key) is not None
    }


def _looks_like_transport_infra(name):
    """Guard against picking a station/gate/parking POI as a must-visit:
    transport hubs stay selectable in the picker but are not sightseeing."""
    lowered = (name or "").lower()
    return (
        lowered.endswith("站")
        or any(marker in lowered for marker in (
            "地铁", "公交", "停车", "加油", "充电", "出入口",
            "进站口", "出站口", "服务区", "售票处", "(a入口)", "(d出口)",
        ))
    )


def choose_must_visit_ref(token, city, keyword):
    """Canonicalize a text must-visit through the owner place search.

    The current contract requires every must-visit to carry a server-signed
    PlaceRef; the picker already excludes never-schedulable kinds, so the
    first candidate whose name contains the keyword (and is not transport
    infrastructure) is the safest choice.
    """
    s, body = api("POST", "/api/trips/places/search",
                  {"city": city, "keyword": keyword, "limit": 5}, token=token)
    candidates = body.get("candidates") or []
    if not candidates:
        return None, None
    for candidate in candidates:
        name = candidate.get("name") or ""
        if keyword in name and not _looks_like_transport_infra(name):
            return name, _ref_from_candidate(candidate)
    for candidate in candidates:
        if not _looks_like_transport_infra(candidate.get("name") or ""):
            return candidate.get("name"), _ref_from_candidate(candidate)
    chosen = candidates[0]
    return chosen.get("name"), _ref_from_candidate(chosen)


def choose_anchor_ref(token, city, keyword):
    """Canonicalize an arrival/departure anchor (a transport hub is expected,
    so unlike must-visit picks, infrastructure names are allowed here)."""
    s, body = api("POST", "/api/trips/places/search",
                  {"city": city, "keyword": keyword, "limit": 5}, token=token)
    candidates = body.get("candidates") or []
    if not candidates:
        return None
    for candidate in candidates:
        if keyword in (candidate.get("name") or ""):
            return _ref_from_candidate(candidate)
    return _ref_from_candidate(candidates[0])


def prepare_trip(token, scenario):
    """Deep-copy the scenario trip and canonicalize must-visit refs and any
    arrival/departure anchors through the owner place search."""
    trip = json.loads(json.dumps(scenario["trip"]))
    constraints = trip["constraints"]
    must = constraints.get("mustVisitPlaces") or []
    names = []
    refs = []
    failures = []
    for name in must:
        chosen_name, ref = choose_must_visit_ref(token, trip["destination"], name)
        if ref is None:
            failures.append(name)
            continue
        names.append(chosen_name)
        refs.append(ref)
    constraints["mustVisitPlaces"] = names
    if refs:
        constraints["mustVisitPlaceRefs"] = refs
    else:
        constraints.pop("mustVisitPlaceRefs", None)
    for anchor_key in ("arrival", "departure"):
        anchor = constraints.get(anchor_key)
        if not anchor or anchor.get("placeRef"):
            continue
        anchor_ref = choose_anchor_ref(
            token, trip["destination"], anchor.get("placeName")
        )
        if anchor_ref is None:
            failures.append(f"{anchor_key}:{anchor.get('placeName')}")
            continue
        anchor["placeRef"] = anchor_ref
    return trip, failures


def plan_trip(token, trip):
    s, created = api("POST", "/api/trips", trip, token=token)
    if s not in (200, 201):
        return {"status": f"TRIP_FAIL({s})", "detail": created.get("message", "")}
    trip_id = created["id"]
    req = urllib.request.Request(
        f"{BASE}/api/trips/{trip_id}/planning-tasks", data=b"", method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}",
                 "Idempotency-Key": str(uuid.uuid4())},
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            task = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"status": f"TASK_FAIL({e.code})"}
    task_id = task["taskId"]
    # 8-minute cap: anchored trips (arrival/departure deadlines) legitimately
    # take minutes; fast scenarios exit on the first terminal status anyway.
    for _ in range(240):
        time.sleep(2)
        s, ts = api("GET", f"/api/planning-tasks/{task_id}", token=token)
        st = ts.get("status", "?")
        if st in ("SUCCEEDED", "COMPLETED", "FAILED", "CANCELLED"):
            if st in ("SUCCEEDED", "COMPLETED"):
                s2, itin = api("GET", f"/api/trips/{trip_id}/itinerary", token=token)
                return {
                    "status": "OK",
                    "itinerary": itin,
                    "score": (ts.get("evaluation") or {}).get("overallScore"),
                }
            return {
                "status": st,
                "errorCode": ts.get("errorCode"),
                "message": ts.get("safeMessage"),
            }
    return {"status": "TIMEOUT"}


def _fabricated_hotels(activities):
    """A hotel is fabricated only when a name/identity is claimed for an
    accommodation the user never requested; structural '住宿地点待确认'
    placeholders (no provider POI) are honest and allowed."""
    fabricated = []
    for activity in activities:
        if activity.get("kind") != "ACCOMMODATION":
            continue
        title = activity.get("title") or ""
        if activity.get("providerPoiId") or "待确认" not in title:
            fabricated.append(title)
    return fabricated


def main():
    uid = str(uuid.uuid4())[:8]
    s, reg = api("POST", "/api/auth/register", {
        "username": f"gs{uid}", "password": "Golden123456!",
        "confirmPassword": "Golden123456!",
        "displayName": "GS", "email": f"gs{uid}@test.local",
    })
    token = reg["accessToken"]
    overall_ok = True
    for sc in SCENARIOS:
        checks = []
        scenario_ok = True
        res = None
        trip, missing = prepare_trip(token, sc)
        if missing:
            checks.append(f"PLACE_SEARCH_MISSING={missing}")
            scenario_ok = False
        else:
            res = plan_trip(token, trip)
            if res["status"] != "OK":
                checks.append(f"STATUS={res['status']} detail={res.get('message') or res.get('detail') or ''}")
                scenario_ok = False
            else:
                days = res["itinerary"].get("days", [])
                activities = [a for d in days for a in d.get("activities", [])]
                types = [d.get("dayType") for d in days]
                if "expect_day_types" in sc:
                    matched = types == sc["expect_day_types"]
                    checks.append(f"types={types} expect={sc['expect_day_types']} -> {'OK' if matched else 'MISMATCH'}")
                    scenario_ok = scenario_ok and matched
                if "expect_experience" in sc:
                    exp = [
                        a.get("title")
                        for a in activities
                        if a.get("kind") in ("EXPERIENCE", "ATTRACTION")
                    ]
                    matched = any(sc["expect_experience"] in (t or "") for t in exp)
                    checks.append(f"sights={exp} expect~{sc['expect_experience']} -> {'OK' if matched else 'MISSING'}")
                    scenario_ok = scenario_ok and matched
                if sc.get("expect_no_fake_hotel"):
                    fabricated = _fabricated_hotels(activities)
                    checks.append(f"fake_hotels={fabricated} -> {'OK' if not fabricated else 'FAKE_HOTEL'}")
                    scenario_ok = scenario_ok and not fabricated
        overall_ok = overall_ok and scenario_ok
        print(f"[{'PASS' if scenario_ok else 'FAIL'}] {sc['name']}: {checks} score={res.get('score') if res else ''}")
    print("GOLDEN_OVERALL=", "PASS" if overall_ok else "FAIL")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
