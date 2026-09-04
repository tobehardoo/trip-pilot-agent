// Feasibility 结果 — 新契约：版本面板可行性徽标 + 历史版本 Drawer（比较/回滚）。
// review 面板（#planning-review-section / WAITING_USER 候选卡）已下线，改为验证
// ItineraryVersionPanel 的可行性徽标（已验证/待修复/未验证/无历史验证）与回滚流程。
import { expect, test, type Page } from '@playwright/test'

const tripId = 'aaaa1111-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
const curVersionId = 'bbbb2222-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
const hisVersionId = 'cccc3333-cccc-cccc-cccc-cccccccccccc'

const session = {
  user: { id: 'eeee5555-eeee-eeee-eeee-eeeeeeeeeeee', email: 'feasibility@example.com', displayName: 'Feasibility Traveler' },
  accessToken: 'feasibility-browser-token',
  tokenType: 'Bearer',
  expiresIn: 900,
}

const trip = {
  id: tripId,
  title: 'Controlled feasibility trip',
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

const itinerary = {
  versionId: curVersionId,
  versionNumber: 2,
  parentVersionId: hisVersionId,
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
  knowledge: {
    status: 'UNAVAILABLE',
    query: 'Guangzhou',
    citations: [],
    freshness: { status: 'UNAVAILABLE', checkedAt: null, staleReason: 'Controlled demo' },
    message: 'Controlled demo',
  },
  createdAt: '2026-07-27T00:10:00Z',
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

function version(vid: string, versionNumber: number, feasibility: unknown, current: boolean) {
  return {
    versionId: vid,
    versionNumber,
    parentVersionId: versionNumber > 1 ? hisVersionId : null,
    planningTaskId: null,
    versionSource: versionNumber > 1 ? 'USER_EDIT' : 'PLANNING_TASK',
    title: itinerary.title,
    estimatedTotalCost: itinerary.estimatedTotalCost,
    provider: 'DEMO',
    rollbackFromVersionId: null,
    createdAt: '2026-07-27T00:10:00Z',
    current,
    feasibility,
  }
}

const emptyDiff: Record<string, unknown> = {
  fromVersionId: hisVersionId,
  toVersionId: curVersionId,
  addedActivities: [],
  removedActivities: [],
  changedActivities: [],
  addedTransitLegs: [],
  removedTransitLegs: [],
  changedTransitLegs: [],
  addedFactImpacts: [],
  removedFactImpacts: [],
  changedFactImpacts: [],
  fromTotalCost: 88,
  toTotalCost: 208,
  budgetChange: 120,
}

async function mockVersionPanel(page: Page, versions: unknown[]) {
  const rollbackBodies: Record<string, unknown>[] = []
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()

    if (path === '/api/auth/refresh') return route.fulfill({ json: session })
    if (path === '/api/trips' && method === 'GET') return route.fulfill({ json: [trip] })
    if (path === `/api/trips/${tripId}`) return route.fulfill({ json: trip })
    if (path === `/api/trips/${tripId}/itinerary`) return route.fulfill({ json: itinerary })
    if (path === `/api/trips/${tripId}/itinerary/versions`) return route.fulfill({ json: versions })
    if (path === `/api/trips/${tripId}/guide-imports` || path === `/api/trips/${tripId}/itinerary/shares`) {
      return route.fulfill({ json: [] })
    }
    if (path === `/api/trips/${tripId}/agent-dialogue/events`) {
      return route.fulfill({ contentType: 'text/event-stream', body: '' })
    }
    if (path === `/api/trips/${tripId}/agent-dialogue/runs` && method === 'POST') {
      return route.fulfill({ status: 202, json: { eventId: 'evt', status: 'QUEUED' } })
    }
    if (path.startsWith(`/api/trips/${tripId}/itinerary/versions/diff`)) {
      return route.fulfill({ json: { ...emptyDiff, addedActivities: [{ key: 'new-1', title: '新活动', date: '2026-08-01' }] } })
    }
    if (path === `/api/trips/${tripId}/itinerary/rollbacks` && method === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>
      rollbackBodies.push(body)
      await route.fulfill({ status: 202, json: { taskId: 'roll-1', tripId, taskType: 'ROLLBACK_VALIDATE', status: 'QUEUED', baselineTripVersion: 2, eventStreamUrl: '', createdAt: '2026-07-27T01:00:00Z', updatedAt: '2026-07-27T01:00:00Z' } })
      return
    }

    await route.fulfill({ status: 501, json: { code: 'UNMOCKED_FEASIBILITY_REQUEST', message: `${method} ${path}` } })
  })
  return rollbackBodies
}

