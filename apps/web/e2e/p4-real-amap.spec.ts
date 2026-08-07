import { expect, test, type Page, type Route } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

/**
 * P5 (real AMap): verifies real provider planning against a compose stack
 * whose agent-service runs PROVIDER_MODE=REAL_ONLY. The itinerary response
 * must carry provider=AMAP, proving the real AMap route/candidate pipeline ran
 * at least once (not the demo provider).
 *
 *   P5_REAL_RUN=1 PLAYWRIGHT_REAL_BASE_URL=http://127.0.0.1:8183 \
 *   P4_EVIDENCE_DIR=test-results/p5 pnpm exec playwright test e2e/p4-real-amap.spec.ts
 */
const REAL_BASE = process.env.PLAYWRIGHT_REAL_BASE_URL
const EVIDENCE = process.env.P4_EVIDENCE_DIR ?? 'test-results/p5'
const RUN_P5 = process.env.P5_REAL_RUN === '1'

test.skip(!REAL_BASE || !RUN_P5, 'set PLAYWRIGHT_REAL_BASE_URL and P5_REAL_RUN=1 for the real-AMap acceptance')

interface Entry { method: string; url: string; status: number; responseBody?: unknown }

function futureDate(daysFromNow: number): string {
  const d = new Date()
  d.setDate(d.getDate() + daysFromNow)
  return d.toISOString().slice(0, 10)
}

async function registerUser(page: Page, email: string): Promise<void> {
  await page.goto(REAL_BASE!, { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: '创建账户' }).click()
  await page.locator('#display-name').fill('真实AMap验收')
  await page.locator('#email').fill(email)
  await page.locator('#password').fill('StrongPass123!')
  await page.getByRole('button', { name: '创建账户并登录' }).click()
  await page.waitForURL(/\/trips/, { timeout: 20_000 })
}

test('real AMap planning: itinerary provider is AMAP after planning completes', async ({ page }) => {
  test.setTimeout(420_000)
  const entries: Entry[] = []
  const consoleLines: string[] = []
  await page.route('**/*', async (route: Route) => {
    const request = route.request()
    const entry: Entry = { method: request.method(), url: request.url(), status: 0 }
    try {
      const response = await route.fetch()
      entry.status = response.status()
      if ((response.headers()['content-type'] ?? '').includes('json')) {
        try { entry.responseBody = await response.json() } catch { /* keep status */ }
      }
      entries.push(entry)
      await route.fulfill({ response, request })
    } catch {
      entries.push(entry)
      await route.abort()
    }
  })
  page.on('console', (message) => {
    if (message.type() === 'error') consoleLines.push(message.text())
  })

  const email = `p5-amap-${Date.now()}@example.com`
  await registerUser(page, email)
  await page.getByRole('button', { name: '创建旅行' }).first().click()
  await page.locator('#trip-title').waitFor({ timeout: 10_000 })
  await page.locator('#trip-title').fill('真实AMap规划')
  await page.selectOption('#region-province', { label: '广东省' })
  await page.selectOption('#region-city', { label: '广州' })
  const start = futureDate(1)
  await page.locator('#start-date').fill(start)
  await page.locator('#end-date').fill(futureDate(3))
  await page.getByRole('button', { name: '保存并开始规划' }).click()
  await page.waitForURL(/\/trips\/[0-9a-f-]{36}/, { timeout: 30_000 })

  // Wait for the real AMap planning pipeline to complete.
  const deadline = Date.now() + 360_000
  let itinerary: unknown
  while (Date.now() < deadline) {
    await page.waitForTimeout(4_000)
    const itineraryEntry = entries
      .filter((e) => /\/itinerary$/.test(e.url) && e.status === 200 && e.responseBody)
      .pop()
    if (itineraryEntry?.responseBody) {
      const body = itineraryEntry.responseBody as { provider?: string; days?: unknown[] }
      if (body.days && (body.days as unknown[]).length > 0) {
        itinerary = body
        break
      }
    }
    const bodyText = await page.locator('body').innerText()
    if (/规划失败/.test(bodyText)) break
  }

  mkdirSync(EVIDENCE, { recursive: true })
  writeFileSync(path.join(EVIDENCE, 'real-amap-network.json'), JSON.stringify(entries, null, 2))
  writeFileSync(path.join(EVIDENCE, 'real-amap-console.log'), consoleLines.join('\n'))
  await page.screenshot({ path: path.join(EVIDENCE, 'p5-real-amap-itinerary.png'), fullPage: true })

  const provider = (itinerary as { provider?: string } | undefined)?.provider
  expect(provider, 'real AMap planning must produce an AMAP itinerary').toBe('AMAP')
  // Real AMap must have been hit for POI/route work.
  expect(entries.some((e) => e.url.includes('restapi.amap.com') || e.url.includes('/api/places/suggest'))).toBe(true)
})
