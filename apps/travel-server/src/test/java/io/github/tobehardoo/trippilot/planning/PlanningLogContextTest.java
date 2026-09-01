package io.github.tobehardoo.trippilot.planning;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Verifies the PlanningLogContext lifecycle: managed keys are populated while
 * a scope is open and restored to their prior state (usually absent) after it
 * closes, on both the success and the exception path, and nested scopes never
 * wipe the outer scope's correlation fields.
 */
class PlanningLogContextTest {

    @AfterEach
    void tearDown() {
        MDC.clear();
    }

    @Test
    void restoresManagedKeysAfterClose() {
        try (PlanningLogContext ctx = PlanningLogContext.open()) {
            ctx.put(PlanningLogContext.TRACE_ID, "trace-1")
                    .put(PlanningLogContext.TASK_ID, "task-1");
            assertThat(MDC.get(PlanningLogContext.TRACE_ID)).isEqualTo("trace-1");
            assertThat(MDC.get(PlanningLogContext.TASK_ID)).isEqualTo("task-1");
        }
        assertThat(MDC.get(PlanningLogContext.TRACE_ID)).isNull();
        assertThat(MDC.get(PlanningLogContext.TASK_ID)).isNull();
    }

    @Test
    void clearsManagedKeysOnTheExceptionPath() {
        try {
            try (PlanningLogContext ctx = PlanningLogContext.open()) {
                ctx.put(PlanningLogContext.TASK_ID, "task-exception");
                assertThat(MDC.get(PlanningLogContext.TASK_ID)).isEqualTo("task-exception");
                throw new IllegalStateException("boom");
            }
        } catch (IllegalStateException expected) {
            // expected
        }
        assertThat(MDC.get(PlanningLogContext.TASK_ID)).isNull();
        assertThat(MDC.get(PlanningLogContext.TRACE_ID)).isNull();
    }

    @Test
    void nestedScopeRestoresOuterValuesRatherThanWipingThem() {
        try (PlanningLogContext outer = PlanningLogContext.open()) {
            outer.put(PlanningLogContext.TRACE_ID, "trace-outer");
            try (PlanningLogContext inner = PlanningLogContext.open()) {
                inner.put(PlanningLogContext.TASK_ID, "task-inner");
                assertThat(MDC.get(PlanningLogContext.TRACE_ID)).isEqualTo("trace-outer");
                assertThat(MDC.get(PlanningLogContext.TASK_ID)).isEqualTo("task-inner");
            }
            assertThat(MDC.get(PlanningLogContext.TRACE_ID)).isEqualTo("trace-outer");
            assertThat(MDC.get(PlanningLogContext.TASK_ID)).isNull();
        }
        assertThat(MDC.get(PlanningLogContext.TRACE_ID)).isNull();
    }

    @Test
    void blankValuesAreNotPutIntoMdc() {
        try (PlanningLogContext ctx = PlanningLogContext.open()) {
            ctx.put(PlanningLogContext.TRACE_ID, "   ");
            assertThat(MDC.get(PlanningLogContext.TRACE_ID)).isNull();
        }
    }

    @Test
    void doesNotTouchUnrelatedMdcKeys() {
        MDC.put("unrelated", "kept");
        try (PlanningLogContext ctx = PlanningLogContext.open()) {
            ctx.put(PlanningLogContext.TASK_ID, "task-1");
        }
        assertThat(MDC.get("unrelated")).isEqualTo("kept");
    }
}
