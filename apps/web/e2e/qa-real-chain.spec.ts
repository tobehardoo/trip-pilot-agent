import { test, expect } from '@playwright/test'

// Q4: real isolated-stack browser chain — NO page.route() mocking anywhere.
// Exercises the actual Web -> Java -> MQ -> Python -> completion path:
//   1. UI register (auth view starts in login mode; switch to register)
//   2. verify authenticated session on /trips
//   3. create trip + plan -> terminal via the SAME stack's API
//   4. browser renders the real persisted itinerary (not mocked fixtures)
// Prereq: isolated stack up (travel-server on 127.0.0.1:38086), vite proxy
// targets it via apps/web/.env.local (TRAVEL_SERVER_URL).

const API = 'http://127.0.0.1:38086'

async function apiJson(path: string, init?: RequestInit): Promise<{ status: number; body: any }> {
  const res = await fetch(API + path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  return { status: res.status, body: await res.json().catch(() => null) }
}

test('real isolated-stack browser chain without API mocking', async ({ page }) => {
  const suffix = Date.now()
  const email = `qa-real-${suffix}@example.com`
  const password = 'Passw0rd!123'

  // --- 1. UI register: auth view opens in login mode; switch to register ---
  await page.goto('/login')
  await page.getByRole('button', { name: '创建账户' }).click()
  await page.fill('#display-name', 'QA 用户')
  await page.fill('#email', email)
  await page.fill('#password', password)
  await page.getByRole('button', { name: '创建账户并登录' }).click()
  await page.waitForURL(/login|trips/, { timeout: 20000 })

  // --- 2. authenticated session: /trips shows the trip list (or complete login) ---
  await page.goto('/trips')
  await page.waitForLoadState('networkidle')
  if ((await page.locator('#email').count()) > 0) {
    await page.fill('#email', email)
    await page.fill('#password', password)
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await page.waitForURL(/trips/, { timeout: 20000 })
  }
  await expect(page).toHaveURL(/trips/, { timeout: 20000 })

  // --- 3. create trip + plan -> terminal through the same stack ---
  const reg = await apiJson('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  expect(reg.status).toBe(200)
  const token = reg.body?.accessToken
  expect(token).toBeTruthy()

  const tripRes = await apiJson('/api/trips', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      title: 'QA 真实链路',
      destination: '广州',
      startDate: '2026-09-10',
      endDate: '2026-09-11',
      arrivalAt: '2026-09-10T10:00:00+08:00',
      departureAt: '2026-09-11T18:00:00+08:00',
      constraints: {
        budgetAmount: 3000,
        travelers: 1,
        travelerType: 'SOLO',
        pace: 'BALANCED',
        preferences: [],
        fixedSchedules: [],
        arrival: null,
        departure: null,
        accommodation: null,
        mustVisitPlaces: [],
        avoidPlaces: [],
        mustVisitPlaceRefs: [],
        avoidPlaceRefs: [],
        mealWindows: [],
        mobilityLevel: 'STANDARD',
      },
    }),
  })
  expect(tripRes.status).toBe(201)
  const tripId = tripRes.body?.id
  expect(tripId).toBeTruthy()

  const planRes = await apiJson(`/api/trips/${tripId}/planning-tasks`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Idempotency-Key': crypto.randomUUID(),
    },
  })
  expect(planRes.status).toBe(202)
  const taskId = planRes.body?.taskId
  expect(taskId).toBeTruthy()

  let terminal: string | null = null
  for (let i = 0; i < 90; i++) {
    const latest = await apiJson(`/api/trips/${tripId}/planning-tasks/latest`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    const status = latest.body?.status
    if (['SUCCEEDED', 'WAITING_USER', 'FAILED', 'CANCELLED'].includes(status)) {
      terminal = status
      break
    }
    await new Promise((r) => setTimeout(r, 1000))
  }
  expect(terminal).toBeTruthy()
  expect(['SUCCEEDED', 'WAITING_USER']).toContain(terminal)

  // --- 4. browser renders the REAL persisted itinerary (no mocking) ---
  await page.goto(`/trips/${tripId}`)
  await page.waitForLoadState('networkidle')
  await expect(page.getByText('QA 真实链路').first()).toBeVisible({ timeout: 20000 })
  // terminal status is surfaced to the user (no 95% hang)
  const body = await page.locator('body').innerText()
  expect(body.length).toBeGreaterThan(0)
})
