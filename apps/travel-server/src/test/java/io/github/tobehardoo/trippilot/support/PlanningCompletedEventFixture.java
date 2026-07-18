package io.github.tobehardoo.trippilot.support;

import java.util.UUID;

public final class PlanningCompletedEventFixture {

    private PlanningCompletedEventFixture() {
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
}
