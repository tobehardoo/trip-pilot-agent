package io.github.tobehardoo.trippilot.route;

public interface AgentRouteClient {

    AgentRouteDtos.RouteFacts route(AgentRouteDtos.RouteRequest request);

    AgentRouteDtos.Recommendation recommend(AgentRouteDtos.RecommendRequest request);
}
