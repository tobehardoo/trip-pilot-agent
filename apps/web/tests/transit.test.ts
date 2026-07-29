import { expect, test } from 'vitest'

import { estimateCommuteOptions, recommendedCommuteMode } from '../src/lib/transit'

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

test('estimates all supported commute modes with time and money values', () => {
  const options = estimateCommuteOptions(leg)

  expect(options.map((option) => option.mode)).toEqual(['WALKING', 'TRANSIT', 'DRIVING', 'TAXI'])
  expect(options.find((option) => option.mode === 'WALKING')?.cost).toBe(0)
  expect(options.every((option) => option.durationSeconds > 0)).toBe(true)
  expect(options.find((option) => option.mode === 'TRANSIT')?.estimated).toBe(true)
  expect(options.find((option) => option.mode === 'TAXI')?.cost).toBeGreaterThan(0)
})

test('recommends the lowest-cost short walk while exposing faster alternatives', () => {
  const options = estimateCommuteOptions({ ...leg, distanceMeters: 800, durationSeconds: 640 })

  expect(recommendedCommuteMode(options)).toBe('WALKING')
  expect(options.find((option) => option.mode === 'TAXI')!.durationSeconds)
    .toBeLessThan(options.find((option) => option.mode === 'WALKING')!.durationSeconds)
})

test('does not recommend a long walk when public transit is available', () => {
  const options = estimateCommuteOptions({ ...leg, distanceMeters: 5250, durationSeconds: 70 * 60 })
  expect(recommendedCommuteMode(options)).toBe('TRANSIT')
})
