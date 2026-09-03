// Composer 创建场景（新契约）：
// /workspace 创建模式空态 → 选目的地（CitySearchInput li[role=option]）
// → 设日期 → 设人数/预算 → 发送 → CreationTranscript → composer-start-planning
// → [开始规划] → createTripFromAgent → 切入 planning 视图。
// 全部 /api/** 路由级 mock，无需后端。

import { expect, test, type Page } from '@playwright/test'

const tripId = 'aaaaaaaa-1111-2222-3333-444444444444'

const session = {
  user: { id: 'bbbbbbbb-1111-2222-3333-555555555555', email: 'creator@example.com', displayName: '创建者' },
  accessToken: 'composer-creation-token',
  tokenType: 'Bearer',
  expiresIn: 900,
}

const createdTrip = {
  id: tripId,
  title: '广州三日',
  destination: '广州',
  startDate: '2026-09-10',
  endDate: '2026-09-12',
  status: 'PLANNING',
  version: 1,
  constraints: {
    budgetAmount: 5500,
    travelers: 2,
    travelerType: 'COUPLE',
    pace: 'BALANCED',
    preferences: ['历史文化'],
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
  createdAt: '2026-09-03T01:00:00Z',
  updatedAt: '2026-09-03T01:00:00Z',
  archivedAt: null,
}

const readyReply = {
  phase: 'READY',
  ready: true,
  messages: [
    { role: 'user', text: '想轻松一点，多看看历史文化', kind: 'TEXT', options: [] },
    {
      role: 'agent',
      text: '好的，去广州（09/10 → 09/12）两人、预算 5500 元以内的行程，可以开始规划了。',
      kind: 'SUMMARY',
      options: [{ action: 'CONFIRM', label: '开始规划', value: 'START_PLANNING' }],
    },
  ],
  slots: {
    destination: { value: '广州', state: 'CONFIRMED', source: 'TRIP' },
  },
}

async function mockCreationApi(page: Page) {
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()

    if (path === '/api/auth/refresh') {
      await route.fulfill({ json: session })
      return
    }
    if (path === '/api/trips' && method === 'GET') {
      await route.fulfill({ json: [] })
      return
    }
    if (path === '/api/agent/dialogue') {
      await route.fulfill({ json: readyReply })
      return
    }
    if (path === '/api/agent/trips' && method === 'POST') {
      await route.fulfill({ json: createdTrip })
      return
    }
    if (path === `/api/trips/${tripId}`) {
      await route.fulfill({ json: createdTrip })
      return
    }
    if (path === `/api/trips/${tripId}/agent-dialogue/runs` && method === 'POST') {
      await route.fulfill({ status: 202, json: { eventId: 'evt-start', status: 'QUEUED' } })
      return
    }
    if (path === `/api/trips/${tripId}/agent-dialogue/events`) {
      await route.fulfill({ contentType: 'text/event-stream', body: '' })
      return
    }

    await route.fulfill({
      status: 501,
      json: { code: 'UNMOCKED_CREATION_REQUEST', message: `${method} ${path}` },
    })
  })
}

test('creates a trip from the workspace composer and lands in the planning view', async ({ page }) => {
  await mockCreationApi(page)
  await page.goto('/workspace')

  // 创建模式空态：中央 Composer + 引导 h1 + 提示
  await expect(page.getByTestId('workspace-creation')).toBeVisible()
  await expect(page.getByRole('heading', { name: '开始规划一次旅行' })).toBeVisible()
  await expect(page.getByTestId('composer-hint')).toContainText('先填写目的地和日期，就可以开始和 TripPilot 聊。')

  const composer = page.getByTestId('workspace-composer')

  // 1) 选目的地：展开 inline CitySearchInput，输入城市名，点 li[role=option]
  await composer.getByTestId('composer-destination-chip').click()
  const cityInput = composer.getByRole('combobox')
  await expect(cityInput).toBeVisible()
  await cityInput.fill('广州')
  await page.locator('li[role=option]').filter({ hasText: '广州' }).first().click()
  await expect(composer.getByTestId('composer-destination-chip')).toContainText('广州')

  // 2) 设日期：弹层内 date 双控件 fill 后自动关闭并 emit
  await composer.getByTestId('composer-date-chip').click()
  const popover = composer.getByTestId('composer-date-popover')
  await expect(popover).toBeVisible()
  await popover.getByTestId('composer-date-start').fill('2026-09-10')
  await popover.getByTestId('composer-date-end').fill('2026-09-12')
  await expect(composer.getByTestId('composer-date-popover')).toBeHidden()
  await expect(composer.getByTestId('composer-date-chip')).toHaveAttribute('aria-label', '日期：09/10 → 09/12')

  // 3) 人数 / 4) 预算
  await composer.getByTestId('composer-travelers').click()
  await composer.getByTestId('composer-travelers-pop').getByTestId('composer-travelers-2').click()
  await composer.getByTestId('composer-budget').click()
  await composer.getByTestId('composer-budget-pop').getByTestId('composer-budget-5500').click()

  // 5) 发送 → CreationTranscript 出现 + 开始规划按钮出现
  await composer.getByTestId('composer-input').fill('想轻松一点，多看看历史文化')
  await composer.getByTestId('composer-send').click()

  await expect(page.getByTestId('creation-transcript')).toBeVisible()
  await expect(page.getByTestId('creation-message-user')).toBeVisible()
  await expect(page.getByTestId('creation-message-agent')).toBeVisible()
  await expect(page.getByTestId('creation-option-开始规划')).toBeVisible()
  await expect(composer.getByTestId('composer-start-planning')).toBeVisible()

  // 6) [开始规划] → createTripFromAgent → adoptTrip → 进入 planning 视图
  await composer.getByTestId('composer-start-planning').click()

  await expect(page.getByTestId('planning-status-line')).toContainText('TripPilot 正在规划你的旅行')
  await expect(page.getByTestId('agent-dialog')).toBeVisible()
  // 新旅行进入侧栏列表
  await expect(page.getByTestId(`workspace-project-${tripId}`)).toBeVisible()
})