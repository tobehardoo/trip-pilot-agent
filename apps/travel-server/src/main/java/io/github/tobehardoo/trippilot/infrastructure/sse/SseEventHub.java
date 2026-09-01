package io.github.tobehardoo.trippilot.infrastructure.sse;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/**
 * UUID-keyed SSE hub shared by the agent-dialog and planning-task streams.
 *
 * Both streams historically owned a private copy of the same emitter
 * lifecycle: a striped-monitor subscriber registry, replay-on-subscribe and
 * terminal-event completion.  This hub keeps that lifecycle in one place;
 * the per-stream history source, event view shape and terminal semantics are
 * supplied by the caller through {@link EventReplayer} and the
 * {@code terminal} flag, so the wire JSON of each stream stays unchanged.
 */
@Component
public class SseEventHub {

    private static final long STREAM_TIMEOUT_MILLIS = 30 * 60 * 1000L;
    private static final int MONITOR_COUNT = 256;

    private final Object[] monitors = createMonitors();
    private final Map<UUID, List<SseEmitter>> subscribers = new ConcurrentHashMap<>();

    /**
     * Registers an SSE emitter for {@code key}, replaying persisted history
     * first.  The replayer returns whether it replayed a terminal event; the
     * stream is completed immediately when the caller declares the subject
     * terminal or a terminal event was replayed.
     */
    public SseEmitter subscribe(UUID key, EventReplayer replayer, boolean completeAfterReplay) {
        SseEmitter emitter = new SseEmitter(STREAM_TIMEOUT_MILLIS);
        emitter.onCompletion(() -> remove(key, emitter));
        emitter.onTimeout(() -> remove(key, emitter));
        emitter.onError(exception -> remove(key, emitter));

        boolean terminalReplayed;
        synchronized (monitorFor(key)) {
            try {
                terminalReplayed = replayer.replay(emitter);
            } catch (IOException | IllegalStateException exception) {
                emitter.completeWithError(exception);
                return emitter;
            }
            if (completeAfterReplay || terminalReplayed) {
                emitter.complete();
            } else {
                subscribers.computeIfAbsent(key, ignored -> new ArrayList<>()).add(emitter);
            }
        }
        return emitter;
    }

    /**
     * Fans a live event out to the subscribers of {@code key}.  Terminal
     * events complete every subscriber and free the registry entry.
     */
    public void publish(UUID key, SseEvent event, boolean terminal) {
        List<SseEmitter> snapshot;
        synchronized (monitorFor(key)) {
            List<SseEmitter> registered = subscribers.get(key);
            if (registered == null) {
                return;
            }
            snapshot = List.copyOf(registered);
            if (terminal) {
                subscribers.remove(key);
            }
        }
        for (SseEmitter emitter : snapshot) {
            try {
                send(emitter, event);
                if (terminal) {
                    emitter.complete();
                }
            } catch (IOException | IllegalStateException exception) {
                if (!terminal) {
                    remove(key, emitter);
                }
                emitter.completeWithError(exception);
            }
        }
    }

    /**
     * Sends one event on an emitter.  Stream replayers reuse this so the
     * wire framing (id / event name / JSON data) is defined in one place.
     */
    public void send(SseEmitter emitter, SseEvent event) throws IOException {
        emitter.send(SseEmitter.event()
                .id(Long.toString(event.id()))
                .name(event.name())
                .data(event.data(), MediaType.APPLICATION_JSON));
    }

    private void remove(UUID key, SseEmitter emitter) {
        synchronized (monitorFor(key)) {
            List<SseEmitter> keySubscribers = subscribers.get(key);
            if (keySubscribers == null) {
                return;
            }
            keySubscribers.remove(emitter);
            if (keySubscribers.isEmpty()) {
                subscribers.remove(key);
            }
        }
    }

    private Object monitorFor(UUID key) {
        int monitorIndex = (key.hashCode() & Integer.MAX_VALUE) % monitors.length;
        return monitors[monitorIndex];
    }

    private static Object[] createMonitors() {
        Object[] monitors = new Object[MONITOR_COUNT];
        Arrays.setAll(monitors, ignored -> new Object());
        return monitors;
    }

    @FunctionalInterface
    public interface EventReplayer {
        /**
         * Sends the persisted history for a key to the fresh emitter.
         *
         * @return true when a terminal event was replayed, so the hub can
         *         complete the stream instead of keeping it registered.
         */
        boolean replay(SseEmitter emitter) throws IOException;
    }

    public record SseEvent(long id, String name, JsonNode data) {
    }
}
