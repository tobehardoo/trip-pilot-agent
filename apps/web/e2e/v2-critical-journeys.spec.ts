import { expect, test, type Page } from '@playwright/test'

const tripId = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'

const session = {
  user: { id: 'dddddddd-dddd-dddd-dddd-dddddddddddd', email: 'v2@example.com', displayName: 'V2 Traveler' },
  accessToken: 'v2-browser-token',
  tokenType: 'Bearer',
  expiresIn: 900,
}

const baseConstraints = {
  budgetAmount: 1200,
  travelers: 1,
  travelerType: 'SOLO',
  pace: 'BALANCED',
  preferences: [],
  fixedSchedules: [],
  arrival: null,
  departure: null,
  accommodation: null,
  mustVisitPlaces: [],
  avoidPlaces: [],
  mealWindows: [],
  mobilityLevel: 'STANDARD',
  schemaVersion: 2,
}

const planningTrip = {
  id: tripId,
  title: 'Controlled planning trip',
  destination: 'Guangzhou',
  startDate: '2026-08-01',
  endDate: '2026-08-02',
  status: 'PLANNING',
  version: 0,
  constraints: baseConstraints,
  createdAt: '2026-07-27T00:00:00Z',
  updatedAt: '2026-07-27T00:00:00Z',
  archivedAt: null,
}

const completedTrip = {
  ...planningTrip,
  title: 'Controlled final trip',
  status: 'COMPLETED',
  version: 1,
}

const emptyItineraryTrip = { ...planningTrip, title: 'Empty completed trip', status: 'COMPLETED', version: 1 }

const plannedItinerary = {
  versionId: 'cccccccc-cccc-cccc-cccc-cccccccccccc',
  versionNumber: 1,
  parentVersionId: null,
  title: 'Controlled final itinerary',
  estimatedTotalCost: 88,
  provider: 'DEMO',
  days: [{
    date: '2026-08-01',
    dayType: null,
    activities: [
      {
        id: 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
        title: 'River walk',
        startTime: '2026-08-01T01:00:00Z',
        endTime: '2026-08-01T02:00:00Z',
        estimatedCost: 0,
        source: 'DEMO',
        providerPoiId: null,
        coordinates: { longitude: 113.26, latitude: 23.13 },
        address: 'Riverside',
        locked: false,
        typeCode: null,
        typeName: null,
        kind: 'EXPERIENCE',
        timeFixed: null,
      },
      {
        id: 'ffffffff-ffff-ffff-ffff-ffffffffffff',
        title: 'Canton Tower',
        startTime: '2026-08-01T04:00:00Z',
        endTime: '2026-08-01T06:00:00Z',
        estimatedCost: 40,
        source: 'DEMO',
        providerPoiId: null,
        coordinates: { longitude: 113.32, latitude: 23.1 },
        address: 'Guangzhou',
        locked: false,
        typeCode: null,
        typeName: 'Landmark',
        kind: 'ATTRACTION',
        timeFixed: null,
      },
    ],
    transitLegs: [{
      id: 'dddddddd-dddd-dddd-dddd-dddddddddddd',
      legOrder: 0,
      fromActivityId: 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
      toActivityId: 'ffffffff-ffff-ffff-ffff-ffffffffffff',
      mode: 'WALKING',
      locked: false,
      distanceMeters: 2000,
      durationSeconds: 1500,
      provider: 'DEMO',
      estimated: true,
      estimatedCost: 0,
      providerRouteId: null,
      calculatedAt: '2026-07-27T00:00:00Z',
      stale: false,
      polyline: [],
    }],
  }],
  knowledge: { status: 'UNAVAILABLE', query: 'Guangzhou', citations: [], freshness: { status: 'UNAVAILABLE', checkedAt: null, staleReason: 'Controlled demo' }, message: 'Controlled demo' },
  createdAt: '2026-07-27T00:10:00Z',
}

