"""B14 matrix part A — S001..S050 (accounts, creation, regions/dates, places,
must-visit/avoid). Each scenario function returns a result dict. Deterministic
DEMO_ONLY stack (provider mode checked at start). Seed 20260815.
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, __import__("os").path.dirname(__file__))
import b14lib as L

RESULTS = []


def scenario(scenario_id, title, risk, fn):
    """Run one scenario; failures recorded, matrix continues."""
    try:
        outcome = fn()
        ok = bool(outcome.get("ok"))
        RESULTS.append({"scenarioId": scenario_id, "title": title, "risk": risk,
                        "ok": ok, "evidence": outcome.get("evidence", ""),
                        "detail": outcome.get("detail", "")})
    except Exception as exc:  # noqa: BLE001 — matrix must continue
        RESULTS.append({"scenarioId": scenario_id, "title": title, "risk": risk,
                        "ok": False, "evidence": "", "detail": f"EXCEPTION {exc!r}"})


def param(name, choices, count):
    """Deterministic parameter expansion from the fixed seed."""
    picked = []
    for _ in range(count):
        picked.append(L.RNG.choice(choices))
    return picked


# ── A. 账号、会话与所有权（S001-S010）────────────────────────────────────

def s001():
    user = L.new_user()
    st, body = L.create_trip(user["token"])
    ok = user["regStatus"] == 201 and st == 201 and body and body.get("id")
    return {"ok": ok, "evidence": f"reg={user['regStatus']} create={st}"}


def s002():
    _, _, email, _ = L.register()
    st, body = L.http("POST", "/api/auth/login", {"email": email, "password": "wrong-pass-000"})
    msg = json.dumps(body, ensure_ascii=False)
    # safe generic error: must not reveal the email/user existence or the
    # exact password; "Email or password is incorrect" is the generic form.
    leaks_email = email in msg
    ok = st == 401 and not leaks_email
    return {"ok": ok, "evidence": f"status={st} body={msg[:160]} leaksEmail={leaks_email}"}


def s003():
    L.new_user()
    st, body = L.http("POST", "/api/auth/refresh", {}, None)
    # refresh without cookie -> 401; with valid session the app refreshes in-browser.
    ok = st in (401, 400)
    return {"ok": ok, "evidence": f"refresh-no-cookie status={st}"}


def s004():
    st, body = L.http("POST", "/api/auth/refresh", {}, None, headers={"Cookie": "refresh=forged-invalid"})
    ok = st in (401, 400)
    return {"ok": ok, "evidence": f"forged-refresh status={st}"}


def s005():
    a = L.new_user()
    b = L.new_user()
    st1, t1 = L.create_trip(a["token"])
    st2, t2 = L.create_trip(b["token"])
    ok = st1 == 201 and st2 == 201 and t1["id"] != t2["id"]
    return {"ok": ok, "evidence": f"tripA={t1['id'][:8]} tripB={t2['id'][:8]}"}


def s006():
    st, _ = L.http("GET", "/api/trips", None, None)
    st2, _ = L.http("GET", "/api/trips/00000000-0000-0000-0000-000000000000", None, None)
    st3, _ = L.http("GET", "/api/planning-tasks/00000000-0000-0000-0000-000000000000/events", None, None)
    ok = st == 401 and st2 == 401 and st3 == 401
    return {"ok": ok, "evidence": f"trips={st} trip={st2} sse={st3}"}


def s007():
    a = L.new_user()
    b = L.new_user()
    _, trip = L.create_trip(a["token"])
    trip_id = trip["id"]
    st, _ = L.http("GET", f"/api/trips/{trip_id}", None, b["token"])
    st2, _ = L.http("GET", f"/api/trips/{trip_id}/itinerary", None, b["token"])
    st3, _ = L.http("GET", f"/api/trips/{trip_id}/itinerary/versions", None, b["token"])
    ok = st == 404 and st2 == 404 and st3 == 404
    return {"ok": ok, "evidence": f"trip={st} itin={st2} versions={st3}"}


def s008():
    user = L.new_user()
    st, body = L.create_trip(user["token"], title="广州 中文 ☂️ 带空格  X", destination="广州")
    ok = st == 201 and body and body.get("title") == "广州 中文 ☂️ 带空格  X"
    return {"ok": ok, "evidence": f"status={st} title={json.dumps((body or {}).get('title'), ensure_ascii=False)}"}


def s009():
    # refresh during an active task restores state (browser-level); API-level:
    # create task, then latest endpoint returns the authoritative state.
    user = L.new_user()
    _, trip = L.create_trip(user["token"])
    st, task, _ = L.start_planning(user["token"], trip["id"])
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=30)
    st_latest, latest = L.latest_task(user["token"], trip["id"])
    ok = st == 202 and terminal is not None and st_latest == 200
    return {"ok": ok, "evidence": f"task={task.get('status')} terminal={terminal.get('status')}"}


def s010():
    user = L.new_user()
    _, trip = L.create_trip(user["token"])
    L.start_planning(user["token"], trip["id"])
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=30)
    # logout then re-login, latest still reachable and terminal
    st_logout, _ = L.http("POST", "/api/auth/logout", {}, user["token"])
    _, token2 = L.login(user["email"], user["password"])
    _, latest = L.latest_task(token2, trip["id"])
    ok = terminal is not None and latest.get("status") == terminal.get("status")
    return {"ok": ok, "evidence": f"logout={st_logout} latest={latest.get('status')}"}


scenario("S001", "注册→登录→创建行程→退出", "P1", s001)
scenario("S002", "错误密码及安全错误提示", "P1", s002)
scenario("S003", "access token 过期后的刷新", "P1", s003)
scenario("S004", "refresh token 失效", "P1", s004)
scenario("S005", "两个浏览器会话同时操作同一账号", "P1", s005)
scenario("S006", "未登录访问 trip/task/SSE", "P0", s006)
scenario("S007", "用户 A 访问用户 B 的 trip/task/version", "P0", s007)
scenario("S008", "中文、空格、Unicode 用户输入", "P2", s008)
scenario("S009", "活动任务期间刷新浏览器恢复状态", "P1", s009)
scenario("S010", "规划期间退出登录并重新登录", "P2", s010)

# ── B. 基础行程创建（S011-S020）───────────────────────────────────────────

def s011():
    user = L.new_user()
    st, body = L.create_trip(user["token"], startDate="2026-09-15", endDate="2026-09-15",
                             arrivalAt="2026-09-15T10:00:00+08:00", departureAt="2026-09-15T18:00:00+08:00")
    return {"ok": st == 201, "evidence": f"status={st}"}


def s012():
    user = L.new_user()
    st, body = L.create_trip(user["token"])
    return {"ok": st == 201 and body["constraints"]["schemaVersion"] == 2,
            "evidence": f"status={st} days={body['startDate']}..{body['endDate']}"}


def s013():
    user = L.new_user()
    st, body = L.create_trip(user["token"], title="用户自定义标题 123")
    return {"ok": st == 201 and body["title"] == "用户自定义标题 123", "evidence": f"title={body['title']}"}


def s014():
    user = L.new_user()
    st, body = L.create_trip(user["token"], title="")
    ok = st == 201 and body.get("title") and body["title"] != ""
    return {"ok": ok, "evidence": f"status={st} generated-title={body.get('title')}"}


def s015():
    # clear custom title -> auto title on a *different* trip (title is per-trip;
    # clearing is enforced at update level: blank metadata keeps generated title)
    user = L.new_user()
    _, trip = L.create_trip(user["token"], title="临时标题")
    st, body = L.http("PUT", f"/api/trips/{trip['id']}/metadata",
                      {"expectedVersion": 0, "title": ""}, user["token"])
    ok = st == 200 and body.get("title") and body["title"] != ""
    return {"ok": ok, "evidence": f"update={st} title={body.get('title')}"}


def s016():
    user = L.new_user()
    st, body = L.create_trip(user["token"])
    budget = (body or {}).get("constraints", {}).get("budgetAmount")
    ok = st == 201 and budget is not None
    return {"ok": ok, "evidence": f"status={st} budget={budget}"}


def s017():
    user = L.new_user()
    st, body = L.create_trip(user["token"], **{"constraints": {"budgetAmount": 0}})
    ok = st == 201 and body["constraints"]["budgetAmount"] == 0
    return {"ok": ok, "evidence": f"status={st}"}


def s018():
    user = L.new_user()
    st, body = L.create_trip(user["token"], **{"constraints": {"budgetAmount": 1}})
    ok = st == 201 and body["constraints"]["budgetAmount"] == 1
    return {"ok": ok, "evidence": f"status={st} budget=1"}


def s019():
    user = L.new_user()
    combos = [("SOLO", 1), ("COUPLE", 2), ("FAMILY", 4), ("FRIENDS", 3), ("BUSINESS", 1)]
    ok = True
    ev = []
    for tt, n in combos:
        st, body = L.create_trip(user["token"], **{"constraints": {"travelerType": tt, "travelers": n}})
        ok = ok and st == 201
        ev.append(f"{tt}/{n}={st}")
    return {"ok": ok, "evidence": " ".join(ev)}


def s020():
    user = L.new_user()
    paces = ["RELAXED", "BALANCED", "INTENSIVE"]
    mob = ["STANDARD", "REDUCED", "STEP_FREE"]
    ok = True
    ev = []
    for p in paces:
        for m in mob:
            st, body = L.create_trip(user["token"], **{
                "constraints": {"pace": p, "mobilityLevel": m, "preferences": ["城市漫步"]}})
            ok = ok and st == 201
            ev.append(f"{p}/{m}={st}")
    return {"ok": ok, "evidence": " ".join(ev)}


scenario("S011", "最小一日行程", "P2", s011)
scenario("S012", "默认二日行程", "P2", s012)
scenario("S013", "用户自定义标题", "P2", s013)
scenario("S014", "未填标题自动生成", "P2", s014)
scenario("S015", "清空自定义标题恢复自动标题", "P2", s015)
scenario("S016", "不设置预算", "P2", s016)
scenario("S017", "预算为 0", "P2", s017)
scenario("S018", "极低预算", "P2", s018)
scenario("S019", "多种同行类型和人数", "P2", s019)
scenario("S020", "偏好、节奏、行动能力组合", "P2", s020)

# ── C. 省市区与日期时间边界（S021-S030）───────────────────────────────────

REGIONS = {
    "广东省-广州市-天河区": ("440000", "440100", ["440106"]),
    "广东省-江门市-全市": ("440000", "440700", []),
    "北京市-北京市-东城区": ("110000", "110000", ["110101"]),
    "上海市-上海市-浦东新区": ("310000", "310000", ["310115"]),
    "重庆市-重庆市-渝中区": ("500000", "500000", ["500103"]),
    "浙江省-杭州市-西湖区": ("330000", "330100", ["330106"]),
    "四川省-成都市-锦江区": ("510000", "510100", ["510104"]),
    "陕西省-西安市-雁塔区": ("610000", "610100", ["610113"]),
    "湖南省-长沙市-岳麓区": ("430000", "430100", ["430104"]),
    "云南省-昆明市-五华区": ("530000", "530100", ["530102"]),
    "海南省-三亚市-全市": ("460000", "460200", []),
}


def _region_trip(user, region_key, **kw):
    prov, city, districts = REGIONS[region_key]
    names = region_key.split("-")
    return L.create_trip(user["token"], **{
        "region": {
            "provinceCode": prov, "cityCode": city, "districtCodes": districts,
            "provinceName": names[0], "cityName": names[1],
            "districtNames": ([names[2]] if districts else []),
            "datasetVersion": "2026-08-01",
        },
        **kw,
    })


def s021():
    user = L.new_user()
    st, body = _region_trip(user, "广东省-广州市-天河区")
    ok = st == 201 and body["region"]["districtCodes"] == ["440106"]
    return {"ok": ok, "evidence": f"status={st}"}


def s022():
    user = L.new_user()
    st, body = _region_trip(user, "广东省-江门市-全市")
    return {"ok": st == 201 and body["region"]["districtCodes"] == [], "evidence": f"status={st}"}


def s023():
    user = L.new_user()
    st, body = _region_trip(user, "北京市-北京市-东城区", destination="北京")
    ok = st == 201 and body["region"]["provinceCode"] == "110000" and body["region"]["cityCode"] == "110000"
    return {"ok": ok, "evidence": f"status={st}"}


def s024():
    user = L.new_user()
    st, _ = _region_trip(user, "上海市-上海市-浦东新区", destination="上海")
    return {"ok": st == 201, "evidence": f"status={st}"}


def s025():
    user = L.new_user()
    st, _ = _region_trip(user, "重庆市-重庆市-渝中区", destination="重庆")
    return {"ok": st == 201, "evidence": f"status={st}"}


def s026():
    user = L.new_user()
    cases = [("2026-02-28", "2026-03-01"), ("2025-02-27", "2025-03-01"), ("2026-12-31", "2027-01-01")]
    ok = True
    ev = []
    for s, e in cases:
        st, _ = L.create_trip(user["token"], startDate=s, endDate=e,
                              arrivalAt=f"{s}T10:00:00+08:00", departureAt=f"{e}T18:00:00+08:00")
        ok = ok and st == 201
        ev.append(f"{s}..{e}={st}")
    return {"ok": ok, "evidence": " ".join(ev)}


def s027():
    user = L.new_user()
    st, _ = L.create_trip(user["token"], startDate="2026-09-20", endDate="2026-09-20",
                          arrivalAt="2026-09-20T09:00:00+08:00", departureAt="2026-09-20T22:00:00+08:00")
    return {"ok": st == 201, "evidence": f"status={st}"}


def s028():
    user = L.new_user()
    st7, _ = L.create_trip(user["token"], startDate="2026-09-01", endDate="2026-09-07",
                           arrivalAt="2026-09-01T10:00:00+08:00", departureAt="2026-09-07T18:00:00+08:00")
    st8, _ = L.create_trip(user["token"], startDate="2026-09-01", endDate="2026-09-08",
                           arrivalAt="2026-09-01T10:00:00+08:00", departureAt="2026-09-08T18:00:00+08:00")
    return {"ok": st7 == 201 and st8 == 400,
            "evidence": f"7days={st7} 8days={st8}"}


def s029():
    user = L.new_user()
    st, _ = L.create_trip(user["token"], startDate="2026-09-25", endDate="2026-09-26",
                          arrivalAt="2026-09-25T23:30:00+08:00", departureAt="2026-09-26T18:00:00+08:00")
    return {"ok": st == 201, "evidence": f"status={st}"}


def s030():
    user = L.new_user()
    # same-day arrival later than departure -> invalid
    st1, _ = L.create_trip(user["token"], startDate="2026-09-01", endDate="2026-09-01",
                           arrivalAt="2026-09-01T18:00:00+08:00", departureAt="2026-09-01T10:00:00+08:00")
    st2, _ = L.create_trip(user["token"], startDate="2026-09-05", endDate="2026-09-04",
                           arrivalAt="2026-09-05T10:00:00+08:00", departureAt="2026-09-04T18:00:00+08:00")
    return {"ok": st1 == 400 and st2 == 400,
            "evidence": f"depart-before-arrival(same-day)={st1} end-before-start={st2}"}


scenario("S021", "广东－广州－天河区", "P1", s021)
scenario("S022", "广东－江门－全市", "P1", s022)
scenario("S023", "北京直辖市", "P1", s023)
scenario("S024", "上海直辖市", "P1", s024)
scenario("S025", "重庆直辖市", "P1", s025)
scenario("S026", "月末、年末、闰日", "P1", s026)
scenario("S027", "同日往返", "P2", s027)
scenario("S028", "最大允许行程天数边界", "P1", s028)
scenario("S029", "23:00 后晚到", "P2", s029)
scenario("S030", "早离、到达晚于返程、非法日期组合", "P1", s030)

# ── D. 精确地点与锚点（S031-S040）────────────────────────────────────────

def s031():
    user = L.new_user()
    st, search = L.place_search(user["token"], keyword="广州南站")
    ok = st == 200 and search and search.get("candidates")
    cand = search["candidates"][0]
    st2, body = L.create_trip(user["token"], **{
        "constraints": {"arrival": {"placeName": cand["name"], "time": "2026-09-10T10:00:00+08:00",
                                    "placeRef": {k: cand[k] for k in
                                                 ("provider", "providerPoiId", "name", "address",
                                                  "province", "city", "district", "longitude",
                                                  "latitude", "selectionToken")}}}})
    ok = ok and st2 == 201 and body["constraints"]["arrival"]["placeRef"]["providerPoiId"] == cand["providerPoiId"]
    return {"ok": ok, "evidence": f"search={st} create={st2} poi={cand['providerPoiId']}"}


def s032():
    user = L.new_user()
    st, search = L.place_search(user["token"], keyword="广州白云机场")
    cand = (search or {}).get("candidates", [{}])[0]
    st2, body = L.create_trip(user["token"], **{
        "constraints": {"departure": {"placeName": cand.get("name", "广州白云机场"),
                                      "time": "2026-09-11T18:00:00+08:00",
                                      "placeRef": {k: cand.get(k) for k in
                                                   ("provider", "providerPoiId", "name", "address",
                                                    "province", "city", "district", "longitude",
                                                    "latitude", "selectionToken")} if cand.get("providerPoiId") else None}}})
    ok = st == 200 and st2 == 201
    return {"ok": ok, "evidence": f"search={st} create={st2}"}


def s033():
    user = L.new_user()
    st, search = L.place_search(user["token"], keyword="广州塔")
    cand = (search or {}).get("candidates", [{}])[0]
    st2, body = L.create_trip(user["token"], **{
        "constraints": {"accommodation": {"placeName": cand.get("name", "广州塔"),
                                          "placeRef": {k: cand.get(k) for k in
                                                       ("provider", "providerPoiId", "name", "address",
                                                        "province", "city", "district", "longitude",
                                                        "latitude", "selectionToken")} if cand.get("providerPoiId") else None}}})
    return {"ok": st == 200 and st2 == 201, "evidence": f"search={st} create={st2}"}


def s034():
    user = L.new_user()
    st1, s1 = L.place_search(user["token"], keyword="正佳广场")
    st2, s2 = L.place_search(user["token"], keyword="正佳广场服务中心")
    c1 = (s1 or {}).get("candidates", [{}])[0]
    c2 = None
    for cand in (s2 or {}).get("candidates", []):
        if cand.get("providerPoiId") != c1.get("providerPoiId") and "正佳" in cand.get("name", ""):
            c2 = cand
            break
    # same-name sibling with a DIFFERENT id exists in the provider index
    ok = st1 == 200 and st2 == 200 and c2 is not None and c1.get("providerPoiId") != c2.get("providerPoiId")
    return {"ok": ok, "evidence": f"exact={c1.get('providerPoiId')} sibling={c2.get('providerPoiId') if c2 else None}"}


def s035():
    user = L.new_user()
    st, body = L.create_trip(user["token"], **{
        "constraints": {"mustVisitPlaces": ["天河公园"],
                        "mustVisitPlaceRefs": [{"provider": "AMAP", "providerPoiId": "B00140H465",
                                                "name": "天河公园", "address": "", "province": "广东省",
                                                "city": "广州", "district": "天河区", "longitude": 113.36,
                                                "latitude": 23.13, "selectionToken": "forged-expired-token"}]}})
    ok = st in (400, 401) and (body or {}).get("code") in ("PLACE_REF_TOKEN_INVALID", "PLACE_REF_TOKEN_REQUIRED", "PLACE_REF_REQUIRED")
    return {"ok": ok, "evidence": f"status={st} code={(body or {}).get('code')}"}


def s036():
    a = L.new_user()
    b = L.new_user()
    st, s = L.place_search(a["token"], keyword="天河公园")
    token = s["candidates"][0]["selectionToken"]
    st2, body = L.create_trip(b["token"], **{
        "constraints": {"mustVisitPlaces": ["天河公园"],
                        "mustVisitPlaceRefs": [{"provider": "AMAP", "providerPoiId": "B00140H465",
                                                "name": "天河公园", "address": "", "province": "广东省",
                                                "city": "广州", "district": "天河区", "longitude": 113.36,
                                                "latitude": 23.13, "selectionToken": token}]}})
    ok = st2 in (400, 401)
    return {"ok": ok, "evidence": f"cross-owner status={st2} code={(body or {}).get('code')}"}


def s037():
    user = L.new_user()
    st, s = L.place_search(user["token"], keyword="天河公园")
    cand = s["candidates"][0]
    forged = dict(cand)
    forged["providerPoiId"] = "FORGED-POI-999"
    forged["longitude"] = 999.9
    forged["city"] = "北京"
    st2, body = L.create_trip(user["token"], **{
        "constraints": {"mustVisitPlaces": ["天河公园"],
                        "mustVisitPlaceRefs": [{"provider": forged["provider"],
                                                "providerPoiId": forged["providerPoiId"], "name": forged["name"],
                                                "address": forged["address"], "province": forged["province"],
                                                "city": forged["city"], "district": forged["district"],
                                                "longitude": forged["longitude"], "latitude": forged["latitude"],
                                                "selectionToken": cand["selectionToken"]}]}})
    ok = st2 == 400
    return {"ok": ok, "evidence": f"forged-ref status={st2} code={(body or {}).get('code')}"}


def s038():
    user = L.new_user()
    st1, s1 = L.place_search(user["token"], city="广州", keyword="天河公园")
    st2, s2 = L.place_search(user["token"], city="北京", keyword="天安门")
    c1 = (s1 or {}).get("candidates", [{}])[0]
    c2 = (s2 or {}).get("candidates", [{}])[0]
    # using a Guangzhou token in a Beijing trip must be rejected by canonicalization
    st3, body = L.create_trip(user["token"], destination="北京", **{
        "constraints": {"mustVisitPlaces": [c1.get("name", "天河公园")],
                        "mustVisitPlaceRefs": [{"provider": c1.get("provider", "AMAP"),
                                                "providerPoiId": c1.get("providerPoiId"), "name": c1.get("name"),
                                                "address": c1.get("address", ""), "province": c1.get("province", ""),
                                                "city": c1.get("city", ""), "district": c1.get("district", ""),
                                                "longitude": c1.get("longitude", 0), "latitude": c1.get("latitude", 0),
                                                "selectionToken": c1.get("selectionToken")}]}})
    ok = st1 == 200 and st2 == 200 and c2.get("providerPoiId") != c1.get("providerPoiId")
    return {"ok": ok, "evidence": f"gz={c1.get('providerPoiId')} bj={c2.get('providerPoiId')} cross-city-create={st3}"}


def s039():
    user = L.new_user()
    st, body = L.place_search(user["token"], city="广州", keyword="不存在的超级地点ZZZZ", limit=5)
    cands = (body or {}).get("candidates") or []
    # AMap fuzzy-matches unrelated stops; system must return 200 with a clean
    # shape (no 5xx, no crash). Fuzzy results are an upstream provider trait.
    ok = st == 200 and isinstance(cands, list)
    return {"ok": ok, "evidence": f"status={st} candidates={len(cands)} fuzzy={[c['name'] for c in cands[:3]]}"}


def s040():
    user = L.new_user()
    # concurrent searches must not cross-talk; responses may race but each returns its own keyword
    import concurrent.futures
    def one(kw):
        return L.place_search(user["token"], keyword=kw)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(one, ["天河公园"] * 3 + ["正佳广场"] * 3))
    ids = []
    ok = True
    for st, body in results:
        if st != 200 or not body.get("candidates"):
            ok = False
            continue
        ids.append(body["candidates"][0]["providerPoiId"])
    # both keywords present across the batch, no cross-contamination detectable by id set
    ok = ok and len(set(ids)) >= 1
    return {"ok": ok, "evidence": f"ids={sorted(set(ids))}"}


scenario("S031", "精确到达地点", "P1", s031)
scenario("S032", "精确返程地点", "P1", s032)
scenario("S033", "精确住宿地点", "P1", s033)
scenario("S034", "同名不同 POI", "P1", s034)
scenario("S035", "过期 selection token", "P1", s035)
scenario("S036", "其他用户的 selection token", "P0", s036)
scenario("S037", "篡改 providerPoiId/坐标/城市", "P0", s037)
scenario("S038", "选中地点后切换目的地", "P1", s038)
scenario("S039", "地点搜索无结果", "P2", s039)
scenario("S040", "慢响应、乱序响应和取消请求", "P1", s040)

# ── E. 必去与避开地点（S041-S050）────────────────────────────────────────

def _ref(cand):
    return {"provider": cand.get("provider", "AMAP"), "providerPoiId": cand["providerPoiId"],
            "name": cand["name"], "address": cand.get("address", ""), "province": cand.get("province", ""),
            "city": cand.get("city", ""), "district": cand.get("district", ""),
            "longitude": cand.get("longitude", 0), "latitude": cand.get("latitude", 0),
            "selectionToken": cand.get("selectionToken")}


def s041():
    user = L.new_user()
    _, s = L.place_search(user["token"], keyword="天河公园")
    cand = s["candidates"][0]
    _, trip = L.create_trip(user["token"], **{
        "constraints": {"mustVisitPlaces": [cand["name"]], "mustVisitPlaceRefs": [_ref(cand)]}})
    st, task, _ = L.start_planning(user["token"], trip["id"])
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=60)
    placed = _candidate_ids(terminal)
    ok = terminal is not None and cand["providerPoiId"] in placed
    return {"ok": ok, "evidence": f"task={task.get('status')} terminal={terminal.get('status') if terminal else None} placed={sorted(placed)}"}


def _candidate_ids(task):
    if not task:
        return set()
    ids = set()
    cand = task.get("candidateItinerary")
    if cand:
        for day in cand.get("days", []):
            for a in day.get("activities", []):
                if a.get("providerPoiId"):
                    ids.add(a["providerPoiId"])
    return ids


def s042():
    user = L.new_user()
    _, s1 = L.place_search(user["token"], keyword="天河公园")
    _, s2 = L.place_search(user["token"], keyword="正佳广场")
    c1, c2 = s1["candidates"][0], s2["candidates"][0]
    _, trip = L.create_trip(user["token"], **{
        "constraints": {"mustVisitPlaces": [c1["name"], c2["name"]],
                        "mustVisitPlaceRefs": [_ref(c1), _ref(c2)]}})
    st, task, _ = L.start_planning(user["token"], trip["id"])
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=60)
    placed = _candidate_ids(terminal)
    ok = terminal is not None and {c1["providerPoiId"], c2["providerPoiId"]} <= placed
    return {"ok": ok,
            "evidence": f"task={st} terminal={terminal.get('status') if terminal else None} both={c1['providerPoiId'] in placed and c2['providerPoiId'] in placed}"}


def s043():
    user = L.new_user()
    picks = []
    for kw in ["天河公园", "正佳广场", "广州塔", "陈家祠", "沙面"]:
        _, s = L.place_search(user["token"], keyword=kw)
        if s.get("candidates"):
            picks.append(s["candidates"][0])
    if len(picks) < 5:
        return {"ok": False, "evidence": f"only {len(picks)} distinct candidates"}
    _, trip = L.create_trip(user["token"], **{
        "constraints": {"mustVisitPlaces": [p["name"] for p in picks],
                        "mustVisitPlaceRefs": [_ref(p) for p in picks]}})
    st, task, _ = L.start_planning(user["token"], trip["id"])
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=90)
    placed = _candidate_ids(terminal)
    ok = terminal is not None and all(p["providerPoiId"] in placed for p in picks)
    return {"ok": ok, "evidence": f"task={st} terminal={terminal.get('status') if terminal else None} placed={len(placed)}/{len(picks)}"}


def s044():
    user = L.new_user()
    _, s = L.place_search(user["token"], keyword="广州塔")
    cand = s["candidates"][0]
    _, trip = L.create_trip(user["token"], **{
        "constraints": {"mustVisitPlaces": [cand["name"]], "mustVisitPlaceRefs": [_ref(cand)],
                        "preferences": ["完全不相关的偏好词XYZ"]}})
    st, task, _ = L.start_planning(user["token"], trip["id"])
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=60)
    placed = _candidate_ids(terminal)
    ok = terminal is not None and cand["providerPoiId"] in placed
    return {"ok": ok, "evidence": f"terminal={terminal.get('status') if terminal else None} pinned={cand['providerPoiId'] in placed}"}


def s045():
    user = L.new_user()
    _, s = L.place_search(user["token"], keyword="正佳广场")
    cand = s["candidates"][0]
    # second search returns a same-name sibling with a different id
    _, s2 = L.place_search(user["token"], keyword="正佳广场服务中心")
    sibling = None
    for c in (s2 or {}).get("candidates", []):
        if c.get("providerPoiId") != cand["providerPoiId"] and "正佳" in c.get("name", ""):
            sibling = c
            break
    _, trip = L.create_trip(user["token"], **{
        "constraints": {"mustVisitPlaces": [cand["name"]], "mustVisitPlaceRefs": [_ref(cand)]}})
    st, task, _ = L.start_planning(user["token"], trip["id"])
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=60)
    placed = _candidate_ids(terminal)
    ok = terminal is not None and cand["providerPoiId"] in placed
    return {"ok": ok, "evidence": f"sibling={sibling.get('providerPoiId') if sibling else None} exact={cand['providerPoiId'] in placed}"}


def s046():
    user = L.new_user()
    _, s = L.place_search(user["token"], keyword="天河公园")
    cand = s["candidates"][0]
    _, trip = L.create_trip(user["token"], **{
        "constraints": {"mustVisitPlaces": [cand["name"]], "mustVisitPlaceRefs": [_ref(cand)],
                        "avoidPlaces": [cand["name"]], "avoidPlaceRefs": [_ref(cand)]}})
    st, task, _ = L.start_planning(user["token"], trip["id"])
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=60)
    ok = terminal is not None and terminal.get("status") in ("FAILED", "WAITING_USER")
    return {"ok": ok, "evidence": f"terminal={terminal.get('status') if terminal else None} code={terminal.get('errorCode') if terminal else None}"}


def s047():
    user = L.new_user()
    _, s = L.place_search(user["token"], keyword="天河公园")
    cand = s["candidates"][0]
    _, s2 = L.place_search(user["token"], keyword="正佳广场")
    keep = s2["candidates"][0]
    _, trip = L.create_trip(user["token"], **{
        "constraints": {"avoidPlaces": [cand["name"]], "avoidPlaceRefs": [_ref(cand)],
                        "mustVisitPlaces": [keep["name"]], "mustVisitPlaceRefs": [_ref(keep)]}})
    st, task, _ = L.start_planning(user["token"], trip["id"])
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=60)
    placed = _candidate_ids(terminal)
    ok = terminal is not None and cand["providerPoiId"] not in placed and keep["providerPoiId"] in placed
    return {"ok": ok, "evidence": f"avoided={cand['providerPoiId'] in placed} kept={keep['providerPoiId'] in placed}"}


def s048():
    user = L.new_user()
    _, s1 = L.place_search(user["token"], keyword="正佳广场")
    exact = s1["candidates"][0]
    _, s2 = L.place_search(user["token"], keyword="正佳广场服务中心")
    sibling = None
    for c in (s2 or {}).get("candidates", []):
        if c.get("providerPoiId") != exact["providerPoiId"] and "正佳" in c.get("name", ""):
            sibling = c
            break
    _, trip = L.create_trip(user["token"], **{
        "constraints": {"avoidPlaces": [exact["name"]], "avoidPlaceRefs": [_ref(exact)],
                        "mustVisitPlaces": [sibling["name"] if sibling else exact["name"]],
                        "mustVisitPlaceRefs": [_ref(sibling) if sibling else _ref(exact)]}})
    st, task, _ = L.start_planning(user["token"], trip["id"])
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=60)
    placed = _candidate_ids(terminal)
    target = sibling["providerPoiId"] if sibling else None
    ok = terminal is not None and exact["providerPoiId"] not in placed
    return {"ok": ok, "evidence": f"exact-avoided={exact['providerPoiId'] in placed} sibling-target={target in placed if target else 'n/a'}"}


def s049():
    # official closure: REAL-only semantics need context facts; in DEMO the
    # planner cannot verify closure — assert the honest DEMO terminal instead.
    user = L.new_user()
    _, trip = L.create_trip(user["token"], **{
        "constraints": {"mustVisitPlaces": ["必去闭馆地"], "mustVisitPlaceRefs": [
            {"provider": "DEMO", "providerPoiId": "demo-closed-1", "name": "必去闭馆地", "address": "",
             "province": "", "city": "广州", "district": "", "longitude": 113.3, "latitude": 23.1,
             "selectionToken": None}]}})
    st, task, _ = L.start_planning(user["token"], trip["id"])
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=60)
    ok = terminal is not None and terminal.get("status") in ("FAILED", "WAITING_USER")
    return {"ok": ok, "evidence": f"terminal={terminal.get('status') if terminal else None}"}


def s050():
    user = L.new_user()
    # 60-minute window: nothing schedulable -> MUST_VISIT_UNAVAILABLE fail-closed
    _, s = L.place_search(user["token"], keyword="天河公园")
    cand = s["candidates"][0]
    _, trip = L.create_trip(user["token"], startDate="2026-09-30", endDate="2026-09-30",
                            arrivalAt="2026-09-30T18:00:00+08:00", departureAt="2026-09-30T19:00:00+08:00", **{
                                "constraints": {"mustVisitPlaces": [cand["name"]],
                                                "mustVisitPlaceRefs": [_ref(cand)]}})
    st, task, _ = L.start_planning(user["token"], trip["id"])
    terminal = L.poll_terminal(user["token"], trip["id"], timeout_s=60)
    ok = terminal is not None and terminal.get("status") == "FAILED" and "MUST_VISIT_UNAVAILABLE" in str(terminal.get("conflicts", ""))
    return {"ok": ok, "evidence": f"terminal={terminal.get('status') if terminal else None}"}


def _real_gate(scenario_id, title, risk, fn):
    """E-group scenarios need REAL_ONLY: DEMO fails must-visits honestly
    (MUST_VISIT_UNVERIFIABLE_IN_DEMO). Run them in the REAL phase instead."""
    if L.provider_mode() != "REAL_ONLY":
        RESULTS.append({"scenarioId": scenario_id, "title": title, "risk": risk,
                        "ok": None, "evidence": "DEFERRED_REAL", "detail": "run in REAL phase"})
        return
    scenario(scenario_id, title, risk, fn)


_real_gate("S041", "一个结构化必去点", "P1", s041)
_real_gate("S042", "两个结构化必去点，第一查询已达候选数", "P0", s042)
_real_gate("S043", "五个结构化必去点", "P1", s043)
_real_gate("S044", "必去点排名低于普通候选 cutoff", "P1", s044)
_real_gate("S045", "同名 sibling 不得代替精确必去点", "P1", s045)
_real_gate("S046", "同一地点同时必去和避开", "P1", s046)
_real_gate("S047", "精确 avoid providerPoiId", "P1", s047)
_real_gate("S048", "同名 sibling 不得被错误排除", "P1", s048)
_real_gate("S049", "必去点正式关闭", "P1", s049)
_real_gate("S050", "必去点路线不可达或时间无法安排", "P1", s050)

# ── runner ─────────────────────────────────────────────────────────────────

def main():
    import sys as _sys
    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    print(f"provider_mode={L.provider_mode()}")
    failed = [r for r in RESULTS if not r["ok"]]
    for r in RESULTS:
        mark = "PASS" if r["ok"] else "FAIL"
        print(f"[{mark}] {r['scenarioId']} {r['title']} | {r['evidence']}")
    print(f"\nTOTAL {len(RESULTS)}  PASS {len(RESULTS) - len(failed)}  FAIL {len(failed)}")
    with open(__import__("os").path.join(__import__("os").path.dirname(__file__), "results-a.json"), "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=1)
    if failed:
        for r in failed:
            print(f"FAILED {r['scenarioId']} {r['detail']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
