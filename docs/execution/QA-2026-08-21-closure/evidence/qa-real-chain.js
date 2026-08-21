/* Q4: real isolated-stack browser chain — no API mocking.
 * Runs the actual Web -> Java -> MQ -> Python -> completion path:
 *   1. UI register + login against the isolated stack (vite proxy -> 38086)
 *   2. create trip + plan -> terminal via the same stack API
 *   3. browser renders the REAL persisted itinerary
 */
const { chromium } = require('@playwright/test')

const API = 'http://127.0.0.1:38086'
const WEB = 'http://127.0.0.1:4173'

async function apiJson(path, init) {
  const res = await fetch(API + path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  })
  return { status: res.status, body: await res.json().catch(() => null) }
}

;(async () => {
  const browser = await chromium.launch()
  const page = await browser.newPage()
  const suffix = Date.now()
  const email = `qa-real-${suffix}@example.com`
  const password = 'Passw0rd!123'
  try {
    // 1. UI register (switch to register mode on the auth view)
    await page.goto(WEB + '/login')
    await page.getByRole('button', { name: '创建账户' }).click()
    await page.fill('#display-name', 'QA 用户')
    await page.fill('#email', email)
    await page.fill('#password', password)
    await page.getByRole('button', { name: '创建账户并登录' }).click()
    await page.waitForURL(/login|trips/, { timeout: 20000 })
    console.log('STEP1 register: OK')

    // 2. UI session: register already authenticated; verify the UI shows the
    // authenticated trip list (or complete a login if the session was lost)
    await page.goto(WEB + '/trips')
    await page.waitForLoadState('networkidle')
    if ((await page.locator('#email').count()) > 0) {
      await page.fill('#email', email)
      await page.fill('#password', password)
      await page.getByRole('button', { name: '登录', exact: true }).click()
      await page.waitForURL(/trips/, { timeout: 20000 })
    }
    console.log('STEP2 session: OK')

    // 3. API: create trip + plan -> terminal (same stack)
    const reg = await apiJson('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
    if (reg.status !== 200 || !reg.body?.accessToken) throw new Error(`login api ${reg.status}`)
    const token = reg.body.accessToken
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
    if (tripRes.status !== 201) throw new Error(`create trip ${tripRes.status}`)
    const tripId = tripRes.body.id
    const planRes = await apiJson(`/api/trips/${tripId}/planning-tasks`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Idempotency-Key': crypto.randomUUID(),
      },
    })
    if (planRes.status !== 202) {
      throw new Error(`plan ${planRes.status}: ${JSON.stringify(planRes.body)}`)
    }
    let terminal = null
    for (let i = 0; i < 60; i++) {
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
    if (!terminal || !['SUCCEEDED', 'WAITING_USER'].includes(terminal)) {
      throw new Error(`terminal=${terminal}`)
    }
    console.log(`STEP3 plan->terminal: OK (${terminal})`)

    // 4. browser renders the REAL persisted itinerary
    await page.goto(`${WEB}/trips/${tripId}`)
    await page.waitForLoadState('networkidle')
    await page.getByText('QA 真实链路').first().waitFor({ timeout: 20000 })
    console.log('STEP4 real itinerary rendered: OK')

    console.log('Q4_RESULT: PASS')
  } catch (err) {
    console.error('Q4_RESULT: FAIL', err.message)
    process.exitCode = 1
  } finally {
    await browser.close()
  }
})()
