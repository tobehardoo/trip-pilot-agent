// Golden journeys — 版本面板回滚生命周期 + 修复耗尽可行性徽标（新契约）。
// 回滚在版 Drawer 中发起，POST /itinerary/rollbacks；新 ROLLBACK 版本成为 current，
// 重新加载后主面板展示「历史回滚」source 徽标 + 新可行性结果。
import { expect, test, type Page } from '@playwright/test'

const tripId = 'aaaa1111-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
const curVersionId = 'dddd5555-dddd-dddd-dddd-dddddddddddd'
const hisVersionId = 'dddd6666-dddd-dddd-dddd-dddddddddddd'
const rollbackVersionId = 'dddd7777-dddd-dddd-dddd-dddddddddddd'

const session = {
  user: { id: 'eeee5555-eeee-eeee-eeee-eeeeeeeeeeee', email: 'golden@example.com', displayName: 'Golden Traveler' },
  accessToken: 'golden-browser-token',
  tokenType: 'Bearer',
  expiresIn: 900,
}

const trip = {
  id: tripId,
  title: 'Golden rollback trip',
  destination: 'Guangzhou',
  startDate: '2026-08-01',
  endDate: '2026-08-01',
  status: 'COMPLETED',
  version: 2,
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

function buildItinerary(vid: string, versionNumber: number) {
  return {
    versionId: vid,
    versionNumber,
    parentVersionId: versionNumber > 1 ? curVersionId : null,
    title: 'Formal itinerary',
    estimatedTotalCost: 88,
    provider: 'DEMO',
    days: [{
      date: '2026-08-01',
      dayType: null,
      activities: [{
        id: 'ffff6666-ffff-ffff-ffff-ffffffffffff',
        title: 'Formal museum',
        startTime: '2026-08-01T01:00:00Z',
        endTime: '2026-08-01T02:00:00Z',
        estimatedCost: 0,
        source: 'DEMO',
        providerPoiId: null,
        coordinates: { longitude: 113.26, latitude: 23.13 },
        address: 'Museum Road',
        locked: false,
        typeCode: null,
        typeName: 'Museum',
        kind: 'ATTRACTION',
        timeFixed: null,
      }],
      transitLegs: [],
    }],
    knowledge: { status: 'UNAVAILABLE', query: 'Guangzhou', citations: [], freshness: { status: 'UNAVAILABLE', checkedAt: null, staleReason: 'Controlled demo' }, message: 'Controlled demo' },
    createdAt: '2026-07-27T00:10:00Z',
  }
}

function meta(status: string) {
  return {
    reportId: `rep-${status}`,
    schemaVersion: 1,
    validatorVersion: 'hard-validator-v4',
    status,
    itineraryFingerprint: `${status}`.padEnd(64, 'a'),
    validatedAt: '2026-07-27T01:00:00Z',
  }
}

function version(vid: string, versionNumber: number, feasibility: unknown, current: boolean, source: string) {
  return {
    versionId: vid,
    versionNumber,
    parentVersionId: versionNumber > 1 ? (versionNumber === 2 ? hisVersionId : curVersionId) : null,
    planningTaskId: null,
    versionSource: source,
    title: 'Formal itinerary',
    estimatedTotalCost: 88,
    provider: 'DEMO',
    rollbackFromVersionId: null,
    createdAt: '2026-07-27T00:10:00Z',
    current,
    feasibility,
  }
}

async function mockRollback(page: Page) {
  let rollbackCompleted = false
  const rollbackBodies: Record<string, unknown>[] = []
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
    if (path === `/api/trips/${tripId}/itinerary`) {
      return route.fulfill({ json: buildItinerary(rollbackCompleted ? rollbackVersionId : curVersionId, rollbackCompleted ? 3 : 2) })
    }
    if (path === `/api/trips/${tripId}/itinerary/versions`) {
      const versions = rollbackCompleted
        ? [
          version(rollbackVersionId, 3, meta('VERIFIED'), true, 'ROLLBACK'),
          version(curVersionId, 2, meta('VERIFIED'), false, 'USER_EDIT'),
          version(hisVersionId, 1, null, false, 'PLANNING_TASK'),
        ]
        : [
          version(curVersionId, 2, meta('VERIFIED'), true, 'USER_EDIT'),
          version(hisVersionId, 1, null, false, 'PLANNING_TASK'),
        ]
      return route.fulfill({ json: versions })
    }
    if (path === `/api/trips/${tripId}/itinerary/rollbacks` && method === 'POST') {
      rollbackBodies.push(request.postDataJSON() as Record<string, unknown>)
      rollbackCompleted = true
      return route.fulfill({ status: 202, json: { taskId: 'roll-1', tripId, taskType: 'ROLLBACK_VALIDATE', status: 'QUEUED', baselineTripVersion: 2, eventStreamUrl: '', createdAt: '2026-07-27T01:00:00Z', updatedAt: '2026-07-27T01:00:00Z' } })
    }
    if (path === `/api/trips/${tripId}/agent-dialogue/events`) {
      return route.fulfill({ contentType: 'text/event-stream', body: '' })
    }
    if (path === `/api/trips/${tripId}/agent-dialogue/runs` && method === 'POST') {
      return route.fulfill({ status: 202, json: { eventId: 'evt', status: 'QUEUED' } })
    }
    return route.fulfill({ status: 501, json: { code: 'UNMOCKED_GOLDEN_ROLLBACK', message: `${method} ${path}` } })
  })
  return rollbackBodies
}

