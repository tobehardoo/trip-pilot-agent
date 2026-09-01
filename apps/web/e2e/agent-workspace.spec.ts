// Agent UX 3.0 验收场景（重构方案 §26，Mock 栈变体）：
// Scenario 1/2/3（一句话 → 执行时间线 → 决策点）、Scenario 4/5（应答 → 完成 →
// 应用即规划）、Scenario 11/12（AGENT_RUN_FINISHED 终态可见 + 携目标重开）、
// 创建会话（/plan/new 会话化创建 + 手动表单 fallback 路由化）。
// 与其余 spec 一致：/api/** 全部路由级 mock，无需后端。

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
  status: 'READY',
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

const completedEvent = agentEvent(3, 'AGENT_COMPLETED', {
  summary: '行程已生成：成都三日',
  itinerary: {
    title: '成都三日',
    estimatedTotalCost: 1200,
    days: [{
      date: '2026-10-01',
      activities: [
        { title: '宽窄巷子', startTime: '2026-10-01T01:00:00Z', endTime: '2026-10-01T03:00:00Z', estimatedCost: 0, source: 'DEMO' },
        { title: '人民公园', startTime: '2026-10-01T04:00:00Z', endTime: '2026-10-01T05:30:00Z', estimatedCost: 0, source: 'DEMO' },
      ],
      transitLegs: [],
    }],
  },
  slots: {
    destination: { value: '成都', state: 'CONFIRMED' },
    budget: { value: 5000, state: 'CONFIRMED' },
    travelers: { value: 2, state: 'CONFIRMED' },
    pace: { value: 'RELAXED', state: 'INFERRED' },
  },
})

async function mockSessionApi(
  page: Page,
  options: { streamBody: string; failStart?: boolean; gateCompletion?: boolean; createTrip?: boolean } = {},
) {
  // 真实服务器在收到应答（AGENT_RESUME）之后才发布完成事件。Mock 用
  // 应答栅栏复刻这一顺序：重连的流在应答发生前保持挂起。
  let streamCall = 0
  let releaseCompletion: (() => void) | null = null
  const answeredGate = new Promise<void>((resolve) => {
    releaseCompletion = resolve
  })

  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname

    if (path === '/api/auth/refresh') {
      await route.fulfill({ json: session })
      return
    }
    if (path === '/api/trips' && request.method() === 'GET') {
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
    if (path === `/api/trips/${tripId}/guide-imports`) {
      await route.fulfill({ json: [] })
      return
    }
    if (path === `/api/trips/${tripId}/itinerary/shares`) {
      await route.fulfill({ json: [] })
      return
    }
    if (options.createTrip && path === '/api/agent/dialogue') {
      const body = request.postDataJSON() as { option?: { action: string }; reset?: boolean }
      if (body.reset) {
        await route.fulfill({ json: { phase: 'COLLECTING', ready: false, messages: [], slots: {} } })
        return
      }
      if (body.option) {
        await route.fulfill({
          json: {
            phase: 'READY', ready: true,
            messages: [{ role: 'agent', text: '旅行约束已齐，可以创建行程了。', kind: 'SUMMARY', options: [] }],
            slots: { destination: { value: '成都', state: 'CONFIRMED', source: 'USER_CONFIRMED' } },
          },
        })
        return
      }
      await route.fulfill({
        json: {
          phase: 'COLLECTING', ready: false,
          messages: [{ role: 'agent', text: '好的，去成都玩几天？', kind: 'CLARIFY', options: [] }],
          slots: { destination: { value: '成都', state: 'INFERRED', source: 'LLM_INFERRED' } },
        },
      })
      return
    }
    if (options.createTrip && path === '/api/agent/trips') {
      await route.fulfill({ json: trip })
      return
    }
    if (path === `/api/trips/${tripId}/planning-tasks/latest`) {
      await route.fulfill({ status: 404, json: { code: 'PLANNING_TASK_NOT_FOUND', message: 'none' } })
      return
    }
    if (path === `/api/trips/${tripId}/agent-dialogue/events`) {
      streamCall += 1
      if (streamCall === 1) {
        await route.fulfill({
          contentType: 'text/event-stream',
          body: options.streamBody,
        })
        return
      }
      if (options.gateCompletion) {
        // 后续重连：等待应答发生后才推送完成事件
        await answeredGate
        await route.fulfill({
          contentType: 'text/event-stream',
          body: completedEvent,
        })
        return
      }
      await route.fulfill({ contentType: 'text/event-stream', body: '' })
      return
    }
    if (path === `/api/trips/${tripId}/agent-dialogue/runs` && request.method() === 'POST') {
      if (options.failStart) {
        await route.fulfill({
          status: 502,
          json: { code: 'AGENT_DIALOGUE_UNAVAILABLE', message: 'Agent dialog service rejected the request' },
        })
        return
      }
      expect(request.headers()['idempotency-key']).toBeTruthy()
      await route.fulfill({ status: 202, json: { eventId: 'evt-start', status: 'QUEUED' } })
      return
    }
    if (/\/agent-dialogue\/runs\/[^/]+\/answers$/.test(path) && request.method() === 'POST') {
      const body = request.postDataJSON() as { answer?: string }
      expect(body.answer).toBe('10月1日')
      await route.fulfill({ status: 202, json: { eventId: 'evt-answer', status: 'QUEUED' } })
      releaseCompletion?.()
      return
    }
    if (path === `/api/trips/${tripId}/constraints` && request.method() === 'PUT') {
      const body = request.postDataJSON() as Record<string, unknown>
      expect(body.version).toBe(7)
      await route.fulfill({ json: { ...trip, version: 8, constraints: { ...trip.constraints, budgetAmount: body.budgetAmount ?? null } } })
      return
    }
    if (path === `/api/trips/${tripId}/planning-tasks` && request.method() === 'POST') {
      await route.fulfill({ status: 202, json: { eventId: 'evt-plan', status: 'QUEUED' } })
      return
    }

    await route.fulfill({
      status: 501,
      json: { code: 'UNMOCKED_AGENT_WORKSPACE_REQUEST', message: `${request.method()} ${path}` },
    })
  })
}

