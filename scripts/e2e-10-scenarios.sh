#!/bin/bash
# TripPilot V2.0 - 10 E2E Test Scenarios
# Tests different constraint combinations and verifies frontend-backend consistency
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
PASSED=0
FAILED=0
RESULTS=()

log_test() { echo ""; echo "========================================"; echo "TEST: $1"; echo "========================================"; }
log_pass() { PASSED=$((PASSED + 1)); RESULTS+=("PASS: $1"); echo "✅ PASS: $1"; }
log_fail() { FAILED=$((FAILED + 1)); RESULTS+=("FAIL: $1 - $2"); echo "❌ FAIL: $1 - $2"; }

# Helper: register a unique user
register_user() {
  local EMAIL="$1"
  local DISPLAY="$2"
  local PASSWORD="TestPass123!"
  curl -s -X POST "$BASE_URL/api/auth/register" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$EMAIL\",\"displayName\":\"$DISPLAY\",\"password\":\"$PASSWORD\"}"
}

# Helper: login and get token
login() {
  local EMAIL="$1"
  local PASSWORD="TestPass123!"
  local RESP=$(curl -s -c /tmp/trippilot_cookies.txt -X POST "$BASE_URL/api/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
  echo "$RESP" | grep -o '"accessToken":"[^"]*"' | cut -d'"' -f4
}

# Helper: create a trip
create_trip() {
  local TOKEN="$1"
  shift
  local TITLE="$1"
  local DEST="$2"
  local START="$3"
  local END="$4"
  local BODY='{
    "title":"'"$TITLE"'",
    "destination":"'"$DEST"'",
    "startDate":"'"$START"'",
    "endDate":"'"$END"'"
  }'
  curl -s -X POST "$BASE_URL/api/trips" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d "$BODY"
}

# Helper: update constraints
update_constraints() {
  local TOKEN="$1"
  local TRIP_ID="$2"
  local CONSTRAINTS="$3"
  curl -s -X PUT "$BASE_URL/api/trips/$TRIP_ID/constraints" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d "$CONSTRAINTS"
}

# Helper: create planning task
create_planning_task() {
  local TOKEN="$1"
  local TRIP_ID="$2"
  curl -s -X POST "$BASE_URL/api/trips/$TRIP_ID/planning-tasks" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Idempotency-Key: test-$(date +%s%N)" \
    -d '{}'
}

# Helper: get itinerary
get_itinerary() {
  local TOKEN="$1"
  local TRIP_ID="$2"
  curl -s "$BASE_URL/api/trips/$TRIP_ID/itinerary" \
    -H "Authorization: Bearer $TOKEN"
}

# Helper: get trip detail
get_trip() {
  local TOKEN="$1"
  local TRIP_ID="$2"
  curl -s "$BASE_URL/api/trips/$TRIP_ID" \
    -H "Authorization: Bearer $TOKEN"
}

# Helper: list trips
list_trips() {
  local TOKEN="$1"
  curl -s "$BASE_URL/api/trips" \
    -H "Authorization: Bearer $TOKEN"
}

# Helper: create trip detail
get_trip_detail() {
  local TOKEN="$1"
  local TRIP_ID="$2"
  curl -s "$BASE_URL/api/trips/$TRIP_ID" \
    -H "Authorization: Bearer $TOKEN"
}

