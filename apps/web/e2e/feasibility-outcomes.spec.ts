import { expect, test, type Page } from '@playwright/test'

const tripId = 'aaaa1111-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
const taskId = 'bbbb2222-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
const oldTaskId = 'cccc3333-cccc-cccc-cccc-cccccccccccc'
const versionId = 'dddd4444-dddd-dddd-dddd-dddddddddddd'

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
  endDate: '2026-08-02',
  status: 'READY',
  version: 1,
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
  versionId,
  versionNumber: 1,
  parentVersionId: null,
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
  knowledge: {
    status: 'UNAVAILABLE',
    query: 'Guangzhou',
    citations: [],
    freshness: { status: 'UNAVAILABLE', checkedAt: null, staleReason: 'Controlled demo' },
    message: 'Controlled demo',
  },
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
    message: '营业时间内开放',
    affectedDates: ['2026-08-01'],
    affectedEntityRefs: [],
    evidenceRefs: [],
    repairable: false,
  }],
  repairAttempts: [],
}

const needsRepairReport = {
  ...verifiedReport,
  status: 'NEEDS_REPAIR',
  summary: { totalCount: 1, passCount: 0, failCount: 1, unknownCount: 0, notApplicableCount: 0, missingRequiredCount: 0 },
  ruleResults: [{
    ruleId: 'OPENING_HOURS',
    ruleVersion: 'hard-rule-v1',
    outcome: 'FAIL',
    reasonCode: 'VENUE_CLOSED',
    message: '场地在该时段关闭',
    affectedDates: ['2026-08-01'],
    affectedEntityRefs: ['activity:ffff6666-ffff-ffff-ffff-ffffffffffff'],
    evidenceRefs: [{ evidenceId: 'ev-1', evidenceType: 'OPENING_HOURS', state: 'STALE', hardConstraintEligible: false }],
    repairable: true,
  }],
  repairAttempts: [{
    attemptIndex: 1,
    triggeringRuleIds: ['OPENING_HOURS'],
    actionCodes: ['MOVE_ACTIVITY'],
    affectedDates: ['2026-08-01'],
    affectedEntityRefs: ['activity:ffff6666-ffff-ffff-ffff-ffffffffffff'],
    beforeFingerprint: 'b'.repeat(64),
    afterFingerprint: 'c'.repeat(64),
    resultingStatus: 'NEEDS_REPAIR',
  }],
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
    message: '营业时间未知',
    affectedDates: [],
    affectedEntityRefs: [],
    evidenceRefs: [{ evidenceId: 'ev-2', evidenceType: 'OPENING_HOURS', state: 'UNKNOWN', hardConstraintEligible: false }],
    repairable: false,
  }],
  repairAttempts: [],
}

const candidate = {
  title: 'Candidate itinerary',
  days: [{
    date: '2026-08-01',
    dayType: null,
    activities: [
      {
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
      },
      {
        activityId: '22228888-2222-2222-2222-222222222222',
        title: 'Candidate activity 2',
        startTime: '2026-08-01T03:00:00Z',
        endTime: '2026-08-01T04:00:00Z',
        estimatedCost: 0,
        source: 'DEMO',
        providerPoiId: null,
        coordinates: null,
        address: null,
        typeCode: null,
        typeName: null,
        kind: null,
        timeFixed: null,
      },
    ],
    transitLegs: [{
      transitId: '33339999-3333-3333-3333-333333333333',
      fromActivityIndex: 0,
      toActivityIndex: 1,
      mode: 'WALKING',
      distanceMeters: 300,
      durationSeconds: 300,
      provider: 'DEMO',
      estimated: true,
      polyline: [],
    }],
  }],
  estimatedTotalCost: 100,
}

const evaluation = {
  schemaVersion: 1,
  evaluatorVersion: 'rule-v1',
  feasible: true,
  overallScore: 91,
  dimensions: {
    constraintSatisfaction: 100,
    timeFeasibility: 90,
    budgetFit: 88,
    routeEfficiency: 85,
    interestMatch: 80,
  },
  warnings: [],
  decisions: [],
  summary: '行程整体质量 91/100。',
  evaluatedAt: '2026-07-27T01:00:02Z',
}

function queuedEvent(eventId: number) {
  return `id: ${eventId}\ndata: ${JSON.stringify({
    eventId,
    taskId,
    eventType: 'PLANNING_QUEUED',
    schemaVersion: 1,
    payload: { status: 'QUEUED' },
    createdAt: '2026-07-27T01:00:00Z',
  })}\n\n`
}

