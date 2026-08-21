import { cleanup, fireEvent, render as renderComponent, screen, waitFor } from '@testing-library/vue'
import type { Component } from 'vue'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import App from '../src/App.vue'
import { createTripPilotRouter } from '../src/app/router'
import TripDetail from '../src/components/TripDetail.vue'

function render(component: Component, options?: Parameters<typeof renderComponent>[1]) {
  if (component !== App) return renderComponent(component, options)

  return renderComponent(component, {
    ...options,
    global: {
      ...options?.global,
      plugins: [createPinia(), createTripPilotRouter(), ...(options?.global?.plugins ?? [])],
    },
  })
}

const authResponse = {
  user: {
    id: '11111111-1111-1111-1111-111111111111',
    email: 'traveler@example.com',
    displayName: '旅行者',
  },
  accessToken: 'access-token',
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

const mustVisitCandidate = {
  provider: 'DEMO',
  providerPoiId: 'demo-chenjiaci',
  name: '陈家祠',
  address: 'Demo location in 广州',
  province: '',
  city: '广州',
  district: '',
  longitude: 113.2405,
  latitude: 23.1256,
  estimated: true,
}

const avoidCandidate = {
  provider: 'DEMO',
  providerPoiId: 'demo-guangzhouta',
  name: '广州塔',
  address: 'Demo location in 广州',
  province: '',
  city: '广州',
  district: '',
  longitude: 113.3245,
  latitude: 23.1066,
  estimated: true,
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
      providerPoiId: null,
      coordinates: { longitude: 113.2392, latitude: 23.1097 },
      address: '广州市荔湾区沙面岛',
    }, {
      id: '77777777-7777-7777-7777-777777777777',
      title: '品尝西关早茶',
      startTime: '2026-07-18T04:00:00Z',
      endTime: '2026-07-18T05:30:00Z',
      estimatedCost: 160,
      source: 'DEMO',
      providerPoiId: null,
      coordinates: { longitude: 113.2489, latitude: 23.1189 },
      address: '广州市荔湾区',
    }],
    transitLegs: [{
      id: '88888888-8888-8888-8888-888888888888',
      legOrder: 0,
      fromActivityId: '66666666-6666-6666-6666-666666666666',
      toActivityId: '77777777-7777-7777-7777-777777777777',
      mode: 'DRIVING',
      distanceMeters: 1380,
      durationSeconds: 1100,
      provider: 'DEMO',
      estimated: true,
      polyline: [
        { longitude: 113.2392, latitude: 23.1097 },
        { longitude: 113.2489, latitude: 23.1189 },
      ],
    }],
  }],
  knowledge: {
    status: 'REAL',
    query: '广州 岭南文化 本地美食 FRIENDS',
    citations: [{
      documentId: 'guangzhou-history-001',
      documentVersion: 2,
      chunkId: 'guangzhou-history-001-v2-c0',
      chunkIndex: 0,
      title: '广州历史文化资料',
      sourceUrl: 'https://www.gz.gov.cn/history',
      sourceName: '广州市人民政府',
      collectedAt: '2026-07-22T02:00:00Z',
      reliabilityLevel: 'official',
      similarity: 0.87,
    }],
    freshness: {
      status: 'FRESH',
      checkedAt: '2026-07-23T01:00:00Z',
      staleReason: null,
    },
    message: null,
  },
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

const planningEvaluation = {
  schemaVersion: 1,
  evaluatorVersion: 'rule-v1',
  feasible: true,
  overallScore: 91,
  dimensions: {
    constraintSatisfaction: 100,
    timeFeasibility: 88,
    budgetFit: 94,
    routeEfficiency: 86,
    interestMatch: 87,
  },
  warnings: [],
  decisions: [],
  summary: '行程整体质量 91/100。',
  evaluatedAt: '2026-08-02T00:00:00Z',
}

const currentPlanningVersion = {
  versionId: itineraryResponse.versionId,
  versionNumber: itineraryResponse.versionNumber,
  parentVersionId: null,
  planningTaskId: planningTaskResponse.taskId,
  versionSource: 'PLANNING_TASK',
  title: itineraryResponse.title,
  estimatedTotalCost: itineraryResponse.estimatedTotalCost,
  provider: itineraryResponse.provider,
  rollbackFromVersionId: null,
  createdAt: itineraryResponse.createdAt,
  current: true,
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

const verifiedFeasibilityReport = {
  schemaVersion: 1,
  reportId: 'c9c467cc-65c4-8ff1-e175-4af42f2ed545',
  validatorVersion: 'hard-validator-v4',
  itineraryFingerprint: 'a'.repeat(64),
  status: 'VERIFIED',
  validatedAt: '2026-07-16T01:00:01Z',
  requiredRuleIds: ['OPENING_HOURS'],
  missingRequiredRuleIds: [],
  summary: { totalCount: 1, passCount: 1, failCount: 0, unknownCount: 0, notApplicableCount: 0, missingRequiredCount: 0 },
  ruleResults: [{
    ruleId: 'OPENING_HOURS',
    ruleVersion: 'hard-rule-v1',
    outcome: 'PASS',
    reasonCode: 'OPENING_HOURS_VERIFIED',
    message: '营业时间内开放',
    affectedDates: ['2026-07-18'],
    affectedEntityRefs: [],
    evidenceRefs: [],
    repairable: false,
  }],
  repairAttempts: [],
}

function completedPayload() {
  return {
    status: 'SUCCEEDED',
    provider: 'DEMO',
    feasibilityReport: verifiedFeasibilityReport,
    evaluation: planningEvaluation,
  }
}

function completedEventStream(): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(planningEvent('PLANNING_COMPLETED', 2, completedPayload())))
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
  let restoreAttempted = false
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (!restoreAttempted && urlOf(input).endsWith('/api/auth/refresh')) {
      restoreAttempted = true
      return response({ code: 'INVALID_REFRESH_TOKEN', message: 'Refresh cookie is missing' }, 401)
    }
    if (urlOf(input).endsWith('/guide-imports') && init?.method !== 'POST') {
      try {
        return await fetchMock(input, init)
      } catch {
        return response([])
      }
    }
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

  await fireEvent.update(await screen.findByLabelText('邮箱'), 'traveler@example.com')
  await fireEvent.update(screen.getByLabelText('密码'), 'correct-password')
  await fireEvent.click(screen.getByRole('button', { name: '登录' }))
}

async function openPlanningWorkspace(fetchMock: ReturnType<typeof vi.fn>) {
  await signIn(fetchMock)
  await screen.findByRole('heading', { name: tripResponse.title })
  await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))
  await screen.findByText('尚未生成行程')
}

/** B13: select a structured destination through the province/city cascade. */
async function selectDestinationCity(province: string, city: string, district?: string) {
  await fireEvent.update(await screen.findByLabelText('省 / 直辖市'), province)
  const citySelect = await screen.findByLabelText('城市')
  await fireEvent.update(citySelect, city)
  if (district) {
    await fireEvent.click(await screen.findByRole('button', { name: district }))
  }
}

/** B13-E: fill the two datetime boundaries of the create form. */
async function fillBoundaries(arrival: string, departure: string) {
  await fireEvent.update(screen.getByLabelText('抵达时间'), arrival)
  await fireEvent.update(screen.getByLabelText('离开时间'), departure)
}

