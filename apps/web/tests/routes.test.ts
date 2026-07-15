import { describe, expect, test } from 'vitest'

import { parseRoute, tripDetailPath } from '../src/lib/routes'

describe('application routes', () => {
  test('maps list aliases and trip detail paths', () => {
    expect(parseRoute('/')).toEqual({ name: 'trip-list' })
    expect(parseRoute('/trips')).toEqual({ name: 'trip-list' })
    expect(parseRoute('/trips/trip%20id')).toEqual({ name: 'trip-detail', tripId: 'trip id' })
    expect(tripDetailPath('trip id')).toBe('/trips/trip%20id')
  })

  test('rejects unrelated and nested paths', () => {
    expect(parseRoute('/settings')).toEqual({ name: 'not-found' })
    expect(parseRoute('/trips/id/plan')).toEqual({ name: 'not-found' })
    expect(parseRoute('/trips/%E0%A4%A')).toEqual({ name: 'not-found' })
  })
})
