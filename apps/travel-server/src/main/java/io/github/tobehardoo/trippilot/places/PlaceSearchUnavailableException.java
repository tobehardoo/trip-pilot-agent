package io.github.tobehardoo.trippilot.places;

/** Raised when the AMap Web Service cannot be reached after bounded retries. */
public class PlaceSearchUnavailableException extends RuntimeException {

    public PlaceSearchUnavailableException() {
        super("Place search provider is unavailable");
    }
}
