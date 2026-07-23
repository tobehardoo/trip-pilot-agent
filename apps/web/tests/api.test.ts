import { afterEach, expect, test, vi } from 'vitest'

import {
  ApiError,
  cancelPlanningTask,
  createGuideImport,
  createPlanningTask,
  createTrip,
  listGuideImports,
  logoutSession,
  refreshSession,
  streamPlanningTaskEvents,
  updateGuideImportEnabled,
  type CreateTripInput,
} from '../src/lib/api'

afterEach(() => {
  vi.unstubAllGlobals()
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

test('cancels a planning task with bearer authentication', async () => {
  const fetchMock = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ status: 'CANCELLED' }),
  } as Response))
  vi.stubGlobal('fetch', fetchMock)

  await cancelPlanningTask('access-token', '33333333-3333-3333-3333-333333333333')

  expect(fetchMock).toHaveBeenCalledWith(
    '/api/planning-tasks/33333333-3333-3333-3333-333333333333',
    expect.objectContaining({
      method: 'DELETE',
      headers: expect.objectContaining({ Authorization: 'Bearer access-token' }),
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
    'https://example.com/guide',
  )
  await listGuideImports('access-token', '22222222-2222-2222-2222-222222222222')

  expect(fetchMock).toHaveBeenNthCalledWith(
    1,
    '/api/trips/22222222-2222-2222-2222-222222222222/guide-imports',
    expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ Authorization: 'Bearer access-token' }),
      body: JSON.stringify({ sourceUrl: 'https://example.com/guide' }),
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

  const lastEventId = await streamPlanningTaskEvents(
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
