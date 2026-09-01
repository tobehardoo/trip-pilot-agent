package io.github.tobehardoo.trippilot.share;

import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;

import static org.assertj.core.api.Assertions.assertThat;

class ItineraryShareControllerTest {

    @Test
    void usesTheFirstForwardedClientAddressWhenRequestsArriveThroughNginx() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setRemoteAddr("172.31.248.7");
        request.addHeader("X-Forwarded-For", "203.0.113.42, 172.31.248.1");

        assertThat(ItineraryShareController.clientAddress(request)).isEqualTo("203.0.113.42");
    }

    @Test
    void fallsBackToThePeerAddressOutsideTheProxyTopology() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setRemoteAddr("127.0.0.1");

        assertThat(ItineraryShareController.clientAddress(request)).isEqualTo("127.0.0.1");
    }
}
