package io.github.tobehardoo.trippilot.planning;

import java.time.Duration;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class PlanningMetricsTest {

    @Test
    void recordsTaskOutcomesAndStageDurationsWithLowCardinalityTags() {
        SimpleMeterRegistry registry = new SimpleMeterRegistry();
        PlanningMetrics metrics = new PlanningMetrics(registry);

        metrics.taskCreated("CREATE");
        metrics.stageDuration("CONTEXT_VALIDATING", Duration.ofMillis(240));
        metrics.taskFinished("CREATE", "SUCCEEDED", Duration.ofSeconds(3));

        assertThat(registry.get("trippilot_planning_tasks")
                .tag("outcome", "created").tag("task_type", "CREATE").counter().count()).isEqualTo(1);
        assertThat(registry.get("trippilot_planning_stage_duration")
                .tag("stage", "CONTEXT_VALIDATING").timer().count()).isEqualTo(1);
        assertThat(registry.get("trippilot_planning_task_duration")
                .tag("outcome", "SUCCEEDED").tag("task_type", "CREATE").timer().count()).isEqualTo(1);
    }
}