function progressEvent(eventId: number, stage: string, sequence: number) {
  return `id: ${eventId}\ndata: ${JSON.stringify({
    eventId,
    taskId,
    eventType: 'PLANNING_PROGRESS',
    schemaVersion: 1,
    payload: { status: 'RUNNING', stage, sequence, progress: 60, message: '正在计算路线', statistics: {} },
    createdAt: '2026-07-27T01:00:00Z',
  })}\n\n`
}

function reviewEvent(eventId: number, report: unknown) {
  return `id: ${eventId}\ndata: ${JSON.stringify({
    eventId,
    taskId,
    eventType: 'PLANNING_REVIEW_REQUIRED',
    schemaVersion: 1,
    payload: { status: 'WAITING_USER', provider: 'DEMO', feasibilityReport: report, candidateItinerary: candidate },
    createdAt: '2026-07-27T01:00:01Z',
  })}\n\n`
}

function completedEvent(eventId: number) {
  return `id: ${eventId}\ndata: ${JSON.stringify({
    eventId,
    taskId,
    eventType: 'PLANNING_COMPLETED',
    schemaVersion: 1,
    payload: { status: 'SUCCEEDED', provider: 'DEMO', feasibilityReport: verifiedReport, evaluation },
    createdAt: '2026-07-27T01:00:01Z',
  })}\n\n`
}

function planningTask(taskIdValue: string, status: string, extra: Record<string, unknown> = {}) {
  return {
    taskId: taskIdValue,
    tripId,
    taskType: 'CREATE',
    status,
    baselineTripVersion: 0,
    eventStreamUrl: `/api/planning-tasks/${taskIdValue}/events`,
    createdAt: '2026-07-27T01:00:00Z',
    updatedAt: '2026-07-27T01:00:00Z',
    ...extra,
  }
}

function versionSummary(meta: unknown, planningTaskIdValue: string) {
  return {
    versionId,
    versionNumber: 1,
    parentVersionId: null,
    planningTaskId: planningTaskIdValue,
    versionSource: 'PLANNING_TASK',
    title: itinerary.title,
    estimatedTotalCost: itinerary.estimatedTotalCost,
    provider: 'DEMO',
    rollbackFromVersionId: null,
    createdAt: '2026-07-27T00:10:00Z',
    current: true,
    feasibility: meta,
  }
}

async function mockBaseline(page: Page, options: {
  versions: unknown | (() => unknown)
  itinerary: unknown | (() => unknown)
  latest?: unknown | (() => unknown)
  tasks?: Record<string, unknown>
  streamBody?: string
  onStream?: () => void
}) {
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path === '/api/auth/refresh') return route.fulfill({ json: session })
    if (path === '/api/trips' && request.method() === 'GET') return route.fulfill({ json: [trip] })
    if (path === `/api/trips/${tripId}`) return route.fulfill({ json: trip })
    if (path === `/api/trips/${tripId}/guide-imports` || path === `/api/trips/${tripId}/itinerary/shares`) {
      return route.fulfill({ json: [] })
    }
    if (path === `/api/trips/${tripId}/itinerary/versions`) {
      const versions = typeof options.versions === 'function' ? options.versions() : options.versions
      return route.fulfill({ json: versions })
    }
    if (path === `/api/trips/${tripId}/itinerary`) {
      const itineraryValue = typeof options.itinerary === 'function' ? options.itinerary() : options.itinerary
      return itineraryValue === null
        ? route.fulfill({ status: 404, json: { code: 'ITINERARY_NOT_FOUND', message: 'Not planned' } })
        : route.fulfill({ json: itineraryValue })
    }
    if (path === `/api/trips/${tripId}/planning-tasks/latest`) {
      const latest = typeof options.latest === 'function' ? options.latest() : options.latest
      return latest === undefined
        ? route.fulfill({ status: 404, json: { code: 'PLANNING_TASK_NOT_FOUND', message: 'Planning task was not found' } })
        : route.fulfill({ json: latest })
    }
    if (path === `/api/trips/${tripId}/planning-tasks` && request.method() === 'POST') {
      return route.fulfill({ status: 202, json: planningTask(taskId, 'QUEUED') })
    }
    if (path === `/api/planning-tasks/${taskId}/events`) {
      options.onStream?.()
      return route.fulfill({ contentType: 'text/event-stream', body: options.streamBody ?? '' })
    }
    const taskMatch = path.match(/^\/api\/planning-tasks\/([0-9a-f-]+)$/)
    if (taskMatch) {
      const task = options.tasks?.[taskMatch[1]!]
      return task ? route.fulfill({ json: task }) : route.fulfill({ status: 404, json: { code: 'NOT_FOUND' } })
    }
    return route.fulfill({ status: 501, json: { code: 'UNMOCKED_FEASIBILITY_REQUEST', message: `${request.method()} ${path}` } })
  })
}

