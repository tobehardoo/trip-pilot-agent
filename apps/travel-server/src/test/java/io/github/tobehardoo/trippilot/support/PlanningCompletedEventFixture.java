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
}
