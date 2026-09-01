package io.github.tobehardoo.trippilot.place;

import io.github.tobehardoo.trippilot.place.PlaceSearchDtos.PlaceSearchRequest;
import io.github.tobehardoo.trippilot.place.PlaceSearchDtos.PlaceSearchResponse;

/**
 * Internal agent-service client for place search (B13-D).
 *
 * The browser never talks to a map provider: the travel server proxies the
 * owner-authenticated request to the agent service with the internal token.
 */
public interface AgentPlaceSearchClient {

    PlaceSearchResponse search(PlaceSearchRequest request);
}