describe('TripPilot application shell', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/trips')
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  test('shows login and registration modes to unauthenticated visitors', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response({ code: 'INVALID_REFRESH_TOKEN' }, 401)))
    render(App)

    expect(await screen.findByRole('heading', { name: '登录 TripPilot' })).toBeTruthy()
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

    const tripsRequest = fetchMock.mock.calls.find(([input]) => urlOf(input).endsWith('/api/trips'))
    expect(tripsRequest?.[1]?.headers).toMatchObject({ Authorization: 'Bearer access-token' })
  })

  test('restores a session by rotating the HttpOnly refresh cookie', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/refresh')) {
        return response(authResponse)
      }
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(App)

    expect(await screen.findByRole('heading', { name: '广州周末四日' })).toBeTruthy()
    const refreshRequest = fetchMock.mock.calls.find(([input]) => urlOf(input).endsWith('/api/auth/refresh'))
    expect(refreshRequest?.[1]?.credentials).toBe('same-origin')
    expect(refreshRequest?.[1]?.body).toBeUndefined()
  })

  test('keeps the rotated session when loading trips has a transient failure', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/refresh')) {
        return response(authResponse)
      }
      if (url.endsWith('/api/trips')) throw new TypeError('connection reset')
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(App)

    expect(await screen.findByRole('heading', { name: '我的旅行' })).toBeTruthy()
    expect((await screen.findByRole('alert')).textContent).toContain('无法连接业务服务，请稍后重试')
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
    await selectDestinationCity('广东省', '广州')
    await fillBoundaries('2026-07-18T09:00', '2026-07-21T18:00')
    await fireEvent.click(screen.getByRole('button', { name: '保存旅行' }))

    expect(await screen.findByRole('heading', { name: '广州周末四日' })).toBeTruthy()
    expect(createAttempts).toBe(2)
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
      expect(request?.[1]?.credentials).toBe('same-origin')
      expect(request?.[1]?.body).toBeUndefined()
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
    await selectDestinationCity('浙江省', '杭州')
    await fillBoundaries('2026-08-01T09:00', '2026-08-04T18:00')
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

    // B13_FIX R6 (P1-3): the create page owns exactly two datetime inputs
    // (the authoritative boundaries); the legacy constraint-time inputs are
    // gone.
    const boundaryTimes = document.querySelectorAll('input[type="datetime-local"]')
    expect(boundaryTimes).toHaveLength(2)
    expect(screen.queryByLabelText('到达时间（北京时间）')).toBeNull()
    expect(screen.queryByLabelText('返程时间（北京时间）')).toBeNull()

    await fireEvent.update(screen.getByLabelText('旅行名称'), '广州周末四日')
    await selectDestinationCity('广东省', '广州')
    await fillBoundaries('2026-07-18T09:00', '2026-07-21T18:00')
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
      region: {
        provinceCode: '440000',
        cityCode: '440100',
        districtCodes: [],
        provinceName: '广东省',
        cityName: '广州',
        districtNames: ['全市'],
        datasetVersion: '2023-06-30',
      },
      arrivalAt: '2026-07-18T09:00:00+08:00',
      departureAt: '2026-07-21T18:00:00+08:00',
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
        mealWindows: [
          { mealType: 'BREAKFAST', startTime: '08:00', endTime: '09:00', source: 'DEFAULT' },
          { mealType: 'LUNCH', startTime: '12:00', endTime: '13:00', source: 'DEFAULT' },
          { mealType: 'DINNER', startTime: '18:00', endTime: '19:00', source: 'DEFAULT' },
        ],
        mobilityLevel: 'STANDARD',
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

  test('restores the evaluation linked to the current itinerary version', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/versions`)) {
        return response([currentPlanningVersion])
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/shares`)) return response([])
      if (url.endsWith(`/api/planning-tasks/${planningTaskResponse.taskId}`)) {
        return response({ ...planningTaskResponse, status: 'SUCCEEDED', evaluation: planningEvaluation, feasibilityReport: verifiedFeasibilityReport })
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) return response(itineraryResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))

    expect(await screen.findByText('91/100')).toBeTruthy()
    expect(screen.getByText('行程整体质量 91/100。')).toBeTruthy()
    expect(
      fetchMock.mock.calls.some(([input]) =>
        urlOf(input as RequestInfo | URL).endsWith(`/api/planning-tasks/${planningTaskResponse.taskId}`),
      ),
    ).toBe(true)
  })

  test.each(['USER_EDIT', 'ROLLBACK'] as const)(
    'does not inherit a planning evaluation for a current %s version',
    async (versionSource) => {
      const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = urlOf(input)
        if (url.endsWith('/api/auth/login')) return response(authResponse)
        if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/versions`)) {
          return response([{ ...currentPlanningVersion, planningTaskId: null, versionSource }])
        }
        if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/shares`)) return response([])
        if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) return response(itineraryResponse)
      if (url.endsWith('/api/planning-tasks/33333333-3333-3333-3333-333333333333/events')) {
        return response('', 200, { 'Content-Type': 'text/event-stream' })
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

      await signIn(fetchMock)
      await screen.findByRole('heading', { name: tripResponse.title })
      await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))
      await screen.findByRole('heading', { name: itineraryResponse.title })

      expect(screen.queryByText('91/100')).toBeNull()
      expect(screen.queryByText('该版本生成时尚未启用质量评估')).toBeNull()
      expect(fetchMock.mock.calls.some(([input]) => urlOf(input).includes('/api/planning-tasks/'))).toBe(false)
    },
  )

  test('keeps the new trip evaluation when an old trip version request finishes late', async () => {
    const secondTrip = {
      ...tripResponse,
      id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
      title: '北京城市三日',
      destination: '北京',
    }
    const secondItinerary = {
      ...itineraryResponse,
      versionId: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
      title: '北京 Demo 行程',
    }
    const secondTaskId = 'cccccccc-cccc-cccc-cccc-cccccccccccc'
    const secondVersion = {
      ...currentPlanningVersion,
      versionId: secondItinerary.versionId,
      planningTaskId: secondTaskId,
      title: secondItinerary.title,
    }
    let resolveFirstVersions!: (result: Response) => void
    const firstVersions = new Promise<Response>((resolve) => {
      resolveFirstVersions = resolve
    })
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/versions`)) return firstVersions
      if (url.endsWith(`/api/trips/${secondTrip.id}/itinerary/versions`)) return response([secondVersion])
      if (url.endsWith('/itinerary/shares')) return response([])
      if (url.endsWith(`/api/planning-tasks/${secondTaskId}`)) {
        return response({
          ...planningTaskResponse,
          taskId: secondTaskId,
          tripId: secondTrip.id,
          status: 'SUCCEEDED',
          evaluation: planningEvaluation,
          feasibilityReport: verifiedFeasibilityReport,
        })
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) return response(itineraryResponse)
      if (url.endsWith(`/api/trips/${secondTrip.id}/itinerary`)) return response(secondItinerary)
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith(`/api/trips/${secondTrip.id}`)) return response(secondTrip)
      if (url.endsWith('/api/trips')) return response([tripResponse, secondTrip])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))
    await waitFor(() => expect(window.location.pathname).toBe(`/trips/${tripResponse.id}`))
    window.history.pushState({}, '', '/trips')
    window.dispatchEvent(new PopStateEvent('popstate'))
    await fireEvent.click(await screen.findByRole('button', { name: `打开 ${secondTrip.title}` }))

    expect(await screen.findByText('91/100')).toBeTruthy()
    resolveFirstVersions(response([currentPlanningVersion]))
    await new Promise((resolve) => setTimeout(resolve, 20))

    expect(screen.getByRole('heading', { name: secondTrip.title, level: 1 })).toBeTruthy()
    expect(screen.getByText('91/100')).toBeTruthy()
  })

  test('ignores an old edit response after leaving and reopening the same trip', async () => {
    const secondTrip = {
      ...tripResponse,
      id: 'dddddddd-dddd-dddd-dddd-dddddddddddd',
      title: '北京城市三日',
      destination: '北京',
    }
    const secondItinerary = {
      ...itineraryResponse,
      versionId: 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
      title: '北京 Demo 行程',
    }
    const secondVersion = {
      ...currentPlanningVersion,
      versionId: secondItinerary.versionId,
      planningTaskId: null,
      versionSource: 'USER_EDIT',
      title: secondItinerary.title,
    }
    let resolveOldEdit!: (result: Response) => void
    const oldEdit = new Promise<Response>((resolve) => {
      resolveOldEdit = resolve
    })
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/edits/preview`)) {
        return response({
          operation: 'DELETE_ACTIVITY',
          canApply: true,
          impactedDates: [itineraryResponse.days[0]!.date],
          impactedActivityIds: [itineraryResponse.days[0]!.activities[0]!.id],
          warnings: [],
          blockingReasons: [],
        })
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/edits/commit`)) return oldEdit
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/versions`)) {
        return response([currentPlanningVersion])
      }
      if (url.endsWith(`/api/trips/${secondTrip.id}/itinerary/versions`)) return response([secondVersion])
      if (url.endsWith('/itinerary/shares')) return response([])
      if (url.endsWith(`/api/planning-tasks/${planningTaskResponse.taskId}`)) {
        return response({ ...planningTaskResponse, status: 'SUCCEEDED', evaluation: planningEvaluation, feasibilityReport: verifiedFeasibilityReport })
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) return response(itineraryResponse)
      if (url.endsWith(`/api/trips/${secondTrip.id}/itinerary`)) return response(secondItinerary)
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith(`/api/trips/${secondTrip.id}`)) return response(secondTrip)
      if (url.endsWith('/api/trips')) return response([tripResponse, secondTrip])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))
    expect(await screen.findByText('91/100')).toBeTruthy()
    const deleteButton = screen.getAllByRole('button', { name: '删除活动 漫步沙面岛' }).at(-1)!
    await waitFor(() => expect(deleteButton.disabled).toBe(false))
    await fireEvent.click(deleteButton)
    await fireEvent.click(await screen.findByRole('button', { name: '应用修改' }))
    await fireEvent.click(screen.getByTestId('save-itinerary-draft'))
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => (
      urlOf(input).endsWith(`/api/trips/${tripResponse.id}/itinerary/edits/commit`)
    ))).toBe(true))

    window.history.pushState({}, '', '/trips')
    window.dispatchEvent(new PopStateEvent('popstate'))
    await fireEvent.click(await screen.findByRole('button', { name: `打开 ${secondTrip.title}` }))
    await screen.findByRole('heading', { name: secondTrip.title, level: 1 })
    window.history.pushState({}, '', '/trips')
    window.dispatchEvent(new PopStateEvent('popstate'))
    await fireEvent.click(await screen.findByRole('button', { name: `打开 ${tripResponse.title}` }))
    expect(await screen.findByText('91/100')).toBeTruthy()

    resolveOldEdit(response({ ...itineraryResponse, title: '迟到的旧编辑' }))
    await new Promise((resolve) => setTimeout(resolve, 20))

    expect(screen.getByRole('heading', { name: itineraryResponse.title })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: '迟到的旧编辑' })).toBeNull()
    expect(screen.getByText('91/100')).toBeTruthy()
  })

  test('reports evaluation hydration failure and retries without reloading the trip', async () => {
    let evaluationLoads = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/versions`)) {
        return response([currentPlanningVersion])
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/shares`)) return response([])
      if (url.endsWith(`/api/planning-tasks/${planningTaskResponse.taskId}`)) {
        evaluationLoads += 1
        return evaluationLoads === 1
          ? response({ code: 'SERVICE_UNAVAILABLE', message: 'temporary failure' }, 503)
          : response({ ...planningTaskResponse, status: 'SUCCEEDED', evaluation: planningEvaluation, feasibilityReport: verifiedFeasibilityReport })
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) return response(itineraryResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))

    expect((await screen.findByRole('alert')).textContent).toContain('行程质量评估暂时无法加载')
    await fireEvent.click(screen.getByRole('button', { name: '重试质量评估' }))

    expect(await screen.findByText('91/100')).toBeTruthy()
    expect(evaluationLoads).toBe(2)
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
    let versionLoads = 0
    let planningCreateAttempts = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith('/api/auth/refresh')) {
        return response({
          ...authResponse,
          accessToken: 'renewed-access-token',
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
      if (url.endsWith(`/api/planning-tasks/${planningTaskResponse.taskId}`)) {
        return response({ ...planningTaskResponse, status: 'SUCCEEDED', evaluation: planningEvaluation, feasibilityReport: verifiedFeasibilityReport })
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/versions`)) {
        versionLoads += 1
        return response(versionLoads === 1 ? [] : [currentPlanningVersion])
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/shares`)) return response([])
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
      `id: 2\nevent: PLANNING_PROGRESS\ndata: ${JSON.stringify({
        eventId: 2,
        taskId: planningTaskResponse.taskId,
        eventType: 'PLANNING_PROGRESS',
        schemaVersion: 2,
        payload: {
          status: 'RUNNING',
          stage: 'REPAIRING',
          sequence: 2,
          progress: 75,
          message: '正在执行第 1 轮有界修复',
          statistics: { attemptIndex: 1, actionCount: 2 },
        },
        createdAt: '2026-07-16T01:00:01Z',
      })}\n\n`,
    ))
    expect(await screen.findByText('执行有界修复')).toBeTruthy()

    streamController.enqueue(encoder.encode(
      `id: 3\nevent: PLANNING_COMPLETED\ndata: ${JSON.stringify({
        eventId: 3,
        taskId: planningTaskResponse.taskId,
        eventType: 'PLANNING_COMPLETED',
        schemaVersion: 9,
        payload: completedPayload(),
        createdAt: '2026-07-16T01:00:02Z',
      })}\n\n`,
    ))
    streamController.close()

    expect(await screen.findByRole('heading', { name: '广州 Demo 行程' })).toBeTruthy()
    expect(await screen.findByText('91/100')).toBeTruthy()
    expect(screen.getByRole('heading', { name: '行程时间轴' })).toBeTruthy()
    expect(screen.getAllByText('漫步沙面岛')).toHaveLength(2)
    expect(screen.getByRole('region', { name: '行程地图' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '定位 品尝西关早茶' })).toBeTruthy()
    expect(screen.getByText('09:00 — 11:00')).toBeTruthy()
    expect(screen.getByText('¥860')).toBeTruthy()
    expect(screen.getByRole('heading', { name: '推荐依据' })).toBeTruthy()
    expect(screen.getByText('真实知识')).toBeTruthy()
    expect(screen.getByText('来源新鲜')).toBeTruthy()
    const sourceLink = screen.getByRole('link', { name: /广州历史文化资料/ })
    expect(sourceLink.getAttribute('href')).toBe('https://www.gz.gov.cn/history')
    expect(sourceLink.getAttribute('target')).toBe('_blank')
    expect(screen.getByText(/广州市人民政府/)).toBeTruthy()
    await fireEvent.click(screen.getByRole('button', { name: '定位 品尝西关早茶' }))
    expect(screen.getByRole('button', { name: '选择活动 品尝西关早茶' }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByText('广州市荔湾区沙面岛')).toBeTruthy()
    await fireEvent.click(screen.getByRole('button', { name: '选择活动 漫步沙面岛' }))
    expect(screen.getByRole('button', { name: '定位 漫步沙面岛' }).getAttribute('aria-pressed')).toBe('true')
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
      `id: 2\nevent: PLANNING_COMPLETED\ndata: ${JSON.stringify({
        eventId: 2,
        taskId: planningTaskResponse.taskId,
        eventType: 'PLANNING_COMPLETED',
        schemaVersion: 1,
        payload: completedPayload(),
        createdAt: '2026-07-16T01:00:01Z',
      })}\n\n`,
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
          conflicts: [{
            code: 'INSUFFICIENT_DAY_CAPACITY',
            message: '活动、交通与固定安排无法同时放入可用时间',
            affected: ['已预约午餐'],
          }],
          relaxationSuggestions: [{
            code: 'REDUCE_OPTIONAL_ACTIVITIES',
            message: '减少一个可选活动',
          }],
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
    expect(screen.getByRole('alert').textContent).toContain('活动、交通与固定安排')
    expect(screen.getByRole('alert').textContent).toContain('建议：减少一个可选活动')
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
    streamController.enqueue(new TextEncoder().encode(planningEvent('PLANNING_COMPLETED', 2, completedPayload())))
    streamController.close()
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(itineraryLoads).toBe(1)
    expect(screen.queryByRole('heading', { name: itineraryResponse.title })).toBeNull()
  })

  test('ignores a late guide import after leaving and reopening the trip', async () => {
    let resolveImport!: (result: Response) => void
    const pendingImport = new Promise<Response>((resolve) => {
      resolveImport = resolve
    })
    const importedGuide = {
      id: '99999999-9999-9999-9999-999999999999',
      sourceType: 'PUBLIC_GUIDE_URL',
      sourceUrl: 'https://example.com/guide',
      finalUrl: 'https://example.com/guide',
      sourceHost: 'example.com',
      title: 'Late guide result',
      excerpt: 'Late data must not cross route boundaries.',
      contentHash: 'a'.repeat(64),
      fetchedAt: '2026-07-23T08:00:00Z',
      facts: [],
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/guide-imports`) && init?.method === 'POST') {
        return pendingImport
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) {
        return response({ code: 'ITINERARY_NOT_FOUND', message: 'Itinerary was not found' }, 404)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await openPlanningWorkspace(fetchMock)
    await fireEvent.update(screen.getByLabelText('公开攻略链接'), importedGuide.sourceUrl)
    await fireEvent.click(screen.getByRole('button', { name: '导入攻略' }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input, init]) => (
        urlOf(input).endsWith(`/api/trips/${tripResponse.id}/guide-imports`)
        && init?.method === 'POST'
      ))).toBe(true)
    })

    await fireEvent.click(screen.getByRole('button', { name: '返回旅行列表' }))
    await fireEvent.click(await screen.findByRole('button', { name: `打开 ${tripResponse.title}` }))
    await screen.findByRole('heading', { name: '攻略情报' })
    resolveImport(response(importedGuide, 201))

    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(screen.queryByText(importedGuide.title)).toBeNull()
    expect(screen.getByText('还没有导入攻略')).toBeTruthy()
  })

  test('ignores a late guide toggle after leaving and reopening the trip', async () => {
    let resolveToggle!: (result: Response) => void
    const pendingToggle = new Promise<Response>((resolve) => {
      resolveToggle = resolve
    })
    const guide = {
      id: '99999999-9999-9999-9999-999999999999',
      sourceType: 'PUBLIC_GUIDE_URL',
      sourceUrl: 'https://example.com/guide',
      finalUrl: 'https://example.com/guide',
      sourceHost: 'example.com',
      title: 'Controllable guide source',
      excerpt: 'Late toggle must not cross route boundaries.',
      contentHash: 'a'.repeat(64),
      fetchedAt: '2026-07-23T08:00:00Z',
      enabled: true,
      facts: [],
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith('/guide-imports') && init?.method !== 'POST') return response([guide])
      if (url.endsWith(`/guide-imports/${guide.id}`) && init?.method === 'PUT') return pendingToggle
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) {
        return response({ code: 'ITINERARY_NOT_FOUND', message: 'Itinerary was not found' }, 404)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await openPlanningWorkspace(fetchMock)
    const guideCard = (await screen.findByText(guide.title)).closest('article')
    const toggle = guideCard?.querySelector('button') as HTMLButtonElement | null
    expect(toggle).toBeTruthy()
    const enabledLabel = toggle?.textContent?.trim()
    await fireEvent.click(toggle!)
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input, init]) => (
        urlOf(input).endsWith(`/guide-imports/${guide.id}`)
        && init?.method === 'PUT'
      ))).toBe(true)
    })

    window.history.pushState({}, '', '/trips')
    window.dispatchEvent(new PopStateEvent('popstate'))
    await waitFor(() => expect(screen.queryByText(guide.title)).toBeNull())
    window.history.pushState({}, '', `/trips/${tripResponse.id}`)
    window.dispatchEvent(new PopStateEvent('popstate'))
    const reopenedCard = (await screen.findByText(guide.title)).closest('article')
    resolveToggle(response({ ...guide, enabled: false }))

    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(reopenedCard?.querySelector('button')?.textContent?.trim()).toBe(enabledLabel)
  })

  test('lets the owner cancel an active planning task', async () => {
    let streamSignal: AbortSignal | undefined
    const body = new ReadableStream<Uint8Array>()
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
      if (url.endsWith(`/api/planning-tasks/${planningTaskResponse.taskId}`) && init?.method === 'DELETE') {
        return response({ ...planningTaskResponse, status: 'CANCELLED' })
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
    await waitFor(() => expect(streamSignal).toBeTruthy())
    await fireEvent.click(screen.getByRole('button', { name: '取消规划' }))

    expect(await screen.findByText('规划已取消')).toBeTruthy()
    expect(streamSignal?.aborted).toBe(true)
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/planning-tasks/${planningTaskResponse.taskId}`,
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  // Heavier async test (multiple SSE/version interactions); CI runners
  // occasionally exceed the 5s default, so give it a bounded larger budget.
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
      if (url.endsWith('/api/trips/places/search')) {
        const body = JSON.parse(String(init?.body))
        if (body.keyword === '广州南站') {
          return response({
            provider: 'DEMO',
            estimated: true,
            candidates: [{ ...mustVisitCandidate, name: '广州南站', providerPoiId: 'demo-gz-south' }],
          })
        }
        if (body.keyword === '广州白云机场') {
          return response({
            provider: 'DEMO',
            estimated: true,
            candidates: [{ ...mustVisitCandidate, name: '广州白云机场', providerPoiId: 'demo-gz-airport' }],
          })
        }
        if (body.keyword === '北京路附近酒店') {
          return response({
            provider: 'DEMO',
            estimated: true,
            candidates: [{ ...mustVisitCandidate, name: '北京路附近酒店', providerPoiId: 'demo-gz-hotel' }],
          })
        }
        return response({
          provider: 'DEMO',
          estimated: true,
          candidates: body.keyword === '广州塔' ? [avoidCandidate] : [mustVisitCandidate],
        })
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
    await fireEvent.update(screen.getByLabelText('到达地点搜索'), '广州南站')
    await fireEvent.click(await screen.findByRole('button', { name: /广州南站/ }))
    await fireEvent.update(screen.getByLabelText('到达时间（北京时间）'), '2026-07-18T11:00')
    await fireEvent.update(screen.getByLabelText('返程地点搜索'), '广州白云机场')
    await fireEvent.click(await screen.findByRole('button', { name: /广州白云机场/ }))
    await fireEvent.update(screen.getByLabelText('返程时间（北京时间）'), '2026-07-21T17:00')
    await fireEvent.update(screen.getByLabelText('住宿锚点搜索'), '北京路附近酒店')
    await fireEvent.click(await screen.findByRole('button', { name: /北京路附近酒店/ }))
    // Close the anchor dropdowns so the candidate click below targets the
    // must-visit list only (anchors are candidate-pickers since B13_FIX R5).
    await fireEvent.blur(screen.getByLabelText('到达地点搜索'))
    await fireEvent.blur(screen.getByLabelText('返程地点搜索'))
    await fireEvent.blur(screen.getByLabelText('住宿锚点搜索'))
    await fireEvent.update(screen.getByLabelText('必去地点搜索'), '陈家祠')
    await fireEvent.click(await screen.findByRole('button', { name: /陈家祠/ }))
    await fireEvent.update(screen.getByLabelText('排除地点搜索'), '广州塔')
    await fireEvent.click(await screen.findByRole('button', { name: /广州塔/ }))
    await fireEvent.update(screen.getByLabelText('行动能力'), 'REDUCED')
    await fireEvent.update(screen.getByLabelText('午餐安排方式'), 'USER')
    await fireEvent.update(screen.getByLabelText('午餐开始时间'), '12:00')
    await fireEvent.update(screen.getByLabelText('午餐结束时间'), '13:00')
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
      arrival: {
        placeName: '广州南站',
        time: '2026-07-18T11:00:00+08:00',
        placeRef: {
          provider: 'DEMO',
          providerPoiId: 'demo-gz-south',
          name: '广州南站',
          address: 'Demo location in 广州',
          province: '',
          city: '广州',
          district: '',
          longitude: 113.2405,
          latitude: 23.1256,
        },
      },
      departure: {
        placeName: '广州白云机场',
        time: '2026-07-21T17:00:00+08:00',
        placeRef: {
          provider: 'DEMO',
          providerPoiId: 'demo-gz-airport',
          name: '广州白云机场',
          address: 'Demo location in 广州',
          province: '',
          city: '广州',
          district: '',
          longitude: 113.2405,
          latitude: 23.1256,
        },
      },
      accommodation: {
        placeName: '北京路附近酒店',
        placeRef: {
          provider: 'DEMO',
          providerPoiId: 'demo-gz-hotel',
          name: '北京路附近酒店',
          address: 'Demo location in 广州',
          province: '',
          city: '广州',
          district: '',
          longitude: 113.2405,
          latitude: 23.1256,
        },
      },
      mustVisitPlaces: ['陈家祠'],
      avoidPlaces: ['广州塔'],
      mustVisitPlaceRefs: [{
        provider: 'DEMO',
        providerPoiId: 'demo-chenjiaci',
        name: '陈家祠',
        address: 'Demo location in 广州',
        province: '',
        city: '广州',
        district: '',
        longitude: 113.2405,
        latitude: 23.1256,
      }],
      avoidPlaceRefs: [{
        provider: 'DEMO',
        providerPoiId: 'demo-guangzhouta',
        name: '广州塔',
        address: 'Demo location in 广州',
        province: '',
        city: '广州',
        district: '',
        longitude: 113.3245,
        latitude: 23.1066,
      }],
      mealWindows: [
        { mealType: 'BREAKFAST', startTime: '08:00', endTime: '09:00', source: 'DEFAULT' },
        { mealType: 'LUNCH', startTime: '12:00', endTime: '13:00', source: 'USER' },
        { mealType: 'DINNER', startTime: '18:00', endTime: '19:00', source: 'DEFAULT' },
      ],
      mobilityLevel: 'REDUCED',
    })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  }, 15_000)

  test('keeps partial travel and meal fields visible instead of silently dropping them', async () => {
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
    await screen.findByRole('heading', { name: '结构化约束' })
    await fireEvent.click(screen.getByRole('button', { name: '编辑约束' }))
    await fireEvent.update(screen.getByLabelText('到达地点搜索'), '广州南站')
    await fireEvent.update(screen.getByLabelText('午餐安排方式'), 'USER')
    await fireEvent.update(screen.getByLabelText('午餐开始时间'), '12:00')
    await fireEvent.click(screen.getByRole('button', { name: '保存约束' }))

    expect((await screen.findByRole('alert')).textContent).toContain('请同时填写到达地点和到达时间')
    expect((screen.getByLabelText('到达地点搜索') as HTMLInputElement).value).toBe('广州南站')
    expect((screen.getByLabelText('午餐开始时间') as HTMLInputElement).value).toBe('12:00')
    expect(fetchMock).not.toHaveBeenCalledWith(
      `/api/trips/${tripResponse.id}/constraints`,
      expect.objectContaining({ method: 'PUT' }),
    )
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
  })

  test('does not restore a session when refresh finishes after logout', async () => {
    let resolveRefresh!: (result: Response) => void
    const pendingRefresh = new Promise<Response>((resolve) => {
      resolveRefresh = resolve
    })
    let logoutRequests = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith('/api/auth/refresh')) return pendingRefresh
      if (url.endsWith('/api/auth/logout')) {
        expect(init?.credentials).toBe('same-origin')
        expect(init?.body).toBeUndefined()
        logoutRequests += 1
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
    }))
    await waitFor(() => expect(logoutRequests).toBe(2))
    expect(screen.getByRole('heading', { name: '登录 TripPilot' })).toBeTruthy()
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

