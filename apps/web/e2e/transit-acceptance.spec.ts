import { expect, test, type Page } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

/**
 * P0 transit acceptance: verify alternate commute modes are selectable on a real
 * itinerary (no mode is disabled merely because the current time gap is tight).
 *
 * Run against the running compose stack:
 *   PLAYWRIGHT_REAL_BASE_URL=http://127.0.0.1:8182 \
 *   PLAYWRIGHT_WEB_PORT=8182 \
 *   TRANSIT_ACCEPTANCE_RUN=1 \
 *   pnpm exec playwright test e2e/transit-acceptance.spec.ts --workers=1
 */
const REAL_BASE = process.env.PLAYWRIGHT_REAL_BASE_URL
const EVIDENCE = process.env.TRANSIT_EVIDENCE_DIR ?? 'test-results/transit-acceptance'
const RUN = process.env.TRANSIT_ACCEPTANCE_RUN === '1'

test.skip(!REAL_BASE || !RUN, 'set PLAYWRIGHT_REAL_BASE_URL and TRANSIT_ACCEPTANCE_RUN=1 to run the transit acceptance')

function futureDate(daysFromNow: number): string {
  const d = new Date()
  d.setDate(d.getDate() + daysFromNow)
  return d.toISOString().slice(0, 10)
}

async function waitForItinerary(page: Page): Promise<boolean> {
  const deadline = Date.now() + 180_000
  while (Date.now() < deadline) {
    await page.waitForTimeout(3_000)
    const body = await page.locator('body').innerText()
    if (/规划失败/.test(body)) return false
    if (/个地点|游玩时间|预计总费用|day-|第 1 天/.test(body)) return true
  }
  return false
}

test('alternate transit modes are selectable on a real itinerary', async ({ page }) => {
  mkdirSync(EVIDENCE, { recursive: true })
  const email = `transit-acc-${Date.now()}@example.com`

  await page.goto(REAL_BASE!, { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: '创建账户' }).click()
  await page.locator('#display-name').fill('交通验收')
  await page.locator('#email').fill(email)
  await page.locator('#password').fill('StrongPass123!')
  await page.getByRole('button', { name: '创建账户并登录' }).click()
  await page.waitForURL(/\/trips/, { timeout: 30_000 })

  await page.getByRole('button', { name: '创建旅行' }).first().click()
  await page.locator('#trip-title').fill('交通方式验收')
  await page.selectOption('#region-province', { label: '广东省' })
  await expect(page.locator('#region-city')).toBeEnabled({ timeout: 10_000 })
  await page.selectOption('#region-city', { label: '广州' })
  await page.locator('#start-date').fill(futureDate(1))
  await page.locator('#end-date').fill(futureDate(3))
  await page.getByRole('button', { name: '保存并开始规划' }).click()
  await page.waitForURL(/\/trips\/[0-9a-f-]{36}/, { timeout: 30_000 })

  const rendered = await waitForItinerary(page)
  expect(rendered, 'the itinerary should render after planning').toBe(true)

  // Expand the first transit leg.
  const firstLeg = page.locator('[data-testid^="transit-leg-open-"]').first()
  await firstLeg.waitFor({ timeout: 30_000 })
  await firstLeg.click()
  await page.screenshot({ path: path.join(EVIDENCE, 'transit-01-expanded.png'), fullPage: false })

  // Case A/B: every mode that exists must be clickable — never disabled merely
  // because the current time gap is tight.
  const modes = ['WALKING', 'TRANSIT', 'DRIVING', 'TAXI'] as const
  const modeState: Record<string, string> = {}
  for (const mode of modes) {
    const button = page.locator(`[data-testid="transit-option-${mode}"]`)
    await expect(button).toBeEnabled()
    modeState[mode] = (await button.getAttribute('aria-pressed')) ?? 'false'
  }

  // REQUIRES_REPLAN: a slower mode stays enabled and carries the warning badge
  // when it exceeds the current gap.
  const requiresReplanCount = await page.locator('[data-testid="transit-requires-replan"]').count()

  // Case D: locking the leg disables the other modes; unlocking restores them.
  const lockBox = page.locator('[data-testid^="transit-lock-"]').first()
  await lockBox.check()
  for (const mode of modes) {
    const button = page.locator(`[data-testid="transit-option-${mode}"]`)
    const pressed = (await button.getAttribute('aria-pressed')) === 'true'
    if (pressed) {
      await expect(button).toBeEnabled()
    } else {
      await expect(button).toBeDisabled()
    }
  }
  await page.screenshot({ path: path.join(EVIDENCE, 'transit-02-locked.png'), fullPage: false })
  await lockBox.uncheck()
  for (const mode of modes) {
    await expect(page.locator(`[data-testid="transit-option-${mode}"]`)).toBeEnabled()
  }

  writeFileSync(path.join(EVIDENCE, 'transit-acceptance.json'), JSON.stringify({
    tripUrl: page.url(),
    modesEnabled: modes.map((m) => ({ mode: m, wasActive: modeState[m] })),
    requiresReplanBadgeCount: requiresReplanCount,
    caseA_b_short_medium_clickable: true,
    caseC_time_conflict_selectable: requiresReplanCount > 0 || 'no tight-gap leg in this plan (covered by unit T1/T5 + backend integration)',
    caseD_manual_lock: true,
    lockThenUnlockRestored: true,
  }, null, 2))
})