test('one session: timeline, decision card, completion and apply-then-plan', async ({ page }) => {
  await mockSessionApi(page, { streamBody: stepEvent + questionEvent, gateCompletion: true })
  await page.goto(`/trips/${tripId}`)

  await expect(page.getByRole('button', { name: 'AI 助手' })).toBeVisible()
  await page.getByRole('button', { name: 'AI 助手' }).click()

  // 会话是一等路由对象：URL 即会话身份
  await expect(page).toHaveURL(new RegExp(`/trips/${tripId}/plan`))
  const workspace = page.getByTestId('planning-session')

  // Scenario 1/3：执行时间线以业务语言呈现，工具名不泄漏
  await expect(workspace.getByText('理解旅行需求')).toBeVisible()
  expect(await workspace.getByText('update_constraints').count()).toBe(0)

  // Scenario 2：决策点 + 等待语义（含 7 天恢复承诺）
  await expect(workspace.getByText('当前任务正在等待你的回答')).toBeVisible()
  await expect(workspace.getByText('行程从哪天开始？')).toBeVisible()

  // Scenario 4：点选快捷日期即应答
  await workspace.getByRole('button', { name: '10月1日' }).click()

  // Scenario 5：结果面板 + 约束区（内部枚举不出现）
  await expect(workspace.getByTestId('agent-completed-card')).toContainText('成都三日')
  await expect(workspace.getByTestId('agent-slot-budget')).toContainText('¥5000')
  await expect(workspace.getByTestId('agent-slot-budget')).toContainText('已确认')
  expect(await workspace.getByText('CONFIRMED').count()).toBe(0)

  // 应用 = PUT 约束 + 启动正式规划（同一次交付动作），随后切入管线在途态
  await workspace.getByTestId('agent-apply-cta').click()
  await expect(workspace.getByTestId('pipeline-building')).toBeVisible()
  await expect(workspace.getByText('正在生成正式行程')).toBeVisible()
})