async function mockApi(page: Page, trip: unknown, itineraryBody: unknown) {
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()
    if (path === '/api/auth/refresh') return route.fulfill({ json: session })
    if (path === '/api/trips' && method === 'GET') return route.fulfill({ json: [trip] })
    if (path === `/api/trips/${tripId}`) return route.fulfill({ json: trip })
    if (path === `/api/trips/${tripId}/guide-imports` || path === `/api/trips/${tripId}/itinerary/shares`) {
      return route.fulfill({ json: [] })
    }
    if (path === `/api/trips/${tripId}/itinerary/versions`) return route.fulfill({ json: [] })
    if (path === `/api/trips/${tripId}/itinerary`) {
      return typeof itineraryBody === 'function'
        ? route.fulfill({ json: itineraryBody() })
        : route.fulfill(itineraryBody as {})
    }
    if (path === `/api/trips/${tripId}/planning-tasks/latest`) {
      return route.fulfill({ status: 404, json: { code: 'PLANNING_TASK_NOT_FOUND', message: 'none' } })
    }
    if (path === `/api/trips/${tripId}/planning-tasks` && method === 'POST') {
      return route.fulfill({ status: 202, json: { taskId: 'task-1', tripId, taskType: 'CREATE', status: 'QUEUED', baselineTripVersion: 0, eventStreamUrl: '', createdAt: '2026-07-27T00:00:00Z', updatedAt: '2026-07-27T00:00:00Z' } })
    }
    if (path === `/api/trips/${tripId}/agent-dialogue/events`) {
      return route.fulfill({ contentType: 'text/event-stream', body: '' })
    }
    if (path === `/api/trips/${tripId}/agent-dialogue/runs` && method === 'POST') {
      return route.fulfill({ status: 202, json: { eventId: 'evt', status: 'QUEUED' } })
    }
    return route.fulfill({ status: 501, json: { code: 'UNMOCKED_V2_REQUEST', message: `${method} ${path}` } })
  })
}

test('stays in the planning view for a planning trip (no fake success)', async ({ page }) => {
  await mockApi(page, planningTrip, {
    status: 404,
    json: { code: 'ITINERARY_NOT_FOUND', message: 'Not planned' },
  })
  await page.goto(`/workspace/trips/${tripId}`)

  await expect(page.getByTestId('planning-status-line')).toContainText('TripPilot 正在规划你的旅行')
  await expect(page.getByTestId('agent-dialog')).toBeVisible()
  // 完成态标记绝不出现
  await expect(page.getByTestId('agent-message-done')).toHaveCount(0)
  await expect(page.getByText('行程已完成，但方案数据当前不可用')).toHaveCount(0)
})

test('renders a completed itinerary with day routes and a transit leg', async ({ page }) => {
  await mockApi(page, completedTrip, { json: plannedItinerary })
  await page.goto(`/workspace/trips/${tripId}`)

  await expect(page.getByTestId('plan-overview-title')).toHaveText(completedTrip.title)
  await expect(page.getByTestId('agent-message-done')).toContainText('旅行方案已经完成')
  await expect(page.getByTestId('trip-route-map')).toBeVisible()
  await expect(page.getByTestId('plan-day-chip-2026-08-01')).toBeVisible()
  await expect(page.getByTestId('plan-activity-River walk')).toBeVisible()
  await expect(page.getByTestId('plan-activity-Canton Tower')).toBeVisible()
  await expect(page.getByTestId('plan-transit-Canton Tower')).toContainText('步行')
})

test('fails closed when a completed trip has no itinerary data (no 0-day fake success)', async ({ page }) => {
  const emptyItinerary = { ...plannedItinerary, days: [] }
  await mockApi(page, emptyItineraryTrip, { json: emptyItinerary })
  await page.goto(`/workspace/trips/${tripId}`)

  await expect(page.getByTestId('workspace-itinerary-empty')).toBeVisible()
  await expect(page.getByText('行程已完成，但方案数据当前不可用。')).toBeVisible()
  // 绝不渲染「已完成 0 天」的假成功条
  await expect(page.getByTestId('agent-message-done')).toHaveCount(0)
})

test('renders a redacted immutable share on a narrow mobile viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.route('**/api/shares/**', (route) => route.fulfill({
    json: {
      title: 'Shared Guangzhou day',
      estimatedTotalCost: 88,
      provider: 'DEMO',
      generatedAt: '2026-07-27T00:00:00Z',
      days: [{
        date: '2026-08-01',
        activities: [{ title: 'River walk', startTime: '2026-08-01T01:00:00Z', endTime: '2026-08-01T02:00:00Z', estimatedCost: 0, address: 'Riverside' }],
        transitLegs: [{ mode: 'TRANSIT', distanceMeters: 1200, durationSeconds: 600, estimatedCost: 2, provider: 'DEMO', estimated: true, stale: false }],
      }],
      sources: [{ title: 'Official source', sourceName: 'Demo source', sourceUrl: 'https://example.com/source', reliabilityLevel: 'OFFICIAL' }],
    },
  }))

  await page.goto('/share/controlled-public-token')
  await expect(page.getByRole('heading', { name: 'Shared Guangzhou day' })).toBeVisible()
  await expect(page.getByText('River walk')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Official source' })).toHaveAttribute('href', 'https://example.com/source')
  await expect(page.locator('body')).not.toContainText('ownerId')
})