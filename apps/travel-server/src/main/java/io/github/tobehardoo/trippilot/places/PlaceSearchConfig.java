package io.github.tobehardoo.trippilot.places;

import java.time.Duration;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

/** Builds the AMap-bound {@link RestClient} with a bounded timeout. */
@Configuration
public class PlaceSearchConfig {

    @Bean
    RestClient amapPlaceSearchRestClient(RestClient.Builder builder, PlaceSearchProperties properties) {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(Duration.ofSeconds(properties.amapTimeoutSeconds()));
        requestFactory.setReadTimeout(Duration.ofSeconds(properties.amapTimeoutSeconds()));
        return builder.requestFactory(requestFactory).build();
    }
}
