package io.github.tobehardoo.trippilot.support;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.UUID;

public final class PlanningCompletedEventFixture {

    private PlanningCompletedEventFixture() {
    }

    public static String sharedV6Fixture(String fixtureName) {
        Path relative = Path.of(
                "contracts", "fixtures", "planning-completed-event-v6", fixtureName
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
            throw new IllegalStateException("Could not read shared completion v6 fixture", exception);
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