describe('itinerary knowledge evidence states', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/trips')
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  test.each([
    ['REAL', 'FRESH', '真实知识', '来源新鲜'],
    ['REAL', 'STALE', '真实知识', '来源可能过期'],
    ['DEMO', 'UNAVAILABLE', '演示知识', '新鲜度不可用'],
    ['UNAVAILABLE', 'UNAVAILABLE', '知识不可用', '新鲜度不可用'],
  ] as const)('renders %s evidence with %s freshness', (
    status,
    freshnessStatus,
    evidenceLabel,
    freshnessText,
  ) => {
    const itinerary = structuredClone(itineraryResponse)
    itinerary.knowledge.status = status
    itinerary.knowledge.freshness.status = freshnessStatus
    itinerary.knowledge.freshness.checkedAt = freshnessStatus === 'UNAVAILABLE'
      ? null
      : '2026-07-23T01:00:00Z'
    itinerary.knowledge.freshness.staleReason = freshnessStatus === 'STALE'
      ? 'SOURCE_VERIFICATION_OVERDUE'
      : null
    if (status !== 'REAL') {
      itinerary.knowledge.citations = []
      itinerary.knowledge.message = status === 'DEMO'
        ? '演示模式未使用生产知识检索'
        : '知识检索暂时不可用'
    }

    render(TripDetail, {
      props: {
        user: authResponse.user,
        trip: tripResponse,
        busy: false,
        error: null,
        itinerary,
        itineraryBusy: false,
        itineraryError: null,
        planningState: 'succeeded',
        planningError: null,
        startPlanning: vi.fn(async () => {}),
        cancelPlanning: vi.fn(async () => {}),
        updateConstraints: vi.fn(async () => {}),
        reloadTrip: vi.fn(async () => true),
      },
    })

    expect(screen.getByText(evidenceLabel)).toBeTruthy()
    expect(screen.getByText(freshnessText)).toBeTruthy()
  })

  test('PLANNING_REVIEW_REQUIRED shows waiting user review without replacing the itinerary', async () => {
    const encoder = new TextEncoder()
    let streamController!: ReadableStreamDefaultController<Uint8Array>
    const eventStream = new ReadableStream<Uint8Array>({
      start(controller) { streamController = controller },
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
      ruleResults: [{
        ruleId: 'OPENING_HOURS',
        ruleVersion: 'hard-rule-v1',
        outcome: 'FAIL',
        reasonCode: 'VENUE_CLOSED',
        message: '景点在行程时间关闭',
        affectedDates: ['2026-07-18'],
        affectedEntityRefs: [],
        evidenceRefs: [],
        repairable: true,
      }],
      repairAttempts: [],
    }
    const reviewCandidate = {
      title: '候选行程',
      days: [{
        date: '2026-07-18',
        dayType: null,
        activities: [{
          activityId: '3d76fb9e-362e-4b28-8a9e-18e8ac7050ae',
          title: '候选活动',
          startTime: '2026-07-18T01:00:00Z',
          endTime: '2026-07-18T02:00:00Z',
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
        return { ok: true, status: 200, body: eventStream } as Response
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/versions`)) {
        return response([{
          ...currentPlanningVersion,
          feasibility: null,
        }])
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/shares`)) return response([])
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) {
        return response(itineraryResponse)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '广州周末四日' })
    await fireEvent.click(await waitFor(() => screen.getByRole('button', { name: '打开 广州周末四日' })))
    await screen.findByRole('heading', { name: '结构化约束' })
    await fireEvent.click(screen.getByRole('button', { name: '重新规划' }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '规划中' })).toHaveProperty('disabled', true)
    })
    streamController.enqueue(encoder.encode(
      'id: 1\nevent: PLANNING_QUEUED\ndata: {"eventId":1,"taskId":"33333333-3333-3333-3333-333333333333","eventType":"PLANNING_QUEUED","schemaVersion":1,"payload":{"status":"QUEUED"},"createdAt":"2026-07-16T01:00:00Z"}\n\n',
    ))
    streamController.enqueue(encoder.encode(
      `id: 2\nevent: PLANNING_REVIEW_REQUIRED\ndata: ${JSON.stringify({
        eventId: 2,
        taskId: '33333333-3333-3333-3333-333333333333',
        eventType: 'PLANNING_REVIEW_REQUIRED',
        schemaVersion: 1,
        payload: {
          status: 'WAITING_USER',
          provider: 'DEMO',
          candidateItinerary: reviewCandidate,
          feasibilityReport: reviewReport,
        },
        createdAt: '2026-07-16T01:00:01Z',
      })}\n\n`,
    ))
    streamController.close()

    // Waiting-user review panel appears with the authoritative report.
    expect(await screen.findByText('方案需要调整')).toBeTruthy()
    // B15: the FAIL surfaces as a Chinese issue summary; no rule wall.
    expect(screen.getByText('需要调整（1）')).toBeTruthy()
    expect(screen.getByText('部分地点的营业时间与行程安排冲突')).toBeTruthy()
    // Candidate renders as preview, distinct from the formal itinerary.
    expect(screen.getAllByText('预览方案').length).toBeGreaterThan(0)
    expect(screen.getByText('候选活动')).toBeTruthy()
    // The formal itinerary heading is still the existing one, not replaced.
    expect(screen.getByRole('heading', { name: '行程时间轴' })).toBeTruthy()
  })

  test('B13-I WAITING_USER without a formal itinerary still shows the weather window', async () => {
    const encoder = new TextEncoder()
    let streamController!: ReadableStreamDefaultController<Uint8Array>
    const eventStream = new ReadableStream<Uint8Array>({
      start(controller) { streamController = controller },
    })
    const reviewCandidate = {
      title: '候选行程',
      days: [{
        date: '2026-07-18',
        dayType: null,
        activities: [{
          activityId: '3d76fb9e-362e-4b28-8a9e-18e8ac7050ae',
          title: '候选活动',
          startTime: '2026-07-18T01:00:00Z',
          endTime: '2026-07-18T02:00:00Z',
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
        return { ok: true, status: 200, body: eventStream } as Response
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/versions`)) return response([])
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/shares`)) return response([])
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) {
        return response({ code: 'ITINERARY_NOT_FOUND', message: '尚未生成行程' }, 404)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    const scrollSpy = vi.fn()
    Element.prototype.scrollIntoView = scrollSpy

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '广州周末四日' })
    await fireEvent.click(await waitFor(() => screen.getByRole('button', { name: '打开 广州周末四日' })))
    await screen.findByRole('heading', { name: '结构化约束' })
    // No formal itinerary yet, so the action is "开始规划".
    await fireEvent.click(screen.getByRole('button', { name: '开始规划' }))
    streamController.enqueue(encoder.encode(
      'id: 1\nevent: PLANNING_QUEUED\ndata: {"eventId":1,"taskId":"33333333-3333-3333-3333-333333333333","eventType":"PLANNING_QUEUED","schemaVersion":1,"payload":{"status":"QUEUED"},"createdAt":"2026-07-16T01:00:00Z"}\n\n',
    ))
    streamController.enqueue(encoder.encode(
      `id: 2\nevent: PLANNING_REVIEW_REQUIRED\ndata: ${JSON.stringify({
        eventId: 2,
        taskId: '33333333-3333-3333-3333-333333333333',
        eventType: 'PLANNING_REVIEW_REQUIRED',
        schemaVersion: 1,
        payload: {
          status: 'WAITING_USER',
          provider: 'DEMO',
          candidateItinerary: reviewCandidate,
          feasibilityReport: {
            schemaVersion: 1,
            reportId: 'c9c467cc-65c4-8ff1-e175-4af42f2ed545',
            validatorVersion: 'hard-validator-v4',
            itineraryFingerprint: 'b'.repeat(64),
            status: 'NEEDS_REPAIR',
            validatedAt: '2026-07-16T01:00:00Z',
            requiredRuleIds: ['MEAL_WINDOW'],
            missingRequiredRuleIds: [],
            summary: { totalCount: 1, passCount: 0, failCount: 1, unknownCount: 0, notApplicableCount: 0, missingRequiredCount: 0 },
            ruleResults: [{
              ruleId: 'MEAL_WINDOW',
              ruleVersion: 'hard-rule-v1',
              outcome: 'FAIL',
              reasonCode: 'MEAL_PLACEMENT_MISSING',
              message: '午餐窗口缺少安排',
              affectedDates: ['2026-07-18'],
              affectedEntityRefs: [],
              evidenceRefs: [],
              repairable: true,
            }],
            repairAttempts: [],
          },
        },
        createdAt: '2026-07-16T01:00:01Z',
      })}\n\n`,
    ))
    streamController.close()

    // The weather window must be visible in waiting_user WITHOUT any
    // formal itinerary, above the review panel.
    expect(await screen.findByText('方案需要调整')).toBeTruthy()
    const weatherRegion = screen.getByRole('region', { name: '行程天气' })
    expect(weatherRegion).toBeTruthy()
    // No formal itinerary → no itinerary heading, and no crash.
    expect(screen.queryByRole('heading', { name: '行程时间轴' })).toBeNull()
    expect(screen.getByText('尚未生成行程')).toBeTruthy()
    // The city-intelligence fetch failed (unmocked route) — a weather
    // source failure must NOT hide the component; safe empty states and the
    // sync action are shown instead (B13-I §5: Provider 失败不得隐藏组件).
    // A weather source failure must NOT hide the component: the bar still
    // renders one of the safe empty states (待同步 / 历史天气尚未同步 /
    // 预报未开放 — depending on the dates vs. today) plus the sync action.
    const safeEmptyStates = screen.getAllByText(/待同步|历史天气尚未同步|预报未开放/)
    expect(safeEmptyStates.length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: '同步天气' })).toBeTruthy()

    // Clicking a weather date selects it and locates the candidate review.
    await fireEvent.click(screen.getByRole('button', { name: '选择 2026-07-18 天气' }))
    expect(scrollSpy).toHaveBeenCalled()
    // The matching candidate day is highlighted (B13-I §4: 高亮候选日期).
    const candidateDay = document.getElementById('candidate-day-2026-07-18')
    expect(candidateDay).toBeTruthy()
    expect(candidateDay!.className).toContain('border-primary-400')
    await fireEvent.click(screen.getByRole('button', { name: '查看全部行程' }))
    expect(screen.getByRole('button', { name: '选择 2026-07-18 天气' }).getAttribute('aria-pressed')).toBe('false')
  })

  test('B13_FIX.1 R5 WAITING_USER weather click never selects the old formal activity', async () => {
    const encoder = new TextEncoder()
    let streamController!: ReadableStreamDefaultController<Uint8Array>
    const eventStream = new ReadableStream<Uint8Array>({
      start(controller) { streamController = controller },
    })
    const reviewCandidate = {
      title: '候选行程',
      days: [{
        date: '2026-07-18',
        dayType: null,
        activities: [{
          activityId: '3d76fb9e-362e-4b28-8a9e-18e8ac7050ae',
          title: '候选活动',
          startTime: '2026-07-18T01:00:00Z',
          endTime: '2026-07-18T02:00:00Z',
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
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/versions`)) return response([])
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/shares`)) return response([])
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) return response(itineraryResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/guide-imports`) && init?.method === 'GET') return response([])
      if (url.endsWith(`/api/trips/${tripResponse.id}/planning-tasks/latest`)) {
        return response({
          taskId: '33333333-3333-3333-3333-333333333333',
          tripId: tripResponse.id,
          taskType: 'CREATE',
          status: 'WAITING_USER',
          baselineTripVersion: 0,
          eventStreamUrl: '/api/planning-tasks/33333333-3333-3333-3333-333333333333/events',
          feasibilityReport: {
            schemaVersion: 1,
            reportId: 'c9c467cc-65c4-8ff1-e175-4af42f2ed545',
            validatorVersion: 'hard-validator-v4',
            itineraryFingerprint: 'b'.repeat(64),
            status: 'NEEDS_REPAIR',
            validatedAt: '2026-07-18T00:00:00Z',
            requiredRuleIds: ['MEAL_WINDOW'],
            missingRequiredRuleIds: [],
            summary: { totalCount: 1, passCount: 0, failCount: 1, unknownCount: 0, notApplicableCount: 0, missingRequiredCount: 0 },
            ruleResults: [{ ruleId: 'MEAL_WINDOW', ruleVersion: 'hard-rule-v1', outcome: 'FAIL', reasonCode: 'MEAL_PLACEMENT_MISSING', message: '午餐窗口缺少安排', affectedDates: ['2026-07-18'], affectedEntityRefs: [], evidenceRefs: [], repairable: true }],
            repairAttempts: [],
          },
          candidateItinerary: reviewCandidate,
          createdAt: '2026-07-16T01:00:00Z',
          updatedAt: '2026-07-16T01:01:00Z',
        })
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    const scrollSpy = vi.fn()
    Element.prototype.scrollIntoView = scrollSpy

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '广州周末四日' })
    await fireEvent.click(await waitFor(() => screen.getByRole('button', { name: '打开 广州周末四日' })))
    await screen.findByRole('heading', { name: '方案需要调整' })

    // The formal itinerary is present with a same-day activity.
    const formalActivity = document.getElementById('activity-66666666-6666-6666-6666-666666666666')
    expect(formalActivity).toBeTruthy()

    await fireEvent.click(screen.getByRole('button', { name: '选择 2026-07-18 天气' }))

    // The candidate day is highlighted.
    const candidateDay = document.getElementById('candidate-day-2026-07-18')
    expect(candidateDay!.className).toContain('border-primary-400')
    // The formal activity must NOT carry the selected class/z-index.
    expect(formalActivity!.className).not.toContain('z-10')
    expect(formalActivity!.className).not.toContain('ring-primary-400')
    // No overview marker is selected.
    const selectedMarkers = document.querySelectorAll('.overview-marker.is-selected')
    expect(selectedMarkers.length).toBe(0)

    // "查看全部行程" clears both the candidate and the formal selection.
    const showAll = await waitFor(() => screen.getByRole('button', { name: '查看全部行程' }))
    await fireEvent.click(showAll)
    expect(candidateDay!.className).not.toContain('border-primary-400')
  })

  test('B13-I queued planning without an itinerary still shows the weather window', async () => {
    const encoder = new TextEncoder()
    let streamController!: ReadableStreamDefaultController<Uint8Array>
    const eventStream = new ReadableStream<Uint8Array>({
      start(controller) { streamController = controller },
    })
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/planning-tasks`) && init?.method === 'POST') {
        return response({
          taskId: '44444444-4444-4444-4444-444444444444',
          tripId: tripResponse.id,
          taskType: 'CREATE',
          status: 'QUEUED',
          baselineTripVersion: 0,
          eventStreamUrl: '/api/planning-tasks/44444444-4444-4444-4444-444444444444/events',
          createdAt: '2026-07-16T01:00:00Z',
          updatedAt: '2026-07-16T01:00:00Z',
        }, 202)
      }
      if (url.endsWith('/api/planning-tasks/44444444-4444-4444-4444-444444444444/events')) {
        return { ok: true, status: 200, body: eventStream } as Response
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/versions`)) return response([])
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/shares`)) return response([])
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) {
        return response({ code: 'ITINERARY_NOT_FOUND', message: '尚未生成行程' }, 404)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '广州周末四日' })
    await fireEvent.click(await waitFor(() => screen.getByRole('button', { name: '打开 广州周末四日' })))
    await screen.findByRole('heading', { name: '结构化约束' })
    await fireEvent.click(screen.getByRole('button', { name: '开始规划' }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '规划中' })).toHaveProperty('disabled', true)
    })
    streamController.enqueue(encoder.encode(
      'id: 1\nevent: PLANNING_QUEUED\ndata: {"eventId":1,"taskId":"44444444-4444-4444-4444-444444444444","eventType":"PLANNING_QUEUED","schemaVersion":1,"payload":{"status":"QUEUED"},"createdAt":"2026-07-16T01:00:00Z"}\n\n',
    ))
    streamController.close()

    // While planning (queued), before any itinerary exists, the weather
    // window is still rendered — it is not bound to the formal itinerary.
    expect(await screen.findByText('正在生成行程')).toBeTruthy()
    expect(screen.getByRole('region', { name: '行程天气' })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: '行程时间轴' })).toBeNull()
    // A weather date can still be selected without any schedule; no error.
    await fireEvent.click(screen.getByRole('button', { name: '选择 2026-07-19 天气' }))
    expect(screen.getByRole('button', { name: '选择 2026-07-19 天气' }).getAttribute('aria-pressed')).toBe('true')
  })

  test('B13-I failed planning without an itinerary still shows the weather window', async () => {
    const encoder = new TextEncoder()
    let streamController!: ReadableStreamDefaultController<Uint8Array>
    const eventStream = new ReadableStream<Uint8Array>({
      start(controller) { streamController = controller },
    })
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/planning-tasks`) && init?.method === 'POST') {
        return response({
          taskId: '55555555-5555-5555-5555-555555555555',
          tripId: tripResponse.id,
          taskType: 'CREATE',
          status: 'QUEUED',
          baselineTripVersion: 0,
          eventStreamUrl: '/api/planning-tasks/55555555-5555-5555-5555-555555555555/events',
          createdAt: '2026-07-16T01:00:00Z',
          updatedAt: '2026-07-16T01:00:00Z',
        }, 202)
      }
      if (url.endsWith('/api/planning-tasks/55555555-5555-5555-5555-555555555555/events')) {
        return { ok: true, status: 200, body: eventStream } as Response
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/versions`)) return response([])
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/shares`)) return response([])
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) {
        return response({ code: 'ITINERARY_NOT_FOUND', message: '尚未生成行程' }, 404)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '广州周末四日' })
    await fireEvent.click(await waitFor(() => screen.getByRole('button', { name: '打开 广州周末四日' })))
    await screen.findByRole('heading', { name: '结构化约束' })
    await fireEvent.click(screen.getByRole('button', { name: '开始规划' }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '规划中' })).toHaveProperty('disabled', true)
    })
    streamController.enqueue(encoder.encode(
      'id: 1\nevent: PLANNING_QUEUED\ndata: {"eventId":1,"taskId":"55555555-5555-5555-5555-555555555555","eventType":"PLANNING_QUEUED","schemaVersion":1,"payload":{"status":"QUEUED"},"createdAt":"2026-07-16T01:00:00Z"}\n\n',
    ))
    streamController.enqueue(encoder.encode(
      `id: 2\nevent: PLANNING_FAILED\ndata: ${JSON.stringify({
        eventId: 2,
        taskId: '55555555-5555-5555-5555-555555555555',
        eventType: 'PLANNING_FAILED',
        schemaVersion: 1,
        payload: { status: 'FAILED', errorCode: 'PLANNING_PROVIDER_FAILED', errorMessage: '规划服务暂不可用' },
        createdAt: '2026-07-16T01:00:01Z',
      })}\n\n`,
    ))
    streamController.close()

    // Failed state still keeps the weather window; only the plan failed.
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByRole('region', { name: '行程天气' })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: '行程时间轴' })).toBeNull()
  })

  test('B13-I cancelled planning without an itinerary still shows the weather window', async () => {
    const encoder = new TextEncoder()
    let streamController!: ReadableStreamDefaultController<Uint8Array>
    const eventStream = new ReadableStream<Uint8Array>({
      start(controller) { streamController = controller },
    })
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/planning-tasks`) && init?.method === 'POST') {
        return response({
          taskId: '66666666-6666-6666-6666-666666666666',
          tripId: tripResponse.id,
          taskType: 'CREATE',
          status: 'QUEUED',
          baselineTripVersion: 0,
          eventStreamUrl: '/api/planning-tasks/66666666-6666-6666-6666-666666666666/events',
          createdAt: '2026-07-16T01:00:00Z',
          updatedAt: '2026-07-16T01:00:00Z',
        }, 202)
      }
      if (url.endsWith('/api/planning-tasks/66666666-6666-6666-6666-666666666666/events')) {
        return { ok: true, status: 200, body: eventStream } as Response
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/versions`)) return response([])
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/shares`)) return response([])
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) {
        return response({ code: 'ITINERARY_NOT_FOUND', message: '尚未生成行程' }, 404)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '广州周末四日' })
    await fireEvent.click(await waitFor(() => screen.getByRole('button', { name: '打开 广州周末四日' })))
    await screen.findByRole('heading', { name: '结构化约束' })
    await fireEvent.click(screen.getByRole('button', { name: '开始规划' }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '规划中' })).toHaveProperty('disabled', true)
    })
    streamController.enqueue(encoder.encode(
      'id: 1\nevent: PLANNING_QUEUED\ndata: {"eventId":1,"taskId":"66666666-6666-6666-6666-666666666666","eventType":"PLANNING_QUEUED","schemaVersion":1,"payload":{"status":"QUEUED"},"createdAt":"2026-07-16T01:00:00Z"}\n\n',
    ))
    streamController.enqueue(encoder.encode(
      `id: 2\nevent: PLANNING_CANCELLED\ndata: ${JSON.stringify({
        eventId: 2,
        taskId: '66666666-6666-6666-6666-666666666666',
        eventType: 'PLANNING_CANCELLED',
        schemaVersion: 1,
        payload: { status: 'CANCELLED' },
        createdAt: '2026-07-16T01:00:01Z',
      })}\n\n`,
    ))
    streamController.close()

    // Cancelled state still keeps the weather window.
    expect(await screen.findByText('规划已取消')).toBeTruthy()
    expect(screen.getByRole('region', { name: '行程天气' })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: '行程时间轴' })).toBeNull()
  })

  test('PLANNING_COMPLETED with VERIFIED report renders authoritative feasibility panel', async () => {
    const encoder = new TextEncoder()
    let streamController!: ReadableStreamDefaultController<Uint8Array>
    const eventStream = new ReadableStream<Uint8Array>({
      start(controller) { streamController = controller },
    })
    const verifiedReport = {
      schemaVersion: 1,
      reportId: 'c9c467cc-65c4-8ff1-e175-4af42f2ed545',
      validatorVersion: 'hard-validator-v4',
      itineraryFingerprint: 'a'.repeat(64),
      status: 'VERIFIED',
      validatedAt: '2026-07-16T01:00:00Z',
      requiredRuleIds: ['OPENING_HOURS'],
      missingRequiredRuleIds: [],
      summary: { totalCount: 1, passCount: 1, failCount: 0, unknownCount: 0, notApplicableCount: 0, missingRequiredCount: 0 },
      ruleResults: [{
        ruleId: 'OPENING_HOURS',
        ruleVersion: 'hard-rule-v1',
        outcome: 'PASS',
        reasonCode: 'OPENING_HOURS_VERIFIED',
        message: '营业时间内开放',
        affectedDates: ['2026-07-18'],
        affectedEntityRefs: [],
        evidenceRefs: [],
        repairable: false,
      }],
      repairAttempts: [],
    }
    let itineraryLoads = 0
    let versionLoads = 0
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
        return { ok: true, status: 200, body: eventStream } as Response
      }
      if (url.endsWith(`/api/planning-tasks/${planningTaskResponse.taskId}`)) {
        return response({ ...planningTaskResponse, status: 'SUCCEEDED', evaluation: planningEvaluation, feasibilityReport: verifiedReport })
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/versions`)) {
        versionLoads += 1
        return response(versionLoads === 1 ? [] : [{
          ...currentPlanningVersion,
          feasibility: {
            reportId: verifiedReport.reportId,
            schemaVersion: 1,
            validatorVersion: 'hard-validator-v4',
            status: 'VERIFIED',
            itineraryFingerprint: 'a'.repeat(64),
            validatedAt: '2026-07-16T01:00:00Z',
          },
        }])
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/shares`)) return response([])
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
    await fireEvent.click(await waitFor(() => screen.getByRole('button', { name: '打开 广州周末四日' })))
    await screen.findByRole('heading', { name: '结构化约束' })
    await fireEvent.click(screen.getByRole('button', { name: '开始规划' }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '规划中' })).toHaveProperty('disabled', true)
    })
    streamController.enqueue(encoder.encode(
      'id: 1\nevent: PLANNING_QUEUED\ndata: {"eventId":1,"taskId":"33333333-3333-3333-3333-333333333333","eventType":"PLANNING_QUEUED","schemaVersion":1,"payload":{"status":"QUEUED"},"createdAt":"2026-07-16T01:00:00Z"}\n\n',
    ))
    streamController.enqueue(encoder.encode(
      `id: 2\nevent: PLANNING_COMPLETED\ndata: ${JSON.stringify({
        eventId: 2,
        taskId: '33333333-3333-3333-3333-333333333333',
        eventType: 'PLANNING_COMPLETED',
        schemaVersion: 1,
        payload: {
          status: 'SUCCEEDED',
          provider: 'DEMO',
          evaluation: planningEvaluation,
          feasibilityReport: verifiedReport,
        },
        createdAt: '2026-07-16T01:00:01Z',
      })}\n\n`,
    ))
    streamController.close()

    expect(await screen.findByRole('heading', { name: '广州 Demo 行程' })).toBeTruthy()
    // Authoritative feasibility panel with VERIFIED status.
    expect((await screen.findAllByText('已保存')).length).toBeGreaterThan(0)
    expect(screen.getByText('行程已验证并保存')).toBeTruthy()
    // Evaluation still renders as experience quality.
    expect(await screen.findByText('91/100')).toBeTruthy()
  })

  test('fails closed when the SSE review event carries a VERIFIED report', async () => {
    const encoder = new TextEncoder()
    let streamController!: ReadableStreamDefaultController<Uint8Array>
    const eventStream = new ReadableStream<Uint8Array>({
      start(controller) { streamController = controller },
    })
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
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/planning-tasks`) && init?.method === 'POST') {
        return response({
          taskId: planningTaskResponse.taskId,
          tripId: tripResponse.id,
          taskType: 'CREATE',
          status: 'QUEUED',
          baselineTripVersion: 0,
          eventStreamUrl: planningTaskResponse.eventStreamUrl,
          createdAt: '2026-07-16T01:00:00Z',
          updatedAt: '2026-07-16T01:00:00Z',
        }, 202)
      }
      if (url.endsWith(planningTaskResponse.eventStreamUrl)) {
        return { ok: true, status: 200, body: eventStream } as Response
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/shares`)) return response([])
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/versions`)) {
        return response([{ ...currentPlanningVersion, feasibility: null }])
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) {
        return response(itineraryResponse)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/planning-tasks/latest`)) {
        return response({ code: 'PLANNING_TASK_NOT_FOUND', message: 'Planning task was not found' }, 404)
      }
      if (url.endsWith(`/api/planning-tasks/${planningTaskResponse.taskId}`)) {
        return response({ ...planningTaskResponse, status: 'QUEUED' })
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '广州周末四日' })
    await fireEvent.click(await waitFor(() => screen.getByRole('button', { name: '打开 广州周末四日' })))
    await screen.findByRole('heading', { name: '结构化约束' })
    await fireEvent.click(screen.getByRole('button', { name: '重新规划' }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '规划中' })).toHaveProperty('disabled', true)
    })
    streamController.enqueue(encoder.encode(
      'id: 1\nevent: PLANNING_QUEUED\ndata: {"eventId":1,"taskId":"33333333-3333-3333-3333-333333333333","eventType":"PLANNING_QUEUED","schemaVersion":1,"payload":{"status":"QUEUED"},"createdAt":"2026-07-16T01:00:00Z"}\n\n',
    ))
    streamController.enqueue(encoder.encode(
      `id: 2\nevent: PLANNING_REVIEW_REQUIRED\ndata: ${JSON.stringify({
        eventId: 2,
        taskId: planningTaskResponse.taskId,
        eventType: 'PLANNING_REVIEW_REQUIRED',
        schemaVersion: 1,
        payload: {
          status: 'WAITING_USER',
          provider: 'DEMO',
          candidateItinerary: reviewCandidate,
          feasibilityReport: verifiedFeasibilityReport,
        },
        createdAt: '2026-07-16T01:00:01Z',
      })}\n\n`,
    ))
    streamController.close()

    // The illegal WAITING_USER + VERIFIED combination must fail closed.
    expect(await screen.findByText('规划结果无法安全读取，请重新规划')).toBeTruthy()
    expect(screen.queryByText('方案还需要完善')).toBeNull()
    expect(screen.queryByText('已保存')).toBeNull()
    expect(screen.queryByText('方案需要调整')).toBeNull()
  })

  test('clears the previous outcome when a new planning task starts', async () => {
    let streamController!: ReadableStreamDefaultController<Uint8Array>
    const eventStream = new ReadableStream<Uint8Array>({
      start(controller) { streamController = controller },
    })
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/planning-tasks`) && init?.method === 'POST') {
        return response({
          taskId: planningTaskResponse.taskId,
          tripId: tripResponse.id,
          taskType: 'CREATE',
          status: 'QUEUED',
          baselineTripVersion: 0,
          eventStreamUrl: planningTaskResponse.eventStreamUrl,
          createdAt: '2026-07-16T01:00:00Z',
          updatedAt: '2026-07-16T01:00:00Z',
        }, 202)
      }
      if (url.endsWith(planningTaskResponse.eventStreamUrl)) {
        return { ok: true, status: 200, body: eventStream } as Response
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/shares`)) return response([])
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/versions`)) {
        return response([{ ...currentPlanningVersion, feasibility: null }])
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) {
        return response(itineraryResponse)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/planning-tasks/latest`)) {
        return response({ code: 'PLANNING_TASK_NOT_FOUND', message: 'Planning task was not found' }, 404)
      }
      if (url.endsWith(`/api/planning-tasks/${planningTaskResponse.taskId}`)) {
        return response({ ...planningTaskResponse, status: 'SUCCEEDED', evaluation: planningEvaluation, feasibilityReport: verifiedFeasibilityReport })
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '广州周末四日' })
    await fireEvent.click(await waitFor(() => screen.getByRole('button', { name: '打开 广州周末四日' })))
    // Page load hydrates the current version's SUCCEEDED task outcome.
    expect(await screen.findByText('行程已验证并保存')).toBeTruthy()
    expect(await screen.findByText('91/100')).toBeTruthy()

    await fireEvent.click(screen.getByRole('button', { name: '重新规划' }))

    // The old authoritative panel must disappear while the new task is queued.
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '规划中' })).toHaveProperty('disabled', true)
    })
    expect(screen.queryByText('行程已验证并保存')).toBeNull()
    expect(screen.queryByText('91/100')).toBeNull()
  })

  test('clears the outcome when a planning task is cancelled', async () => {
    const encoder = new TextEncoder()
    let streamController!: ReadableStreamDefaultController<Uint8Array>
    const eventStream = new ReadableStream<Uint8Array>({
      start(controller) { streamController = controller },
    })
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/planning-tasks`) && init?.method === 'POST') {
        return response({
          taskId: planningTaskResponse.taskId,
          tripId: tripResponse.id,
          taskType: 'CREATE',
          status: 'QUEUED',
          baselineTripVersion: 0,
          eventStreamUrl: planningTaskResponse.eventStreamUrl,
          createdAt: '2026-07-16T01:00:00Z',
          updatedAt: '2026-07-16T01:00:00Z',
        }, 202)
      }
      if (url.endsWith(planningTaskResponse.eventStreamUrl)) {
        return { ok: true, status: 200, body: eventStream } as Response
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/shares`)) return response([])
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/versions`)) {
        return response([{ ...currentPlanningVersion, feasibility: null }])
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) {
        return response(itineraryResponse)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/planning-tasks/latest`)) {
        return response({ code: 'PLANNING_TASK_NOT_FOUND', message: 'Planning task was not found' }, 404)
      }
      if (url.endsWith(`/api/planning-tasks/${planningTaskResponse.taskId}`)) {
        return response({ ...planningTaskResponse, status: 'SUCCEEDED', evaluation: planningEvaluation, feasibilityReport: verifiedFeasibilityReport })
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '广州周末四日' })
    await fireEvent.click(await waitFor(() => screen.getByRole('button', { name: '打开 广州周末四日' })))
    expect(await screen.findByText('行程已验证并保存')).toBeTruthy()

    await fireEvent.click(screen.getByRole('button', { name: '重新规划' }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '规划中' })).toHaveProperty('disabled', true)
    })
    streamController.enqueue(encoder.encode(
      `id: 1\nevent: PLANNING_CANCELLED\ndata: ${JSON.stringify({
        eventId: 1,
        taskId: planningTaskResponse.taskId,
        eventType: 'PLANNING_CANCELLED',
        schemaVersion: 1,
        payload: { status: 'CANCELLED' },
        createdAt: '2026-07-16T01:00:01Z',
      })}\n\n`,
    ))
    streamController.close()

    expect(await screen.findByText('规划已取消')).toBeTruthy()
    expect(screen.queryByText('行程已验证并保存')).toBeNull()
    expect(screen.queryByText('91/100')).toBeNull()
  })

  // ── B13-A: unified create entry ─────────────────────────────────────────

  const emptyListFetch = () => vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = urlOf(input)
    if (url.endsWith('/api/auth/login')) return response(authResponse)
    if (url.endsWith('/api/auth/logout')) return response(undefined, 204)
    if (url.endsWith('/api/trips')) return response([])
    throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
  })

  test('B13-A shows no quick-start templates and no natural-language entry', async () => {
    const fetchMock = emptyListFetch()
    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '我的旅行' })
    await screen.findByText('还没有旅行')

    expect(screen.queryByText('快速开始')).toBeNull()
    expect(screen.queryByText('广州 City Walk')).toBeNull()
    expect(screen.queryByText('长沙美食之旅')).toBeNull()
    expect(screen.queryByText('杭州周末游')).toBeNull()
    expect(screen.queryByText('用一句话描述旅行计划')).toBeNull()
    expect(screen.queryByRole('button', { name: /解析/ })).toBeNull()
  })

  test('B13-A offers a single create entry even on the empty state', async () => {
    const fetchMock = emptyListFetch()
    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '我的旅行' })
    await screen.findByText('还没有旅行')

    expect(screen.getAllByRole('button', { name: '创建旅行' })).toHaveLength(1)
    expect(screen.queryByRole('button', { name: '创建第一条旅行' })).toBeNull()
  })

  test('B13-A opens the create dialog with an empty destination cascade', async () => {
    const fetchMock = emptyListFetch()
    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '我的旅行' })
    await fireEvent.click(screen.getByRole('button', { name: '创建旅行' }))

    const province = await screen.findByLabelText('省 / 直辖市') as HTMLSelectElement
    expect(province.value).toBe('')
    expect(screen.queryByLabelText('城市')).toBeNull()
  })

  test('B13-A does not keep a stale draft when the dialog is reopened', async () => {
    const fetchMock = emptyListFetch()
    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '我的旅行' })
    await fireEvent.click(screen.getByRole('button', { name: '创建旅行' }))
    await fireEvent.update(screen.getByLabelText('旅行名称'), '临时草稿')
    await fireEvent.click(screen.getByRole('button', { name: '取消' }))
    await fireEvent.click(screen.getByRole('button', { name: '创建旅行' }))

    expect((screen.getByLabelText('旅行名称') as HTMLInputElement).value).toBe('')
    expect((screen.getByLabelText('省 / 直辖市') as HTMLSelectElement).value).toBe('')
    expect(screen.queryByLabelText('城市')).toBeNull()
  })

  // ── B13-B: structured province → city → district destination ────────────

  test('B13-B submits 广东省—广州市—天河区 with structured region codes', async () => {
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
    await selectDestinationCity('广东省', '广州', '天河区')
    await fillBoundaries('2026-07-18T09:00', '2026-07-21T18:00')
    await fireEvent.click(screen.getByRole('button', { name: '保存旅行' }))

    await waitFor(() => expect(submittedBody).toBeDefined())
    expect((submittedBody as { region: unknown }).region).toEqual({
      provinceCode: '440000',
      cityCode: '440100',
      districtCodes: ['440106'],
      provinceName: '广东省',
      cityName: '广州',
      districtNames: ['天河区'],
      datasetVersion: '2023-06-30',
    })
    expect((submittedBody as { destination: string }).destination).toBe('广州')
  })

  test('B13-B submits 广东省—江门市—全市 without district codes', async () => {
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
    await selectDestinationCity('广东省', '江门')
    await fillBoundaries('2026-07-18T09:00', '2026-07-21T18:00')
    await fireEvent.click(screen.getByRole('button', { name: '保存旅行' }))

    await waitFor(() => expect(submittedBody).toBeDefined())
    expect((submittedBody as { region: unknown }).region).toEqual({
      provinceCode: '440000',
      cityCode: '440700',
      districtCodes: [],
      provinceName: '广东省',
      cityName: '江门',
      districtNames: ['全市'],
      datasetVersion: '2023-06-30',
    })
  })

  test('B13-B clears the district selection when the city changes', async () => {
    const fetchMock = emptyListFetch()
    await signIn(fetchMock)
    await screen.findByRole('heading', { name: '我的旅行' })
    await fireEvent.click(screen.getByRole('button', { name: '创建旅行' }))
    await selectDestinationCity('广东省', '广州', '天河区')
    expect(screen.getByRole('button', { name: '天河区' }).className).toContain('border-primary-300')

    await fireEvent.update(screen.getByLabelText('城市'), '江门')
    expect(screen.queryByRole('button', { name: '天河区' })).toBeNull()
    expect(screen.getByText(/目的地：广东省 江门/)).toBeTruthy()
  })

  // ── B13-C: optional title with deterministic default and rename ──────────

  test('B13-C omits a blank title so the server generates the deterministic default', async () => {
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
    await selectDestinationCity('广东省', '广州')
    await fillBoundaries('2026-08-20T09:00', '2026-08-21T18:00')

    expect(screen.getByText(/预览：2026年08月20日—08月21日 广州市旅行规划/)).toBeTruthy()

    await fireEvent.click(screen.getByRole('button', { name: '保存旅行' }))
    await waitFor(() => expect(submittedBody).toBeDefined())
    expect(submittedBody).not.toHaveProperty('title')
    expect((submittedBody as { arrivalAt: string }).arrivalAt).toBe('2026-08-20T09:00:00+08:00')
  })

  test('B13-C renames a trip through the version-aware metadata endpoint', async () => {
    let renameBody: unknown
    const renamedTrip = { ...tripResponse, title: '国庆广州行', version: 1 }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/metadata`) && init?.method === 'PUT') {
        renameBody = JSON.parse(String(init.body))
        return response(renamedTrip)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/planning-tasks/latest`)) {
        return response({ code: 'PLANNING_TASK_NOT_FOUND', message: 'Planning task was not found' }, 404)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/versions`)) return response([])
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) {
        return response({ code: 'ITINERARY_NOT_FOUND', message: 'Not planned' }, 404)
      }
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))
    await screen.findByText('尚未生成行程')
    for (const internalLabel of ['Trip', 'Constraints', 'Live Guide Intelligence']) {
      expect(screen.queryByText(internalLabel)).toBeNull()
    }

    await fireEvent.click(screen.getByRole('button', { name: '修改旅行名称' }))
    await fireEvent.update(screen.getByLabelText('旅行新名称'), '国庆广州行')
    await fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(renameBody).toEqual({ expectedVersion: 0, title: '国庆广州行' }))
    expect(await screen.findByRole('heading', { name: '国庆广州行' })).toBeTruthy()
  })

  test('B13-C clears a custom title to restore the server-generated title', async () => {
    let renameBody: unknown
    const automaticTitle = '2026年07月18日—07月21日 广州市旅行规划'
    const renamedTrip = { ...tripResponse, title: automaticTitle, version: 1 }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/metadata`) && init?.method === 'PUT') {
        renameBody = JSON.parse(String(init.body))
        return response(renamedTrip)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/planning-tasks/latest`)) {
        return response({ code: 'PLANNING_TASK_NOT_FOUND', message: 'Planning task was not found' }, 404)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/versions`)) return response([])
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) {
        return response({ code: 'ITINERARY_NOT_FOUND', message: 'Not planned' }, 404)
      }
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))
    await screen.findByText('尚未生成行程')

    await fireEvent.click(screen.getByRole('button', { name: '修改旅行名称' }))
    await fireEvent.update(screen.getByLabelText('旅行新名称'), '')
    await fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(renameBody).toEqual({ expectedVersion: 0, title: '' }))
    expect(await screen.findByRole('heading', { name: automaticTitle })).toBeTruthy()
  })

  test('B13-C surfaces a 409 rename conflict without overwriting the title', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/metadata`) && init?.method === 'PUT') {
        return response({ code: 'TRIP_VERSION_CONFLICT', message: 'Trip was updated by another request; reload it before retrying' }, 409)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
      if (url.endsWith(`/api/trips/${tripResponse.id}/planning-tasks/latest`)) {
        return response({ code: 'PLANNING_TASK_NOT_FOUND', message: 'Planning task was not found' }, 404)
      }
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary/versions`)) return response([])
      if (url.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) {
        return response({ code: 'ITINERARY_NOT_FOUND', message: 'Not planned' }, 404)
      }
      if (url.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))
    await screen.findByText('尚未生成行程')

    await fireEvent.click(screen.getByRole('button', { name: '修改旅行名称' }))
    await fireEvent.update(screen.getByLabelText('旅行新名称'), '越权改名')
    await fireEvent.click(screen.getByRole('button', { name: '保存' }))

    expect(await screen.findByText('Trip was updated by another request; reload it before retrying')).toBeTruthy()
    expect((screen.getByLabelText('旅行新名称') as HTMLInputElement).value).toBe('越权改名')
  })
})
