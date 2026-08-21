"""Q5+Q7: manual-edit TRANSIT real-provider closed loop on the isolated stack.

REAL_ONLY mode: create plan -> SUCCEEDED (real AMAP facts), then commit an
UPDATE_TRANSIT_LEG mode=TRANSIT edit -> candidate-validation async chain ->
AMap TRANSIT -> completion -> new version whose leg must be
mode=TRANSIT / provider=AMAP / estimated=false.

Bounded real AMap usage: one create-plan + one edit validation.
"""
import json
import sys
import time

sys.path.insert(0, "C:/Windows/Temp/opencode/qa-b14")
import b14lib as L  # noqa: E402

BASE = L.BASE  # http://127.0.0.1:38086


def main() -> None:
    user = L.new_user()
    print("register/login:", user["regStatus"])
    st, trip = L.create_trip(user["token"], title="QA manual TRANSIT")
    trip_id = trip["id"]
    print("trip:", trip_id)

    st, task, _ = L.start_planning(user["token"], trip_id)
    print("plan create:", st)
    terminal = L.poll_terminal(user["token"], trip_id, timeout_s=120)
    print("plan terminal:", terminal.get("status") if terminal else None)
    if terminal is None or terminal.get("status") != "SUCCEEDED":
        print("Q5 RESULT: FAIL plan not succeeded")
        return

    # baseline itinerary
    st_it, itinerary = L.http("GET", f"/api/trips/{trip_id}/itinerary", None, user["token"])
    print("itinerary:", st_it)
    if st_it != 200:
        print("Q5 RESULT: FAIL itinerary fetch")
        return
    version_id = itinerary["versionId"]
    days = itinerary["days"]
    legs = [leg for day in days for leg in day.get("transitLegs", [])]
    print("legs:", [(leg.get("mode"), leg.get("provider")) for leg in legs])
    if not legs:
        print("Q5 RESULT: FAIL no transit legs in baseline")
        return
    leg = legs[0]
    leg_id = leg["id"]

    # commit a TRANSIT mode edit on that leg
    body = {
        "baseVersionId": version_id,
        "edits": [
            {
                "baseVersionId": version_id,
                "operation": "UPDATE_TRANSIT_LEG",
                "transitLegId": leg_id,
                "transitMode": "TRANSIT",
                "transitLocked": False,
            }
        ],
    }
    st_commit, commit = L.http(
        "POST", f"/api/trips/{trip_id}/itinerary/edits/commit", body, user["token"],
        headers={"Idempotency-Key": str(uuid4())},
    )
    print("edit commit:", st_commit)
    if st_commit != 202:
        print("Q5 RESULT: FAIL commit", commit)
        return
    edit_terminal = L.poll_terminal(user["token"], trip_id, timeout_s=120)
    print("edit terminal:", edit_terminal.get("status") if edit_terminal else None)

    # fetch the new current itinerary and inspect the edited leg
    st2, it2 = L.http("GET", f"/api/trips/{trip_id}/itinerary", None, user["token"])
    legs2 = [leg for day in it2.get("days", []) for leg in day.get("transitLegs", [])]
    target = next((l for l in legs2 if l["id"] == leg_id), None)
    if target is None:
        print("Q5 RESULT: FAIL edited leg missing")
        return
    mode, provider, estimated = target.get("mode"), target.get("provider"), target.get("estimated")
    print("edited leg:", mode, provider, estimated)
    ok = (
        edit_terminal is not None
        and edit_terminal.get("status") in ("SUCCEEDED", "WAITING_USER")
        and mode == "TRANSIT"
        and provider == "AMAP"
        and estimated is False
    )
    print("Q5 RESULT:", "PASS" if ok else "FAIL",
          {"mode": mode, "provider": provider, "estimated": estimated,
           "editTerminal": edit_terminal.get("status") if edit_terminal else None})


def uuid4():
    import uuid
    return uuid.uuid4()


if __name__ == "__main__":
    main()