test('renders the authoritative VERIFIED report with the experience evaluation', async ({ page }) => {
  let completed = false
  await mockBaseline(page, {
    versions: () => completed ? [versionSummary({
      reportId: verifiedReport.reportId,
      schemaVersion: 1,
      validatorVersion: 'hard-validator-v4',
      status: 'VERIFIED',
      itineraryFingerprint: 'a'.repeat(64),
      validatedAt: '2026-07-27T01:00:00Z',
    }, taskId)] : [],
    itinerary: () => completed ? itinerary : null,
    streamBody: queuedEvent(1) + completedEvent(2),
    onStream: () => { completed = true },
    tasks: {
      [taskId]: planningTask(taskId, 'SUCCEEDED', { feasibilityReport: verifiedReport, evaluation }),
    },
  })

  await page.goto('/trips')
  await page.getByRole('button', { name: '打开 Controlled feasibility trip' }).click()
  await page.getByTestId('start-planning').click()

  await expect(page.getByRole('heading', { name: '硬可行性验证' })).toBeVisible()
  await expect(page.getByText('已验证').first()).toBeVisible()
  await expect(page.getByText('营业时间内开放')).toBeVisible()
  await expect(page.getByText('91/100', { exact: true })).toBeVisible()
  await expect(page.getByText('仅代表体验质量，不代表硬可行性验证')).toBeVisible()
})

test('shows the NEEDS_REPAIR review panel without replacing the formal itinerary', async ({ page }) => {
  await mockBaseline(page, {
    versions: [versionSummary(null, taskId)],
    itinerary,
    streamBody: queuedEvent(1) + reviewEvent(2, needsRepairReport),
  })

  await page.goto('/trips')
  await page.getByRole('button', { name: '打开 Controlled feasibility trip' }).click()
  await page.getByTestId('start-planning').click()

  await expect(page.getByRole('heading', { name: '规划需要确认' })).toBeVisible()
  await expect(page.getByText('待修复').first()).toBeVisible()
  await expect(page.getByText('场地在该时段关闭')).toBeVisible()
  await expect(page.getByText('修复历史')).toBeVisible()
  await expect(page.getByText(/尝试 1/)).toBeVisible()
  await expect(page.getByText('Candidate itinerary')).toBeVisible()
  await expect(page.getByText('Candidate activity').first()).toBeVisible()
  // No accept / force-save / skip buttons.
  await expect(page.getByRole('button', { name: /接受|强制保存|忽略验证|跳过验证/ })).toHaveCount(0)
  // The formal itinerary stays in place.
  await expect(page.getByRole('heading', { name: 'Formal itinerary' })).toBeVisible()
})

test('shows an UNVERIFIED review without any verified wording', async ({ page }) => {
  await mockBaseline(page, {
    versions: [versionSummary(null, taskId)],
    itinerary,
    streamBody: queuedEvent(1) + reviewEvent(2, unverifiedReport),
  })

  await page.goto('/trips')
  await page.getByRole('button', { name: '打开 Controlled feasibility trip' }).click()
  await page.getByTestId('start-planning').click()

  await expect(page.getByRole('heading', { name: '规划需要确认' })).toBeVisible()
  await expect(page.getByText('未验证')).toBeVisible()
  await expect(page.getByText('证据未知')).toBeVisible()
  await expect(page.locator('body')).not.toContainText('已验证')
})

