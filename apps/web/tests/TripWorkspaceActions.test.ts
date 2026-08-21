import { cleanup, fireEvent, render as renderComponent, screen, waitFor } from '@testing-library/vue'
import type { Component } from 'vue'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import App from '../src/App.vue'
import { createTripPilotRouter } from '../src/app/router'

/**
 * B13_FIX R8 (P1-8): App-level coverage for the TripWorkspace handlers that
 * drive real user flows — trip search/archive/restore, itinerary sharing,
 * export, version diff/rollback, local replanning and candidate abandon.
 * These handlers were previously only reachable through the full shell.
 */

function render(component: Component, options?: Parameters<typeof renderComponent>[1]) {
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

const archivedTrip = {
  ...tripResponse,
  id: '99999999-9999-9999-9999-999999999999',
  title: '北京城市三日',
  destination: '北京',
  archivedAt: '2026-07-20T01:00:00Z',
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
  versionNumber: 1,
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

const olderVersion = {
  ...currentPlanningVersion,
  versionId: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  versionNumber: 0,
  title: '旧版本行程',
  current: false,
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

/** A minimal Response-like for the binary export endpoint. */
function exportResponse(): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => null },
    blob: async () => new Blob(['dummy']),
  } as unknown as Response
}

function completedEventStream(): Response {
  const event = `id: 2\nevent: PLANNING_COMPLETED\ndata: ${JSON.stringify({
    eventId: 2,
    taskId: planningTaskResponse.taskId,
    eventType: 'PLANNING_COMPLETED',
    schemaVersion: 1,
    payload: {
      status: 'SUCCEEDED',
      provider: 'DEMO',
      feasibilityReport: verifiedFeasibilityReport,
      evaluation: planningEvaluation,
    },
    createdAt: '2026-07-16T01:00:02Z',
  })}\n\n`
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(event))
      controller.close()
    },
  })
  return { ok: true, status: 200, body } as Response
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

