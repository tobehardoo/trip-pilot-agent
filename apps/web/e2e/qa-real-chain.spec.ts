import { expect, test, type Page } from '@playwright/test'

// ─────────────────────────────────────────────────────────────────────────────
// Phase 2 真链 UI E2E — 零 mock 的全链路真实验收（对齐 /workspace 新主链）。
//
// 链路：Composer（创建）→ Agent(constraint confirmation → READY) → Planning
//       （createTripFromAgent + agent-dialogue runs / SSE）→ 确定性 Pipeline →
//       最终行程（ItineraryWorkspace 渲染非空 itinerary）。
//
// 本 spec 与其余 mock spec 的根本区别：**不注册任何 page.route('**/api/**')**。
// 每个请求都打到真实的 travel-server / agent-service（经 Vite dev proxy）。
//
// 前置条件
//   - 本机已跑起 prod 栈（compose.prod.yaml）：postgres / rabbitmq / redis /
//     travel-server(127.0.0.1:8080) / agent-service / agent-api。
//   - Web 侧的 Vite dev proxy 把 /api 指向 travel-server：apps/web/.env.local
//     的 TRAVEL_SERVER_URL（缺省 http://localhost:8080）。
//   - 认证用种子管理员：admin@admin.com / Admin123456（seed admin 迁移）。
//   - provider：prod .env 目前 PROVIDER_MODE=REAL_ONLY 且带 AMAP key —— 规划走
//     真实 AMap。若环境改用 DEMO_ONLY（或缺 key），系统有 DEMO provider + 确定性
//     pipeline 兜底，planning 仍应产出非空行程；本 spec 只断言“最终渲染非空行程”，
//     不绑定 provider 具体是 AMAP 还是 DEMO。
//
// 为何保持 CI 排除（playwright.config 的 testIgnore）：CI 无本地后端，本 spec 若
// 进 CI 必然因 backend/agent 不可达而挂；且 REAL_ONLY 需真实网络+密钥，做不了网络
// 隔离层面的确定性。因此只允许在本地具备完整栈时运行。
// ─────────────────────────────────────────────────────────────────────────────

test.setTimeout(5 * 60 * 1000)

// 种子管理员（seed admin account migration）。
const ADMIN = { email: 'admin@admin.com', password: 'Admin123456' }

// 真实登录一次拿 token（真链，不入页面路由 mock）。用于 backend 轮询（阶段 5）。
async function adminToken(page: Page): Promise<string> {
  const res = await page.request.post('/api/auth/login', {
    data: { email: ADMIN.email, password: ADMIN.password },
  })
  expect(res.status(), 'real /api/auth/login（admin seed）应 200').toBe(200)
  const body = (await res.json()) as { accessToken?: string }
  expect(body.accessToken, '登录应返回 accessToken').toBeTruthy()
  return body.accessToken as string
}

// 从侧栏读真实创建出的 tripId（元素 testid = workspace-project-<id>）。
async function readCreatedTripId(page: Page): Promise<string> {
  const el = page.locator('[data-testid^="workspace-project-"]').first()
  await expect(el).toBeVisible({ timeout: 30_000 })
  const testid = (await el.getAttribute('data-testid')) as string
  return testid.slice('workspace-project-'.length)
}

