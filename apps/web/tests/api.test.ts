import { afterEach, expect, test, vi } from 'vitest'

import {
  ApiError,
  createPlanningTask,
  createTrip,
  streamPlanningTaskEvents,
  type CreateTripInput,
} from '../src/lib/api'

afterEach(() => {
  vi.unstubAllGlobals()
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
