package io.github.tobehardoo.trippilot.agentdialog;

import java.util.UUID;

import io.github.tobehardoo.trippilot.trip.TripService;
import org.springframework.stereotype.Component;

/** Ownership gate for agent dialog commands (backed by {@link TripService}). */
public interface TripOwnershipGuard {

    void requireOwnership(UUID ownerId, UUID tripId);

    @Component
    class TripServiceAdapter implements TripOwnershipGuard {

        private final TripService tripService;

        TripServiceAdapter(TripService tripService) {
            this.tripService = tripService;
        }

        @Override
        public void requireOwnership(UUID ownerId, UUID tripId) {
            tripService.get(ownerId, tripId);
        }
    }
}
