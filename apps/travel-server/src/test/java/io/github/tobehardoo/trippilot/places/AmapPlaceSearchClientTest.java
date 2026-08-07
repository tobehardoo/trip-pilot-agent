package io.github.tobehardoo.trippilot.places;

import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.test.web.client.RequestMatcher;
import org.springframework.web.client.RestClient;
import org.springframework.web.util.UriComponentsBuilder;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class AmapPlaceSearchClientTest {

    private static final String HOST = "restapi.amap.com";
    private static final String PATH = "/v3/place/text";

    private MockRestServiceServer server;
    private AmapPlaceSearchClient client;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder();
        server = MockRestServiceServer.bindTo(builder).build();
        client = new AmapPlaceSearchClient(
                builder.build(),
                new PlaceSearchProperties("test-key", 5, 8, 30, 100)
        );
    }

    @Test
    void parsesStructuredPoisAndRestrictsToTheCity() {
        server.expect(amapEndpoint())
                .andExpect(queryParams(Map.of(
                        "citylimit", List.of("true"),
                        "city", List.of("长沙"),
                        "offset", List.of("8"),
                        "types", List.of("150300|150301|150302|150400|150401|150402|150500|150600|150700|150800")
                )))
                .andRespond(withSuccess("""
                        {
                          "status": "1",
                          "info": "OK",
                          "pois": [{
                            "id": "B0FFFABC12",
                            "name": "长沙希尔顿酒店",
                            "location": "112.9834,28.1987",
                            "address": "长沙市岳麓区枫林一路123号",
                            "pname": "湖南省",
                            "cityname": "长沙市",
                            "adname": "岳麓区",
                            "type": "住宿服务;宾馆酒店;经济型酒店",
                            "typecode": "120100"
                          }]
                        }
                        """, MediaType.APPLICATION_JSON));

        List<PlacePoi> results = client.search("希尔顿", "长沙", 8);

        assertThat(results).singleElement().satisfies(poi -> {
            assertThat(poi.name()).isEqualTo("长沙希尔顿酒店");
            assertThat(poi.providerPoiId()).isEqualTo("B0FFFABC12");
            assertThat(poi.fullAddress()).isEqualTo("长沙市岳麓区枫林一路123号");
            assertThat(poi.longitude()).isEqualByComparingTo("112.9834");
            assertThat(poi.latitude()).isEqualByComparingTo("28.1987");
            assertThat(poi.city()).isEqualTo("长沙市");
            assertThat(poi.district()).isEqualTo("岳麓区");
            assertThat(poi.categoryName()).isEqualTo("经济型酒店");
            assertThat(poi.categoryCode()).isEqualTo("120100");
        });
        server.verify();
    }

    @Test
    void fallsBackToTheRequestedCityWhenCitynameIsAnArray() {
        server.expect(amapEndpoint())
                .andRespond(withSuccess("""
                        {
                          "status": "1",
                          "info": "OK",
                          "pois": [{
                            "id": "B0FFFABC12",
                            "name": "长沙希尔顿酒店",
                            "location": "112.9834,28.1987",
                            "address": "长沙市岳麓区枫林一路123号",
                            "pname": "湖南省",
                            "cityname": [],
                            "adname": "岳麓区"
                          }]
                        }
                        """, MediaType.APPLICATION_JSON));

        List<PlacePoi> results = client.search("希尔顿", "长沙", 8);

        assertThat(results).singleElement()
                .extracting(PlacePoi::city)
                .isEqualTo("长沙");
    }

    @Test
    void returnsEmptyWhenThereAreNoPois() {
        server.expect(amapEndpoint())
                .andRespond(withSuccess("""
                        {"status":"1","info":"OK","pois":[]}
                        """, MediaType.APPLICATION_JSON));

        assertThat(client.search("不存在的酒店", "长沙", 8)).isEmpty();
    }

    @Test
    void failsClosedOnServerErrorAfterBoundedRetries() {
        server.expect(amapEndpoint()).andRespond(withServerError());
        server.expect(amapEndpoint()).andRespond(withServerError());

        assertThatThrownBy(() -> client.search("希尔顿", "长沙", 8))
                .isInstanceOf(PlaceSearchUnavailableException.class);
        server.verify();
    }

    /** Matches the AMap host and path regardless of the query string. */
    private static RequestMatcher amapEndpoint() {
        return request -> {
            org.junit.jupiter.api.Assertions.assertEquals(HOST, request.getURI().getHost());
            org.junit.jupiter.api.Assertions.assertEquals(PATH, request.getURI().getPath());
        };
    }

    /** Asserts query parameters against their decoded values. */
    private static RequestMatcher queryParams(Map<String, List<String>> expected) {
        return request -> {
            Map<String, List<String>> raw = UriComponentsBuilder
                    .fromUri(request.getURI())
                    .build(true)
                    .getQueryParams();
            for (Map.Entry<String, List<String>> entry : expected.entrySet()) {
                List<String> actual = raw.getOrDefault(entry.getKey(), List.of()).stream()
                        .map(AmapPlaceSearchClientTest::decode)
                        .toList();
                org.junit.jupiter.api.Assertions.assertEquals(
                        entry.getValue(), actual,
                        "query param [" + entry.getKey() + "]"
                );
            }
        };
    }

    private static String decode(String value) {
        return java.net.URLDecoder.decode(value, java.nio.charset.StandardCharsets.UTF_8);
    }
}
