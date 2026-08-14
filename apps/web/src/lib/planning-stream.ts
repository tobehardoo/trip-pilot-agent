/**
 * B12: direct terminal short-circuit for planning SSE streams.
 *
 * A single SSE response must never apply more than one terminal outcome:
 * once the first terminal-typed frame has been accepted, every subsequent
 * frame of the same stream is ignored.  The guard is eventType-based and
 * purely synchronous so TripWorkspace can check it before updating its
 * lastEventId cursor, which keeps ignored frames from polluting the
 * Last-Event-ID reconnect position.
 */
export const TERMINAL_PLANNING_EVENT_TYPES: ReadonlySet<string> = new Set([
  'PLANNING_COMPLETED',
  'PLANNING_REVIEW_REQUIRED',
  'PLANNING_FAILED',
  'PLANNING_CANCELLED',
])

export interface TerminalShortCircuit {
  /**
   * Returns true when the frame may be processed.  Accepting a terminal
   * frame arms the short-circuit: every later call returns false.
   */
  accept(event: { eventType: string }): boolean
  readonly armed: boolean
}

export function createTerminalShortCircuit(): TerminalShortCircuit {
  let armed = false
  return {
    accept(event) {
      if (armed) return false
      if (TERMINAL_PLANNING_EVENT_TYPES.has(event.eventType)) {
        armed = true
      }
      return true
    },
    get armed() {
      return armed
    },
  }
}
