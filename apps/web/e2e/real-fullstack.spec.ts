import { expect, test } from '@playwright/test'

/**
 * Real full-stack planning journey against a running compose stack.
 *
 * Unlike the API-mocked specs in this directory, this test performs no
 * page.route mocking of core APIs: it registers a real user, creates a real
 * trip through the unified form, submits 保存并开始规划, and waits for the
 * real RabbitMQ worker to finish planning before asserting the itinerary
 * renders. It is the acceptance-level regression test for the create-flow
 * race where an auto-started planning task could be left untracked.
 *
 * Requires PLAYWRIGHT_REAL_BASE_URL to point at a healthy compose web
 * (e.g. http://127.0.0.1:8181). Skipped otherwise so normal CI runs of the
 * mocked specs are unaffected.
 */
const REAL_BASE = process.env.PLAYWRIGHT_REAL_BASE_URL

test.skip(!REAL_BASE, 'set PLAYWRIGHT_REAL_BASE_URL to run against a real compose stack')

test('creates a trip through the unified form and renders the real planned itinerary', async ({ page }) => {
  test.setTimeout(240_000)
  const base = REAL_BASE!

  await page.goto(base, { waitUntil: 'networkidle' })

  // Real registration through the UI.
  const email = `real-e2e-${Date.now()}@example.com`
  await page.getByRole('button', { name: '创建账户' }).click()
  await page.locator('#display-name').fill('真实全链')
  await page.locator('#email').fill(email)
  await page.locator('#password').fill('StrongPass123!')
  await page.getByRole('button', { name: '创建账户并登录' }).click()
  await page.waitForURL(/\/trips/, { timeout: 20_000 })

  // Open the unified create form and fill a Changsha 3-day trip.
  await page.getByRole('button', { name: '创建旅行' }).first().click()
  await page.locator('#trip-title').waitFor({ timeout: 10_000 })
  const start = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10)
  const end = new Date(Date.now() + 3 * 86_400_000).toISOString().slice(0, 10)
  await page.locator('#trip-title').fill('长沙三日游-真实全链')
  await page.locator('#destination').fill('长沙')
  await page.locator('#start-date').fill(start)
  await page.locator('#end-date').fill(end)

  // Submit: creates the trip, navigates to detail, and auto-starts planning.
  await page.getByRole('button', { name: '保存并开始规划' }).click()
  await page.waitForURL(/\/trips\/[0-9a-f-]{36}/, { timeout: 30_000 })

  // Wait for the real worker to complete and the itinerary to render.
  const deadline = Date.now() + 180_000
  let rendered = false
  while (Date.now() < deadline) {
    await page.waitForTimeout(3_000)
    const body = await page.locator('body').innerText()
    if (/个地点/.test(body) || /游玩时间/.test(body)) {
      rendered = true
      break
    }
    if (/规划失败/.test(body)) break
  }
  expect(rendered, 'the real itinerary should render after planning completes').toBe(true)
  await page.screenshot({ path: 'test-results/real-fullstack.png', fullPage: true })
})
