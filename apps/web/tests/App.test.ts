import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import App from '../src/App.vue'

const authResponse = {
  user: {
    id: '11111111-1111-1111-1111-111111111111',
    email: 'traveler@example.com',
    displayName: '旅行者',
  },
  accessToken: 'access-token',
  refreshToken: 'refresh-token',
  tokenType: 'Bearer',
  expiresIn: 900,
}

const tripResponse = {
  id: '22222222-2222-2222-2222-222222222222',
  title: '广州周末四日',
  destination: '广州',
  startDate: '2026-07-18',
  endDate: '2026-07-21',
  status: 'DRAFT',
  version: 0,
  constraints: {
    budgetAmount: 4000,
    travelers: 2,
    travelerType: 'FRIENDS',
    pace: 'BALANCED',
    preferences: ['岭南文化', '本地美食'],
    fixedSchedules: [],
    schemaVersion: 1,
  },
  createdAt: '2026-07-13T01:00:00Z',
  updatedAt: '2026-07-13T01:00:00Z',
}

const itineraryResponse = {
  versionId: '55555555-5555-5555-5555-555555555555',
  versionNumber: 1,
  parentVersionId: null,
  title: '广州 Demo 行程',
  estimatedTotalCost: 860,
  provider: 'DEMO',
  days: [{
    date: '2026-07-18',
    activities: [{
      id: '66666666-6666-6666-6666-666666666666',
      title: '漫步沙面岛',
      startTime: '2026-07-18T01:00:00Z',
      endTime: '2026-07-18T03:00:00Z',
      estimatedCost: 0,
      source: 'DEMO',
    }, {
      id: '77777777-7777-7777-7777-777777777777',
      title: '品尝西关早茶',
      startTime: '2026-07-18T04:00:00Z',
      endTime: '2026-07-18T05:30:00Z',
      estimatedCost: 160,
      source: 'DEMO',
    }],
  }],
  createdAt: '2026-07-16T01:00:01Z',
}

const planningTaskResponse = {
  taskId: '33333333-3333-3333-3333-333333333333',
  tripId: tripResponse.id,
  taskType: 'CREATE',
  status: 'QUEUED',
  baselineTripVersion: 0,
  eventStreamUrl: '/api/planning-tasks/33333333-3333-3333-3333-333333333333/events',
  createdAt: '2026-07-16T01:00:00Z',
  updatedAt: '2026-07-16T01:00:00Z',
}

function planningEvent(eventType: string, eventId: number, payload: Record<string, unknown>) {
  return `id: ${eventId}\nevent: ${eventType}\ndata: ${JSON.stringify({
    eventId,
    taskId: planningTaskResponse.taskId,
    eventType,
    schemaVersion: 1,
    payload,
    createdAt: `2026-07-16T01:00:0${eventId}Z`,
  })}\n\n`
}

function completedEventStream(): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(planningEvent('PLANNING_COMPLETED', 2, { status: 'SUCCEEDED' })))
      controller.close()
    },
  })
  return { ok: true, status: 200, body } as Response
}

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

function urlOf(input: RequestInfo | URL): string {
  return typeof input === 'string' ? input : input.toString()
}

async function signIn(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    try {
      return await fetchMock(input, init)
    } catch (cause) {
      if (urlOf(input).endsWith('/itinerary')) {
        return response({ code: 'ITINERARY_NOT_FOUND', message: 'Itinerary was not found' }, 404)
      }
      throw cause
    }
  }))
  render(App)

  await fireEvent.update(screen.getByLabelText('邮箱'), 'traveler@example.com')
  await fireEvent.update(screen.getByLabelText('密码'), 'correct-password')
  await fireEvent.click(screen.getByRole('button', { name: '登录' }))
}

async function openPlanningWorkspace(fetchMock: ReturnType<typeof vi.fn>) {
  await signIn(fetchMock)
  await screen.findByRole('heading', { name: tripResponse.title })
  await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))
  await screen.findByText('尚未生成行程')
}

