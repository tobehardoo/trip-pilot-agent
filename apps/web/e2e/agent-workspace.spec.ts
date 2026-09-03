// Agent UX — 新 /workspace 统一契约（旅行模式：planning 视图）。
// 认证必经 /api/auth/refresh；进入 /workspace/trips/:id 后渲染
// planning-status-line + TripRouteMap + agent-dialog + docked workspace-composer。
// 全部 /api/** 路由级 mock，无需后端。

import { expect, test, type Page } from '@playwright/test'

const tripId = '33333333-3333-3333-3333-333333333333'

const session = {
  user: {
    id: '11111111-1111-1111-1111-111111111111',
    email: 'traveler@example.com',
    displayName: '旅行者',
  },
  accessToken: 'agent-workspace-token',
  tokenType: 'Bearer',
  expiresIn: 900,
}

const trip = {
  id: tripId,
  title: '成都四日',
  destination: '成都',
  startDate: '2026-10-01',
  endDate: '2026-10-04',
  status: 'PLANNING',
  version: 7,
  constraints: {
    budgetAmount: null,
    travelers: 2,
    travelerType: 'COUPLE',
    pace: 'BALANCED',
    preferences: ['本地美食'],
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
  createdAt: '2026-08-01T01:00:00Z',
  updatedAt: '2026-08-01T02:00:00Z',
  archivedAt: null,
}

function sseFrame(id: number, event: Record<string, unknown>): string {
  const nl = String.fromCharCode(10)
  return `id: ${id}${nl}event: ${event.eventType}${nl}data: ${JSON.stringify(event)}${nl}${nl}`
}

function agentEvent(id: number, eventType: string, payload: Record<string, unknown>): string {
  return sseFrame(id, {
    eventId: id,
    tripId,
    runId: 'aaaa3333-3333-3333-3333-333333333333',
    eventType,
    schemaVersion: 1,
    payload,
  })
}

const stepEvent = agentEvent(1, 'AGENT_STEP', {
  seq: 0,
  tool: 'update_constraints',
  ok: true,
  summary: '已记录 3 项旅行条件',
})

const questionEvent = agentEvent(2, 'AGENT_ASK_USER', {
  question: '行程从哪天开始？',
  options: ['10月1日', '10月2日'],
  expectedType: 'DATE',
})

async function mockSessionApi(page: Page, streamBody?: string) {
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()

    if (path === '/api/auth/refresh') {
      await route.fulfill({ json: session })
      return
    }
    if (path === '/api/trips' && method === 'GET') {
      await route.fulfill({ json: [trip] })
      return
    }
    if (path === `/api/trips/${tripId}`) {
      await route.fulfill({ json: trip })
      return
    }
    if (path === `/api/trips/${tripId}/itinerary`) {
      await route.fulfill({ status: 404, json: { code: 'ITINERARY_NOT_FOUND', message: 'Not planned yet' } })
      return
    }
    if (path === `/api/trips/${tripId}/itinerary/versions`) {
      await route.fulfill({ json: [] })
      return
    }
    if (path === `/api/trips/${tripId}/itinerary/shares`) {
      await route.fulfill({ json: [] })
      return
    }
    if (path === `/api/trips/${tripId}/guide-imports`) {
      await route.fulfill({ json: [] })
      return
    }
    if (path === `/api/trips/${tripId}/planning-tasks/latest`) {
      await route.fulfill({ status: 404, json: { code: 'PLANNING_TASK_NOT_FOUND', message: 'none' } })
      return
    }
    if (path === `/api/trips/${tripId}/agent-dialogue/events`) {
      await route.fulfill({
        contentType: 'text/event-stream',
        body: streamBody ?? '',
      })
      return
    }
    if (path === `/api/trips/${tripId}/agent-dialogue/runs` && method === 'POST') {
      expect(request.headers()['idempotency-key']).toBeTruthy()
      await route.fulfill({ status: 202, json: { eventId: 'evt-start', status: 'QUEUED' } })
      return
    }
    if (/\/agent-dialogue\/runs\/[^/]+\/answers$/.test(path) && method === 'POST') {
      const body = request.postDataJSON() as { answer?: string }
      expect(body.answer).toBeTruthy()
      await route.fulfill({ status: 202, json: { eventId: 'evt-answer', status: 'QUEUED' } })
      return
    }
    if (path === `/api/trips/${tripId}/planning-tasks` && method === 'POST') {
      await route.fulfill({ status: 202, json: { eventId: 'evt-plan', status: 'QUEUED' } })
      return
    }

    await route.fulfill({
      status: 501,
      json: { code: 'UNMOCKED_AGENT_WORKSPACE_REQUEST', message: `${method} ${path}` },
    })
  })
}

test('restores a session and renders the guarded trip planning view', async ({ page }) => {
  await mockSessionApi(page, '')
  await page.goto(`/workspace/trips/${tripId}`)

  await expect(page.getByTestId('workspace-shell')).toBeVisible()
  await expect(page.getByTestId('planning-status-line')).toContainText('TripPilot 正在规划你的旅行')
  await expect(page.getByTestId('agent-dialog')).toBeVisible()
  await expect(page.getByTestId('trip-route-map')).toBeVisible()
  await expect(page.getByTestId('trip-route-placeholder')).toBeVisible()
  // docked composer（旅行模式）
  await expect(page.getByTestId('workspace-composer')).toBeVisible()
  await expect(page.getByTestId('composer-input')).toBeVisible()
  // 侧栏列出该旅行
  await expect(page.getByTestId(`workspace-project-${tripId}`)).toBeVisible()
})

test('renders a human-language planning timeline without leaking tool names', async ({ page }) => {
  await mockSessionApi(page, stepEvent)
  await page.goto(`/workspace/trips/${tripId}`)

  const dialog = page.getByTestId('agent-dialog')
  // 折叠态摘要用业务语言
  await expect(dialog.getByText('正在了解你的旅行需求……')).toBeVisible()

  // 展开 → 步骤以中文标题/摘要呈现，原始工具名不下屏
  await dialog.getByTestId('agent-dialog-toggle').click()
  await expect(dialog.getByText('理解旅行需求')).toBeVisible()
  await expect(dialog.getByText('已记录 3 项旅行条件')).toBeVisible()
  expect(await page.getByText('update_constraints').count()).toBe(0)
})

test('sends a refinement command from the docked composer to the trip agent', async ({ page }) => {
  await mockSessionApi(page, '')
  await page.goto(`/workspace/trips/${tripId}`)

  const composer = page.getByTestId('workspace-composer')
  await composer.getByTestId('composer-input').fill('把住宿改在市区')
  await composer.getByTestId('composer-send').click()

  const dialog = page.getByTestId('agent-dialog')
  await dialog.getByTestId('agent-dialog-toggle').click()
  await expect(dialog.getByText('把住宿改在市区').first()).toBeVisible()
})

test('answers a clarification from the trip agent while planning', async ({ page }) => {
  await mockSessionApi(page, questionEvent)
  await page.goto(`/workspace/trips/${tripId}`)

  const dialog = page.getByTestId('agent-dialog')
  await expect(dialog.getByText('请回答旅行相关问题')).toBeVisible()

  const composer = page.getByTestId('workspace-composer')
  await composer.getByTestId('composer-input').fill('10月1日')
  await composer.getByTestId('composer-send').click()

  // 应答到达 answerAgentRun（runs/:id/answers）——mock 已断言 body.answer 非空
  await expect(dialog.getByTestId('agent-dialog-toggle')).toBeVisible()
})