test('run finished: recovery card keeps context and restart carries the goal', async ({ page }) => {
  // 流 1 = 理解步骤；重连流 = 终态（用户目标句已在本地回合中，重开可携带）。
  let streamCall = 0
  const finishedEvent = agentEvent(2, 'AGENT_RUN_FINISHED', {
    status: 'EXPIRED',
    reasonCode: 'RUN_EXPIRED',
    message: '这次对话搁置太久已自动结束，重新发起即可继续。',
  })
  await mockSessionApi(page, { streamBody: stepEvent })
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/agent-dialogue/events')) {
      streamCall += 1
      if (streamCall >= 2) {
        await route.fulfill({ contentType: 'text/event-stream', body: finishedEvent })
        return
      }
    }
    await route.fallback()
  })
  await page.goto(`/trips/${tripId}`)
  await page.getByRole('button', { name: 'AI 助手' }).click()

  const workspace = page.getByTestId('planning-session')
  await expect(workspace.getByText('理解旅行需求')).toBeVisible()
  await workspace.getByTestId('agent-input').fill('十一想去成都玩')
  await workspace.getByRole('button', { name: '发送' }).click()

  await expect(workspace.getByTestId('agent-error-card')).toBeVisible({ timeout: 15000 })
  await expect(workspace.getByText('这次对话已自动结束')).toBeVisible()
  expect(await workspace.getByText('RUN_EXPIRED').count()).toBe(0)

  // 重新开始：携带原目标句回到输入框（Scenario 12 恢复语义）
  await workspace.getByTestId('agent-error-restart').click()
  await expect(workspace.getByTestId('agent-input')).toHaveValue('十一想去成都玩')
})

test('start failure: backend rejection is mapped to user-safe copy', async ({ page }) => {
  await mockSessionApi(page, { streamBody: '', failStart: true })
  await page.goto(`/trips/${tripId}`)
  await page.getByRole('button', { name: 'AI 助手' }).click()

  const workspace = page.getByTestId('planning-session')
  await workspace.getByTestId('agent-input').fill('十一想去成都玩')
  await workspace.getByRole('button', { name: '发送' }).click()

  await expect(workspace.getByTestId('agent-command-error')).toContainText('AI 助手服务暂时不可用')
  expect(await workspace.getByText('rejected the request').count()).toBe(0)
})

test('create session: /plan/new speaks first, no greeting, manual fallback routes on', async ({ page }) => {
  page.on('request', (req) => { if (req.url().includes('/api/agent/dialogue')) console.log('[dlg]', new URL(req.url()).pathname, req.postData()) })
  await mockSessionApi(page, { streamBody: '', createTrip: true })
  await page.goto('/trips')

  await expect(page.getByTestId('agent-plan-entry')).toBeVisible()
  await page.getByTestId('agent-plan-entry').click()
  await expect(page).toHaveURL(/\/plan\/new/)

  const workspace = page.getByTestId('planning-session')
  // START 体验：能力一句话 + 示例；无"我是助手"式寒暄
  await expect(workspace.getByText('把你的旅行想法，变成一份可执行的行程')).toBeVisible()

  // 一句话开始（Scenario 1 创建版）：无问候语
  await workspace.getByTestId('agent-input').fill('国庆去成都四天')
  await workspace.getByRole('button', { name: '发送' }).click()
  await expect(workspace.getByText('好的，去成都玩几天？')).toBeVisible()
  expect(await workspace.getByText('我是行程规划助手').count()).toBe(0)

  // 重新开始（二次确认）回到目标画布；手动表单 fallback → /trips/new（死路由接活）
  await workspace.getByTestId('session-restart').click()
  await workspace.getByTestId('session-restart').click()
  await expect(workspace.getByTestId('goal-canvas')).toBeVisible()
  await workspace.getByTestId('goal-manual-fallback').click()
  await expect(page).toHaveURL(/trips\/new/)
})
