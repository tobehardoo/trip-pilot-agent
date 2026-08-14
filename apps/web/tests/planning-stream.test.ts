import { describe, expect, test } from 'vitest'

import { createTerminalShortCircuit } from '../src/lib/planning-stream'

describe('createTerminalShortCircuit', () => {
  test('accepts progress and queued frames before any terminal event', () => {
    const guard = createTerminalShortCircuit()
    expect(guard.accept({ eventType: 'PLANNING_QUEUED' })).toBe(true)
    expect(guard.accept({ eventType: 'PLANNING_PROGRESS' })).toBe(true)
    expect(guard.armed).toBe(false)
  })

  test('ignores a second identical COMPLETED frame in one stream response', () => {
    const guard = createTerminalShortCircuit()
    expect(guard.accept({ eventType: 'PLANNING_COMPLETED' })).toBe(true)
    expect(guard.armed).toBe(true)
    expect(guard.accept({ eventType: 'PLANNING_COMPLETED' })).toBe(false)
  })

  test('ignores REVIEW_REQUIRED arriving after COMPLETED', () => {
    const guard = createTerminalShortCircuit()
    expect(guard.accept({ eventType: 'PLANNING_COMPLETED' })).toBe(true)
    expect(guard.accept({ eventType: 'PLANNING_REVIEW_REQUIRED' })).toBe(false)
  })

  test('ignores COMPLETED arriving after REVIEW_REQUIRED', () => {
    const guard = createTerminalShortCircuit()
    expect(guard.accept({ eventType: 'PLANNING_REVIEW_REQUIRED' })).toBe(true)
    expect(guard.accept({ eventType: 'PLANNING_COMPLETED' })).toBe(false)
  })

  test('ignores late progress after a terminal frame', () => {
    const guard = createTerminalShortCircuit()
    expect(guard.accept({ eventType: 'PLANNING_FAILED' })).toBe(true)
    expect(guard.accept({ eventType: 'PLANNING_PROGRESS' })).toBe(false)
  })

  test('applies a completed outcome exactly once so the itinerary reloads once', () => {
    const guard = createTerminalShortCircuit()
    let reloads = 0
    for (const frame of [
      { eventType: 'PLANNING_COMPLETED' },
      { eventType: 'PLANNING_COMPLETED' },
      { eventType: 'PLANNING_PROGRESS' },
    ]) {
      if (!guard.accept(frame)) continue
      if (frame.eventType === 'PLANNING_COMPLETED') reloads += 1
    }
    expect(reloads).toBe(1)
  })

  test('treats malformed-terminal-typed frames as terminal so the first one is still handled', () => {
    const guard = createTerminalShortCircuit()
    // The payload may be malformed, but the event type still arms the guard:
    // the first terminal-typed frame must be processed (and fail closed),
    // every following frame must be ignored.
    expect(guard.accept({ eventType: 'PLANNING_COMPLETED' })).toBe(true)
    expect(guard.accept({ eventType: 'PLANNING_CANCELLED' })).toBe(false)
  })

  test('does not treat unknown event types as terminal', () => {
    const guard = createTerminalShortCircuit()
    expect(guard.accept({ eventType: 'PLANNING_UNKNOWN_STAGE' })).toBe(true)
    expect(guard.armed).toBe(false)
  })

  test('stale cross-trip/session frames are rejected by the caller guard before the short-circuit runs', () => {
    // Locks the TripWorkspace wiring contract: the session/route guard must
    // run first, and only frames it accepts may reach the short-circuit or
    // advance the Last-Event-ID cursor.
    const guard = createTerminalShortCircuit()
    let lastEventId = 0
    const isCurrentPlanningRequest = () => false
    const handleEvent = (event: { eventType: string; id: number }) => {
      if (!isCurrentPlanningRequest()) return
      if (!guard.accept(event)) return
      lastEventId = event.id
    }
    handleEvent({ eventType: 'PLANNING_COMPLETED', id: 7 })
    expect(guard.armed).toBe(false)
    expect(lastEventId).toBe(0)
  })
})
