// Weather window — completed 视图天气条（weather-banner，来自城市情报 WEATHER facts）。
// 同步入口为「攻略情报」面板的「同步城市情报」按钮（POST /guide-imports CITY_INTELLIGENCE）。
import { expect, test, type Page } from '@playwright/test'

const tripId = '22222222-2222-2222-2222-222222222222'

const session = {
  user: { id: '11111111-1111-1111-1111-111111111111', email: 'traveler@example.com', displayName: '旅行者' },
  accessToken: 'weather-window-token',
  tokenType: 'Bearer',
  expiresIn: 900,
}

const trip = {
  id: tripId,
  title: '广州周末二日',
  destination: '广州',
  startDate: '2026-08-01',
  endDate: '2026-08-02',
  status: 'COMPLETED',
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
  archivedAt: null,
}

const itinerary = {
  versionId: '55555555-5555-5555-5555-555555555555',
  versionNumber: 2,
  parentVersionId: null,
  title: '广州 Demo 行程',
  estimatedTotalCost: 160,
  provider: 'DEMO',
  days: [
    {
      date: '2026-08-01',
      dayType: null,
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
        typeCode: null,
        typeName: '景点',
        kind: 'ATTRACTION',
        timeFixed: null,
      }],
      transitLegs: [],
    },
    {
      date: '2026-08-02',
      dayType: null,
      activities: [{
        id: '99999999-9999-4999-8999-999999999999',
        title: '陈家祠',
        startTime: '2026-08-02T02:00:00Z',
        endTime: '2026-08-02T04:00:00Z',
        estimatedCost: 20,
        source: 'DEMO',
        providerPoiId: null,
        coordinates: { longitude: 113.2489, latitude: 23.1189 },
        address: '广州市荔湾区陈家祠',
        locked: false,
        typeCode: null,
        typeName: '古迹',
        kind: 'ATTRACTION',
        timeFixed: null,
      }],
      transitLegs: [],
    },
  ],
  knowledge: {
    status: 'UNAVAILABLE',
    query: '广州',
    citations: [],
    freshness: { status: 'UNAVAILABLE', checkedAt: null, staleReason: 'Demo' },
    message: 'Demo',
  },
  createdAt: '2026-07-26T02:00:00Z',
}

function weatherImport(id: string, effectiveDate: string, statement: string) {
  return {
    id,
    sourceType: 'CITY_INTELLIGENCE',
    sourceUrl: 'https://dev.qweather.com/',
    finalUrl: 'https://dev.qweather.com/',
    sourceHost: 'QWeather',
    title: '广州城市天气情报',
    excerpt: statement,
    contentHash: `hash-${id}`,
    fetchedAt: '2026-08-01T00:00:00Z',
    enabled: true,
    facts: [{
      id: `fact-${id}`,
      category: 'WEATHER',
      statement,
      evidence: 'Controlled weather response',
      confidence: 0.9,
      observedAt: '2026-08-01T00:00:00Z',
      expiresAt: '2026-08-03T00:00:00Z',
      effectiveDate,
    }],
    quality: null,
  }
}

async function mockWeatherApi(page: Page, initialImports: unknown[]) {
  const createdImports = new Map<string, unknown>()
  const syncBodies: unknown[] = []
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()

    if (path === '/api/auth/refresh') {
      await route.fulfill({ json: session })
      return
    }
    if (path === '/api/trips' && method === 'GET') {
      await route.fulfill({ json: [trip] })
      return
    }
    if (path === `/api/trips/${tripId}`) {
      await route.fulfill({ json: trip })
      return
    }
    if (path === `/api/trips/${tripId}/itinerary`) {
      await route.fulfill({ json: itinerary })
      return
    }
    if (path === `/api/trips/${tripId}/itinerary/versions`) {
      await route.fulfill({ json: [] })
      return
    }
    if (path === `/api/trips/${tripId}/itinerary/shares`) {
      await route.fulfill({ json: [] })
      return
    }
    if (path === `/api/trips/${tripId}/guide-imports` && method === 'GET') {
      await route.fulfill({ json: [...createdImports.values(), ...initialImports] })
      return
    }
    if (path === `/api/trips/${tripId}/guide-imports` && method === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>
      syncBodies.push(body)
      const created = weatherImport(
        `created-${syncBodies.length}`,
        String(body.startDate).slice(0, 10),
        `${trip.destination}天气预报：白天晴 33℃，夜间多云 26℃，东风3级。`,
      )
      createdImports.set(created.id, created)
      await route.fulfill({ status: 201, json: created })
      return
    }
    if (path === `/api/trips/${tripId}/agent-dialogue/events`) {
      await route.fulfill({ contentType: 'text/event-stream', body: '' })
      return
    }
    if (path === `/api/trips/${tripId}/agent-dialogue/runs` && method === 'POST') {
      await route.fulfill({ status: 202, json: { eventId: 'evt', status: 'QUEUED' } })
      return
    }

    await route.fulfill({ status: 501, json: { code: 'UNMOCKED_WEATHER_REQUEST', message: `${method} ${path}` } })
  })
  return syncBodies
}

test('renders a weather banner from city-intelligence facts and focuses a single day', async ({ page }) => {
  await mockWeatherApi(page, [
    weatherImport('imp-1', '2026-08-01', '2026-08-01 广州天气预报：白天晴 32℃，夜间多云。'),
    weatherImport('imp-2', '2026-08-02', '2026-08-02 广州天气预报：白天有雨 28℃。'),
  ])
  await page.goto(`/workspace/trips/${tripId}`)

  const banner = page.getByTestId('weather-banner')
  await expect(banner).toBeVisible()
  // 未聚焦：头标「行程天气」
  await expect(banner).toContainText('行程天气')
  await expect(banner).toContainText('2026/08/01')
  await expect(banner).toContainText('2026/08/02')
  await expect(banner).toContainText('白天晴')

  // 点选某天聚焦：Banner 头标切换为具体日期，只保留当天
  const dayChip = page.getByTestId('plan-day-chip-2026-08-02')
  await dayChip.click()
  await expect(dayChip).toHaveAttribute('aria-pressed', 'true')
  await expect(banner).toContainText('2026/08/02')
  await expect(banner.getByText('行程天气')).toHaveCount(0)
  await expect(banner.getByText('2026/08/01')).toHaveCount(0)
})

test('syncs weather through the city-intelligence sync button in the guide panel', async ({ page }) => {
  const syncBodies = await mockWeatherApi(page, [])
  await page.goto(`/workspace/trips/${tripId}`)

  // 无天气数据时 weather-banner 不渲染
  await expect(page.getByTestId('weather-banner')).toHaveCount(0)

  // 打开「攻略情报」手风琴 → 同步城市情报
  await page.getByTestId('more-toggle-guide').click()
  const guidePanel = page.locator('#guide-intelligence-title')
  await expect(guidePanel).toBeVisible()

  await page.getByRole('button', { name: '同步城市情报' }).click()

  await expect.poll(() => syncBodies.length).toBe(1)
  expect(syncBodies[0]).toEqual({
    sourceType: 'CITY_INTELLIGENCE',
    city: '广州',
    startDate: '2026-08-01',
    endDate: '2026-08-02',
  })

  // 同步结果注入 guideImports → 天气条出现
  await expect(page.getByTestId('weather-banner')).toBeVisible()
  await expect(page.getByTestId('weather-banner')).toContainText('白天晴 33℃')
})