async function openVersionPanel(page: Page) {
  await page.getByTestId('tool-tab-version').click()
  await expect(page.getByRole('heading', { name: '行程版本' })).toBeVisible()
}

test('renders the VERIFIED feasibility badge on the current version with no review copy', async ({ page }) => {
  await mockVersionPanel(page, [
    version(curVersionId, 2, meta('VERIFIED'), true),
    version(hisVersionId, 1, null, false),
  ])
  await page.goto(`/workspace/trips/${tripId}`)

  await openVersionPanel(page)
  await expect(page.getByText('当前版本')).toBeVisible()
  await expect(page.getByText('V2', { exact: true })).toBeVisible()
  await expect(page.getByText('已验证')).toBeVisible()
  // 已删 review 面板文案不再出现
  await expect(page.getByText('方案需要调整')).toHaveCount(0)
})

test('renders NEEDS_REPAIR as 「待修复」 and never verified wording', async ({ page }) => {
  await mockVersionPanel(page, [
    version(curVersionId, 2, meta('NEEDS_REPAIR'), true),
    version(hisVersionId, 1, null, false),
  ])
  await page.goto(`/workspace/trips/${tripId}`)

  await openVersionPanel(page)
  await expect(page.getByText('待修复')).toBeVisible()
  await expect(page.getByText('已验证')).toHaveCount(0)
  await expect(page.getByText('需要调整')).toHaveCount(0)
})

test('shows historical null feasibility as 无历史验证, never 未验证', async ({ page }) => {
  await mockVersionPanel(page, [
    version(curVersionId, 2, null, true),
    version(hisVersionId, 1, null, false),
  ])
  await page.goto(`/workspace/trips/${tripId}`)

  await openVersionPanel(page)
  await expect(page.getByText('无历史验证')).toBeVisible()
  await expect(page.getByText('未验证')).toHaveCount(0)
  await expect(page.locator('body')).not.toContainText('已验证')
})

test('compares a historical version with the current one in the version drawer', async ({ page }) => {
  await mockVersionPanel(page, [
    version(curVersionId, 2, meta('VERIFIED'), true),
    version(hisVersionId, 1, null, false),
  ])
  await page.goto(`/workspace/trips/${tripId}`)
  await openVersionPanel(page)

  await page.getByTestId('open-version-history').click()
  await expect(page.getByRole('heading', { name: '历史版本' })).toBeVisible()
  await expect(page.getByText('版本 1')).toBeVisible()

  await page.getByRole('button', { name: '比较版本 1 与当前版本' }).click()
  await expect(page.getByText('与当前版本的差异')).toBeVisible()
  await expect(page.getByText('预算变化 +¥120')).toBeVisible()
  await expect(page.getByText('新增：新活动')).toBeVisible()
})

test('rolls the itinerary back to a historical version after confirmation', async ({ page }) => {
  const rollbackBodies = await mockVersionPanel(page, [
    version(curVersionId, 2, meta('VERIFIED'), true),
    version(hisVersionId, 1, null, false),
  ])
  await page.goto(`/workspace/trips/${tripId}`)
  await openVersionPanel(page)

  await page.getByTestId('open-version-history').click()
  await page.getByRole('button', { name: '回滚到版本 1' }).click()

  await expect(page.getByRole('alertdialog', { name: '确认版本回滚' })).toBeVisible()
  await page.getByRole('button', { name: '确认回滚到版本 1' }).click()

  await expect.poll(() => rollbackBodies.length).toBe(1)
  expect(rollbackBodies[0]).toEqual({
    sourceVersionId: hisVersionId,
    expectedCurrentVersionId: curVersionId,
  })
  await expect(page.getByRole('alertdialog', { name: '确认版本回滚' })).toBeHidden()
})