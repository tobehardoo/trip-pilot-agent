import { expect, test, type Page } from '@playwright/test'

const tripId = '22222222-2222-2222-2222-222222222222'

const session = {
  user: {
    id: '11111111-1111-1111-1111-111111111111',
    email: 'traveler@example.com',
    displayName: '旅行者',
  },
  accessToken: 'browser-smoke-token',
  tokenType: 'Bearer',
  expiresIn: 900,
}

const trip = {
  id: tripId,
  title: '广州周末四日',
  destination: '广州',
  startDate: '2026-08-01',
  endDate: '2026-08-04',
  status: 'READY',
  version: 2,
  constraints: {
    budgetAmount: 4000,
    travelers: 2,
    travelerType: 'FRIENDS',
    pace: 'BALANCED',
    preferences: ['岭南文化', '本地美食'],
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
  createdAt: '2026-07-26T01:00:00Z',
  updatedAt: '2026-07-26T02:00:00Z',
}

const itinerary = {
  versionId: '55555555-5555-5555-5555-555555555555',
  versionNumber: 2,
  parentVersionId: '44444444-4444-4444-4444-444444444444',
  title: '广州 Demo 行程',
  estimatedTotalCost: 160,
  provider: 'DEMO',
  days: [{
    date: '2026-08-01',
    activities: [{
      id: '66666666-6666-6666-6666-666666666666',
      title: '漫步沙面岛',
      startTime: '2026-08-01T01:00:00Z',
      endTime: '2026-08-01T03:00:00Z',
      estimatedCost: 0,
      source: 'DEMO',
      providerPoiId: null,
      coordinates: { longitude: 113.2392, latitude: 23.1097 },
      address: '广州市荔湾区沙面岛',
      locked: false,
    }, {
      id: '77777777-7777-7777-7777-777777777777',
      title: '品尝西关早茶',
      startTime: '2026-08-01T04:00:00Z',
      endTime: '2026-08-01T05:30:00Z',
      estimatedCost: 160,
      source: 'DEMO',
      providerPoiId: null,
      coordinates: { longitude: 113.2489, latitude: 23.1189 },
      address: '广州市荔湾区',
      locked: false,
    }],
    transitLegs: [{
      id: '88888888-8888-8888-8888-888888888888',
      legOrder: 0,
      fromActivityId: '66666666-6666-6666-6666-666666666666',
      toActivityId: '77777777-7777-7777-7777-777777777777',
      mode: 'DRIVING',
      distanceMeters: 1380,
      durationSeconds: 1100,
      provider: 'DEMO',
      estimated: true,
      polyline: [],
      locked: false,
    }],
  }],
  knowledge: {
    status: 'UNAVAILABLE',
    query: '广州 岭南文化 本地美食',
    citations: [],
    freshness: {
      status: 'UNAVAILABLE',
      checkedAt: null,
      staleReason: 'Demo 模式未连接真实知识源',
    },
    message: 'Demo 模式未声明实时知识',
  },
  createdAt: '2026-07-26T02:00:00Z',
}

const combinedItinerary = {
  ...itinerary,
  days: [
    ...itinerary.days,
    {
      date: '2026-08-02',
      activities: [{
        id: '99999999-9999-4999-8999-999999999999',
        title: 'Museum day two',
        startTime: '2026-08-02T02:00:00Z',
        endTime: '2026-08-02T04:00:00Z',
        estimatedCost: 20,
        source: 'DEMO',
        providerPoiId: null,
        coordinates: { longitude: 113.27, latitude: 23.13 },
        address: 'Museum Road',
        locked: false,
      }],
      transitLegs: [],
    },
  ],
}

const planningTaskId = '33333333-3333-4333-8333-333333333333'

const combinedEvaluation = {
  schemaVersion: 1,
  evaluatorVersion: 'rule-v1',
  feasible: true,
  overallScore: 91,
  dimensions: {
    constraintSatisfaction: 100,
    timeFeasibility: 88,
    budgetFit: 94,
    routeEfficiency: 86,
    interestMatch: 87,
  },
  warnings: [],
  decisions: [],
  summary: 'Combined browser acceptance score.',
  evaluatedAt: '2026-08-02T00:00:00Z',
}

const cityIntelligence = {
  id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  sourceType: 'CITY_INTELLIGENCE',
  sourceUrl: 'https://dev.qweather.com/en/docs/api/',
  finalUrl: 'https://dev.qweather.com/en/docs/api/',
  sourceHost: 'QWeather',
  title: 'Combined city intelligence',
  excerpt: '2026-08-02 weather forecast.',
  contentHash: 'a'.repeat(64),
  fetchedAt: '2026-08-02T00:00:00Z',
  enabled: true,
  facts: [{
    id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    category: 'WEATHER',
    statement: '2026-08-02 广州天气预报：白天晴 32℃，夜间多云 25℃，东风3级。',
    evidence: 'Controlled QWeather response.',
    confidence: 0.9,
    observedAt: '2026-08-02T00:00:00Z',
    expiresAt: '2026-08-03T00:00:00Z',
  }],
}

async function mockReleaseApi(page: Page, options: { combined?: boolean } = {}) {
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname

    if (path === '/api/auth/refresh') {
      await route.fulfill({ json: session })
      return
    }
    if (path === '/api/trips' && request.method() === 'GET') {
      await route.fulfill({ json: [trip] })
      return
    }
    if (path === `/api/trips/${tripId}`) {
      await route.fulfill({ json: trip })
      return
    }
    if (path === `/api/trips/${tripId}/itinerary`) {
      await route.fulfill({ json: options.combined ? combinedItinerary : itinerary })
      return
    }
    if (path === `/api/trips/${tripId}/itinerary/versions`) {
      await route.fulfill({ json: [{
        versionId: itinerary.versionId,
        versionNumber: itinerary.versionNumber,
        parentVersionId: itinerary.parentVersionId,
        planningTaskId: options.combined ? planningTaskId : null,
        versionSource: options.combined ? 'PLANNING_TASK' : 'USER_EDIT',
        title: itinerary.title,
        estimatedTotalCost: itinerary.estimatedTotalCost,
        provider: itinerary.provider,
        rollbackFromVersionId: null,
        createdAt: itinerary.createdAt,
        current: true,
      }] })
      return
    }
    if (path === `/api/trips/${tripId}/guide-imports`) {
      await route.fulfill({ json: options.combined ? [cityIntelligence] : [] })
      return
    }
    if (options.combined && path === `/api/planning-tasks/${planningTaskId}`) {
      await route.fulfill({
        json: {
          taskId: planningTaskId,
          tripId,
          taskType: 'CREATE',
          status: 'SUCCEEDED',
          baselineTripVersion: 0,
          eventStreamUrl: `/api/planning-tasks/${planningTaskId}/events`,
          evaluation: combinedEvaluation,
          createdAt: '2026-08-02T00:00:00Z',
          updatedAt: '2026-08-02T00:01:00Z',
        },
      })
      return
    }
    if (path === `/api/trips/${tripId}/itinerary/edits/preview`) {
      await route.fulfill({
        json: {
          operation: 'LOCK_ACTIVITY',
          canApply: true,
          impactedDates: ['2026-08-01'],
          impactedActivityIds: ['66666666-6666-6666-6666-666666666666'],
          warnings: ['锁定后局部重规划会保留此活动'],
          blockingReasons: [],
        },
      })
      return
    }
    if (path === `/api/trips/${tripId}/itinerary/edits/commit` && request.method() === 'POST') {
      await route.fulfill({ json: itinerary })
      return
    }

    await route.fulfill({
      status: 501,
      json: { code: 'UNMOCKED_RELEASE_SMOKE_REQUEST', message: `${request.method()} ${path}` },
    })
  })
}

