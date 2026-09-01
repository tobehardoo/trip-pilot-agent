package io.github.tobehardoo.trippilot.support;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

public final class PlanningCompletedEventFixture {

    private PlanningCompletedEventFixture() {
    }

    public static String sharedV6Fixture(String fixtureName) {
        return sharedFixture("planning-completed-event-v6", fixtureName, "v6");
    }

    public static String sharedV8Fixture(String fixtureName) {
        return sharedFixture("planning-completed-event-v8", fixtureName, "v8");
    }

    public static String sharedV9Fixture(String fixtureName) {
        return sharedFixture("planning-completed-event-v9", fixtureName, "v9");
    }

    public static String sharedReviewV1Fixture(String fixtureName) {
        return sharedFixture("planning-review-required-event-v1", fixtureName, "review v1");
    }

    private static String sharedFixture(String directory, String fixtureName, String label) {
        Path relative = Path.of(
                "contracts", "fixtures", directory, fixtureName
        );
        Path workingDirectory = Path.of("").toAbsolutePath();
        Path fixture = workingDirectory.resolve(relative);
        if (!Files.isRegularFile(fixture)) {
            fixture = workingDirectory.resolve(Path.of("..", ".."))
                    .resolve(relative).normalize();
        }
        try {
            return Files.readString(fixture, StandardCharsets.UTF_8);
        } catch (IOException exception) {
            throw new IllegalStateException(
                    "Could not read shared completion " + label + " fixture", exception);
        }
    }

    public static String completedEvent(UUID eventId, UUID traceId, UUID taskId, UUID tripId) {
        return """
                {
                  "eventType": "PLANNING_COMPLETED",
                  "schemaVersion": 1,
                  "eventId": "%s",
                  "traceId": "%s",
                  "taskId": "%s",
                  "tripId": "%s",
                  "runId": "a61f2109-ec3f-51f8-a536-25f0049d8326",
                  "occurredAt": "2026-07-15T03:00:00Z",
                  "payload": {
                    "provider": "DEMO",
                    "itinerary": {
                      "title": "广州 Demo 行程",
                      "days": [
                        {
                          "date": "2026-08-01",
                          "activities": [
                            {
                              "title": "广州 Demo 探索",
                              "startTime": "2026-08-01T09:00:00+08:00",
                              "endTime": "2026-08-01T11:00:00+08:00",
                              "estimatedCost": 0,
                              "source": "DEMO"
                            }
                          ]
                        }
                      ],
                      "estimatedTotalCost": 0
                    }
                  }
                }
                """.formatted(eventId, traceId, taskId, tripId);
    }

    public static String completedAmapEventV2(
            UUID eventId, UUID traceId, UUID taskId, UUID tripId
    ) {
        return """
                {
                  "eventType": "PLANNING_COMPLETED",
                  "schemaVersion": 2,
                  "eventId": "%s",
                  "traceId": "%s",
                  "taskId": "%s",
                  "tripId": "%s",
                  "runId": "a61f2109-ec3f-51f8-a536-25f0049d8326",
                  "occurredAt": "2026-07-16T03:00:00Z",
                  "payload": {
                    "provider": "AMAP",
                    "itinerary": {
                      "title": "广州真实地点行程",
                      "days": [
                        {
                          "date": "2026-08-01",
                          "activities": [
                            {
                              "title": "广东省博物馆",
                              "startTime": "2026-08-01T09:00:00+08:00",
                              "endTime": "2026-08-01T11:00:00+08:00",
                              "estimatedCost": 0,
                              "source": "AMAP",
                              "providerPoiId": "B00140TWHT",
                              "coordinates": {
                                "longitude": 113.319263,
                                "latitude": 23.109078
                              },
                              "address": "珠江东路2号"
                            }
                          ]
                        }
                      ],
                      "estimatedTotalCost": 0
                    }
                  }
                }
                """.formatted(eventId, traceId, taskId, tripId);
    }

