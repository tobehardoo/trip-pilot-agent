import { afterEach, expect, test, vi } from 'vitest'

import {
  ApiError,
  applyItineraryEdit,
  createGuideImport,
  createItineraryReplan,
  createPlanningTask,
  createTrip,
  downloadItineraryExport,
  getPlanningTask,
  getSharedItinerary,
  listGuideImports,
  logoutSession,
  refreshSession,
  searchTrips,
  previewItineraryEdit,
  streamSseEvents,
  updateGuideImportEnabled,
  type CreateTripInput,
  type PlanningTaskEvent,
} from '../src/lib/api'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

test('releases an export blob only after triggering the browser download', async () => {
  vi.useFakeTimers()
  const createObjectUrl = vi.fn(() => 'blob:trip-pilot-export')
  const revokeObjectUrl = vi.fn()
  vi.stubGlobal('URL', { createObjectURL: createObjectUrl, revokeObjectURL: revokeObjectUrl })
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true,
    status: 200,
    headers: new Headers({ 'Content-Disposition': "attachment; filename*=UTF-8''trip.ics" }),
    blob: async () => new Blob(['calendar']),
  } as Response)))
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)

  await downloadItineraryExport('access-token', 'trip-1', 'version-1', 'ics')

  expect(createObjectUrl).toHaveBeenCalledOnce()
  expect(revokeObjectUrl).not.toHaveBeenCalled()
  await vi.runAllTimersAsync()
  expect(revokeObjectUrl).toHaveBeenCalledWith('blob:trip-pilot-export')
})

test('searches trips with bearer authentication', async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ items: [], page: 0, size: 100, totalElements: 0, totalPages: 0 }),
  } as Response)
  vi.stubGlobal('fetch', fetchMock)

  await searchTrips('access-token', { destination: 'Guangzhou', includeArchived: true, size: 100 })

  expect(fetchMock).toHaveBeenCalledWith(
    '/api/trips/search?destination=Guangzhou&includeArchived=true&page=0&size=100',
    expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer access-token' }) }),
  )
})

test('refreshes and logs out with the HttpOnly cookie and no token request body', async () => {
  const fetchMock = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({}),
  } as Response))
  vi.stubGlobal('fetch', fetchMock)

  await refreshSession()
  await logoutSession()

  expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/auth/refresh', expect.objectContaining({
    method: 'POST',
    credentials: 'same-origin',
  }))
  expect(fetchMock.mock.calls[0]?.[1]?.body).toBeUndefined()
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/auth/logout', expect.objectContaining({
    method: 'POST',
    credentials: 'same-origin',
  }))
  expect(fetchMock.mock.calls[1]?.[1]?.body).toBeUndefined()
})

test('turns an empty unauthorized response into a structured API error', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: false,
    status: 401,
    json: async () => { throw new SyntaxError('Unexpected end of JSON input') },
  } as Response)))
  const input: CreateTripInput = {
    title: '广州周末四日',
    destination: '广州',
    startDate: '2026-07-18',
    endDate: '2026-07-21',
    constraints: {
      budgetAmount: 4000,
      travelers: 2,
      travelerType: 'FRIENDS',
      pace: 'BALANCED',
      preferences: ['岭南文化'],
      fixedSchedules: [],
    },
  }

  await expect(createTrip('expired-token', input)).rejects.toEqual(
    new ApiError(401, 'REQUEST_FAILED', '请求失败'),
  )
})

test('loads a public shared itinerary without attaching an access token', async () => {
  const fetchMock = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ title: 'Shared itinerary', days: [], sources: [] }),
  } as Response))
  vi.stubGlobal('fetch', fetchMock)

  await getSharedItinerary('secure-token')

  expect(fetchMock).toHaveBeenCalledWith('/api/shares/secure-token', expect.objectContaining({
    headers: expect.not.objectContaining({ Authorization: expect.any(String) }),
  }))
})

