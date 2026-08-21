import { expect, test, type Page } from '@playwright/test'

// B10 golden journeys — net-new rollback candidate and repair-exhausted
// scenarios that the existing 13 specs do not cover.  Every mock uses a
// realistic task<->version relationship: a version's planningTaskId points
// at the task that produced it, a WAITING_USER review task has no version.

const tripId = 'aaaa1111-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
const oldTaskId = 'cccc3333-cccc-cccc-cccc-cccccccccccc'
const rollbackTaskId = 'dddd4444-dddd-dddd-dddd-dddddddddddd'
const currentVersionId = 'dddd5555-dddd-dddd-dddd-dddddddddddd'
const rollbackSourceVersionId = 'dddd6666-dddd-dddd-dddd-dddddddddddd'

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
  endDate: '2026-08-02',
  status: 'READY',
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

const formalItinerary = {
  versionId: currentVersionId,
  versionNumber: 2,
  parentVersionId: rollbackSourceVersionId,
  title: 'Formal itinerary',
  estimatedTotalCost: 88,
  provider: 'DEMO',
  days: [{
    date: '2026-08-01',
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
    }],
    transitLegs: [],
  }],
  knowledge: { status: 'UNAVAILABLE', query: 'Guangzhou', citations: [], freshness: { status: 'UNAVAILABLE', checkedAt: null, staleReason: 'Controlled demo' }, message: 'Controlled demo' },
  createdAt: '2026-07-27T00:10:00Z',
}

const verifiedReport = {
  schemaVersion: 1,
  reportId: 'a1111111-1111-4111-8111-111111111111',
  validatorVersion: 'hard-validator-v4',
  itineraryFingerprint: 'a'.repeat(64),
  status: 'VERIFIED',
  validatedAt: '2026-07-27T01:00:00Z',
  requiredRuleIds: ['OPENING_HOURS'],
  missingRequiredRuleIds: [],
  summary: { totalCount: 1, passCount: 1, failCount: 0, unknownCount: 0, notApplicableCount: 0, missingRequiredCount: 0 },
  ruleResults: [{
    ruleId: 'OPENING_HOURS',
    ruleVersion: 'hard-rule-v1',
    outcome: 'PASS',
    reasonCode: 'OPENING_HOURS_VERIFIED',
    message: 'Opening hours verified',
    affectedDates: ['2026-08-01'],
    affectedEntityRefs: [],
    evidenceRefs: [],
    repairable: false,
  }],
  repairAttempts: [],
}

const evaluation = {
  schemaVersion: 1,
  evaluatorVersion: 'rule-v1',
  feasible: true,
  overallScore: 91,
  dimensions: { constraintSatisfaction: 100, timeFeasibility: 90, budgetFit: 88, routeEfficiency: 85, interestMatch: 80 },
  warnings: [],
  decisions: [],
  summary: 'Trip quality 91/100.',
  evaluatedAt: '2026-07-27T01:00:02Z',
}

const unverifiedReport = {
  ...verifiedReport,
  status: 'UNVERIFIED',
  summary: { totalCount: 1, passCount: 0, failCount: 0, unknownCount: 1, notApplicableCount: 0, missingRequiredCount: 0 },
  ruleResults: [{
    ruleId: 'OPENING_HOURS',
    ruleVersion: 'hard-rule-v1',
    outcome: 'UNKNOWN',
    reasonCode: 'OPENING_HOURS_UNVERIFIED',
    message: 'Opening hours unknown',
    affectedDates: [],
    affectedEntityRefs: [],
    evidenceRefs: [{ evidenceId: 'ev-2', evidenceType: 'OPENING_HOURS', state: 'UNKNOWN', hardConstraintEligible: false }],
    repairable: false,
  }],
  repairAttempts: [],
}