    public static String completedAmapEventV3(
            UUID eventId, UUID traceId, UUID taskId, UUID tripId
    ) {
        return """
                {
                  "eventType": "PLANNING_COMPLETED",
                  "schemaVersion": 3,
                  "eventId": "%s",
                  "traceId": "%s",
                  "taskId": "%s",
                  "tripId": "%s",
                  "runId": "a61f2109-ec3f-51f8-a536-25f0049d8326",
                  "occurredAt": "2026-07-17T03:00:00Z",
                  "payload": {
                    "provider": "AMAP",
                    "itinerary": {
                      "title": "广州真实路线行程",
                      "days": [
                        {
                          "date": "2026-08-01",
                          "activities": [
                            {
                              "title": "广东省博物馆",
                              "startTime": "2026-08-01T09:00:00+08:00",
                              "endTime": "2026-08-01T11:00:00+08:00",
                              "estimatedCost": 0,
                              "source": "AMAP",
                              "providerPoiId": "B00140TWHT",
                              "coordinates": {"longitude": 113.319263, "latitude": 23.109078},
                              "address": "珠江东路2号"
                            },
                            {
                              "title": "广州塔",
                              "startTime": "2026-08-01T13:00:00+08:00",
                              "endTime": "2026-08-01T15:00:00+08:00",
                              "estimatedCost": 0,
                              "source": "AMAP",
                              "providerPoiId": "B00141TTHJ",
                              "coordinates": {"longitude": 113.324553, "latitude": 23.106414},
                              "address": "阅江西路222号"
                            }
                          ],
                          "transitLegs": [
                            {
                              "fromActivityIndex": 0,
                              "toActivityIndex": 1,
                              "mode": "WALKING",
                              "distanceMeters": 1280,
                              "durationSeconds": 960,
                              "provider": "AMAP",
                              "estimated": false,
                              "polyline": [
                                {"longitude": 113.319263, "latitude": 23.109078},
                                {"longitude": 113.324553, "latitude": 23.106414}
                              ]
                            }
                          ]
                        }
                      ],
                      "estimatedTotalCost": 0
                    }
                  }
                }
                """.formatted(eventId, traceId, taskId, tripId);
    }

    public static String completedAmapEventV4(
            UUID eventId, UUID traceId, UUID taskId, UUID tripId
    ) {
        String v3 = completedAmapEventV3(eventId, traceId, taskId, tripId)
                .replace("\"schemaVersion\": 3", "\"schemaVersion\": 4");
        String knowledge = """
                "knowledge": {
                  "status": "REAL",
                  "query": "广州 历史 FRIENDS",
                  "citations": [
                    {
                      "documentId": "guangzhou-history-001",
                      "documentVersion": 2,
                      "chunkId": "guangzhou-history-001-v2-c0",
                      "chunkIndex": 0,
                      "title": "广州历史文化资料",
                      "sourceUrl": "https://www.gz.gov.cn/history",
                      "sourceName": "广州市人民政府",
                      "collectedAt": "2026-07-22T02:00:00Z",
                      "reliabilityLevel": "official",
                      "similarity": 0.87
                    }
                  ],
                  "freshness": {
                    "status": "FRESH",
                    "checkedAt": "2026-07-23T01:00:00Z"
                  }
                },
                """;
        return v3.replace("\"itinerary\": {", knowledge + "\"itinerary\": {");
    }

    public static String completedMixedEventV6(
            UUID eventId, UUID traceId, UUID taskId, UUID tripId
    ) {
        return completedAmapEventV4(eventId, traceId, taskId, tripId)
                .replace("\"schemaVersion\": 4", "\"schemaVersion\": 6")
                .replace(
                        "\"knowledge\": {",
                        "\"factImpacts\": [],\n                    \"knowledge\": {"
                )
                .replace(
                        "\"provider\": \"AMAP\"",
                        "\"provider\": \"DEMO\""
                )
                .replaceFirst(
                        "\"provider\": \"DEMO\"",
                        "\"provider\": \"AMAP\""
                )
                .replace("\"estimated\": false", "\"estimated\": true");
    }