test('creates a planning task with bearer authentication and an idempotency key', async () => {
  const fetchMock = vi.fn(async () => ({
    ok: true,
    status: 202,
    json: async () => ({
      taskId: '33333333-3333-3333-3333-333333333333',
      tripId: '22222222-2222-2222-2222-222222222222',
      taskType: 'CREATE',
      status: 'QUEUED',
      baselineTripVersion: 0,
      eventStreamUrl: '/api/planning-tasks/33333333-3333-3333-3333-333333333333/events',
      createdAt: '2026-07-16T01:00:00Z',
      updatedAt: '2026-07-16T01:00:00Z',
    }),
  } as Response))
  vi.stubGlobal('fetch', fetchMock)

  await createPlanningTask(
    'access-token',
    '22222222-2222-2222-2222-222222222222',
    '44444444-4444-4444-8444-444444444444',
  )

  expect(fetchMock).toHaveBeenCalledWith(
    '/api/trips/22222222-2222-2222-2222-222222222222/planning-tasks',
    expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({
        Authorization: 'Bearer access-token',
        'Idempotency-Key': '44444444-4444-4444-8444-444444444444',
      }),
    }),
  )
})

test('previews and applies an itinerary edit with its base version', async () => {
  const fetchMock = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ canApply: true }),
  } as Response))
  vi.stubGlobal('fetch', fetchMock)
  const input = {
    baseVersionId: '11111111-1111-1111-1111-111111111111',
    operation: 'DELETE_ACTIVITY' as const,
    activityId: '22222222-2222-2222-2222-222222222222',
  }

  await previewItineraryEdit('access-token', '33333333-3333-3333-3333-333333333333', input)
  await applyItineraryEdit('access-token', '33333333-3333-3333-3333-333333333333', input)

  expect(fetchMock).toHaveBeenNthCalledWith(
    1,
    '/api/trips/33333333-3333-3333-3333-333333333333/itinerary/edits/preview',
    expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ Authorization: 'Bearer access-token' }),
      body: JSON.stringify(input),
    }),
  )
  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    '/api/trips/33333333-3333-3333-3333-333333333333/itinerary/edits',
    expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ Authorization: 'Bearer access-token' }),
      body: JSON.stringify(input),
    }),
  )
})

test('creates a local itinerary replan with impacted dates and an idempotency key', async () => {
  const fetchMock = vi.fn(async () => ({
    ok: true,
    status: 202,
    json: async () => ({ taskType: 'REPLAN' }),
  } as Response))
  vi.stubGlobal('fetch', fetchMock)
  const input = {
    baseVersionId: '11111111-1111-1111-1111-111111111111',
    dates: ['2026-08-01'],
  }

  await createItineraryReplan(
    'access-token',
    '33333333-3333-3333-3333-333333333333',
    input,
    '44444444-4444-4444-8444-444444444444',
  )

  expect(fetchMock).toHaveBeenCalledWith(
    '/api/trips/33333333-3333-3333-3333-333333333333/itinerary/replans',
    expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({
        Authorization: 'Bearer access-token',
        'Idempotency-Key': '44444444-4444-4444-8444-444444444444',
      }),
      body: JSON.stringify(input),
    }),
  )
})

test('creates and lists trip-scoped guide imports with bearer authentication', async () => {
  const fetchMock = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ([]),
  } as Response))
  vi.stubGlobal('fetch', fetchMock)

  await createGuideImport(
    'access-token',
    '22222222-2222-2222-2222-222222222222',
    {
      sourceType: 'PUBLIC_GUIDE_URL',
      sourceUrl: 'https://example.com/guide',
    },
  )
  await listGuideImports('access-token', '22222222-2222-2222-2222-222222222222')

  expect(fetchMock).toHaveBeenNthCalledWith(
    1,
    '/api/trips/22222222-2222-2222-2222-222222222222/guide-imports',
    expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ Authorization: 'Bearer access-token' }),
      body: JSON.stringify({
        sourceType: 'PUBLIC_GUIDE_URL',
        sourceUrl: 'https://example.com/guide',
      }),
    }),
  )
  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    '/api/trips/22222222-2222-2222-2222-222222222222/guide-imports',
    expect.objectContaining({
      headers: expect.objectContaining({ Authorization: 'Bearer access-token' }),
    }),
  )
})

