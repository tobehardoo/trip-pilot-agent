package io.github.tobehardoo.trippilot.place;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.place.PlaceSearchDtos.PlaceSearchRequest;
import io.github.tobehardoo.trippilot.place.PlaceSearchDtos.PlaceSearchResponse;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

class HttpAgentPlaceSearchClientTest {

    private HttpAgentPlaceSearchClient client(MockRestServiceServer server, RestClient.Builder builder) {
        return new HttpAgentPlaceSearchClient(builder.baseUrl("http://agent:8080").build(),
                "internal-secret-token");
    }

    @Test
    void postsWithInternalTokenAndMapsCandidates() {
        RestClient.Builder builder = RestClient.builder();
        MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
        server.expect(requestTo("http://agent:8080/internal/v1/places/search"))
                .andExpect(header("X-Internal-Token", "internal-secret-token"))
                .andRespond(withSuccess("""
                        {
                          "provider": "DEMO",
                          "estimated": true,
                          "candidates": [{
                            "provider": "DEMO",
                            "providerPoiId": "demo-abc",
                            "name": "陈家祠 (demo)",
                            "address": "Demo location in 广州",
                            "province": "",
                            "city": "广州",
                            "district": "",
                            "longitude": 113.2644,
                            "latitude": 23.1291,
                            "estimated": true
                          }]
                        }
                        """, MediaType.APPLICATION_JSON));

        PlaceSearchResponse response = client(server, builder)
                .search(new PlaceSearchRequest("广州", "陈家祠", 10));

        server.verify();
        assertThat(response.provider()).isEqualTo("DEMO");
        assertThat(response.estimated()).isTrue();
        assertThat(response.candidates()).hasSize(1);
        assertThat(response.candidates().get(0).providerPoiId()).isEqualTo("demo-abc");
        assertThat(response.candidates().get(0).estimated()).isTrue();
    }

    @Test
    void passesThroughEmptyResultSet() {
        // B14_FIX R4 (D04): "no result" from the agent is a legitimate
        // business outcome (200 + empty candidates), never a 502 — the
        // web layer renders "未找到结果" from the empty set.
        RestClient.Builder builder = RestClient.builder();
        MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
        server.expect(requestTo("http://agent:8080/internal/v1/places/search"))
                .andRespond(withSuccess("""
                        {
                          "provider": "AMAP",
                          "estimated": false,
                          "candidates": []
                        }
                        """, MediaType.APPLICATION_JSON));

        PlaceSearchResponse response = client(server, builder)
                .search(new PlaceSearchRequest("广州", "asdfghjklqwerty", 5));

        server.verify();
        assertThat(response.provider()).isEqualTo("AMAP");
        assertThat(response.estimated()).isFalse();
        assertThat(response.candidates()).isEmpty();
    }

    @Test
    void mapsAgentFailuresToSafeBadGateway() {
        RestClient.Builder builder = RestClient.builder();
        MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
        server.expect(requestTo("http://agent:8080/internal/v1/places/search"))
                .andRespond(withServerError().body("raw upstream secret detail"));

        assertThatThrownBy(() -> client(server, builder)
                .search(new PlaceSearchRequest("广州", "陈家祠", 10)))
                .isInstanceOf(ApiException.class)
                .satisfies(error -> {
                    ApiException api = (ApiException) error;
                    assertThat(api.code()).isEqualTo("PLACE_SEARCH_UNAVAILABLE");
                    assertThat(api.getMessage()).doesNotContain("secret");
                });
    }
}