    public static String completedAmapEventV8(
            UUID eventId, UUID traceId, UUID taskId, UUID tripId
    ) {
        return """
                {
                  "eventType": "PLANNING_COMPLETED",
                  "schemaVersion": 8,
                  "eventId": "%s",
                  "traceId": "%s",
                  "taskId": "%s",
                  "tripId": "%s",
                  "runId": "a61f2109-ec3f-51f8-a536-25f0049d8326",
                  "occurredAt": "2026-07-18T03:00:00Z",
                  "payload": {
                    "provider": "AMAP",
                    "itinerary": {
                      "title": "广州真实路线行程",
                      "days": [
                        {
                          "date": "2026-08-01",
                          "dayType": "ARRIVAL_DAY",
                          "activities": [
                            {
                              "activityId": "6b4e8b2d-7f3e-4e2f-8f0a-1b2c3d4e5f60",
                              "title": "广州站",
                              "startTime": "2026-08-01T13:30:00+08:00",
                              "endTime": "2026-08-01T14:00:00+08:00",
                              "estimatedCost": 0,
                              "source": "AMAP",
                              "providerPoiId": "STATION-1",
                              "coordinates": {"longitude": 113.249382, "latitude": 23.149933},
                              "address": "环市西路159号",
                              "kind": "ARRIVAL",
                              "timeFixed": true
                            },
                            {
                              "activityId": "6b4e8b2d-7f3e-4e2f-8f0a-1b2c3d4e5f61",
                              "title": "越秀公园",
                              "startTime": "2026-08-01T14:40:00+08:00",
                              "endTime": "2026-08-01T16:10:00+08:00",
                              "estimatedCost": 0,
                              "source": "AMAP",
                              "providerPoiId": "PARK-1",
                              "coordinates": {"longitude": 113.264385, "latitude": 23.140326},
                              "address": "解放北路988号",
                              "kind": "ATTRACTION",
                              "timeFixed": false
                            },
                            {
                              "activityId": "6b4e8b2d-7f3e-4e2f-8f0a-1b2c3d4e5f62",
                              "title": "晚餐（建议在当前区域自行选择餐馆）",
                              "startTime": "2026-08-01T17:00:00+08:00",
                              "endTime": "2026-08-01T18:00:00+08:00",
                              "estimatedCost": 0,
                              "source": "AMAP",
                              "kind": "MEAL",
                              "timeFixed": false
                            }
                          ],
                          "transitLegs": [
                            {
                              "transitId": "6b4e8b2d-7f3e-4e2f-8f0a-1b2c3d4e5f70",
                              "fromActivityIndex": 0,
                              "toActivityIndex": 1,
                              "mode": "DRIVING",
                              "distanceMeters": 2600,
                              "durationSeconds": 900,
                              "provider": "AMAP",
                              "estimated": false,
                              "polyline": [
                                {"longitude": 113.249382, "latitude": 23.149933},
                                {"longitude": 113.264385, "latitude": 23.140326}
                              ]
                            }
                          ]
                        }
                      ],
                      "estimatedTotalCost": 0
                    },
                    "factImpacts": [],
                    "knowledge": {
                      "status": "DEMO",
                      "query": "广州",
                      "citations": [],
                      "freshness": {"status": "UNAVAILABLE"},
                      "message": "演示模式未使用生产知识检索"
                    }
                  }
                }
                """.formatted(eventId, traceId, taskId, tripId);
    }

    public static String completedAmapEventV9(
            UUID eventId, UUID traceId, UUID taskId, UUID tripId
    ) {
        String v8 = completedAmapEventV8(eventId, traceId, taskId, tripId);
        try {
            ObjectNode event = (ObjectNode) new ObjectMapper().readTree(v8);
            event.put("schemaVersion", 9);
            ObjectNode payload = (ObjectNode) event.path("payload");
            payload.set("evaluation", v9Evaluation());
            payload.set("feasibilityReport", v9FeasibilityReport(
                    payload.path("itinerary")));
            return new ObjectMapper().writeValueAsString(event);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Could not build v9 completion fixture", exception);
        }
    }

    /**
     * Builds a v10 completion (B16: Information Missing != Planning Failed).
     * The report is UNVERIFIED with UNKNOWN-only rule outcomes (no FAIL, no
     * missing required rule), so the payload carries hasBlocker=false and the
     * event is a savable completion despite the unverified status.
     */
    public static String completedAmapEventV10(
            UUID eventId, UUID traceId, UUID taskId, UUID tripId
    ) {
        String v9 = completedAmapEventV9(eventId, traceId, taskId, tripId);
        try {
            ObjectNode event = (ObjectNode) new ObjectMapper().readTree(v9);
            event.put("schemaVersion", 10);
            ObjectNode payload = (ObjectNode) event.path("payload");
            ObjectNode report = (ObjectNode) payload.path("feasibilityReport");
            report.put("status", "UNVERIFIED");
            ((ObjectNode) report.path("summary"))
                    .put("passCount", 0)
                    .put("unknownCount", V9_REQUIRED_RULE_IDS.length)
                    .put("notApplicableCount", 0);
            ArrayNode ruleResults = (ArrayNode) report.path("ruleResults");
            ruleResults.removeAll();
            for (String ruleId : V9_REQUIRED_RULE_IDS) {
                ruleResults.add(v10UnknownRuleResult(ruleId));
            }
            payload.put("hasBlocker", false);
            return new ObjectMapper().writeValueAsString(event);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Could not build v10 completion fixture", exception);
        }
    }

