import { expect, test, type Page } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

/** Scan every transit leg on a real itinerary for the REQUIRES_REPLAN case. */
const REAL_BASE = process.env.PLAYWRIGHT_REAL_BASE_URL
const EVIDENCE = process.env.TRANSIT_EVIDENCE_DIR ?? 'test-results/transit-case-c'
const RUN = process.env.TRANSIT_ACCEPTANCE_RUN === '1'

test.skip(!REAL_BASE || !RUN, 'set PLAYWRIGHT_REAL_BASE_URL and TRANSIT_ACCEPTANCE_RUN=1')

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

test('every leg keeps slow modes enabled and marks them requires-replan when the gap is tight', async ({ page }) => {
  mkdirSync(EVIDENCE, { recursive: true })
  const email = `transit-c3-${Date.now()}@example.com`

  await page.goto(REAL_BASE!, { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: '创建账户' }).click()
  await page.locator('#display-name').fill('交通C3')
  await page.locator('#email').fill(email)
  await page.locator('#password').fill('StrongPass123!')
  await page.getByRole('button', { name: '创建账户并登录' }).click()
  await page.waitForURL(/\/trips/, { timeout: 30_000 })

  await page.getByRole('button', { name: '创建旅行' }).first().click()
  await page.locator('#trip-title').fill('交通C3验收')
  await page.selectOption('#region-province', { label: '广东省' })
  await expect(page.locator('#region-city')).toBeEnabled({ timeout: 10_000 })
  await page.selectOption('#region-city', { label: '广州' })
  await page.locator('#start-date').fill(futureDate(1))
  await page.locator('#end-date').fill(futureDate(3))
  await page.getByRole('button', { name: '保存并开始规划' }).click()
  await page.waitForURL(/\/trips\/[0-9a-f-]{36}/, { timeout: 30_000 })
  expect(await waitForItinerary(page), 'the itinerary should render').toBe(true)

  const legs = page.locator('[data-testid^="transit-leg-open-"]')
  const count = await legs.count()
  const findings: Array<Record<string, unknown>> = []

  for (let index = 0; index < count; index += 1) {
    await legs.nth(index).click()
    const badgeCount = await page.locator('[data-testid="transit-requires-replan"]').count()
    const allEnabled = await (async () => {
      for (const mode of ['WALKING', 'TRANSIT', 'DRIVING', 'TAXI'] as const) {
        const button = page.locator(`[data-testid="transit-option-${mode}"]`)
        const disabled = await button.isDisabled().catch(() => false)
        if (disabled) return false
      }
      return true
    })()
    findings.push({ legIndex: index, requiresReplanModes: badgeCount, allModesEnabled: allEnabled })
    await legs.nth(index).click() // collapse
  }

  writeFileSync(path.join(EVIDENCE, 'transit-case-c.json'), JSON.stringify({
    legsScanned: count,
    legsWithRequiresReplan: findings.filter((f) => f.requiresReplanModes! > 0).length,
    findings,
  }, null, 2))

  // 即使存在 REQUIRES_REPLAN 的 leg，所有方式也必须可点击。
  const anyDisabled = findings.some((f) => !f.allModesEnabled)
  expect(anyDisabled, 'no mode may be disabled merely because the gap is tight').toBe(false)
})