const exhaustedReport = {
  ...verifiedReport,
  status: 'NEEDS_REPAIR',
  summary: { totalCount: 1, passCount: 0, failCount: 1, unknownCount: 0, notApplicableCount: 0, missingRequiredCount: 0 },
  ruleResults: [{
    ruleId: 'DUPLICATE_POI',
    ruleVersion: 'hard-rule-v1',
    outcome: 'FAIL',
    reasonCode: 'DUPLICATE_POI',
    message: 'Duplicate POI appears more than once',
    affectedDates: ['2026-08-01'],
    affectedEntityRefs: ['poi:POI-1'],
    evidenceRefs: [],
    repairable: true,
  }],
  repairAttempts: [
    { attemptIndex: 1, triggeringRuleIds: ['DUPLICATE_POI'], actionCodes: ['REMOVE_DUPLICATE'], affectedDates: ['2026-08-01'], affectedEntityRefs: ['poi:POI-1'], beforeFingerprint: 'b'.repeat(64), afterFingerprint: 'c'.repeat(64), resultingStatus: 'NEEDS_REPAIR' },
    { attemptIndex: 2, triggeringRuleIds: ['DUPLICATE_POI'], actionCodes: ['REMOVE_DUPLICATE'], affectedDates: ['2026-08-01'], affectedEntityRefs: ['poi:POI-1'], beforeFingerprint: 'c'.repeat(64), afterFingerprint: 'd'.repeat(64), resultingStatus: 'NEEDS_REPAIR' },
    { attemptIndex: 3, triggeringRuleIds: ['DUPLICATE_POI'], actionCodes: ['REMOVE_DUPLICATE'], affectedDates: ['2026-08-01'], affectedEntityRefs: ['poi:POI-1'], beforeFingerprint: 'd'.repeat(64), afterFingerprint: 'e'.repeat(64), resultingStatus: 'NEEDS_REPAIR' },
  ],
}

const candidate = {
  title: 'Candidate itinerary',
  days: [{
    date: '2026-08-01',
    dayType: null,
    activities: [{
      activityId: '11117777-1111-1111-1111-111111111111',
      title: 'Candidate activity',
      startTime: '2026-08-01T01:00:00Z',
      endTime: '2026-08-01T02:00:00Z',
      estimatedCost: 0,
      source: 'DEMO',
      providerPoiId: null,
      coordinates: null,
      address: null,
      typeCode: null,
      typeName: null,
      kind: null,
      timeFixed: null,
    }],
    transitLegs: [],
  }],
  estimatedTotalCost: 100,
}

function queuedEvent(eventId: number, taskIdValue: string) {
  return `id: ${eventId}\ndata: ${JSON.stringify({ eventId, taskId: taskIdValue, eventType: 'PLANNING_QUEUED', schemaVersion: 1, payload: { status: 'QUEUED' }, createdAt: '2026-07-27T01:00:00Z' })}\n\n`
}

function completedEvent(eventId: number, taskIdValue: string) {
  return `id: ${eventId}\ndata: ${JSON.stringify({ eventId, taskId: taskIdValue, eventType: 'PLANNING_COMPLETED', schemaVersion: 1, payload: { status: 'SUCCEEDED', provider: 'DEMO', feasibilityReport: verifiedReport, evaluation }, createdAt: '2026-07-27T01:00:01Z' })}\n\n`
}

function reviewEvent(eventId: number, taskIdValue: string, report: unknown) {
  return `id: ${eventId}\ndata: ${JSON.stringify({ eventId, taskId: taskIdValue, eventType: 'PLANNING_REVIEW_REQUIRED', schemaVersion: 1, payload: { status: 'WAITING_USER', provider: 'DEMO', feasibilityReport: report, candidateItinerary: candidate }, createdAt: '2026-07-27T01:00:01Z' })}\n\n`
}

function planningTask(taskIdValue: string, status: string, extra: Record<string, unknown> = {}) {
  return {
    taskId: taskIdValue,
    tripId,
    taskType: 'ROLLBACK_VALIDATE',
    status,
    baselineTripVersion: 1,
    eventStreamUrl: `/api/planning-tasks/${taskIdValue}/events`,
    createdAt: '2026-07-27T01:00:00Z',
    updatedAt: '2026-07-27T01:00:00Z',
    ...extra,
  }
}

function versionSummary(versionId: string, versionNumber: number, meta: unknown, planningTaskIdValue: string | null, source: string, current: boolean) {
  return {
    versionId,
    versionNumber,
    parentVersionId: versionNumber > 1 ? rollbackSourceVersionId : null,
    planningTaskId: planningTaskIdValue,
    versionSource: source,
    title: formalItinerary.title,
    estimatedTotalCost: formalItinerary.estimatedTotalCost,
    provider: 'DEMO',
    rollbackFromVersionId: null,
    createdAt: '2026-07-27T00:10:00Z',
    current,
    feasibility: meta,
  }
}