async function openVersionPanel(page: Page) {
  await page.getByTestId('more-toggle-version').click()
  await expect(page.getByRole('heading', { name: '行程版本' })).toBeVisible()
}

test('G rollback creates a new current ROLLBACK version with a fresh report', async ({ page }) => {
  const rollbackBodies = await mockRollback(page)
  await page.goto(`/workspace/trips/${tripId}`)

  // 初始：版本 2 为当前
  await openVersionPanel(page)
  await expect(page.getByText('V2', { exact: true })).toBeVisible()
  await page.getByTestId('open-version-history').click()
  await page.getByRole('button', { name: '回滚到版本 1' }).click()
  await page.getByRole('button', { name: '确认回滚到版本 1' }).click()

  await expect.poll(() => rollbackBodies.length).toBe(1)
  expect(rollbackBodies[0]).toEqual({
    sourceVersionId: hisVersionId,
    expectedCurrentVersionId: curVersionId,
  })

  // 重新加载 → 新 ROLLBACK 版本（V3）成为当前，source 徽标「历史回滚」
  await page.reload()
  await openVersionPanel(page)
  await expect(page.getByText('V3', { exact: true })).toBeVisible()
  await expect(page.getByText('已验证')).toBeVisible()
  await expect(page.getByText('历史回滚').first()).toBeVisible()
})

test('G repair-exhausted current version surfaces 待修复 with no internal details', async ({ page }) => {
  await mockRollback(page)
  // 用一个独立的只读 mock：当前版本为 NEEDS_REPAIR（repair 已耗尽），历史无验证。
  const exhaustedVersions = [version(curVersionId, 2, meta('NEEDS_REPAIR'), true, 'USER_EDIT')]
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === `/api/trips/${tripId}/itinerary/versions`) {
      await route.fulfill({ json: exhaustedVersions })
      return
    }
    await route.fallback()
  })

  await page.goto(`/workspace/trips/${tripId}`)
  await openVersionPanel(page)

  await expect(page.getByText('待修复')).toBeVisible()
  await expect(page.getByText('已验证')).toHaveCount(0)
  await expect(page.getByText('修复历史')).toHaveCount(0)
  await expect(page.getByText('DUPLICATE_POI', { exact: true })).toHaveCount(0)
})