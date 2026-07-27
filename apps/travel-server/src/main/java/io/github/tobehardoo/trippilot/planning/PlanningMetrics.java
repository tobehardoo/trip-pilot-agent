package io.github.tobehardoo.trippilot.planning;

import java.time.Duration;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.springframework.stereotype.Component;

@Component
public class PlanningMetrics {

    private final MeterRegistry registry;

    public PlanningMetrics(MeterRegistry registry) {
        this.registry = registry;
    }

    public void taskCreated(String taskType) {
        Counter.builder("trippilot_planning_tasks")
                .tag("outcome", "created")
                .tag("task_type", taskType)
                .register(registry)
                .increment();
    }

    public void stageDuration(String stage, Duration duration) {
        Timer.builder("trippilot_planning_stage_duration")
                .tag("stage", stage)
                .publishPercentileHistogram()
                .register(registry)
                .record(nonNegative(duration));
    }

    public void progressObserved(String stage) {
        Counter.builder("trippilot_planning_progress_events")
                .tag("stage", stage)
                .register(registry)
                .increment();
    }

    public void taskFinished(String taskType, String outcome, Duration duration) {
        Counter.builder("trippilot_planning_tasks")
                .tag("outcome", outcome.toLowerCase(java.util.Locale.ROOT))
                .tag("task_type", taskType)
                .register(registry)
                .increment();
        Timer.builder("trippilot_planning_task_duration")
                .tag("outcome", outcome)
                .tag("task_type", taskType)
                .publishPercentileHistogram()
                .register(registry)
                .record(nonNegative(duration));
    }

    private Duration nonNegative(Duration duration) {
        return duration.isNegative() ? Duration.ZERO : duration;
    }
}