test('reconnects the stream with Last-Event-ID and applies the terminal event once', async ({ page }) => {
  let streamAttempts = 0
  let completed = false
  const lastEventIds: (string | null)[] = []
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path === '/api/auth/refresh') return route.fulfill({ json: session })
    if (path === '/api/trips' && request.method() === 'GET') return route.fulfill({ json: [trip] })
    if (path === `/api/trips/${tripId}`) return route.fulfill({ json: trip })
    if (path === `/api/trips/${tripId}/guide-imports` || path === `/api/trips/${tripId}/itinerary/shares`) {
      return route.fulfill({ json: [] })
    }
    if (path === `/api/trips/${tripId}/itinerary/versions`) {
      return route.fulfill({ json: completed ? [versionSummary({
        reportId: verifiedReport.reportId,
        schemaVersion: 1,
        validatorVersion: 'hard-validator-v4',
        status: 'VERIFIED',
        itineraryFingerprint: 'a'.repeat(64),
        validatedAt: '2026-07-27T01:00:00Z',
      }, taskId)] : [] })
    }
    if (path === `/api/trips/${tripId}/itinerary`) {
      return completed
        ? route.fulfill({ json: itinerary })
        : route.fulfill({ status: 404, json: { code: 'ITINERARY_NOT_FOUND', message: 'Not planned' } })
    }
    if (path === `/api/trips/${tripId}/planning-tasks/latest`) {
      return route.fulfill({ status: 404, json: { code: 'PLANNING_TASK_NOT_FOUND' } })
    }
    if (path === `/api/trips/${tripId}/planning-tasks` && request.method() === 'POST') {
      return route.fulfill({ status: 202, json: planningTask(taskId, 'QUEUED') })
    }
    if (path === `/api/planning-tasks/${taskId}/events`) {
      streamAttempts += 1
      lastEventIds.push(request.headers()['last-event-id'] ?? null)
      if (streamAttempts === 1) {
        return route.fulfill({
          contentType: 'text/event-stream',
          body: queuedEvent(1) + progressEvent(2, 'ROUTES_CALCULATING', 1),
        })
      }
      completed = true
      // Second attempt replays progress (id 2) and terminates once (id 3).
      return route.fulfill({
        contentType: 'text/event-stream',
        body: progressEvent(2, 'ROUTES_CALCULATING', 1) + completedEvent(3),
      })
    }
    if (path === `/api/planning-tasks/${taskId}`) {
      return route.fulfill({ json: planningTask(taskId, 'SUCCEEDED', { feasibilityReport: verifiedReport, evaluation }) })
    }
    return route.fulfill({ status: 501, json: { code: 'UNMOCKED', message: path } })
  })

  await page.goto('/trips')
  await page.getByRole('button', { name: '打开 Controlled feasibility trip' }).click()
  await page.getByTestId('start-planning').click()

  // Terminal applied once: one formal itinerary, no disconnect error.
  await expect(page.getByRole('heading', { name: 'Formal itinerary' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '硬可行性验证' })).toBeVisible()
  await expect(page.getByText('任务状态连接已中断，请稍后重试')).toHaveCount(0)
  expect(streamAttempts).toBeGreaterThanOrEqual(2)
  // The reconnect carries the last seen event id (progress id 2) as Last-Event-ID.
  expect(lastEventIds[1]).toBe('2')
})

test('shows historical feasibility null as 无历史验证, never 未验证', async ({ page }) => {
  await mockBaseline(page, {
    versions: [versionSummary(null, oldTaskId)],
    itinerary,
    latest: undefined,
    tasks: {
      [oldTaskId]: planningTask(oldTaskId, 'SUCCEEDED', { feasibilityReport: verifiedReport, evaluation }),
    },
  })

  await page.goto('/trips')
  await page.getByRole('button', { name: '打开 Controlled feasibility trip' }).click()

  await expect(page.getByText('无历史验证')).toBeVisible()
  await expect(page.locator('body')).not.toContainText('未验证')
})

test('recovers a review-required task through the latest endpoint after a refresh', async ({ page }) => {
  // Real backend relationship: the current version was created by an old
  // SUCCEEDED task; the WAITING_USER review task has no version at all.
  await mockBaseline(page, {
    versions: [versionSummary({
      reportId: verifiedReport.reportId,
      schemaVersion: 1,
      validatorVersion: 'hard-validator-v4',
      status: 'VERIFIED',
      itineraryFingerprint: 'a'.repeat(64),
      validatedAt: '2026-07-27T01:00:00Z',
    }, oldTaskId)],
    itinerary,
    latest: planningTask(taskId, 'WAITING_USER', {
      feasibilityReport: needsRepairReport,
      candidateItinerary: candidate,
    }),
    tasks: {
      [oldTaskId]: planningTask(oldTaskId, 'SUCCEEDED', { feasibilityReport: verifiedReport, evaluation }),
    },
  })

  await page.goto('/trips')
  await page.getByRole('button', { name: '打开 Controlled feasibility trip' }).click()

  // The review is discovered via the latest endpoint, not the version chain.
  await expect(page.getByRole('heading', { name: '规划需要确认' })).toBeVisible()
  await expect(page.getByText('Candidate itinerary')).toBeVisible()
  await expect(page.getByText('待修复').first()).toBeVisible()
  // The formal itinerary and its old version badge stay untouched.
  await expect(page.getByRole('heading', { name: 'Formal itinerary' })).toBeVisible()
  await expect(page.getByText('已验证').first()).toBeVisible()
})

test('fails closed on an illegal WAITING_USER + VERIFIED combination', async ({ page }) => {
  await mockBaseline(page, {
    versions: [versionSummary(null, taskId)],
    itinerary,
    streamBody: queuedEvent(1) + reviewEvent(2, verifiedReport),
  })

  await page.goto('/trips')
  await page.getByRole('button', { name: '打开 Controlled feasibility trip' }).click()
  await page.getByTestId('start-planning').click()

  await expect(page.getByText('规划结果无法安全读取，请重新规划')).toBeVisible()
  await expect(page.locator('body')).not.toContainText('已验证')
})