test('toggles a trip guide source with bearer authentication', async () => {
  const fetchMock = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ enabled: false }),
  } as Response))
  vi.stubGlobal('fetch', fetchMock)

  await updateGuideImportEnabled(
    'access-token',
    '22222222-2222-2222-2222-222222222222',
    '11111111-1111-1111-1111-111111111111',
    false,
  )

  expect(fetchMock).toHaveBeenCalledWith(
    '/api/trips/22222222-2222-2222-2222-222222222222/guide-imports/11111111-1111-1111-1111-111111111111',
    expect.objectContaining({
      method: 'PUT',
      headers: expect.objectContaining({ Authorization: 'Bearer access-token' }),
      body: JSON.stringify({ enabled: false }),
    }),
  )
})

test('parses chunked multiline SSE data, ignores heartbeats, and sends the last event id', async () => {
  const encoder = new TextEncoder()
  const chunks = [
    ': heartbeat\n\nid: 12\nevent: PLANNING_COM',
    'PLETED\ndata: {"eventId":12,\ndata: "taskId":"33333333-3333-3333-3333-333333333333",',
    '\ndata: "eventType":"PLANNING_COMPLETED","schemaVersion":1,',
    '\ndata: "payload":{"status":"SUCCEEDED"},"createdAt":"2026-07-16T01:00:01Z"}\n\n',
  ]
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)))
      controller.close()
    },
  })
  const fetchMock = vi.fn(async () => ({ ok: true, status: 200, body } as Response))
  vi.stubGlobal('fetch', fetchMock)
  const received: string[] = []

  const lastEventId = await streamSseEvents(
    'access-token',
    '/api/planning-tasks/33333333-3333-3333-3333-333333333333/events',
    (event) => received.push(event.eventType),
    { lastEventId: 11 },
  )

  expect(received).toEqual(['PLANNING_COMPLETED'])
  expect(lastEventId).toBe(12)
  expect(fetchMock).toHaveBeenCalledWith(
    '/api/planning-tasks/33333333-3333-3333-3333-333333333333/events',
    expect.objectContaining({
      headers: {
        Accept: 'text/event-stream',
        Authorization: 'Bearer access-token',
        'Last-Event-ID': '11',
      },
    }),
  )
})

const reviewReport = {
  schemaVersion: 1,
  reportId: 'c9c467cc-65c4-8ff1-e175-4af42f2ed545',
  validatorVersion: 'hard-validator-v4',
  itineraryFingerprint: 'a'.repeat(64),
  status: 'NEEDS_REPAIR',
  validatedAt: '2026-07-16T01:00:00Z',
  requiredRuleIds: ['OPENING_HOURS'],
  missingRequiredRuleIds: [],
  summary: { totalCount: 1, passCount: 0, failCount: 1, unknownCount: 0, notApplicableCount: 0, missingRequiredCount: 0 },
  ruleResults: [],
  repairAttempts: [],
}
const reviewCandidate = {
  title: '候选行程',
  days: [{
    date: '2026-07-18',
    dayType: null,
    activities: [{ activityId: null, title: '候选活动', startTime: '2026-07-18T01:00:00Z', endTime: '2026-07-18T02:00:00Z', estimatedCost: 0, source: 'DEMO', providerPoiId: null, coordinates: null, address: null, typeCode: null, typeName: null, kind: null, timeFixed: null }],
    transitLegs: [],
  }],
  estimatedTotalCost: 100,
}
const verifiedEvaluation = {
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
  evaluatedAt: '2026-07-16T01:00:02Z',
}

test('loads a planning task with the authoritative report and review candidate', async () => {
  const fetchMock = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({
      taskId: '33333333-3333-3333-3333-333333333333',
      tripId: '22222222-2222-2222-2222-222222222222',
      taskType: 'CREATE',
      status: 'WAITING_USER',
      baselineTripVersion: 0,
      eventStreamUrl: '/api/planning-tasks/33333333-3333-3333-3333-333333333333/events',
      feasibilityReport: reviewReport,
      candidateItinerary: reviewCandidate,
      createdAt: '2026-07-16T01:00:00Z',
      updatedAt: '2026-07-16T01:00:00Z',
    }),
  } as Response))
  vi.stubGlobal('fetch', fetchMock)

  const task = await getPlanningTask('access-token', '33333333-3333-3333-3333-333333333333')

  expect(task.status).toBe('WAITING_USER')
  expect(task.feasibilityReport).toEqual(reviewReport)
  expect(task.candidateItinerary).toEqual(reviewCandidate)
  expect(fetchMock).toHaveBeenCalledWith(
    '/api/planning-tasks/33333333-3333-3333-3333-333333333333',
    expect.objectContaining({
      headers: expect.objectContaining({ Authorization: 'Bearer access-token' }),
    }),
  )
})

