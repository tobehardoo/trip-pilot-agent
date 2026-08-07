package io.github.tobehardoo.trippilot.places;

import java.util.List;

public record PlaceSuggestResponse(List<PlaceSuggestItem> items) {

    public PlaceSuggestResponse {
        items = List.copyOf(items);
    }
}