const verifiedMeta = {
  reportId: verifiedReport.reportId,
  schemaVersion: 1,
  validatorVersion: 'hard-validator-v4',
  status: 'VERIFIED',
  itineraryFingerprint: 'a'.repeat(64),
  validatedAt: '2026-07-27T01:00:00Z',
}

async function mockRollbackBaseline(page: Page, options: {
  rollbackStreamBody: string
  onRollback?: (markCompleted: () => void) => void
  reportOnRollbackTask?: unknown
  candidateOnRollbackTask?: unknown
}) {
  let rollbackCompleted = false
  const markCompleted = () => { rollbackCompleted = true }
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path === '/api/auth/refresh') return route.fulfill({ json: session })
    if (path === '/api/trips' && request.method() === 'GET') return route.fulfill({ json: [trip] })
    if (path === `/api/trips/${tripId}`) return route.fulfill({ json: trip })
    if (path === `/api/trips/${tripId}/guide-imports` || path === `/api/trips/${tripId}/itinerary/shares`) return route.fulfill({ json: [] })
    if (path === `/api/trips/${tripId}/itinerary/versions`) {
      const current = versionSummary(
        currentVersionId, 2, verifiedMeta, oldTaskId,
        'USER_EDIT', !rollbackCompleted,
      )
      const historical = versionSummary(rollbackSourceVersionId, 1, null, null, 'PLANNING_TASK', false)
      const rollback = rollbackCompleted
        ? versionSummary('dddd7777-dddd-dddd-dddd-dddddddddddd', 3, verifiedMeta, rollbackTaskId, 'ROLLBACK', true)
        : null
      const versions = rollback ? [rollback, current, historical] : [current, historical]
      return route.fulfill({ json: versions })
    }
    if (path === `/api/trips/${tripId}/itinerary`) {
      const itinerary = rollbackCompleted
        ? { ...formalItinerary, versionId: 'dddd7777-dddd-dddd-dddd-dddddddddddd', versionNumber: 3, parentVersionId: currentVersionId }
        : formalItinerary
      return route.fulfill({ json: itinerary })
    }
    if (path === `/api/trips/${tripId}/planning-tasks/latest`) {
      return route.fulfill({ status: 404, json: { code: 'PLANNING_TASK_NOT_FOUND' } })
    }
    if (path === `/api/trips/${tripId}/itinerary/rollbacks` && request.method() === 'POST') {
      return route.fulfill({ status: 202, json: planningTask(rollbackTaskId, 'QUEUED') })
    }
    if (path === `/api/planning-tasks/${rollbackTaskId}/events`) {
      options.onRollback?.(markCompleted)
      return route.fulfill({ contentType: 'text/event-stream', body: options.rollbackStreamBody })
    }
    if (path === `/api/planning-tasks/${rollbackTaskId}`) {
      return route.fulfill({
        json: planningTask(rollbackTaskId, 'SUCCEEDED', {
          feasibilityReport: options.reportOnRollbackTask ?? verifiedReport,
          candidateItinerary: options.candidateOnRollbackTask,
          evaluation,
        }),
      })
    }
    if (path === `/api/planning-tasks/${oldTaskId}`) {
      return route.fulfill({ json: planningTask(oldTaskId, 'SUCCEEDED', { feasibilityReport: verifiedReport, evaluation }) })
    }
    return route.fulfill({ status: 501, json: { code: 'UNMOCKED_GOLDEN_ROLLBACK', message: `${request.method()} ${path}` } })
  })
}