test('loads a succeeded planning task with its report and evaluation', async () => {
  const verifiedReport = { ...reviewReport, status: 'VERIFIED', summary: { ...reviewReport.summary, passCount: 1, failCount: 0 } }
  const fetchMock = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({
      taskId: '33333333-3333-3333-3333-333333333333',
      tripId: '22222222-2222-2222-2222-222222222222',
      taskType: 'CREATE',
      status: 'SUCCEEDED',
      baselineTripVersion: 1,
      eventStreamUrl: '/api/planning-tasks/33333333-3333-3333-3333-333333333333/events',
      feasibilityReport: verifiedReport,
      evaluation: verifiedEvaluation,
      createdAt: '2026-07-16T01:00:00Z',
      updatedAt: '2026-07-16T01:00:05Z',
    }),
  } as Response))
  vi.stubGlobal('fetch', fetchMock)

  const task = await getPlanningTask('access-token', '33333333-3333-3333-3333-333333333333')

  expect(task.status).toBe('SUCCEEDED')
  expect(task.feasibilityReport).toEqual(verifiedReport)
  expect(task.evaluation).toEqual(verifiedEvaluation)
})

test('streams a PLANNING_REVIEW_REQUIRED event with report and candidate payload', async () => {
  const encoder = new TextEncoder()
  const payload = {
    eventId: 5,
    taskId: '33333333-3333-3333-3333-333333333333',
    eventType: 'PLANNING_REVIEW_REQUIRED',
    schemaVersion: 1,
    payload: { status: 'WAITING_USER', feasibilityReport: reviewReport, candidateItinerary: reviewCandidate },
    createdAt: '2026-07-16T01:00:01Z',
  }
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(
        `event: PLANNING_REVIEW_REQUIRED\ndata: ${JSON.stringify(payload)}\n\n`,
      ))
      controller.close()
    },
  })
  const fetchMock = vi.fn(async () => ({ ok: true, status: 200, body } as Response))
  vi.stubGlobal('fetch', fetchMock)
  const received: PlanningTaskEvent[] = []

  await streamSseEvents(
    'access-token',
    '/api/planning-tasks/33333333-3333-3333-3333-333333333333/events',
    (event) => received.push(event),
  )

  expect(received).toHaveLength(1)
  expect(received[0]!.eventType).toBe('PLANNING_REVIEW_REQUIRED')
  expect(received[0]!.payload.feasibilityReport).toEqual(reviewReport)
  expect(received[0]!.payload.candidateItinerary).toEqual(reviewCandidate)
})

test('streams a PLANNING_COMPLETED event with report and evaluation payload', async () => {
  const encoder = new TextEncoder()
  const payload = {
    eventId: 6,
    taskId: '33333333-3333-3333-3333-333333333333',
    eventType: 'PLANNING_COMPLETED',
    schemaVersion: 1,
    payload: { status: 'SUCCEEDED', feasibilityReport: { ...reviewReport, status: 'VERIFIED' }, evaluation: verifiedEvaluation },
    createdAt: '2026-07-16T01:00:02Z',
  }
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(
        `event: PLANNING_COMPLETED\ndata: ${JSON.stringify(payload)}\n\n`,
      ))
      controller.close()
    },
  })
  const fetchMock = vi.fn(async () => ({ ok: true, status: 200, body } as Response))
  vi.stubGlobal('fetch', fetchMock)
  const received: PlanningTaskEvent[] = []

  await streamSseEvents(
    'access-token',
    '/api/planning-tasks/33333333-3333-3333-3333-333333333333/events',
    (event) => received.push(event),
  )

  expect(received).toHaveLength(1)
  expect(received[0]!.eventType).toBe('PLANNING_COMPLETED')
  expect(received[0]!.payload.feasibilityReport).toEqual({ ...reviewReport, status: 'VERIFIED' })
  expect(received[0]!.payload.evaluation).toEqual(verifiedEvaluation)
})