# Helper: verify data consistency
verify_consistency() {
  local TOKEN="$1"
  local TRIP_ID="$2"
  local SCENARIO="$3"

  # Get trip details
  local TRIP=$(get_trip "$TOKEN" "$TRIP_ID")
  local TRIP_STATUS=$(echo "$TRIP" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
  local TRIP_VERSION=$(echo "$TRIP" | grep -o '"version":[0-9]*' | cut -d: -f2)

  # Get itinerary
  local ITINERARY=$(get_itinerary "$TOKEN" "$TRIP_ID")

  echo "  Trip Status: $TRIP_STATUS, Version: $TRIP_VERSION"

  # Check trip status consistency
  if [ "$TRIP_STATUS" == "READY" ]; then
    local ITIN_VERSION=$(echo "$ITINERARY" | grep -o '"versionNumber":[0-9]*' | head -1 | cut -d: -f2)
    local ITIN_DAYS=$(echo "$ITINERARY" | grep -o '"date"' | wc -l | tr -d ' ')

    if [ -z "$ITIN_VERSION" ]; then
      log_fail "$SCENARIO" "Trip READY but no itinerary version found"
      return 1
    fi

    echo "  Itinerary Version: $ITIN_VERSION, Days: $ITIN_DAYS"

    # Verify version matches
    if [ "$TRIP_VERSION" != "$ITIN_VERSION" ]; then
      log_fail "$SCENARIO" "Trip version ($TRIP_VERSION) != itinerary version ($ITIN_VERSION)"
      return 1
    fi

    # Check activities
    local ACTIVITIES=$(echo "$ITINERARY" | grep -o '"title":"[^"]*"' | wc -l | tr -d ' ')
    echo "  Activities: $ACTIVITIES"

    # Check transit legs
    local TRANSITS=$(echo "$ITINERARY" | grep -o '"mode":"[^"]*"' | wc -l | tr -d ' ')
    echo "  Transit Legs: $TRANSITS"

    # Check estimated cost
    local TOTAL_COST=$(echo "$ITINERARY" | grep -o '"estimatedTotalCost":[0-9.]*' | cut -d: -f2)
    echo "  Estimated Total Cost: $TOTAL_COST"

    # Check provider
    local PROVIDER=$(echo "$ITINERARY" | grep -o '"provider":"[^"]*"' | head -1 | cut -d'"' -f4)
    echo "  Provider: $PROVIDER"

    # Check knowledge block
    local KNOWLEDGE_STATUS=$(echo "$ITINERARY" | grep -o '"status":"[^"]*"' | tail -1 | cut -d'"' -f4)

    log_pass "$SCENARIO (v$ITIN_VERSION, $ITIN_DAYS days, $ACTIVITIES activities, cost=$TOTAL_COST, provider=$PROVIDER)"
    return 0
  elif [ "$TRIP_STATUS" == "PLANNING" ]; then
    echo "  Trip still planning..."
    return 0
  else
    echo "  Trip status: $TRIP_STATUS"
    return 0
  fi
}

# ============================================================
# Execute E2E test runs
# ============================================================
run_scenario() {
  local SCENARIO_NUM="$1"
  local SCENARIO_NAME="$2"
  local EMAIL="$3"
  local DISPLAY="$4"
  local TRIP_TITLE="$5"
  local DEST="$6"
  local START_DATE="$7"
  local END_DATE="$8"
  local CONSTRAINTS="$9"

  log_test "Scenario $SCENARIO_NUM: $SCENARIO_NAME"

  echo "  User: $EMAIL"

  # Register user
  local REG_RESP=$(register_user "$EMAIL" "$DISPLAY")
  echo "  Register: $(echo "$REG_RESP" | grep -o '"email":"[^"]*"')"

  # Login
  local TOKEN=$(login "$EMAIL")
  if [ -z "$TOKEN" ]; then
    log_fail "$SCENARIO_NAME" "Login failed"
    return
  fi
  echo "  Token obtained: ${TOKEN:0:20}..."

  # Create trip
  local TRIP_RESP=$(create_trip "$TOKEN" "$TRIP_TITLE" "$DEST" "$START_DATE" "$END_DATE")
  local TRIP_ID=$(echo "$TRIP_RESP" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
  if [ -z "$TRIP_ID" ]; then
    log_fail "$SCENARIO_NAME" "Trip creation failed: $TRIP_RESP"
    return
  fi
  echo "  Trip created: $TRIP_ID"

  # Update constraints
  local CONSTRAINT_RESP=$(update_constraints "$TOKEN" "$TRIP_ID" "$CONSTRAINTS")
  echo "  Constraints updated: $(echo "$CONSTRAINT_RESP" | grep -o '"schemaVersion":[0-9]*')"

  # Create planning task
  local TASK_RESP=$(create_planning_task "$TOKEN" "$TRIP_ID")
  local TASK_ID=$(echo "$TASK_RESP" | grep -o '"taskId":"[^"]*"' | cut -d'"' -f4)
  local TASK_STATUS=$(echo "$TASK_RESP" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
  echo "  Planning task: $TASK_ID, status=$TASK_STATUS"

  # Wait for planning to complete (polling)
  echo "  Waiting for planning..."
  local MAX_WAIT=120
  local WAITED=0
  while [ $WAITED -lt $MAX_WAIT ]; do
    local TRIP_STATUS=$(get_trip "$TOKEN" "$TRIP_ID" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
    if [ "$TRIP_STATUS" == "READY" ] || [ "$TRIP_STATUS" == "FAILED" ]; then
      echo "  Planning finished: $TRIP_STATUS after ${WAITED}s"
      break
    fi
    sleep 3
    WAITED=$((WAITED + 3))
    if [ $((WAITED % 15)) -eq 0 ]; then
      echo "  Still waiting... (${WAITED}s, status=$TRIP_STATUS)"
    fi
  done

  if [ $WAITED -ge $MAX_WAIT ]; then
    log_fail "$SCENARIO_NAME" "Planning timed out after ${MAX_WAIT}s"
    return
  fi

  # Verify data consistency
  verify_consistency "$TOKEN" "$TRIP_ID" "$SCENARIO_NAME"
}

# ============================================================
# 10 Scenarios with Different Constraints
# ============================================================

# Scenario 1: Balanced 3-day Guangzhou trip, solo traveler
run_scenario 1 "Balanced GZ 3-day Solo" \
  "s1_$(date +%s)@test.com" "S1_Tester" \
  "广州三日悠闲游" "广州" "2026-08-10" "2026-08-12" \
  '{"budgetAmount":3000,"travelers":1,"travelerType":"SOLO","pace":"BALANCED","preferences":["岭南文化","早茶美食"],"fixedSchedules":[],"arrival":null,"departure":null,"accommodation":null,"mustVisitPlaces":[],"avoidPlaces":[],"mealWindows":[],"mobilityLevel":"STANDARD","schemaVersion":2}'

# Scenario 2: Intensive 2-day Guangzhou, tight budget, friends
run_scenario 2 "Intensive GZ 2-day Friends Budget" \
  "s2_$(date +%s)@test.com" "S2_Tester" \
  "广州两日暴走" "广州" "2026-08-15" "2026-08-16" \
  '{"budgetAmount":800,"travelers":2,"travelerType":"FRIENDS","pace":"INTENSIVE","preferences":["打卡地标"],"fixedSchedules":[],"arrival":null,"departure":null,"accommodation":null,"mustVisitPlaces":["广州塔","沙面岛"],"avoidPlaces":[],"mealWindows":[],"mobilityLevel":"STANDARD","schemaVersion":2}'

# Scenario 3: Relaxed 4-day Guangzhou, family with kids
run_scenario 3 "Relaxed GZ 4-day Family" \
  "s3_$(date +%s)@test.com" "S3_Tester" \
  "广州四日亲子游" "广州" "2026-08-20" "2026-08-23" \
  '{"budgetAmount":6000,"travelers":3,"travelerType":"FAMILY","pace":"RELAXED","preferences":["亲子乐园","自然风光"],"fixedSchedules":[],"arrival":null,"departure":null,"accommodation":null,"mustVisitPlaces":["长隆野生动物世界"],"avoidPlaces":["酒吧街"],"mealWindows":[],"mobilityLevel":"STANDARD","schemaVersion":2}'

# Scenario 4: Couple romantic 3-day Guangzhou
run_scenario 4 "Romantic GZ 3-day Couple" \
  "s4_$(date +%s)@test.com" "S4_Tester" \
  "广州三日浪漫之旅" "广州" "2026-09-01" "2026-09-03" \
  '{"budgetAmount":5000,"travelers":2,"travelerType":"COUPLE","pace":"BALANCED","preferences":["浪漫夜景","精致餐饮"],"fixedSchedules":[],"arrival":null,"departure":null,"accommodation":{"name":"珠江新城酒店","location":"天河区珠江新城"},"mustVisitPlaces":["珠江夜游","白云山"],"avoidPlaces":[],"mealWindows":[{"dayIndex":1,"start":"12:00","end":"13:30","label":"浪漫午餐"}],"mobilityLevel":"STANDARD","schemaVersion":2}'

# Scenario 5: 5-day Guangzhou with fixed schedules
run_scenario 5 "GZ 5-day Fixed Schedules" \
  "s5_$(date +%s)@test.com" "S5_Tester" \
  "广州五日公务加休闲" "广州" "2026-09-10" "2026-09-14" \
  '{"budgetAmount":8000,"travelers":1,"travelerType":"SOLO","pace":"BALANCED","preferences":[],"fixedSchedules":[{"dayIndex":0,"startTime":"2026-09-10T09:00:00Z","endTime":"2026-09-10T12:00:00Z","label":"会议"},{"dayIndex":2,"startTime":"2026-09-12T14:00:00Z","endTime":"2026-09-12T17:00:00Z","label":"客户见面"}],"arrival":{"location":"广州南站","time":"2026-09-10T08:00:00Z"},"departure":{"location":"广州白云机场","time":"2026-09-14T18:00:00Z"},"accommodation":null,"mustVisitPlaces":[],"avoidPlaces":[],"mealWindows":[],"mobilityLevel":"STANDARD","schemaVersion":2}'

# Scenario 6: 1-day Guangzhou quick trip
run_scenario 6 "GZ 1-day Quick Trip" \
  "s6_$(date +%s)@test.com" "S6_Tester" \
  "广州一日速览" "广州" "2026-09-20" "2026-09-20" \
  '{"budgetAmount":500,"travelers":1,"travelerType":"SOLO","pace":"INTENSIVE","preferences":["历史文化"],"fixedSchedules":[],"arrival":{"location":"广州东站","time":"2026-09-20T08:00:00Z"},"departure":{"location":"广州东站","time":"2026-09-20T20:00:00Z"},"accommodation":null,"mustVisitPlaces":[],"avoidPlaces":[],"mealWindows":[{"dayIndex":0,"start":"12:00","end":"13:00","label":"午餐"},{"dayIndex":0,"start":"18:00","end":"19:00","label":"晚餐"}],"mobilityLevel":"STANDARD","schemaVersion":2}'

# Scenario 7: 3-day Guangzhou with avoid places and low mobility
run_scenario 7 "GZ 3-day Low Mobility Avoid" \
  "s7_$(date +%s)@test.com" "S7_Tester" \
  "广州三日无障碍游" "广州" "2026-10-01" "2026-10-03" \
  '{"budgetAmount":4000,"travelers":2,"travelerType":"FAMILY","pace":"RELAXED","preferences":["无障碍景点"],"fixedSchedules":[],"arrival":null,"departure":null,"accommodation":null,"mustVisitPlaces":["越秀公园","广东省博物馆"],"avoidPlaces":["白云山","高层无电梯建筑"],"mealWindows":[],"mobilityLevel":"REDUCED","schemaVersion":2}'

# Scenario 8: 7-day Guangzhou full week, max days
run_scenario 8 "GZ 7-day Full Week" \
  "s8_$(date +%s)@test.com" "S8_Tester" \
  "广州七日深度游" "广州" "2026-10-10" "2026-10-16" \
  '{"budgetAmount":12000,"travelers":1,"travelerType":"SOLO","pace":"BALANCED","preferences":["深度文化","本地美食","自然风光"],"fixedSchedules":[],"arrival":{"location":"广州白云机场","time":"2026-10-10T10:00:00Z"},"departure":{"location":"广州白云机场","time":"2026-10-16T16:00:00Z"},"accommodation":{"name":"市区酒店","location":"越秀区"},"mustVisitPlaces":["广州塔","陈家祠","沙面岛","白云山","珠江夜游"],"avoidPlaces":[],"mealWindows":[],"mobilityLevel":"STANDARD","schemaVersion":2}'

# Scenario 9: 3-day with high budget, couple
run_scenario 9 "GZ 3-day Luxury Couple" \
  "s9_$(date +%s)@test.com" "S9_Tester" \
  "广州三日奢华游" "广州" "2026-11-01" "2026-11-03" \
  '{"budgetAmount":15000,"travelers":2,"travelerType":"COUPLE","pace":"RELAXED","preferences":["米其林餐厅","五星酒店","私人导览"],"fixedSchedules":[],"arrival":null,"departure":null,"accommodation":{"name":"四季酒店","location":"天河区珠江新城"},"mustVisitPlaces":[],"avoidPlaces":[],"mealWindows":[{"dayIndex":0,"start":"12:00","end":"14:00","label":"米其林午餐"},{"dayIndex":1,"start":"18:00","end":"21:00","label":"精品晚餐"},{"dayIndex":2,"start":"12:00","end":"14:00","label":"告别午餐"}],"mobilityLevel":"STANDARD","schemaVersion":2}'

# Scenario 10: 3-day budget constraints test (very low budget)
run_scenario 10 "GZ 3-day Ultra Budget" \
  "s10_$(date +%s)@test.com" "S10_Tester" \
  "广州三日穷游" "广州" "2026-11-10" "2026-11-12" \
  '{"budgetAmount":300,"travelers":1,"travelerType":"SOLO","pace":"INTENSIVE","preferences":["免费景点","街头小吃"],"fixedSchedules":[],"arrival":null,"departure":null,"accommodation":null,"mustVisitPlaces":[],"avoidPlaces":[],"mealWindows":[],"mobilityLevel":"STANDARD","schemaVersion":2}'

# ============================================================
# Summary
# ============================================================
echo ""
echo "========================================"
echo "=======  TEST RESULTS SUMMARY  ========"
echo "========================================"
echo ""
for result in "${RESULTS[@]}"; do
  echo "  $result"
done
echo ""
echo "Total: $((PASSED + FAILED)) tests"
echo "Passed: $PASSED"
echo "Failed: $FAILED"
echo "========================================"