test('restores a session and opens the trip planning workspace', async ({ page }) => {
  await mockReleaseApi(page)
  await page.goto('/trips')

  await expect(page.getByRole('heading', { name: '我的旅行' })).toBeVisible()
  await expect(page.getByRole('heading', { name: trip.title })).toBeVisible()
  await page.getByRole('button', { name: `打开 ${trip.title}` }).click()

  await expect(page).toHaveURL(`/trips/${tripId}`)
  await expect(page.getByRole('heading', { name: trip.title, level: 1 })).toBeVisible()
  await expect(page.getByLabel('行程版本').getByText('版本 2')).toBeVisible()
  await expect(page.getByRole('button', { name: '选择活动 漫步沙面岛' })).toBeVisible()
})

test('opens an itinerary edit preview before applying a mutation', async ({ page }) => {
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await mockReleaseApi(page)
  await page.goto('/trips')
  await page.getByRole('button', { name: `打开 ${trip.title}` }).click()
  await expect(page.getByRole('heading', { name: trip.title, level: 1 })).toBeVisible()

  const previewResponse = page.waitForResponse((response) => (
    new URL(response.url()).pathname.endsWith('/itinerary/edits/preview')
  ))
  await page.getByRole('button', { name: '锁定活动 漫步沙面岛' }).click()
  await expect((await previewResponse).status()).toBe(200)
  expect(pageErrors).toEqual([])

  const dialog = page.getByRole('dialog', { name: '确认行程修改' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText('锁定活动')).toBeVisible()
  await expect(dialog.getByText('2026-08-01')).toBeVisible()
  await expect(dialog.getByRole('button', { name: '应用修改' })).toBeEnabled()
})

test('stores several traveller edits as a draft and commits them only after confirmation', async ({ page }) => {
  await mockReleaseApi(page)
  await page.goto('/trips')
  await page.getByRole('button', { name: `打开 ${trip.title}` }).click()
  await page.getByRole('button', { name: '锁定活动 漫步沙面岛' }).click()
  await page.getByRole('button', { name: '应用修改' }).click()

  await expect(page.getByTestId('save-itinerary-draft')).toBeVisible()
  await page.getByTestId('save-itinerary-draft').click()
  await expect(page.getByTestId('save-itinerary-draft')).toBeHidden()
})

test('restores evaluation and links the weather date to the map route', async ({ page }) => {
  await mockReleaseApi(page, { combined: true })
  await page.goto(`/trips/${tripId}`)

  await expect(page.getByText('行程质量')).toBeVisible()
  await expect(page.getByText('91/100')).toBeVisible()

  const weather = page.getByRole('region', { name: '行程天气' })
  const map = page.getByTestId('trip-map')
  const mapLocations = map.locator('button[aria-label^="定位 "]')
  await expect(weather).toBeVisible()
  await expect(mapLocations).toHaveCount(3)

  const secondDay = weather.getByRole('button', { name: '选择 2026-08-02 天气' })
  await secondDay.click()

  await expect(secondDay).toHaveAttribute('aria-pressed', 'true')
  await expect(mapLocations).toHaveCount(1)
  await expect(map.getByRole('button', { name: '定位 Museum day two' })).toBeVisible()
})