describe('TripPilot application shell', () => {
  beforeEach(() => {
    sessionStorage.clear()
    window.history.replaceState({}, '', '/trips')
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  test('shows login and registration modes to unauthenticated visitors', async () => {
    render(App)

    expect(screen.getByRole('heading', { name: '登录 TripPilot' })).toBeTruthy()
    expect(screen.getByLabelText('邮箱')).toBeTruthy()
    expect(screen.getByLabelText('密码')).toBeTruthy()

    await fireEvent.click(screen.getByRole('button', { name: '创建账户' }))

    expect(screen.getByRole('heading', { name: '创建 TripPilot 账户' })).toBeTruthy()
    expect(screen.getByLabelText('显示名称')).toBeTruthy()
  })

  test('logs in and loads the authenticated users trips', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith('/api/trips') && init?.method !== 'POST') return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)

    expect(await screen.findByRole('heading', { name: '我的旅行' })).toBeTruthy()
    expect(await screen.findByRole('heading', { name: '广州周末四日' })).toBeTruthy()
    expect(screen.getByText('旅行者')).toBeTruthy()
    expect(sessionStorage.getItem('trip-pilot.refresh-token')).toBe('refresh-token')

    const tripsRequest = fetchMock.mock.calls.find(([input]) => urlOf(input).endsWith('/api/trips'))
    expect(tripsRequest?.[1]?.headers).toMatchObject({ Authorization: 'Bearer access-token' })
  })

  test('restores a session by rotating the saved refresh token', async () => {
    sessionStorage.setItem('trip-pilot.refresh-token', 'saved-refresh-token')
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/refresh')) {
        return response({ ...authResponse, refreshToken: 'rotated-refresh-token' })
      }
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(App)

    expect(await screen.findByRole('heading', { name: '广州周末四日' })).toBeTruthy()
    expect(sessionStorage.getItem('trip-pilot.refresh-token')).toBe('rotated-refresh-token')
  })

  test('keeps the rotated session when loading trips has a transient failure', async () => {
    sessionStorage.setItem('trip-pilot.refresh-token', 'saved-refresh-token')
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/refresh')) {
        return response({ ...authResponse, refreshToken: 'rotated-refresh-token' })
      }
      if (url.endsWith('/api/trips')) throw new TypeError('connection reset')
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(App)

    expect(await screen.findByRole('heading', { name: '我的旅行' })).toBeTruthy()
    expect((await screen.findByRole('alert')).textContent).toContain('无法连接业务服务，请稍后重试')
    expect(sessionStorage.getItem('trip-pilot.refresh-token')).toBe('rotated-refresh-token')
  })

  test('refreshes an expired access token and retries trip creation once', async () => {
    let createAttempts = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith('/api/auth/refresh')) {
        return response({
          ...authResponse,
          accessToken: 'renewed-access-token',
          refreshToken: 'rotated-refresh-token',
        })
      }
      if (url.endsWith('/api/trips') && init?.method === 'POST') {
        createAttempts += 1
        if (createAttempts === 1) return response({}, 401)
        expect(init.headers).toMatchObject({ Authorization: 'Bearer renewed-access-token' })
        return response(tripResponse, 201)
      }
      if (url.endsWith('/api/trips')) return response([])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '我的旅行' })
    await fireEvent.click(screen.getByRole('button', { name: '创建旅行' }))
    await fireEvent.update(screen.getByLabelText('旅行名称'), '广州周末四日')
    await fireEvent.update(screen.getByLabelText('目的地'), '广州')
    await fireEvent.update(screen.getByLabelText('开始日期'), '2026-07-18')
    await fireEvent.update(screen.getByLabelText('结束日期'), '2026-07-21')
    await fireEvent.click(screen.getByRole('button', { name: '保存旅行' }))

    expect(await screen.findByRole('heading', { name: '广州周末四日' })).toBeTruthy()
    expect(createAttempts).toBe(2)
    expect(sessionStorage.getItem('trip-pilot.refresh-token')).toBe('rotated-refresh-token')
  })

  test('revokes the refresh token when the user logs out', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith('/api/auth/logout')) return response(undefined, 204)
      if (url.endsWith('/api/trips')) return response([])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '我的旅行' })
    await fireEvent.click(screen.getByRole('button', { name: '退出登录' }))

    expect(await screen.findByRole('heading', { name: '登录 TripPilot' })).toBeTruthy()
    await waitFor(() => {
      const request = fetchMock.mock.calls.find(([input]) => urlOf(input).endsWith('/api/auth/logout'))
      expect(JSON.parse(String(request?.[1]?.body))).toEqual({ refreshToken: 'refresh-token' })
    })
  })

  test('ignores a successful trip-list response from a previous session', async () => {
    const secondAuthResponse = {
      ...authResponse,
      user: {
        id: '33333333-3333-3333-3333-333333333333',
        email: 'second@example.com',
        displayName: '第二位旅行者',
      },
      accessToken: 'second-access-token',
      refreshToken: 'second-refresh-token',
    }
    const secondTrip = {
      ...tripResponse,
      id: '44444444-4444-4444-4444-444444444444',
      title: '北京城市三日',
      destination: '北京',
    }
    let loginAttempts = 0
    let listLoads = 0
    let resolveStaleList!: (result: Response) => void
    const staleList = new Promise<Response>((resolve) => {
      resolveStaleList = resolve
    })
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) {
        loginAttempts += 1
        return response(loginAttempts === 1 ? authResponse : secondAuthResponse)
      }
      if (url.endsWith('/api/auth/logout')) return response(undefined, 204)
      if (url.endsWith('/api/trips')) {
        listLoads += 1
        if (listLoads === 1) return response([tripResponse])
        if (listLoads === 2) return staleList
        return response([secondTrip])
      }
      throw new Error(`Unexpected request: GET ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    window.dispatchEvent(new PopStateEvent('popstate'))
    await waitFor(() => expect(listLoads).toBe(2))

    await fireEvent.click(screen.getByRole('button', { name: '退出登录' }))
    await screen.findByRole('heading', { name: '登录 TripPilot' })
    await fireEvent.update(screen.getByLabelText('邮箱'), 'second@example.com')
    await fireEvent.update(screen.getByLabelText('密码'), 'correct-password')
    await fireEvent.click(screen.getByRole('button', { name: '登录' }))
    expect(await screen.findByRole('heading', { name: secondTrip.title })).toBeTruthy()

    resolveStaleList(response([tripResponse]))
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(screen.getByRole('heading', { name: secondTrip.title })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: tripResponse.title })).toBeNull()
  })

  test('does not let a stale list snapshot overwrite a newly created trip', async () => {
    const createdTrip = {
      ...tripResponse,
      id: '55555555-5555-5555-5555-555555555555',
      title: '杭州周末两日',
      destination: '杭州',
    }
    let listLoads = 0
    let resolveStaleList!: (result: Response) => void
    const staleList = new Promise<Response>((resolve) => {
      resolveStaleList = resolve
    })
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith('/api/trips') && init?.method === 'POST') return response(createdTrip, 201)
      if (url.endsWith('/api/trips')) {
        listLoads += 1
        return listLoads === 1 ? response([tripResponse]) : staleList
      }
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    window.dispatchEvent(new PopStateEvent('popstate'))
    await waitFor(() => expect(listLoads).toBe(2))

    await fireEvent.click(screen.getByRole('button', { name: '创建旅行' }))
    await fireEvent.update(screen.getByLabelText('旅行名称'), createdTrip.title)
    await fireEvent.update(screen.getByLabelText('目的地'), createdTrip.destination)
    await fireEvent.update(screen.getByLabelText('开始日期'), createdTrip.startDate)
    await fireEvent.update(screen.getByLabelText('结束日期'), createdTrip.endDate)
    await fireEvent.click(screen.getByRole('button', { name: '保存旅行' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    resolveStaleList(response([tripResponse]))
    expect(await screen.findByRole('heading', { name: createdTrip.title })).toBeTruthy()
  })

  test('creates a trip with structured constraints and adds it to the list', async () => {
    let submittedBody: unknown
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith('/api/trips') && init?.method === 'POST') {
        submittedBody = JSON.parse(String(init.body))
        return response(tripResponse, 201)
      }
      if (url.endsWith('/api/trips')) return response([])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '我的旅行' })
    await fireEvent.click(screen.getByRole('button', { name: '创建旅行' }))
    await fireEvent.update(screen.getByLabelText('旅行名称'), '广州周末四日')
    await fireEvent.update(screen.getByLabelText('目的地'), '广州')
    await fireEvent.update(screen.getByLabelText('开始日期'), '2026-07-18')
    await fireEvent.update(screen.getByLabelText('结束日期'), '2026-07-21')
    await fireEvent.update(screen.getByLabelText('预算'), '4000')
    await fireEvent.update(screen.getByLabelText('同行人数'), '2')
    await fireEvent.update(screen.getByLabelText('同行类型'), 'FRIENDS')
    await fireEvent.click(screen.getByLabelText('岭南文化'))
    await fireEvent.click(screen.getByLabelText('本地美食'))
    await fireEvent.click(screen.getByRole('button', { name: '保存旅行' }))

    expect(await screen.findByRole('heading', { name: '广州周末四日' })).toBeTruthy()
    expect(submittedBody).toEqual({
      title: '广州周末四日',
      destination: '广州',
      startDate: '2026-07-18',
      endDate: '2026-07-21',
      constraints: {
        budgetAmount: 4000,
        travelers: 2,
        travelerType: 'FRIENDS',
        pace: 'BALANCED',
        preferences: ['岭南文化', '本地美食'],
        fixedSchedules: [],
      },
    })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  test('opens a trip detail route and loads its structured constraints', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '广州周末四日' })
    await fireEvent.click(screen.getByRole('button', { name: '打开 广州周末四日' }))

    expect(await screen.findByRole('heading', { name: '广州周末四日', level: 1 })).toBeTruthy()
    expect(window.location.pathname).toBe(`/trips/${tripResponse.id}`)
    expect(screen.getByRole('heading', { name: '结构化约束' })).toBeTruthy()
    expect(screen.getByText('版本 0')).toBeTruthy()
    expect(screen.getByText('2 人 · 朋友同行')).toBeTruthy()
  })

  test('creates a planning task and renders the completed Demo itinerary from SSE', async () => {
    const encoder = new TextEncoder()
    let streamController!: ReadableStreamDefaultController<Uint8Array>
    const eventStream = new ReadableStream<Uint8Array>({
      start(controller) {
        streamController = controller
      },
    })
    let itineraryLoads = 0
    let planningCreateAttempts = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith('/api/auth/refresh')) {
        return response({
          ...authResponse,
          accessToken: 'renewed-access-token',
          refreshToken: 'rotated-refresh-token',
        })
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/planning-tasks`) && init?.method === 'POST') {
        planningCreateAttempts += 1
        if (planningCreateAttempts === 1) return response({}, 401)
        return response({
          taskId: '33333333-3333-3333-3333-333333333333',
          tripId: tripResponse.id,
          taskType: 'CREATE',
          status: 'QUEUED',
          baselineTripVersion: 0,
          eventStreamUrl: '/api/planning-tasks/33333333-3333-3333-3333-333333333333/events',
          createdAt: '2026-07-16T01:00:00Z',
          updatedAt: '2026-07-16T01:00:00Z',
        }, 202)
      }
      if (url.endsWith('/api/planning-tasks/33333333-3333-3333-3333-333333333333/events')) {
        return { ok: true, status: 200, body: eventStream } as Response
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) {
        itineraryLoads += 1
        return itineraryLoads === 1
          ? response({ code: 'ITINERARY_NOT_FOUND', message: 'Itinerary was not found' }, 404)
          : response(itineraryResponse)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '广州周末四日' })
    await fireEvent.click(screen.getByRole('button', { name: '打开 广州周末四日' }))

    expect(await screen.findByText('尚未生成行程')).toBeTruthy()
    await fireEvent.click(screen.getByRole('button', { name: '开始规划' }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '规划中' })).toHaveProperty('disabled', true)
    })
    streamController.enqueue(encoder.encode(
      'id: 1\nevent: PLANNING_QUEUED\ndata: {"eventId":1,"taskId":"33333333-3333-3333-3333-333333333333","eventType":"PLANNING_QUEUED","schemaVersion":1,"payload":{"status":"QUEUED"},"createdAt":"2026-07-16T01:00:00Z"}\n\n',
    ))
    expect((await screen.findByRole('status')).textContent).toContain('正在生成行程')

    streamController.enqueue(encoder.encode(
      'id: 2\nevent: PLANNING_COMPLETED\ndata: {"eventId":2,"taskId":"33333333-3333-3333-3333-333333333333","eventType":"PLANNING_COMPLETED","schemaVersion":1,"payload":{"status":"SUCCEEDED"},"createdAt":"2026-07-16T01:00:01Z"}\n\n',
    ))
    streamController.close()

    expect(await screen.findByRole('heading', { name: '广州 Demo 行程' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: '行程时间轴' })).toBeTruthy()
    expect(screen.getByText('漫步沙面岛')).toBeTruthy()
    expect(screen.getByText('09:00 — 11:00')).toBeTruthy()
    expect(screen.getByText('¥860')).toBeTruthy()
    const planningRequests = fetchMock.mock.calls.filter(([input]) => (
      urlOf(input).endsWith(`/api/trips/${tripResponse.id}/planning-tasks`)
    ))
    expect(planningRequests).toHaveLength(2)
    expect(planningRequests[1]?.[1]?.headers).toMatchObject({
      Authorization: 'Bearer renewed-access-token',
      'Idempotency-Key': expect.stringMatching(/^[0-9a-f-]{36}$/),
    })
    expect((planningRequests[0]?.[1]?.headers as Record<string, string>)['Idempotency-Key']).toBe(
      (planningRequests[1]?.[1]?.headers as Record<string, string>)['Idempotency-Key'],
    )
    const streamRequest = fetchMock.mock.calls.find(([input]) => (
      urlOf(input).endsWith('/api/planning-tasks/33333333-3333-3333-3333-333333333333/events')
    ))
    expect(streamRequest?.[1]?.headers).toMatchObject({
      Accept: 'text/event-stream',
      Authorization: 'Bearer renewed-access-token',
    })
  })

  test('reconnects an interrupted planning stream from the last received event', async () => {
    const encoder = new TextEncoder()
    const queuedEvent = encoder.encode(
      'id: 1\nevent: PLANNING_QUEUED\ndata: {"eventId":1,"taskId":"33333333-3333-3333-3333-333333333333","eventType":"PLANNING_QUEUED","schemaVersion":1,"payload":{"status":"QUEUED"},"createdAt":"2026-07-16T01:00:00Z"}\n\n',
    )
    const completedEvent = encoder.encode(
      'id: 2\nevent: PLANNING_COMPLETED\ndata: {"eventId":2,"taskId":"33333333-3333-3333-3333-333333333333","eventType":"PLANNING_COMPLETED","schemaVersion":1,"payload":{"status":"SUCCEEDED"},"createdAt":"2026-07-16T01:00:01Z"}\n\n',
    )
    let streamLoads = 0
    let itineraryLoads = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/planning-tasks`) && init?.method === 'POST') {
        return response({
          taskId: '33333333-3333-3333-3333-333333333333',
          tripId: tripResponse.id,
          taskType: 'CREATE',
          status: 'QUEUED',
          baselineTripVersion: 0,
          eventStreamUrl: '/api/planning-tasks/33333333-3333-3333-3333-333333333333/events',
          createdAt: '2026-07-16T01:00:00Z',
          updatedAt: '2026-07-16T01:00:00Z',
        }, 202)
      }
      if (url.endsWith('/api/planning-tasks/33333333-3333-3333-3333-333333333333/events')) {
        streamLoads += 1
        if (streamLoads === 1) {
          let reads = 0
          return {
            ok: true,
            status: 200,
            body: {
              getReader: () => ({
                read: async () => {
                  reads += 1
                  if (reads === 1) return { done: false, value: queuedEvent }
                  throw new TypeError('connection reset')
                },
              }),
            },
          } as unknown as Response
        }
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(completedEvent)
            controller.close()
          },
        })
        return { ok: true, status: 200, body } as Response
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) {
        itineraryLoads += 1
        return itineraryLoads === 1
          ? response({ code: 'ITINERARY_NOT_FOUND', message: 'Itinerary was not found' }, 404)
          : response(itineraryResponse)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '广州周末四日' })
    await fireEvent.click(screen.getByRole('button', { name: '打开 广州周末四日' }))
    await screen.findByText('尚未生成行程')
    await fireEvent.click(screen.getByRole('button', { name: '开始规划' }))

    expect(await screen.findByRole('heading', { name: '广州 Demo 行程' })).toBeTruthy()
    expect(streamLoads).toBe(2)
    const reconnectRequest = fetchMock.mock.calls.filter(([input]) => (
      urlOf(input).endsWith('/api/planning-tasks/33333333-3333-3333-3333-333333333333/events')
    ))[1]
    expect(reconnectRequest?.[1]?.headers).toMatchObject({ 'Last-Event-ID': '1' })
  })

  test('shows a retryable message when planning reports a business failure', async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(planningEvent('PLANNING_FAILED', 2, {
          status: 'FAILED',
          errorCode: 'STALE_TRIP_VERSION',
          message: '旅行约束已变化，请确认最新条件后重试',
        })))
        controller.close()
      },
    })
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/planning-tasks`) && init?.method === 'POST') {
        return response(planningTaskResponse, 202)
      }
      if (url.endsWith(planningTaskResponse.eventStreamUrl)) return { ok: true, status: 200, body } as Response
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) {
        return response({ code: 'ITINERARY_NOT_FOUND', message: 'Itinerary was not found' }, 404)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await openPlanningWorkspace(fetchMock)
    await fireEvent.click(screen.getByRole('button', { name: '开始规划' }))

    expect((await screen.findByRole('alert')).textContent).toContain('旅行约束已变化')
    expect(screen.getByRole('button', { name: '开始规划' })).toBeTruthy()
  })

  test('offers retry after three stream attempts end in network errors', async () => {
    let streamLoads = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/planning-tasks`) && init?.method === 'POST') {
        return response(planningTaskResponse, 202)
      }
      if (url.endsWith(planningTaskResponse.eventStreamUrl)) {
        streamLoads += 1
        return {
          ok: true,
          status: 200,
          body: { getReader: () => ({ read: async () => { throw new TypeError('connection reset') } }) },
        } as unknown as Response
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) {
        return response({ code: 'ITINERARY_NOT_FOUND', message: 'Itinerary was not found' }, 404)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await openPlanningWorkspace(fetchMock)
    await fireEvent.click(screen.getByRole('button', { name: '开始规划' }))

    expect((await screen.findByRole('alert')).textContent).toContain('无法连接业务服务')
    expect(streamLoads).toBe(3)
    expect(screen.getByRole('button', { name: '开始规划' })).toBeTruthy()
  })

  test('rotates an expired token and retries the authenticated event stream', async () => {
    let streamLoads = 0
    let itineraryLoads = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith('/api/auth/refresh')) {
        return response({
          ...authResponse,
          accessToken: 'renewed-access-token',
          refreshToken: 'rotated-refresh-token',
        })
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/planning-tasks`) && init?.method === 'POST') {
        return response(planningTaskResponse, 202)
      }
      if (url.endsWith(planningTaskResponse.eventStreamUrl)) {
        streamLoads += 1
        return streamLoads === 1 ? response({}, 401) : completedEventStream()
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) {
        itineraryLoads += 1
        return itineraryLoads === 1
          ? response({ code: 'ITINERARY_NOT_FOUND', message: 'Itinerary was not found' }, 404)
          : response(itineraryResponse)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await openPlanningWorkspace(fetchMock)
    await fireEvent.click(screen.getByRole('button', { name: '开始规划' }))

    expect(await screen.findByRole('heading', { name: itineraryResponse.title })).toBeTruthy()
    const streamRequests = fetchMock.mock.calls.filter(([input]) => urlOf(input).endsWith(planningTaskResponse.eventStreamUrl))
    expect(streamRequests).toHaveLength(2)
    expect(streamRequests[0]?.[1]?.headers).toMatchObject({ Authorization: 'Bearer access-token' })
    expect(streamRequests[1]?.[1]?.headers).toMatchObject({ Authorization: 'Bearer renewed-access-token' })
  })

  test('aborts the planning stream and ignores a late completion after returning to the list', async () => {
    let streamController!: ReadableStreamDefaultController<Uint8Array>
    let streamSignal: AbortSignal | undefined
    let itineraryLoads = 0
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        streamController = controller
      },
    })
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/planning-tasks`) && init?.method === 'POST') {
        return response(planningTaskResponse, 202)
      }
      if (url.endsWith(planningTaskResponse.eventStreamUrl)) {
        streamSignal = init?.signal ?? undefined
        return { ok: true, status: 200, body } as Response
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) {
        itineraryLoads += 1
        return response({ code: 'ITINERARY_NOT_FOUND', message: 'Itinerary was not found' }, 404)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await openPlanningWorkspace(fetchMock)
    await fireEvent.click(screen.getByRole('button', { name: '开始规划' }))
    await waitFor(() => expect(streamSignal).toBeTruthy())
    await fireEvent.click(screen.getByRole('button', { name: '返回旅行列表' }))

    expect(await screen.findByRole('heading', { name: '我的旅行' })).toBeTruthy()
    expect(streamSignal?.aborted).toBe(true)
    streamController.enqueue(new TextEncoder().encode(planningEvent('PLANNING_COMPLETED', 2, { status: 'SUCCEEDED' })))
    streamController.close()
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(itineraryLoads).toBe(1)
    expect(screen.queryByRole('heading', { name: itineraryResponse.title })).toBeNull()
  })

  test('updates constraints with the current version and preserves fixed schedules', async () => {
    const fixedSchedules = [{
      placeName: '广东省博物馆',
      startTime: '2026-07-19T10:00:00+08:00',
      endTime: '2026-07-19T12:00:00+08:00',
    }]
    const detailTrip = {
      ...tripResponse,
      constraints: { ...tripResponse.constraints, fixedSchedules },
    }
    const updatedTrip = {
      ...detailTrip,
      version: 1,
      constraints: {
        ...detailTrip.constraints,
        budgetAmount: 5200,
        travelers: 3,
        travelerType: 'FAMILY',
        pace: 'RELAXED',
      },
    }
    let submittedBody: unknown
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/constraints`) && init?.method === 'PUT') {
        submittedBody = JSON.parse(String(init.body))
        return response(updatedTrip)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(detailTrip)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '广州周末四日' })
    await fireEvent.click(screen.getByRole('button', { name: '打开 广州周末四日' }))
    await screen.findByRole('heading', { name: '结构化约束' })
    await fireEvent.click(screen.getByRole('button', { name: '编辑约束' }))
    await fireEvent.update(screen.getByLabelText('预算'), '5200')
    await fireEvent.update(screen.getByLabelText('同行人数'), '3')
    await fireEvent.update(screen.getByLabelText('同行类型'), 'FAMILY')
    await fireEvent.click(screen.getByLabelText('舒缓'))
    await fireEvent.click(screen.getByRole('button', { name: '保存约束' }))

    expect(await screen.findByText('版本 1')).toBeTruthy()
    expect(screen.getByText('¥5200')).toBeTruthy()
    expect(screen.getByText('3 人 · 家庭出行')).toBeTruthy()
    expect(submittedBody).toEqual({
      version: 0,
      budgetAmount: 5200,
      travelers: 3,
      travelerType: 'FAMILY',
      pace: 'RELAXED',
      preferences: ['岭南文化', '本地美食'],
      fixedSchedules,
    })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  test('keeps edits visible after a version conflict and can reload the latest trip', async () => {
    const latestTrip = {
      ...tripResponse,
      version: 2,
      constraints: { ...tripResponse.constraints, budgetAmount: 4800 },
    }
    let detailLoads = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/constraints`) && init?.method === 'PUT') {
        return response({ code: 'TRIP_VERSION_CONFLICT', message: '旅行约束已被其他请求更新' }, 409)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) {
        detailLoads += 1
        return response(detailLoads === 1 ? tripResponse : latestTrip)
      }
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '广州周末四日' })
    await fireEvent.click(screen.getByRole('button', { name: '打开 广州周末四日' }))
    await screen.findByRole('heading', { name: '结构化约束' })
    await fireEvent.click(screen.getByRole('button', { name: '编辑约束' }))
    await fireEvent.update(screen.getByLabelText('预算'), '5200')
    await fireEvent.click(screen.getByRole('button', { name: '保存约束' }))

    expect((await screen.findByRole('alert')).textContent).toContain('数据已更新')
    expect((screen.getByLabelText('预算') as HTMLInputElement).value).toBe('5200')
    await fireEvent.click(screen.getByRole('button', { name: '重新加载最新数据' }))

    expect(await screen.findByText('版本 2')).toBeTruthy()
    expect(screen.getByText('¥4800')).toBeTruthy()
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    await fireEvent.click(screen.getByRole('button', { name: '返回旅行列表' }))
    expect(await screen.findByText('¥4800')).toBeTruthy()
  })

  test('restores a deep-linked trip and loads the list when navigating back', async () => {
    window.history.replaceState({}, '', `/trips/${tripResponse.id}`)
    sessionStorage.setItem('trip-pilot.refresh-token', 'saved-refresh-token')
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/refresh')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: GET ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(App)

    expect(await screen.findByRole('heading', { name: '广州周末四日', level: 1 })).toBeTruthy()
    expect(window.location.pathname).toBe(`/trips/${tripResponse.id}`)
    await fireEvent.click(screen.getByRole('button', { name: '返回旅行列表' }))

    expect(await screen.findByRole('heading', { name: '广州周末四日', level: 2 })).toBeTruthy()
    expect(window.location.pathname).toBe('/trips')
  })

  test('ignores an older detail response after navigating to another trip', async () => {
    const secondTrip = {
      ...tripResponse,
      id: '33333333-3333-3333-3333-333333333333',
      title: '北京城市三日',
      destination: '北京',
    }
    let resolveFirstTrip!: (result: Response) => void
    const firstTripResponse = new Promise<Response>((resolve) => {
      resolveFirstTrip = resolve
    })
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return firstTripResponse
      if (url.endsWith(`/api/trips/${secondTrip.id}`)) return response(secondTrip)
      if (url.endsWith('/api/trips')) return response([tripResponse, secondTrip])
      throw new Error(`Unexpected request: GET ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '广州周末四日', level: 2 })
    await fireEvent.click(screen.getByRole('button', { name: '打开 广州周末四日' }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => urlOf(input).endsWith(`/api/trips/${tripResponse.id}`))).toBe(true)
    })

    window.history.pushState({}, '', '/trips')
    window.dispatchEvent(new PopStateEvent('popstate'))
    await fireEvent.click(await screen.findByRole('button', { name: '打开 北京城市三日' }))
    expect(await screen.findByRole('heading', { name: '北京城市三日', level: 1 })).toBeTruthy()

    resolveFirstTrip(response(tripResponse))
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(screen.getByRole('heading', { name: '北京城市三日', level: 1 })).toBeTruthy()
    expect(window.location.pathname).toBe(`/trips/${secondTrip.id}`)
  })

  test('keeps conflicted edits when reloading the latest trip fails', async () => {
    let detailLoads = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/constraints`) && init?.method === 'PUT') {
        return response({ code: 'TRIP_VERSION_CONFLICT', message: '旅行约束已被其他请求更新' }, 409)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) {
        detailLoads += 1
        return detailLoads === 1
          ? response(tripResponse)
          : response({ code: 'SERVICE_UNAVAILABLE', message: '暂时无法加载最新数据' }, 503)
      }
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '广州周末四日' })
    await fireEvent.click(screen.getByRole('button', { name: '打开 广州周末四日' }))
    await screen.findByRole('heading', { name: '结构化约束' })
    await fireEvent.click(screen.getByRole('button', { name: '编辑约束' }))
    await fireEvent.update(screen.getByLabelText('预算'), '5200')
    await fireEvent.click(screen.getByRole('button', { name: '保存约束' }))
    await screen.findByRole('button', { name: '重新加载最新数据' })
    await fireEvent.click(screen.getByRole('button', { name: '重新加载最新数据' }))

    expect(await screen.findByRole('dialog')).toBeTruthy()
    expect((screen.getByLabelText('预算') as HTMLInputElement).value).toBe('5200')
    expect(await screen.findByText('重新加载失败，当前修改仍保留，请稍后重试。')).toBeTruthy()
  })

  test('returns to login when access-token refresh is rejected', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith('/api/auth/refresh')) {
        return response({ code: 'INVALID_REFRESH_TOKEN', message: '登录状态已过期' }, 401)
      }
      if (url.endsWith('/api/trips')) return response({}, 401)
      throw new Error(`Unexpected request: GET ${url}`)
    })

    await signIn(fetchMock)

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => urlOf(input).endsWith('/api/auth/refresh'))).toBe(true)
    })
    expect(await screen.findByRole('heading', { name: '登录 TripPilot' })).toBeTruthy()
    expect(sessionStorage.getItem('trip-pilot.refresh-token')).toBeNull()
  })

  test('does not restore a session when refresh finishes after logout', async () => {
    let resolveRefresh!: (result: Response) => void
    const pendingRefresh = new Promise<Response>((resolve) => {
      resolveRefresh = resolve
    })
    const revokedTokens: string[] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith('/api/auth/refresh')) return pendingRefresh
      if (url.endsWith('/api/auth/logout')) {
        revokedTokens.push(JSON.parse(String(init?.body)).refreshToken)
        return response(undefined, 204)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response({}, 401)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '广州周末四日' })
    await fireEvent.click(screen.getByRole('button', { name: '打开 广州周末四日' }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => urlOf(input).endsWith('/api/auth/refresh'))).toBe(true)
    })
    await fireEvent.click(screen.getByRole('button', { name: '退出登录' }))
    expect(await screen.findByRole('heading', { name: '登录 TripPilot' })).toBeTruthy()

    resolveRefresh(response({
      ...authResponse,
      accessToken: 'late-access-token',
      refreshToken: 'late-refresh-token',
    }))
    await waitFor(() => expect(revokedTokens).toEqual(['refresh-token', 'late-refresh-token']))
    expect(screen.getByRole('heading', { name: '登录 TripPilot' })).toBeTruthy()
    expect(sessionStorage.getItem('trip-pilot.refresh-token')).toBeNull()
  })

  test('shows a recoverable error when browser navigation cannot load the trip list', async () => {
    let listLoads = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) {
        listLoads += 1
        if (listLoads === 1) return response([tripResponse])
        throw new TypeError('connection reset')
      }
      throw new Error(`Unexpected request: GET ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '广州周末四日' })
    await fireEvent.click(screen.getByRole('button', { name: '打开 广州周末四日' }))
    await screen.findByRole('heading', { name: '结构化约束' })
    window.history.pushState({}, '', '/trips')
    window.dispatchEvent(new PopStateEvent('popstate'))

    expect((await screen.findByRole('alert')).textContent).toContain('无法连接业务服务')
    expect(screen.getByRole('heading', { name: '我的旅行' })).toBeTruthy()
  })

  test('allows cent-precision budgets in create and edit forms', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: GET ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '广州周末四日' })
    await fireEvent.click(screen.getByRole('button', { name: '创建旅行' }))
    expect((screen.getByLabelText('预算') as HTMLInputElement).step).toBe('0.01')
    await fireEvent.click(screen.getByRole('button', { name: '取消' }))
    await fireEvent.click(screen.getByRole('button', { name: '打开 广州周末四日' }))
    await screen.findByRole('heading', { name: '结构化约束' })
    await fireEvent.click(screen.getByRole('button', { name: '编辑约束' }))
    expect((screen.getByLabelText('预算') as HTMLInputElement).step).toBe('0.01')
  })

  test('moves focus into the create dialog and restores it after Escape', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith('/api/trips')) return response([])
      throw new Error(`Unexpected request: GET ${url}`)
    })

    await signIn(fetchMock)
    const createButton = await screen.findByRole('button', { name: '创建旅行' })
    await fireEvent.click(createButton)

    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText('旅行名称')))
    await fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(document.activeElement).toBe(createButton)
  })

  test('traps keyboard focus inside the constraint editor', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: GET ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '广州周末四日' })
    await fireEvent.click(screen.getByRole('button', { name: '打开 广州周末四日' }))
    await screen.findByRole('heading', { name: '结构化约束' })
    const editButton = screen.getByRole('button', { name: '编辑约束' })
    await fireEvent.click(editButton)
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText('预算')))

    const dialog = screen.getByRole('dialog')
    const saveButton = screen.getByRole('button', { name: '保存约束' })
    saveButton.focus()
    await fireEvent.keyDown(dialog, { key: 'Tab' })
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '关闭' }))
    await fireEvent.keyDown(dialog, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(document.activeElement).toBe(editButton)
  })
})