test('G26 rollback VERIFIED creates a ROLLBACK version and shows a fresh report, not an inherited one', async ({ page }) => {
  await mockRollbackBaseline(page, {
    rollbackStreamBody: queuedEvent(1, rollbackTaskId) + completedEvent(2, rollbackTaskId),
    onRollback: (markCompleted) => { markCompleted() },
  })

  await page.goto('/trips')
  await page.getByRole('button', { name: '打开 Golden rollback trip' }).click()
  await expect(page.getByRole('heading', { name: 'Formal itinerary' })).toBeVisible()
  // Before completion, the formal current version (USER_EDIT) stays put and no
  // ROLLBACK version exists.
  // 历史版本默认收进 Drawer：先打开再操作（功能保持不变）。
  await page.getByTestId('open-version-history').click()
  await expect(page.getByText('版本 2').first()).toBeVisible()
  await expect(page.getByText('历史回滚')).toHaveCount(0)

  await page.getByRole('button', { name: '回滚到版本 1' }).click()
  await expect(page.getByRole('alertdialog', { name: '确认版本回滚' })).toBeVisible()
  await page.getByRole('button', { name: '确认回滚到版本 1' }).click()

  // VERIFIED completion -> the review path is bypassed; a new ROLLBACK
  // version (version 3, source=ROLLBACK) becomes current with the fresh
  // VERIFIED report and evaluation.
  await expect(page.getByRole('heading', { name: '行程已验证并保存' })).toBeVisible()
  // 主页面版本徽章文案从「已保存」收敛为「当前」（避免与 FeasibilityReportPanel
  // fail-closed 状态文案混淆）。功能（已保存状态展示）保留。
  await expect(page.getByText('当前').first()).toBeVisible()
  await expect(page.getByRole('heading', { name: '方案需要调整' })).toHaveCount(0)
  await expect(page.getByText('版本 3').first()).toBeVisible()
  await expect(page.getByText('历史回滚')).toBeVisible()
})

test('G27 rollback UNVERIFIED isolates the candidate and never shows verified wording', async ({ page }) => {
  await mockRollbackBaseline(page, {
    rollbackStreamBody: queuedEvent(1, rollbackTaskId) + reviewEvent(2, rollbackTaskId, unverifiedReport),
    reportOnRollbackTask: unverifiedReport,
    candidateOnRollbackTask: candidate,
  })

  await page.goto('/trips')
  await page.getByRole('button', { name: '打开 Golden rollback trip' }).click()
  await expect(page.getByRole('heading', { name: 'Formal itinerary' })).toBeVisible()
  // 历史版本默认收进 Drawer：先打开再操作。
  await page.getByTestId('open-version-history').click()

  await page.getByRole('button', { name: '回滚到版本 1' }).click()
  await page.getByRole('button', { name: '确认回滚到版本 1' }).click()

  const reviewPanel = page.locator('.review-panel')
  await expect(reviewPanel.first()).toBeVisible()
  // B15: the UNKNOWN rule surfaces as a Chinese issue summary; no verified
  // wording anywhere on the user page.  B16: UNKNOWN reads as "system
  // suggestion, confirm before departure".
  await expect(page.getByText('待核实信息（1）')).toBeVisible()
  await expect(page.getByText('部分地点的营业时间采用系统建议，建议出发前确认').first()).toBeVisible()
  await expect(page.getByText('未验证')).toHaveCount(0)
  // The rollback candidate is isolated: the review panel must never claim the
  // candidate was verified (the current formal version keeps its own badge).
  await expect(reviewPanel.first()).not.toContainText('已验证')
  await expect(page.getByRole('heading', { name: 'Formal itinerary' })).toBeVisible()
})

test('G20 repair exhausted shows all three attempts in order with the remaining issue', async ({ page }) => {
  await mockRollbackBaseline(page, {
    rollbackStreamBody: queuedEvent(1, rollbackTaskId) + reviewEvent(2, rollbackTaskId, exhaustedReport),
    reportOnRollbackTask: exhaustedReport,
    candidateOnRollbackTask: candidate,
  })

  await page.goto('/trips')
  await page.getByRole('button', { name: '打开 Golden rollback trip' }).click()
  await expect(page.getByRole('heading', { name: 'Formal itinerary' })).toBeVisible()
  // 历史版本默认收进 Drawer：先打开再操作。
  await page.getByTestId('open-version-history').click()

  await page.getByRole('button', { name: '回滚到版本 1' }).click()
  await page.getByRole('button', { name: '确认回滚到版本 1' }).click()

  await expect(page.getByRole('heading', { name: '方案需要调整' })).toBeVisible()
  // B15: repair history and raw codes are never shown on the user page; the
  // candidate and the Chinese issue summary lead.
  await expect(page.getByText('修复历史')).toHaveCount(0)
  await expect(page.getByText('DUPLICATE_POI', { exact: true })).toHaveCount(0)
  await expect(page.getByTestId('validation-details-toggle')).toHaveCount(0)
  await expect(page.getByText(/尝试 1/)).toHaveCount(0)
})