    private static ObjectNode v10UnknownRuleResult(String ruleId) {
        ObjectNode result = new ObjectMapper().createObjectNode();
        result.put("ruleId", ruleId);
        result.put("ruleVersion", "hard-rule-v1");
        result.put("outcome", "UNKNOWN");
        result.put("reasonCode", "EVIDENCE_UNAVAILABLE");
        result.put("message", "no evidence available in demo mode");
        result.putArray("affectedDates");
        result.putArray("affectedEntityRefs");
        result.putArray("evidenceRefs");
        result.put("repairable", false);
        return result;
    }

    /**
     * Upgrades a historical (v1-v8) completion event to the active v9 shape
     * for runtime integration tests: schemaVersion=9 plus the v9-required
     * knowledge/factImpacts/evaluation/feasibilityReport fields, keeping the
     * original itinerary content.  The report fingerprint is recomputed from
     * the payload itinerary so the Java verifier accepts the event.
     */
    public static String upgradeToV9(String historicalEventJson) {
        try {
            ObjectNode event = (ObjectNode) new ObjectMapper().readTree(historicalEventJson);
            event.put("schemaVersion", 9);
            ObjectNode payload = (ObjectNode) event.path("payload");
            if (!payload.has("knowledge")) {
                payload.set("knowledge", demoKnowledge());
            }
            if (!payload.has("factImpacts")) {
                payload.set("factImpacts", new ObjectMapper().createArrayNode());
            }
            for (JsonNode day : payload.path("itinerary").path("days")) {
                if (!day.has("transitLegs")) {
                    ((ObjectNode) day).set("transitLegs",
                            new ObjectMapper().createArrayNode());
                }
            }
            if (!payload.has("evaluation")) {
                payload.set("evaluation", v9Evaluation());
            }
            if (!payload.has("feasibilityReport")) {
                payload.set("feasibilityReport", v9FeasibilityReport(
                        payload.path("itinerary")));
            }
            return new ObjectMapper().writeValueAsString(event);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Could not upgrade completion fixture to v9",
                    exception);
        }
    }

    private static ObjectNode demoKnowledge() {
        ObjectNode knowledge = new ObjectMapper().createObjectNode();
        knowledge.put("status", "DEMO");
        knowledge.put("query", "广州");
        knowledge.putArray("citations");
        knowledge.putObject("freshness").put("status", "UNAVAILABLE");
        knowledge.put("message", "演示模式未使用生产知识检索");
        return knowledge;
    }

    private static ObjectNode v9Evaluation() {
        ObjectNode evaluation = new ObjectMapper().createObjectNode();
        evaluation.put("schemaVersion", 2);
        evaluation.put("evaluatorVersion", "rule-v2");
        evaluation.put("feasible", true);
        evaluation.put("overallScore", 100);
        ObjectNode dimensions = evaluation.putObject("dimensions");
        dimensions.put("constraintSatisfaction", 100)
                .put("timeFeasibility", 100)
                .put("budgetFit", 100)
                .put("routeEfficiency", 100);
        evaluation.putArray("warnings");
        evaluation.putArray("decisions");
        evaluation.put("summary", "所有检查通过");
        evaluation.put("evaluatedAt", "2026-08-10T10:15:00Z");
        return evaluation;
    }

    private static final String[] V9_REQUIRED_RULE_IDS = {
            "TRIP_DATE_RANGE", "FIXED_SCHEDULE_COVERAGE", "BUDGET_LIMIT",
            "MUST_VISIT_COVERAGE", "DUPLICATE_POI", "ACTIVITY_OVERLAP",
            "ROUTE_ENDPOINT_CONTINUITY", "CROSS_DAY_CONTINUITY", "OPENING_HOURS",
            "VISIT_DURATION", "MEAL_WINDOW"
    };

    private static ObjectNode v9FeasibilityReport(JsonNode itinerary) {
        ObjectNode report = new ObjectMapper().createObjectNode();
        report.put("schemaVersion", 1);
        report.put("reportId", UUID.randomUUID().toString());
        report.put("validatorVersion", "hard-validator-v3");
        report.put("itineraryFingerprint",
                io.github.tobehardoo.trippilot.feasibility.ItineraryFingerprintVerifier
                        .compute(itinerary));
        report.put("status", "VERIFIED");
        report.put("validatedAt", "2026-08-10T12:00:00Z");
        ArrayNode requiredRuleIds = report.putArray("requiredRuleIds");
        for (String ruleId : V9_REQUIRED_RULE_IDS) {
            requiredRuleIds.add(ruleId);
        }
        report.putArray("missingRequiredRuleIds");
        ObjectNode summary = report.putObject("summary");
        summary.put("totalCount", V9_REQUIRED_RULE_IDS.length)
                .put("passCount", 0)
                .put("failCount", 0)
                .put("unknownCount", 0)
                .put("notApplicableCount", V9_REQUIRED_RULE_IDS.length)
                .put("missingRequiredCount", 0);
        ArrayNode ruleResults = report.putArray("ruleResults");
        for (String ruleId : V9_REQUIRED_RULE_IDS) {
            ruleResults.add(v9RuleResult(ruleId));
        }
        report.putArray("repairAttempts");
        return report;
    }

    private static ObjectNode v9RuleResult(String ruleId) {
        ObjectNode result = new ObjectMapper().createObjectNode();
        result.put("ruleId", ruleId);
        result.put("ruleVersion", "hard-rule-v1");
        result.put("outcome", "NOT_APPLICABLE");
        result.put("reasonCode", "N/A");
        result.put("message", "not applicable");
        result.putArray("affectedDates");
        result.putArray("affectedEntityRefs");
        result.putArray("evidenceRefs");
        result.put("repairable", false);
        return result;
    }

    public static String completedTwoDayAmapEventV3(
            UUID eventId, UUID traceId, UUID taskId, UUID tripId
    ) {
        String firstDay = completedAmapEventV3(eventId, traceId, taskId, tripId);
        String secondDay = """
                ,
                        {
                          "date": "2026-08-02",
                          "activities": [
                            {
                              "title": "Yuexiu Park",
                              "startTime": "2026-08-02T09:00:00+08:00",
                              "endTime": "2026-08-02T11:00:00+08:00",
                              "estimatedCost": 0,
                              "source": "AMAP",
                              "providerPoiId": "PARK-1",
                              "coordinates": {"longitude": 113.264385, "latitude": 23.140326},
                              "address": "Jiefang North Road"
                            },
                            {
                              "title": "Chen Clan Academy",
                              "startTime": "2026-08-02T13:00:00+08:00",
                              "endTime": "2026-08-02T15:00:00+08:00",
                              "estimatedCost": 0,
                              "source": "AMAP",
                              "providerPoiId": "ACADEMY-1",
                              "coordinates": {"longitude": 113.246749, "latitude": 23.129191},
                              "address": "Zhongshan 7th Road"
                            }
                          ],
                          "transitLegs": [
                            {
                              "fromActivityIndex": 0,
                              "toActivityIndex": 1,
                              "mode": "WALKING",
                              "distanceMeters": 910,
                              "durationSeconds": 600,
                              "provider": "AMAP",
                              "estimated": false,
                              "polyline": [
                                {"longitude": 113.264385, "latitude": 23.140326},
                                {"longitude": 113.246749, "latitude": 23.129191}
                              ]
                            }
                          ]
                        }
                """;
        int totalCostIndex = firstDay.indexOf("\"estimatedTotalCost\"");
        int daysEndIndex = firstDay.lastIndexOf(']', totalCostIndex);
        if (daysEndIndex < 0) {
            throw new IllegalStateException("Could not extend the planning completion fixture");
        }
        return firstDay.substring(0, daysEndIndex)
                + secondDay
                + firstDay.substring(daysEndIndex);
    }
}
