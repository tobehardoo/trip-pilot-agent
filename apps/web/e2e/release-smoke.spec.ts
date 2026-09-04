// Release smoke — 新契约 completed 视图（ItineraryWorkspace）。
// 认证必经 /api/auth/refresh；completed 要求非空 itinerary 且 days 与 trip 日期跨度一致。
import { expect, test, type Page } from '@playwright/test'

const tripId = '22222222-2222-2222-2222-222222222222'
const editTaskId = '77778888-7777-7777-7777-777777777777'

const session = {
  user: { id: '11111111-1111-1111-1111-111111111111', email: 'traveler@example.com', displayName: '旅行者' },
  accessToken: 'release-smoke-token',
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

const a1 = {
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
}
const a2 = {
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
  typeCode: null,
  typeName: '餐厅',
  kind: 'MEAL',
  timeFixed: null,
}

function buildItinerary(locked: boolean) {
  return {
    versionId: '55555555-5555-5555-5555-555555555555',
    versionNumber: 2,
    parentVersionId: '44444444-4444-4444-4444-444444444444',
    title: '广州 Demo 行程',
    estimatedTotalCost: 160,
    provider: 'DEMO',
    days: [{
      date: '2026-08-01',
      dayType: null,
      activities: [{ ...a1, locked }, a2],
      transitLegs: [{
        id: '88888888-8888-8888-8888-888888888888',
        legOrder: 0,
        fromActivityId: a1.id,
        toActivityId: a2.id,
        mode: 'WALKING',
        locked: false,
        distanceMeters: 1380,
        durationSeconds: 1100,
        provider: 'DEMO',
        estimated: true,
        estimatedCost: 0,
        providerRouteId: null,
        calculatedAt: '2026-08-01T00:00:00Z',
        stale: false,
        polyline: [],
      }],
    }, {
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
    }],
    knowledge: {
      status: 'UNAVAILABLE',
      query: '广州 岭南文化 本地美食',
      citations: [],
      freshness: { status: 'UNAVAILABLE', checkedAt: null, staleReason: 'Demo 模式未连接真实知识源' },
      message: 'Demo 模式未声明实时知识',
    },
    createdAt: '2026-07-26T02:00:00Z',
  }
}

async function mockReleaseApi(page: Page) {
  let locked = false
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
      await route.fulfill({ json: buildItinerary(locked) })
      return
    }
    if (path === `/api/trips/${tripId}/itinerary/versions`) {
      await route.fulfill({ json: [] })
      return
    }
    if (path === `/api/trips/${tripId}/guide-imports`) {
      await route.fulfill({ json: [] })
      return
    }
    if (path === `/api/trips/${tripId}/itinerary/shares`) {
      await route.fulfill({ json: [] })
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
    if (path === '/api/trips/places/search' && method === 'POST') {
      await route.fulfill({ json: {
        provider: 'AMAP',
        estimated: true,
        candidates: [{
          provider: 'AMAP',
          providerPoiId: 'poi-chenjiaci',
          name: '陈家祠',
          address: '广州市荔湾区中山七路',
          province: '广东省',
          city: '广州市',
          district: '荔湾区',
          longitude: 113.2405,
          latitude: 23.1247,
          estimated: true,
        }],
      } })
      return
    }
    if (path === `/api/trips/${tripId}/itinerary/edits` && method === 'POST') {
      locked = true
      await route.fulfill({ json: { taskId: editTaskId, tripId, taskType: 'EDIT', status: 'RUNNING', baselineTripVersion: 2, eventStreamUrl: '', createdAt: '2026-08-02T00:00:00Z', updatedAt: '2026-08-02T00:00:00Z' } })
      return
    }
    if (path === `/api/planning-tasks/${editTaskId}` && method === 'GET') {
      await route.fulfill({ json: { taskId: editTaskId, tripId, taskType: 'EDIT', status: 'SUCCEEDED', baselineTripVersion: 2, eventStreamUrl: '', createdAt: '2026-08-02T00:00:00Z', updatedAt: '2026-08-02T00:00:00Z' } })
      return
    }

    await route.fulfill({ status: 501, json: { code: 'UNMOCKED_RELEASE_SMOKE_REQUEST', message: `${method} ${path}` } })
  })
}

test('restores a session and renders the completed itinerary workspace', async ({ page }) => {
  await mockReleaseApi(page)
  await page.goto(`/workspace/trips/${tripId}`)

  // 摘要卡：标题 + kicker + 徽章
  await expect(page.getByTestId('plan-overview-kicker')).toContainText('TripPilot · 完整方案')
  await expect(page.getByTestId('plan-overview-title')).toHaveText(trip.title)
  await expect(page.getByTestId('plan-overview-stats')).toContainText('2 天')
  await expect(page.getByTestId('plan-overview-stats')).toContainText('2 人')

  // 完成条
  await expect(page.getByTestId('agent-message-done')).toContainText('旅行方案已经完成')

  // 路线 + Day chips + 地图
  await expect(page.getByTestId('trip-route-map')).toBeVisible()
  await expect(page.getByTestId('plan-day-chip-2026-08-01')).toHaveAttribute('aria-pressed', 'false')

  // 天卡 + 活动 + 交通行
  await expect(page.getByTestId('plan-day-2026-08-01')).toBeVisible()
  await expect(page.getByTestId('plan-day-toggle-2026-08-01')).toBeVisible()
  await expect(page.getByTestId('plan-day-2026-08-01').getByTestId('plan-day-activities')).toBeVisible()
  await expect(page.getByTestId('plan-activity-漫步沙面岛')).toBeVisible()
  await expect(page.getByTestId('plan-transit-品尝西关早茶')).toContainText('步行')

  // 管理手风琴 + docked composer
  await expect(page.getByTestId('tool-tab-version')).toBeVisible()
  await expect(page.getByTestId('tool-tab-share')).toBeVisible()
  await expect(page.getByTestId('tool-tab-guide')).toBeVisible()
  await expect(page.getByTestId('workspace-composer')).toBeVisible()
})

test('opens the inline activity editor and searches a replacement place', async ({ page }) => {
  await mockReleaseApi(page)
  await page.goto(`/workspace/trips/${tripId}`)

  await page.getByTestId('activity-edit-漫步沙面岛').click()
  const editor = page.getByTestId('activity-inline-edit')
  await expect(editor).toBeVisible()

  await editor.getByTestId('activity-edit-place').fill('陈家祠')
  await expect(editor.getByTestId('activity-edit-results')).toBeVisible()
  await expect(editor.getByTestId('activity-edit-pick-陈家祠')).toBeVisible()
  await editor.getByTestId('activity-edit-pick-陈家祠').click()
  await expect(editor.getByTestId('activity-edit-picked')).toContainText('陈家祠')

  await editor.getByTestId('activity-edit-cancel').click()
  await expect(page.getByTestId('activity-inline-edit')).toBeHidden()
})

test('locks and unlocks an activity through an edit task', async ({ page }) => {
  await mockReleaseApi(page)
  await page.goto(`/workspace/trips/${tripId}`)

  await expect(page.getByTestId('activity-lock-漫步沙面岛')).toBeVisible()
  await page.getByTestId('activity-lock-漫步沙面岛').click()

  // 编辑任务 SUCCEEDED 后重新加载行程 → 活动变已锁定（按钮形态切换为 unlock）
  await expect(page.getByTestId('activity-unlock-漫步沙面岛')).toBeVisible()
})