function detailEndpoints(
  fetchMock: ReturnType<typeof vi.fn>,
  overrides: {
    versions?: unknown[]
    shares?: unknown[]
    itinerary?: unknown
    latestTask?: Response
  } = {},
  extra?: (input: RequestInfo | URL, init?: RequestInit) => Response | null,
) {
  const url = urlOf
  fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const requestUrl = url(input)
    if (extra) {
      const handled = await extra(input, init)
      if (handled) return handled
    }
    if (requestUrl.endsWith('/api/auth/login')) return response(authResponse)
    if (requestUrl.endsWith(`/api/trips/${tripResponse.id}/itinerary/versions`)) {
      return response(overrides.versions ?? [currentPlanningVersion])
    }
    if (requestUrl.endsWith(`/api/trips/${tripResponse.id}/itinerary/shares`)) {
      return response(overrides.shares ?? [])
    }
    if (requestUrl.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) {
      return response(overrides.itinerary ?? itineraryResponse)
    }
    if (requestUrl.endsWith(`/api/trips/${tripResponse.id}/planning-tasks/latest`)) {
      return overrides.latestTask ?? response({ code: 'TASK_NOT_FOUND' }, 404)
    }
    if (requestUrl.endsWith(`/api/planning-tasks/${planningTaskResponse.taskId}`)) {
      return response({ ...planningTaskResponse, status: 'SUCCEEDED', evaluation: planningEvaluation, feasibilityReport: verifiedFeasibilityReport })
    }
    if (requestUrl.endsWith(`/api/trips/${tripResponse.id}`)) return response(tripResponse)
    if (requestUrl.endsWith('/api/trips')) return response([tripResponse])
    throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${requestUrl}`)
  })
}

describe('TripWorkspace list handlers', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/trips')
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  test('searches the trip list by destination and toggles archived inclusion', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const requestUrl = urlOf(input)
      if (requestUrl.endsWith('/api/auth/login')) return response(authResponse)
      if (requestUrl.endsWith('/api/trips/search')) {
        const searchUrl = new URL(requestUrl, 'http://localhost')
        return response({
          items: searchUrl.searchParams.get('destination') ? [tripResponse] : [],
          page: 0,
          size: 100,
          totalElements: 1,
          totalPages: 1,
        })
      }
      if (requestUrl.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${requestUrl}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })

    await fireEvent.update(screen.getByLabelText('目的地搜索'), '广州')
    await fireEvent.click(screen.getByRole('button', { name: '搜索旅行' }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => {
        const requestUrl = urlOf(input as RequestInfo | URL)
        return requestUrl.includes('/api/trips/search') && requestUrl.includes('destination=%E5%B9%BF%E5%B7%9E')
      })).toBe(true)
    })

    // Toggling 包含已归档 switches the list to the search endpoint with the
    // archived flag set (B13_FIX R8 / P1-8).
    await fireEvent.click(screen.getByTestId('include-archived'))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => {
        const requestUrl = urlOf(input as RequestInfo | URL)
        return requestUrl.includes('/api/trips/search') && requestUrl.includes('includeArchived=true')
      })).toBe(true)
    })
  })

  test('archives and restores trips from the dashboard', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const requestUrl = urlOf(input)
      if (requestUrl.endsWith('/api/auth/login')) return response(authResponse)
      if (requestUrl.includes('/api/trips/search')) {
        return response({ items: [archivedTrip], page: 0, size: 100, totalElements: 1, totalPages: 1 })
      }
      if (requestUrl.endsWith(`/api/trips/${tripResponse.id}/archive`) && init?.method === 'POST') {
        return response(null, 204)
      }
      if (requestUrl.endsWith(`/api/trips/${archivedTrip.id}/restore`) && init?.method === 'POST') {
        return response(null, 204)
      }
      if (requestUrl.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${requestUrl}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })

    await fireEvent.click(screen.getByRole('button', { name: `归档 ${tripResponse.title}` }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => (
        urlOf(input as RequestInfo | URL).endsWith(`/api/trips/${tripResponse.id}/archive`)
      ))).toBe(true)
    })
    // The refresh reloads through the search endpoint (archived trips shown).
    await screen.findByRole('heading', { name: archivedTrip.title })

    await fireEvent.click(screen.getByRole('button', { name: `恢复 ${archivedTrip.title}` }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => (
        urlOf(input as RequestInfo | URL).endsWith(`/api/trips/${archivedTrip.id}/restore`)
      ))).toBe(true)
    })
  })
})

describe('TripWorkspace itinerary actions', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/trips')
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  test('creates and revokes a read-only share and exports the itinerary', async () => {
    const fetchMock = vi.fn()
    detailEndpoints(fetchMock, {}, async (input, init) => {
      const requestUrl = urlOf(input)
      if (requestUrl.endsWith(`/api/trips/${tripResponse.id}/itinerary/shares`) && init?.method === 'POST') {
        return response({
          id: 'share-1',
          versionId: itineraryResponse.versionId,
          expiresAt: null,
          revokedAt: null,
          createdAt: '2026-07-16T01:00:00Z',
          shareToken: 'share-token-1',
        }, 201)
      }
      if (requestUrl.endsWith('/itinerary/shares/share-1') && init?.method === 'DELETE') {
        return response(null, 204)
      }
      if (requestUrl.endsWith(`/api/trips/${tripResponse.id}/itinerary/exports/ics`)) {
        return exportResponse()
      }
      if (requestUrl.endsWith(`/api/trips/${tripResponse.id}/itinerary/exports/pdf`)) {
        return exportResponse()
      }
      return null
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))
    await screen.findByRole('heading', { name: itineraryResponse.title })

    // Export both formats (B13_FIX R8 / P1-8): handler must survive blob download.
    await fireEvent.click(screen.getByTestId('export-ics'))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => (
        urlOf(input as RequestInfo | URL).includes('/itinerary/exports/ics')
      ))).toBe(true)
    })
    await fireEvent.click(screen.getByTestId('export-pdf'))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => (
        urlOf(input as RequestInfo | URL).includes('/itinerary/exports/pdf')
      ))).toBe(true)
    })

    // Create a read-only share and copy the URL.
    await fireEvent.click(screen.getByTestId('create-itinerary-share'))
    expect(await screen.findByTestId('share-url')).toBeTruthy()
    expect(screen.getByTestId('share-url').textContent).toContain('/share/share-token-1')

    // Revoke it.
    await fireEvent.click(screen.getByTestId('revoke-share-share-1'))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => (
        urlOf(input as RequestInfo | URL).includes('/itinerary/shares/share-1')
      ))).toBe(true)
    })
  })

  test('compares an older version and rolls back to it after confirmation', async () => {
    const fetchMock = vi.fn()
    detailEndpoints(fetchMock, { versions: [currentPlanningVersion, olderVersion] }, async (input, init) => {
      const requestUrl = urlOf(input)
      if (requestUrl.includes('/itinerary/versions/diff')) {
        return response({
          fromVersionId: olderVersion.versionId,
          toVersionId: itineraryResponse.versionId,
          addedActivities: [],
          removedActivities: [],
          changedActivities: [],
          addedTransitLegs: [],
          removedTransitLegs: [],
          changedTransitLegs: [],
          addedFactImpacts: [],
          removedFactImpacts: [],
          changedFactImpacts: [],
          fromTotalCost: 700,
          toTotalCost: 860,
          budgetChange: 160,
        })
      }
      if (requestUrl.endsWith('/itinerary/rollbacks') && init?.method === 'POST') {
        return response({
          ...planningTaskResponse,
          taskType: 'ROLLBACK',
          eventStreamUrl: '/api/planning-tasks/33333333-3333-3333-3333-333333333333/events',
        }, 202)
      }
      if (requestUrl.endsWith('/api/planning-tasks/33333333-3333-3333-3333-333333333333/events')) {
        return completedEventStream()
      }
      return null
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))
    await screen.findByRole('heading', { name: itineraryResponse.title })

    await fireEvent.click(screen.getByRole('button', { name: `比较版本 0 与当前版本` }))
    expect(await screen.findByText('与当前版本的差异')).toBeTruthy()
    expect(screen.getByText(/预算变化 \+¥160/)).toBeTruthy()

    await fireEvent.click(screen.getByRole('button', { name: '回滚到版本 0' }))
    expect(screen.getByRole('alertdialog', { name: '确认版本回滚' })).toBeTruthy()
    await fireEvent.click(screen.getByRole('button', { name: '确认回滚到版本 0' }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => (
        urlOf(input as RequestInfo | URL).endsWith('/itinerary/rollbacks')
      ))).toBe(true)
    })
  })

  test('replans the current version locally when a transit gap exists', async () => {
    const gapItinerary = structuredClone(itineraryResponse)
    gapItinerary.days[0].transitLegs = []
    const fetchMock = vi.fn()
    detailEndpoints(fetchMock, { itinerary: gapItinerary }, async (input, init) => {
      const requestUrl = urlOf(input)
      if (requestUrl.endsWith('/itinerary/replans') && init?.method === 'POST') {
        const body = JSON.parse(String(init?.body))
        expect(body).toMatchObject({
          baseVersionId: itineraryResponse.versionId,
          dates: ['2026-07-18'],
        })
        return response({ ...planningTaskResponse, taskType: 'REPLAN' }, 202)
      }
      if (requestUrl.endsWith('/api/planning-tasks/33333333-3333-3333-3333-333333333333/events')) {
        return completedEventStream()
      }
      return null
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))
    await screen.findByRole('heading', { name: itineraryResponse.title })

    await fireEvent.click(screen.getByRole('button', { name: '刷新交通' }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => (
        urlOf(input as RequestInfo | URL).endsWith('/itinerary/replans')
      ))).toBe(true)
    })
    await screen.findByRole('heading', { name: itineraryResponse.title })
  })

  test('abandons a WAITING_USER candidate without touching the formal itinerary', async () => {
    const reviewReport = {
      ...verifiedFeasibilityReport,
      status: 'NEEDS_REPAIR',
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
    const latestTask = {
      ...planningTaskResponse,
      status: 'WAITING_USER',
      feasibilityReport: reviewReport,
      candidateItinerary: reviewCandidate,
    }
    const fetchMock = vi.fn()
    detailEndpoints(fetchMock, {
      latestTask: response(latestTask),
      shares: [],
    }, async (input, init) => {
      const requestUrl = urlOf(input)
      if (requestUrl.endsWith(`/api/planning-tasks/${planningTaskResponse.taskId}`) && init?.method === 'DELETE') {
        return response({ ...latestTask, status: 'CANCELLED' })
      }
      return null
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))

    // The review panel surfaces the candidate; the formal itinerary heading
    // must remain the formal one.
    expect((await screen.findAllByText('候选行程')).length).toBeGreaterThan(0)
    expect((await screen.findAllByText('广州 Demo 行程')).length).toBeGreaterThan(0)
    await fireEvent.click(screen.getByTestId('abandon-candidate'))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input, callInit]) => (
        urlOf(input as RequestInfo | URL).endsWith(`/api/planning-tasks/${planningTaskResponse.taskId}`)
        && callInit?.method === 'DELETE'
      ))).toBe(true)
    })
    expect(await screen.findByText('规划已取消')).toBeTruthy()
  })
})

describe('TripWorkspace failure paths', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/trips')
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  test('renders the not-found page for an unknown authenticated route', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const requestUrl = urlOf(input)
      if (requestUrl.endsWith('/api/auth/login')) return response(authResponse)
      if (requestUrl.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${requestUrl}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })

    window.history.pushState({}, '', '/no-such-page')
    window.dispatchEvent(new PopStateEvent('popstate'))
    expect(await screen.findByText('页面不存在')).toBeTruthy()
    await fireEvent.click(screen.getByRole('button', { name: '返回旅行列表' }))
    expect(await screen.findByRole('heading', { name: tripResponse.title })).toBeTruthy()
  })

  test('surfaces a trip-detail load failure without a generic crash', async () => {
    const fetchMock = vi.fn()
    detailEndpoints(fetchMock, {}, async (input) => {
      const requestUrl = urlOf(input)
      if (requestUrl.endsWith(`/api/trips/${tripResponse.id}`)) {
        return response({ code: 'INTERNAL', message: '数据库暂时不可用' }, 500)
      }
      return null
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('数据库暂时不可用')
  })

  test('surfaces an itinerary load failure without hiding the navigation', async () => {
    const fetchMock = vi.fn()
    detailEndpoints(fetchMock, {}, async (input) => {
      const requestUrl = urlOf(input)
      if (requestUrl.endsWith(`/api/trips/${tripResponse.id}/itinerary`)) {
        return response({ code: 'INTERNAL', message: '行程读取失败' }, 500)
      }
      return null
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))
    expect(await screen.findByText('行程读取失败')).toBeTruthy()
    expect(screen.getByRole('heading', { name: tripResponse.title, level: 1 })).toBeTruthy()
  })

  test('surfaces a version list failure on the detail page', async () => {
    const fetchMock = vi.fn()
    detailEndpoints(fetchMock, {}, async (input) => {
      const requestUrl = urlOf(input)
      if (requestUrl.endsWith(`/api/trips/${tripResponse.id}/itinerary/versions`)) {
        return response({ code: 'INTERNAL', message: '版本读取失败' }, 500)
      }
      return null
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))
    expect(await screen.findByText('版本读取失败')).toBeTruthy()
    expect(await screen.findByRole('heading', { name: itineraryResponse.title })).toBeTruthy()
  })

  test('tolerates a share-list failure and a guide-import failure on the detail page', async () => {
    const fetchMock = vi.fn()
    detailEndpoints(fetchMock, {}, async (input) => {
      const requestUrl = urlOf(input)
      if (requestUrl.endsWith(`/api/trips/${tripResponse.id}/itinerary/shares`)) {
        return response({ code: 'INTERNAL', message: '分享读取失败' }, 500)
      }
      if (requestUrl.endsWith(`/api/trips/${tripResponse.id}/guide-imports`)) {
        return response({ code: 'INTERNAL', message: '攻略读取失败' }, 500)
      }
      return null
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))
    // The formal itinerary still renders while secondary panels degrade.
    expect(await screen.findByRole('heading', { name: itineraryResponse.title })).toBeTruthy()
    expect(await screen.findByText('攻略读取失败')).toBeTruthy()
  })

  test('ignores malformed progress frames during an SSE planning stream', async () => {
    const encoder = new TextEncoder()
    let streamController!: ReadableStreamDefaultController<Uint8Array>
    const eventStream = new ReadableStream<Uint8Array>({
      start(controller) { streamController = controller },
    })
    const fetchMock = vi.fn()
    let eventsCallCount = 0
    detailEndpoints(fetchMock, {}, async (input, init) => {
      const requestUrl = urlOf(input)
      if (requestUrl.endsWith(`/api/trips/${tripResponse.id}/planning-tasks`) && init?.method === 'POST') {
        return response({ ...planningTaskResponse, taskType: 'CREATE' }, 202)
      }
      if (requestUrl.endsWith('/api/planning-tasks/33333333-3333-3333-3333-333333333333/events')) {
        // First call: deliver the malformed frames then close.  Reconnect
        // attempts get a fresh closed stream so the fail-closed
        // "connection interrupted" path is reached.
        eventsCallCount += 1
        if (eventsCallCount === 1) {
          return { ok: true, status: 200, body: eventStream } as Response
        }
        const closed = new ReadableStream<Uint8Array>({
          start(controller) { controller.close() },
        })
        return { ok: true, status: 200, body: closed } as Response
      }
      return null
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))
    await screen.findByRole('heading', { name: itineraryResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: '重新规划' }))
    await screen.findByRole('status')

    // Invalid stage/sequence/progress/message combos must be ignored.
    streamController.enqueue(encoder.encode(
      `id: 1\nevent: PLANNING_PROGRESS\ndata: ${JSON.stringify({
        eventId: 1,
        taskId: planningTaskResponse.taskId,
        eventType: 'PLANNING_PROGRESS',
        schemaVersion: 2,
        payload: { status: 'RUNNING', stage: 'NOT_A_STAGE', sequence: 1, progress: 10, message: 'x' },
        createdAt: '2026-07-16T01:00:01Z',
      })}\n\n`,
    ))
    streamController.enqueue(encoder.encode(
      `id: 2\nevent: PLANNING_PROGRESS\ndata: ${JSON.stringify({
        eventId: 2,
        taskId: planningTaskResponse.taskId,
        eventType: 'PLANNING_PROGRESS',
        schemaVersion: 2,
        payload: { status: 'RUNNING', stage: 'POI_RECALLING', sequence: -1, progress: 50, message: 'x' },
        createdAt: '2026-07-16T01:00:02Z',
      })}\n\n`,
    ))
    streamController.enqueue(encoder.encode(
      `id: 3\nevent: PLANNING_PROGRESS\ndata: ${JSON.stringify({
        eventId: 3,
        taskId: planningTaskResponse.taskId,
        eventType: 'PLANNING_PROGRESS',
        schemaVersion: 1,
        payload: { status: 'RUNNING', stage: 'REPAIRING', sequence: 3, progress: 60, message: 'x' },
        createdAt: '2026-07-16T01:00:03Z',
      })}\n\n`,
    ))
    // A valid frame with a lower sequence than the current one is a replay.
    streamController.enqueue(encoder.encode(
      `id: 4\nevent: PLANNING_PROGRESS\ndata: ${JSON.stringify({
        eventId: 4,
        taskId: planningTaskResponse.taskId,
        eventType: 'PLANNING_PROGRESS',
        schemaVersion: 2,
        payload: { status: 'RUNNING', stage: 'CITY_FACTS_LOADING', sequence: 1, progress: 20, message: 'x' },
        createdAt: '2026-07-16T01:00:04Z',
      })}\n\n`,
    ))
    streamController.close()
    // The stream ends without a terminal frame: the task must fail closed.
    expect(await screen.findByText('任务状态连接已中断，请稍后重试')).toBeTruthy()
  })

  test('keeps working when logout fails while the server is unavailable', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const requestUrl = urlOf(input)
      if (requestUrl.endsWith('/api/auth/login')) return response(authResponse)
      if (requestUrl.endsWith('/api/auth/logout')) {
        return response({ code: 'INTERNAL', message: '离线' }, 503)
      }
      if (requestUrl.endsWith('/api/trips')) return response([tripResponse])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${requestUrl}`)
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: '退出登录' }))
    expect(await screen.findByRole('heading', { name: '登录 TripPilot' })).toBeTruthy()
  })
})

