package io.github.tobehardoo.trippilot.route;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

import io.github.tobehardoo.trippilot.common.ApiException;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.jsonPath;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withTooManyRequests;

class HttpAgentRouteClientTest {

    private static AgentRouteDtos.RouteRequest routeRequest(String mode) {
        return new AgentRouteDtos.RouteRequest(
                new AgentRouteDtos.Coordinates(new BigDecimal("113.31"), new BigDecimal("23.11")),
                new AgentRouteDtos.Coordinates(new BigDecimal("113.34"), new BigDecimal("23.14")),
                mode, OffsetDateTime.parse("2026-08-20T12:00:00+08:00"),
                "origin", "destination", "Guangzhou");
    }

    @Test
    void callsTheProtectedRouteFactsEndpoint() {
        RestClient.Builder builder = RestClient.builder();
        MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
        HttpAgentRouteClient client = new HttpAgentRouteClient(
                builder.baseUrl("http://agent:8090").build(), "internal-secret");
        server.expect(requestTo("http://agent:8090/internal/v1/routes"))
                .andExpect(header("X-Internal-Token", "internal-secret"))
                .andExpect(jsonPath("$.mode").value("TRANSIT"))
                .andRespond(withSuccess("""
                        {
                          "mode":"TRANSIT","distanceMeters":2000,"durationSeconds":500,
                          "polyline":[{"longitude":113.31,"latitude":23.11},{"longitude":113.34,"latitude":23.14}],
                          "estimatedCost":3.0,"walkingDistanceMeters":300,"transferCount":1,
                          "provider":"AMAP","estimated":false,"cached":false,
                          "fetchedAt":"2026-08-20T04:00:00Z"
                        }
                        """, MediaType.APPLICATION_JSON));

        AgentRouteDtos.RouteFacts facts = client.route(routeRequest("TRANSIT"));

        assertThat(facts.mode()).isEqualTo("TRANSIT");
        assertThat(facts.provider()).isEqualTo("AMAP");
        assertThat(facts.estimated()).isFalse();
        assertThat(facts.polyline()).hasSize(2);
        server.verify();
    }

    @Test
    void callsTheRecommendationEndpointWithoutSendingAutoAsAProviderMode() {
        RestClient.Builder builder = RestClient.builder();
        MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
        HttpAgentRouteClient client = new HttpAgentRouteClient(
                builder.baseUrl("http://agent:8090").build(), "internal-secret");
        server.expect(requestTo("http://agent:8090/internal/v1/routes/recommend"))
                .andExpect(header("X-Internal-Token", "internal-secret"))
                .andExpect(jsonPath("$.mode").doesNotExist())
                .andExpect(jsonPath("$.mobilityLevel").value("REDUCED"))
                .andRespond(withSuccess("""
                        {
                          "selectedMode":"DRIVING","reason":"ROAD_SIGNIFICANTLY_FASTER",
                          "providerCallsUsed":2,"budgetDegraded":false,
                          "route":{"mode":"DRIVING","distanceMeters":2000,"durationSeconds":300,
                            "polyline":[{"longitude":113.31,"latitude":23.11},{"longitude":113.34,"latitude":23.14}],
                            "estimatedCost":null,"walkingDistanceMeters":null,"transferCount":null,
                            "provider":"AMAP","estimated":false,"cached":false,
                            "fetchedAt":"2026-08-20T04:00:00Z"}
                        }
                        """, MediaType.APPLICATION_JSON));

        AgentRouteDtos.Recommendation recommendation = client.recommend(
                AgentRouteDtos.RecommendRequest.from(routeRequest("DRIVING"), "REDUCED"));

        assertThat(recommendation.selectedMode()).isEqualTo("DRIVING");
        assertThat(recommendation.route().durationSeconds()).isEqualTo(300);
        server.verify();
    }

    @Test
    void mapsProviderFailuresToOneSafeTravelServerError() {
        RestClient.Builder builder = RestClient.builder();
        MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
        HttpAgentRouteClient client = new HttpAgentRouteClient(
                builder.baseUrl("http://agent:8090").build(), "internal-secret");
        server.expect(requestTo("http://agent:8090/internal/v1/routes"))
                .andRespond(withTooManyRequests().body("secret upstream detail"));

        assertThatThrownBy(() -> client.route(routeRequest("DRIVING")))
                .isInstanceOf(ApiException.class)
                .hasMessage("Route service is temporarily unavailable")
                .extracting("code")
                .isEqualTo("ROUTE_PROVIDER_UNAVAILABLE");
        server.verify();
    }
}