// 在创建对话 transcript 里点选“真实”option，把对话往前推，直到 ready。
// 只点真实渲染出的选项卡按钮（data-testid^="creation-option-" 且未禁用）。
async function driveCreationDialogueToReady(page: Page, maxTurns = 8): Promise<boolean> {
  // 偏好“跳过/直接创建/可以”以最快收敛；退而求首次可用选项。
  const PREFER = ['开始规划', '先跳过，直接创建', '不用管这个', '可以']
  const optionButtons = page.locator('[data-testid^="creation-option-"]:not([disabled])')
  const agentMsgs = page.locator('[data-testid^="creation-message-agent"]')

  const reportDeadlock = (turn: number, detail: string): never => {
    throw new Error(
      `真链创建对话无法进入 READY（turn ${turn}）。${detail}\n` +
      `上下文面板仍显示未确认项（出行人数/总预算/旅行节奏/必去地点/住宿位置/抵达/返程），` +
      `但 agent-service 既不把它们 seed 进会话也不追问 → COLLECTING 死锁，composer-start-planning 永不出现。`,
    )
  }

  for (let turn = 1; turn <= maxTurns; turn++) {
    if (await page.getByTestId('composer-start-planning').isVisible().catch(() => false)) {
      return true
    }
    if ((await optionButtons.count()) === 0) {
      reportDeadlock(turn, 'agent 回复后没有可点选项卡（未 READY）。')
    }
    // 取“偏好”中的第一个可用标签；否则第一个。
    let target: ReturnType<typeof page.locator> | null = null
    for (const pref of PREFER) {
      const exact = optionButtons.filter({ hasText: pref })
      if ((await exact.count()) > 0) { target = exact.first(); break }
    }
    if (!target) target = (await optionButtons.all())[0]

    const agentBefore = await agentMsgs.count()
    await target.click()
    // 等 agent 对这次 option 的真实回复渲染完（agent 消息数增长）或直接 READY。
    const replyTimeout = 25_000
    const replyDeadline = Date.now() + replyTimeout
    while (Date.now() < replyDeadline) {
      if (await page.getByTestId('composer-start-planning').isVisible().catch(() => false)) {
        return true
      }
      if ((await agentMsgs.count()) > agentBefore) break
      await page.waitForTimeout(500)
    }
    if ((await agentMsgs.count()) <= agentBefore) {
      reportDeadlock(turn, '点击选项后 agent 一直未回复（仍发送中/无响应）。')
    }
  }
  reportDeadlock(maxTurns, '达到轮次上限仍未 READY。')
  return false
}