describe('TripWorkspace WAITING_USER state machine (B13_FIX.2 R10)', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/trips')
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  const reviewReport = {
    ...verifiedFeasibilityReport,
    status: 'UNVERIFIED',
    summary: { totalCount: 6, passCount: 6, unknownCount: 2, failCount: 0, notApplicableCount: 3, missingRequiredCount: 0 },
    ruleResults: [
      {
        ruleId: 'OPENING_HOURS',
        ruleVersion: 'hard-rule-v1',
        outcome: 'UNKNOWN',
        reasonCode: 'OPENING_HOURS_UNVERIFIED',
        message: '缺少营业时间证据',
        affectedDates: ['2026-07-18'],
        affectedEntityRefs: [],
        evidenceRefs: [],
        repairable: false,
      },
    ],
  }
  const reviewCandidate = {
    title: '候选行程',
    days: [{
      date: '2026-07-18',
      dayType: 'FULL_DAY',
      activities: [{
        id: 'aaaaaaaa-1111-1111-1111-111111111111',
        title: '漫步沙面',
        startTime: '2026-07-18T01:00:00Z',
        endTime: '2026-07-18T03:00:00Z',
        estimatedCost: 0,
        source: 'AMAP',
        providerPoiId: 'B001234567',
        coordinates: { longitude: 113.2392, latitude: 23.1097 },
        address: '广州市荔湾区沙面',
        kind: 'ATTRACTION',
        timeFixed: false,
      }],
      transitLegs: [],
    }],
    estimatedTotalCost: 0,
  }
  const reviewTask = {
    ...planningTaskResponse,
    status: 'WAITING_USER',
    feasibilityReport: reviewReport,
    candidateItinerary: reviewCandidate,
  }
  const failedTask = {
    ...planningTaskResponse,
    status: 'FAILED',
    errorMessage: '行程规划失败，请检查必去地点后重试',
  }

  test('waiting_user disables start planning and never sends a create request', async () => {
    const fetchMock = vi.fn()
    detailEndpoints(fetchMock, {
      latestTask: response(reviewTask),
      itinerary: null, // no formal itinerary: the candidate panel must still show
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))

    // Candidate panel is visible without a formal itinerary.
    expect(await screen.findAllByText('候选行程')).not.toHaveLength(0)

    const startButton = await screen.findByTestId('start-planning')
    expect(startButton.hasAttribute('disabled')).toBe(true)
    await fireEvent.click(startButton)
    await new Promise((resolve) => setTimeout(resolve, 50))
    const createCalls = fetchMock.mock.calls.filter(([input, init]) => (
      urlOf(input as RequestInfo | URL).endsWith(`/api/trips/${tripResponse.id}/planning-tasks`)
      && (init as RequestInit | undefined)?.method === 'POST'
    ))
    expect(createCalls).toHaveLength(0)
  })

  test('recovers WAITING_USER from a 409 PLANNING_TASK_ACTIVE race without losing the candidate', async () => {
    const fetchMock = vi.fn()
    let latestCalls = 0
    detailEndpoints(fetchMock, {}, async (input, init) => {
      const requestUrl = urlOf(input)
      if (requestUrl.endsWith(`/api/trips/${tripResponse.id}/planning-tasks/latest`)) {
        latestCalls += 1
        // First call is page hydration (no task visible to this tab);
        // the recovery call after the 409 returns the WAITING_USER review.
        return latestCalls === 1
          ? response({ code: 'TASK_NOT_FOUND' }, 404)
          : response(reviewTask)
      }
      if (requestUrl.endsWith(`/api/trips/${tripResponse.id}/planning-tasks`) && init?.method === 'POST') {
        return response({
          code: 'PLANNING_TASK_ACTIVE',
          message: '已有候选行程待确认，请先查看或放弃候选',
        }, 409)
      }
      return null
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))
    await fireEvent.click(await screen.findByTestId('start-planning'))

    // The authoritative WAITING_USER state is restored: candidate visible,
    // no failed alert, button disabled again, candidate/report not cleared.
    expect(await screen.findAllByText('候选行程')).not.toHaveLength(0)
    expect(screen.queryByRole('alert')).toBeNull()
    await waitFor(() => {
      expect(screen.getByTestId('start-planning').hasAttribute('disabled')).toBe(true)
    })
    expect(screen.queryByText('行程规划失败')).toBeNull()
  })

  test('clears a stale planning error when the race recovery returns a review', async () => {
    const fetchMock = vi.fn()
    let latestCalls = 0
    detailEndpoints(fetchMock, {}, async (input, init) => {
      const requestUrl = urlOf(input)
      if (requestUrl.endsWith(`/api/trips/${tripResponse.id}/planning-tasks/latest`)) {
        latestCalls += 1
        // Hydration sees the previous FAILED task (stale error), the
        // recovery after the 409 returns the WAITING_USER review.
        return latestCalls === 1
          ? response(failedTask)
          : response(reviewTask)
      }
      if (requestUrl.endsWith(`/api/trips/${tripResponse.id}/planning-tasks`) && init?.method === 'POST') {
        return response({
          code: 'PLANNING_TASK_ACTIVE',
          message: '已有候选行程待确认，请先查看或放弃候选',
        }, 409)
      }
      return null
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))
    // The stale failed state surfaces its error first.
    expect(await screen.findByText('行程规划失败，请检查必去地点后重试')).toBeTruthy()

    await fireEvent.click(await screen.findByTestId('start-planning'))

    // Applying the review clears the old planningError.
    expect(await screen.findAllByText('候选行程')).not.toHaveLength(0)
    await waitFor(() => {
      expect(screen.queryByText('行程规划失败，请检查必去地点后重试')).toBeNull()
    })
    expect(screen.queryByRole('alert')).toBeNull()
  })

  test('allows planning again after abandoning the candidate (B13_FIX.2 R11)', async () => {
    const fetchMock = vi.fn()
    detailEndpoints(fetchMock, {
      latestTask: response(reviewTask),
    }, async (input, init) => {
      const requestUrl = urlOf(input)
      if (requestUrl.endsWith(`/api/planning-tasks/${planningTaskResponse.taskId}`) && init?.method === 'DELETE') {
        return response({ ...reviewTask, status: 'CANCELLED' })
      }
      return null
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))
    expect(await screen.findAllByText('候选行程')).not.toHaveLength(0)

    await fireEvent.click(await screen.findByTestId('abandon-candidate'))
    expect(await screen.findByText('规划已取消')).toBeTruthy()

    // After the abandon the start button is usable again and really sends a
    // create request (the active slot is free).
    const startButton = await screen.findByTestId('start-planning')
    expect(startButton.hasAttribute('disabled')).toBe(false)
    await fireEvent.click(startButton)
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input, callInit]) => (
        urlOf(input as RequestInfo | URL).endsWith(`/api/trips/${tripResponse.id}/planning-tasks`)
        && (callInit as RequestInit | undefined)?.method === 'POST'
      ))).toBe(true)
    })
  })

  test('allows a normal retry after a FAILED task (B13_FIX.2 R11)', async () => {
    const fetchMock = vi.fn()
    detailEndpoints(fetchMock, {
      latestTask: response(failedTask),
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))
    expect(await screen.findByText('行程规划失败，请检查必去地点后重试')).toBeTruthy()

    const startButton = await screen.findByTestId('start-planning')
    expect(startButton.hasAttribute('disabled')).toBe(false)
    await fireEvent.click(startButton)
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input, callInit]) => (
        urlOf(input as RequestInfo | URL).endsWith(`/api/trips/${tripResponse.id}/planning-tasks`)
        && (callInit as RequestInit | undefined)?.method === 'POST'
      ))).toBe(true)
    })
  })

  test('uses Chinese copy and keeps the formal itinerary isolated from the candidate (B13_FIX.2 R11)', async () => {
    const fetchMock = vi.fn()
    detailEndpoints(fetchMock, {
      latestTask: response(reviewTask),
    })

    await signIn(fetchMock)
    await screen.findByRole('heading', { name: tripResponse.title })
    await fireEvent.click(screen.getByRole('button', { name: `打开 ${tripResponse.title}` }))

    // WAITING_USER copy: the progress header and the button are localized.
    expect(await screen.findByText('规划进度')).toBeTruthy()
    const startButton = await screen.findByTestId('start-planning')
    expect(startButton.textContent).toContain('等待规划结果')
    // Candidate and formal itinerary coexist without replacing each other.
    expect(await screen.findAllByText('预览方案')).not.toHaveLength(0)
    expect(screen.getByRole('heading', { name: itineraryResponse.title })).toBeTruthy()
  })
})
