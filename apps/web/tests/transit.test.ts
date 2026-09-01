import { expect, test } from 'vitest'

import {
  commuteModeLabel,
  persistedTransitDisplayCost,
} from '../src/lib/transit'

const leg = {
  id: 'leg-1',
  legOrder: 0,
  fromActivityId: 'a',
  toActivityId: 'b',
  mode: 'WALKING' as const,
  distanceMeters: 2400,
  durationSeconds: 1920,
  provider: 'AMAP' as const,
  estimated: false,
  polyline: [],
}

test('maps every persisted road route to the stable taxi presentation', () => {
  expect(commuteModeLabel('DRIVING')).toBe('打车')
  expect(commuteModeLabel('TAXI')).toBe('打车')
})

test('never exposes a persisted driving toll as a user-visible taxi fare', () => {
  expect(persistedTransitDisplayCost({
    mode: 'DRIVING',
    estimatedCost: 6.5,
    displayCost: undefined,
  })).toBeNull()
})
