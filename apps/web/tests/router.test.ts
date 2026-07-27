import { createMemoryHistory } from 'vue-router'
import { describe, expect, test } from 'vitest'

describe('TripPilot router', () => {
  test('resolves the V2 application routes with stable route names', async () => {
    const { createTripPilotRouter } = await import('../src/app/router')
    const router = createTripPilotRouter(createMemoryHistory())

    await router.push('/trips')
    await router.isReady()
    expect(router.currentRoute.value.name).toBe('trip-list')

    await router.push('/trips/trip%20id/versions')
    expect(router.currentRoute.value).toMatchObject({
      name: 'trip-versions',
      params: { tripId: 'trip id' },
    })

    await router.push('/share/shared%20version')
    expect(router.currentRoute.value).toMatchObject({
      name: 'shared-itinerary',
      params: { shareToken: 'shared version' },
    })
  })
})
