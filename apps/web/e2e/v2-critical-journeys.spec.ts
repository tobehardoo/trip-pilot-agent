import { expect, test, type Page } from '@playwright/test'

const tripId = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
const taskId = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
const versionId = 'cccccccc-cccc-cccc-cccc-cccccccccccc'

const session = {
  user: { id: 'dddddddd-dddd-dddd-dddd-dddddddddddd', email: 'v2@example.com', displayName: 'V2 Traveler' },
  accessToken: 'v2-browser-token',
  tokenType: 'Bearer',
  expiresIn: 900,
}

const trip = {
  id: tripId,
  title: 'Controlled planning trip',
  destination: 'Guangzhou',
  startDate: '2026-08-01',
  endDate: '2026-08-02',
  status: 'DRAFT',
  version: 0,
  constraints: {
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
  },
  createdAt: '2026-07-27T00:00:00Z',
  updatedAt: '2026-07-27T00:00:00Z',
  archivedAt: null,
}

const plannedItinerary = {
  versionId,
  versionNumber: 1,
  parentVersionId: null,
  title: 'Controlled final itinerary',
  estimatedTotalCost: 88,
  provider: 'DEMO',
  days: [{
    date: '2026-08-01',
    activities: [{
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
    }],
    transitLegs: [],
  }],
  knowledge: { status: 'UNAVAILABLE', query: 'Guangzhou', citations: [], freshness: { status: 'UNAVAILABLE', checkedAt: null, staleReason: 'Controlled demo' }, message: 'Controlled demo' },
  createdAt: '2026-07-27T00:10:00Z',
}

function progressEvent(eventId: number, sequence: number, stage: string, progress: number, message: string) {
  return `id: ${eventId}\ndata: ${JSON.stringify({ eventId, eventType: 'PLANNING_PROGRESS', payload: { stage, sequence, progress, message, statistics: {} }, createdAt: '2026-07-27T00:00:00Z' })}\n\n`
}

function completedEvent(eventId: number) {
  return `id: ${eventId}\ndata: ${JSON.stringify({ eventId, eventType: 'PLANNING_COMPLETED', payload: {}, createdAt: '2026-07-27T00:00:02Z' })}\n\n`
}

async function mockPlanningApi(page: Page) {
  let streamAttempts = 0
  let completed = false
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path === '/api/auth/refresh') return route.fulfill({ json: session })
    if (path === '/api/trips' && request.method() === 'GET') return route.fulfill({ json: [trip] })
    if (path === `/api/trips/${tripId}`) return route.fulfill({ json: trip })
    if (path === `/api/trips/${tripId}/guide-imports` || path === `/api/trips/${tripId}/itinerary/shares`) return route.fulfill({ json: [] })
    if (path === `/api/trips/${tripId}/itinerary/versions`) return route.fulfill({ json: completed ? [{ id: versionId, versionNumber: 1, title: plannedItinerary.title, createdAt: plannedItinerary.createdAt }] : [] })
    if (path === `/api/trips/${tripId}/itinerary`) {
      return completed
        ? route.fulfill({ json: plannedItinerary })
        : route.fulfill({ status: 404, json: { code: 'ITINERARY_NOT_FOUND', message: 'Not planned' } })
    }
    if (path === `/api/trips/${tripId}/planning-tasks` && request.method() === 'POST') {
      return route.fulfill({ status: 202, json: { taskId, tripId, taskType: 'CREATE', status: 'QUEUED', baselineTripVersion: 0, eventStreamUrl: `/api/planning-tasks/${taskId}/events`, createdAt: '2026-07-27T00:00:00Z', updatedAt: '2026-07-27T00:00:00Z' } })
    }
    if (path === `/api/planning-tasks/${taskId}/events`) {
      streamAttempts += 1
      if (streamAttempts === 1) return route.abort('connectionreset')
      completed = true
      return route.fulfill({
        contentType: 'text/event-stream',
        body: progressEvent(2, 2, 'ROUTES_CALCULATING', 60, 'Routes calculated')
          + progressEvent(3, 2, 'ROUTES_CALCULATING', 60, 'Routes calculated')
          + progressEvent(4, 3, 'RESULT_PERSISTING', 95, 'Persisted final itinerary')
          + completedEvent(5),
      })
    }
    return route.fulfill({ status: 501, json: { code: 'UNMOCKED_V2_REQUEST', message: `${request.method()} ${path}` } })
  })
  return () => streamAttempts
}

test('recovers the planning stream and ignores a duplicate stage before showing one final itinerary', async ({ page }) => {
  const streamAttempts = await mockPlanningApi(page)
  await page.goto('/trips')
  await page.getByRole('button', { name: '打开 Controlled planning trip' }).click()
  await page.getByTestId('start-planning').click()

  await expect(page.getByTestId('planning-current-stage')).toContainText('正在保存行程版本')
  await expect(page.getByRole('heading', { name: 'River walk', level: 3 })).toBeVisible()
  await expect(page.getByText('Controlled final itinerary')).toBeVisible()
  await expect.poll(streamAttempts).toBe(2)
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