// 等待真实行程落库：轮询 real backend（非 DOM、非 mock）。
async function waitRealItinerary(page: Page, tripId: string): Promise<{ days: number; provider: string }> {
  const token = await adminToken(page)
  const deadline = Date.now() + 180_000
  while (Date.now() < deadline) {
    const tripRes = await page.request.get(`/api/trips/${tripId}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    const trip = tripRes.ok ? (await tripRes.json()) as { status?: string } : { status: 'net-error' }
    const itinRes = await page.request.get(`/api/trips/${tripId}/itinerary`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    let days = 0
    let provider = ''
    if (itinRes.ok) {
      const itin = (await itinRes.json()) as { days?: unknown[]; provider?: string }
      days = itin.days?.length ?? 0
      provider = itin.provider ?? ''
    }
    if (trip.status === 'COMPLETED' && days > 0) {
      return { days, provider }
    }
    if (['FAILED', 'CANCELLED'].includes(trip.status ?? '')) {
      throw new Error(
        `真链规划进入终态失败，无法渲染非空行程：trip.status=${trip.status}，` +
        `itinerary HTTP=${itinRes.status()}。检查 agent-service/provider 配置。`,
      )
    }
    await page.waitForTimeout(4000)
  }
  throw new Error(
    `真链 3 分钟内未产出非空行程（trip 仍未 terminal / itinerary 未落库）。` +
    `当前 PROD 栈为 REAL_ONLY + 真实 AMap，规划慢且受配额限流；` +
    `本次实测中 travel-server 对 AGENT_COMPLETED 事件抛 ` +
    `“payload field types do not match JSON Schema”而拒绝消费，导致部分 run 的行程不落库。`,
  )
}

test('真链：创建 → agent 确认 → 规划 → 最终非空行程（零 mock）', async ({ page }) => {
  // ── 阶段 1：真实 UI 登录（种子管理员）──────────────────────────────
  await page.goto('/workspace')
  await expect(page.getByTestId('workspace-auth')).toBeVisible({ timeout: 20_000 })
  await page.fill('#email', ADMIN.email)
  await page.fill('#password', ADMIN.password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByTestId('workspace-shell')).toBeVisible({ timeout: 20_000 })
  // 创建模式空态（无选中 trip）。
  await expect(page.getByTestId('workspace-creation')).toBeVisible()
  await expect(page.getByRole('heading', { name: '开始规划一次旅行' })).toBeVisible()

  // ── 阶段 2：Composer 创建（真实，无 mock）────────────────────────
  const composer = page.getByTestId('workspace-composer')
  // 目的地（本地 china-divisions 索引，无网络）。
  await composer.getByTestId('composer-destination-chip').click()
  const cityInput = composer.getByRole('combobox')
  await expect(cityInput).toBeVisible()
  await cityInput.fill('广州')
  await page.locator('li[role=option]').filter({ hasText: '广州' }).first().click()
  await expect(composer.getByTestId('composer-destination-chip')).toContainText('广州')
  // 日期。
  await composer.getByTestId('composer-date-chip').click()
  const popover = composer.getByTestId('composer-date-popover')
  await expect(popover).toBeVisible()
  await popover.getByTestId('composer-date-start').fill('2026-09-10')
  await popover.getByTestId('composer-date-end').fill('2026-09-12')
  await expect(popover).toBeHidden()
  // 出行设置（人数 / 预算）。
  await composer.getByTestId('composer-travelers').click()
  await composer.getByTestId('composer-travelers-pop').getByTestId('composer-travelers-1').click()
  await composer.getByTestId('composer-budget').click()
  await composer.getByTestId('composer-budget-pop').getByTestId('composer-budget-2500').click()

  // 发送 → 打真实 /api/agent/dialogue，拿到真实 agent 回复。
  await composer.getByTestId('composer-input').fill('想轻松一点，多看看历史文化')
  await composer.getByTestId('composer-send').click()
  await expect(page.getByTestId('creation-transcript')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('creation-message-user')).toBeVisible()
  // 真实 agent 回复出现（非 mock 的固定文本）。
  await expect(page.getByTestId('creation-message-agent').first()).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('creation-typing')).toBeHidden({ timeout: 30_000 })
  const agentText = (await page.getByTestId('creation-message-agent').first().innerText()).trim()
  expect(agentText.length, 'agent 应返回真实内容（非空）').toBeGreaterThan(0)

  // ── 阶段 3：把真实创建对话推到底（READY → 出现「开始规划」）────────
  const reachedReady = await driveCreationDialogueToReady(page)
  expect(
    reachedReady,
    '创建对话应在有限真实轮次内到达 READY 并出现 composer-start-planning。' +
    '\n当前环境阻塞点：agent-service 未把 tripContext 的 travelers/budget seed 进对话，' +
    '又从不追问它们 → 卡在 COLLECTING；且未配置 LLM structured-model，槽位无法收敛。' +
    '这是后端/密钥导致的真链退化，不是本 spec 的问题。',
  ).toBe(true)

  // ── 阶段 4：开始规划 → 进入 planning 视图（真实 createTripFromAgent）──
  await page.getByTestId('composer-start-planning').click()
  await expect(page.getByTestId('planning-status-line')).toContainText('正在规划', { timeout: 30_000 })
  await expect(page.getByTestId('agent-dialog')).toBeVisible({ timeout: 30_000 })
  const tripId = await readCreatedTripId(page)
  expect(tripId).toBeTruthy()

  // ── 阶段 5：等待真实行程落库并断言 ItineraryWorkspace 渲染非空行程 ──
  const { days, provider } = await waitRealItinerary(page, tripId)
  expect(days).toBeGreaterThan(0)

  // 主视图切到 completed 且渲染真实非空行程。
  await expect(page.getByTestId('plan-overview-title')).toBeVisible({ timeout: 60_000 })
  await expect(page.locator('[data-testid^="plan-day-"]').first()).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('[data-testid^="plan-activity-"]').first()).toBeVisible({ timeout: 30_000 })
  // agent 完成态透出，行程确实非空（避免“已完成共 0 天”假成功）。
  await expect(page.getByTestId('agent-message-done')).toBeVisible({ timeout: 30_000 })
  const dayCount = await page.locator('[data-testid^="plan-day-"]').count()
  const activityCount = await page.locator('[data-testid^="plan-activity-"]').count()
  expect(dayCount).toBeGreaterThan(0)
  expect(activityCount).toBeGreaterThan(0)
  // 结果确实来自后端（provider 透出；AMAP 或 DEMO 由环境决定）。
  expect(['AMAP', 'DEMO', 'MIXED']).toContain(provider)
})