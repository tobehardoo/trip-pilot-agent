import { expect, test, type Page, type Route } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

/**
 * P4 acceptance: real full-stack journeys against a healthy compose stack.
 *
 * No core API is mocked via page.route. A pass-through request recorder
 * captures a HAR-style network summary plus console log for evidence. Run
 * with:
 *
 *   P4_REAL_RUN=1 \
 *   PLAYWRIGHT_REAL_BASE_URL=http://127.0.0.1:8182 \
 *   PLAYWRIGHT_WEB_PORT=8182 \
 *   P4_EVIDENCE_DIR=test-results/p4 \
 *   pnpm exec playwright test e2e/p4-full-chain.spec.ts
 */
const REAL_BASE = process.env.PLAYWRIGHT_REAL_BASE_URL
const EVIDENCE = process.env.P4_EVIDENCE_DIR ?? 'test-results/p4'
const RUN_P4 = process.env.P4_REAL_RUN === '1'

test.skip(!REAL_BASE || !RUN_P4, 'set PLAYWRIGHT_REAL_BASE_URL and P4_REAL_RUN=1 to run the P4 acceptance suite')

interface NetworkEntry {
  method: string
  url: string
  status: number
  requestBody?: unknown
  responseBody?: unknown
  timestamp: number
}

interface Evidence {
  entries: NetworkEntry[]
  console: string[]
  ids: Record<string, string>
  step: string
}

function futureDate(daysFromNow: number): string {
  const d = new Date()
  d.setDate(d.getDate() + daysFromNow)
  return d.toISOString().slice(0, 10)
}

function evidenceDir(): string {
  mkdirSync(EVIDENCE, { recursive: true })
  return EVIDENCE
}

function writeEvidence(evidence: Evidence, name: string): void {
  writeFileSync(path.join(evidenceDir(), name), JSON.stringify(evidence, null, 2))
}

/** Pass-through network recorder; never modifies requests or responses. */
async function startRecorder(page: Page, evidence: Evidence): Promise<void> {
  await page.route('**/*', async (route: Route) => {
    const request = route.request()
    // Never buffer or hold streaming endpoints (SSE planning progress): pass
    // them straight through so the frontend receives live events.
    if ((request.headers()['accept'] ?? '').includes('text/event-stream')) {
      await route.continue()
      return
    }
    const entry: NetworkEntry = {
      method: request.method(),
      url: request.url(),
      status: 0,
      timestamp: Date.now(),
    }
    try {
      const response = await route.fetch()
      entry.status = response.status()
      const contentType = response.headers()['content-type'] ?? ''
      if (contentType.includes('json')) {
        try {
          entry.responseBody = await response.json()
        } catch {
          // keep status only
        }
      }
      evidence.entries.push(entry)
      await route.fulfill({ response, request })
    } catch {
      evidence.entries.push(entry)
      // A failed probe must never abort the user's request; let it proceed.
      await route.continue()
    }
  })
  page.on('console', (message) => {
    if (['error', 'warning'].includes(message.type())) {
      evidence.console.push(`[${message.type()}] ${message.text()}`)
    }
  })
}

function captureId(evidence: Evidence, urlSuffix: string, jsonPath: string): string | undefined {
  const match = evidence.entries
    .filter((e) => e.url.endsWith(urlSuffix) && e.responseBody)
    .pop()
  if (!match?.responseBody) return undefined
  return (match.responseBody as Record<string, unknown>)[jsonPath] as string
}

async function registerUser(page: Page, email: string): Promise<void> {
  await page.goto(REAL_BASE!, { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: '创建账户' }).click()
  await page.locator('#display-name').fill('P4真实全链')
  await page.locator('#email').fill(email)
  await page.locator('#password').fill('StrongPass123!')
  await page.getByRole('button', { name: '创建账户并登录' }).click()
  await page.waitForURL(/\/trips/, { timeout: 20_000 })
}

async function openCreateForm(page: Page): Promise<void> {
  await page.getByRole('button', { name: '创建旅行' }).first().click()
  await page.locator('#trip-title').waitFor({ timeout: 10_000 })
}

async function selectRegion(page: Page, province: string, city: string): Promise<void> {
  await page.selectOption('#region-province', { label: province })
  await expect(page.locator('#region-city')).toBeEnabled({ timeout: 10_000 })
  await page.selectOption('#region-city', { label: city })
}

async function selectPoi(page: Page, keyword: string): Promise<void> {
  await page.getByTestId('poi-search-input').fill(keyword)
  const results = page.getByTestId('poi-results')
  await results.waitFor({ timeout: 15_000 })
  // Only concrete POI rows can be locked; REGION/SUGGESTION rows are excluded.
  await results.getByTestId('poi-row').first().click()
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

test.describe('P4 real full-stack acceptance', () => {
  test('F1 basic chain: region-only trip plans end to end', async ({ page }) => {
    test.setTimeout(300_000)
    const evidence: Evidence = { entries: [], console: [], ids: {}, step: 'F1' }
    await startRecorder(page, evidence)
    const email = `p4-f1-${Date.now()}@example.com`
    await registerUser(page, email)

    await openCreateForm(page)
    await page.screenshot({ path: path.join(evidenceDir(), 'p4-01-region-selector.png'), fullPage: false })
    await page.locator('#trip-title').fill('广州基础场景')
    await selectRegion(page, '广东省', '广州')
    const start = futureDate(1)
    const end = futureDate(3)
    await page.locator('#start-date').fill(start)
    await page.locator('#end-date').fill(end)
    // Defaults: three meals, BALANCED, STANDARD.

    await page.getByRole('button', { name: '保存并开始规划' }).click()
    await page.waitForURL(/\/trips\/[0-9a-f-]{36}/, { timeout: 30_000 })
    await page.screenshot({ path: path.join(evidenceDir(), 'p4-04-created-workspace.png'), fullPage: true })

    const rendered = await waitForItinerary(page)
    await page.screenshot({ path: path.join(evidenceDir(), 'p4-05-itinerary-ready.png'), fullPage: true })

    evidence.ids.tripId = captureId(evidence, '/api/trips', 'id') ?? ''
    evidence.ids.planningTaskId = captureId(evidence, '/planning-tasks', 'taskId') ?? ''
    evidence.ids.itineraryVersionId = captureId(evidence, '/itinerary', 'versionId') ?? ''
    writeEvidence(evidence, 'f1-evidence.json')

    expect(rendered, 'the real itinerary should render after planning completes').toBe(true)
    expect(evidence.entries.some((e) => e.url.includes('/api/trips') && e.method === 'POST')).toBe(true)
  })

  test('F2 full POI chain: arrival/departure/hotel anchors plan with coords', async ({ page }) => {
    test.setTimeout(360_000)
    const evidence: Evidence = { entries: [], console: [], ids: {}, step: 'F2' }
    await startRecorder(page, evidence)
    const email = `p4-f2-${Date.now()}@example.com`
    await registerUser(page, email)

    await openCreateForm(page)
    await page.locator('#trip-title').fill('广州完整POI场景')
    await selectRegion(page, '广东省', '广州')
    // Optional district multi-select.
    await page.getByText('越秀区', { exact: true }).click()
    const start = futureDate(1)
    const end = futureDate(3)
    await page.locator('#start-date').fill(start)
    await page.locator('#end-date').fill(end)

    // Arrival anchor.
    await page.getByPlaceholder('搜索到达站（如：广州南站）').fill('广州南站')
    const arrivalResults = page.getByTestId('poi-results')
    await arrivalResults.waitFor({ timeout: 15_000 })
    await page.screenshot({ path: path.join(evidenceDir(), 'p4-02-poi-mixed-results.png'), fullPage: false })
    await arrivalResults.getByTestId('poi-row').first().click()
    await page.screenshot({ path: path.join(evidenceDir(), 'p4-03-poi-locked.png'), fullPage: false })
    await page.locator('#arrival-date').fill(start)
    await page.locator('#arrival-time').fill('14:30')

    // Departure anchor.
    await page.getByPlaceholder('搜索返程站（如：广州白云机场）').fill('广州白云机场')
    const departureResults = page.getByTestId('poi-results')
    await departureResults.waitFor({ timeout: 15_000 })
    await departureResults.getByTestId('poi-row').first().click()
    await page.locator('#departure-date').fill(end)
    await page.locator('#departure-time').fill('16:00')

    // Hotel anchor (scene-filtered to lodging).
    await page.getByPlaceholder('搜索酒店门店').fill('希尔顿')
    const hotelResults = page.getByTestId('poi-results')
    await hotelResults.waitFor({ timeout: 15_000 })
    await hotelResults.getByTestId('poi-row').first().click()

    await page.getByRole('button', { name: '保存并开始规划' }).click()
    await page.waitForURL(/\/trips\/[0-9a-f-]{36}/, { timeout: 30_000 })
    const rendered = await waitForItinerary(page)

    evidence.ids.tripId = captureId(evidence, '/api/trips', 'id') ?? ''
    evidence.ids.planningTaskId = captureId(evidence, '/planning-tasks', 'taskId') ?? ''
    evidence.ids.itineraryVersionId = captureId(evidence, '/itinerary', 'versionId') ?? ''
    writeEvidence(evidence, 'f2-evidence.json')

    expect(rendered, 'the full POI itinerary should render').toBe(true)
    expect(evidence.entries.some((e) => e.url.includes('/api/places/suggest'))).toBe(true)
  })

  test('F3 modal stability: repeated open/close, in-flight search, no crash', async ({ page }) => {
    test.setTimeout(180_000)
    const evidence: Evidence = { entries: [], console: [], ids: {}, step: 'F3' }
    await startRecorder(page, evidence)
    const email = `p4-f3-${Date.now()}@example.com`
    await registerUser(page, email)

    // Open/close the modal twenty times.
    for (let i = 0; i < 20; i += 1) {
      await openCreateForm(page)
      await page.locator('#trip-title').fill(`往返第${i}次`)
      await page.getByRole('button', { name: '关闭' }).click()
      await page.waitForURL(/\/trips$/, { timeout: 10_000 })
    }

    // Fast input then close while the suggest request is in flight.
    await openCreateForm(page)
    await selectRegion(page, '广东省', '广州')
    await page.getByPlaceholder('搜索到达站（如：广州南站）').fill('广州南')
    await page.getByRole('button', { name: '关闭' }).click()
    await page.waitForURL(/\/trips$/, { timeout: 10_000 })

    // City switch during search.
    await openCreateForm(page)
    await selectRegion(page, '广东省', '广州')
    await page.getByPlaceholder('搜索到达站（如：广州南站）').fill('广州南站')
    await page.getByTestId('poi-results').waitFor({ timeout: 15_000 })
    await selectRegion(page, '广东省', '深圳')
    await expect(page.getByTestId('poi-results')).toHaveCount(0)

    // Modal still functional.
    await page.locator('#trip-title').fill('稳定弹窗')
    await expect(page.locator('#trip-title')).toHaveValue('稳定弹窗')
    writeEvidence(evidence, 'f3-evidence.json')

    // No unhandled promise rejections or Vue runtime errors.
    const errors = evidence.console.filter((line) => /Uncaught|Vue warn|\[Vue warn\]/.test(line))
    expect(errors).toEqual([])
  })

  test('F4 invalid input: unselected text and incomplete anchors are rejected', async ({ page }) => {
    test.setTimeout(180_000)
    const evidence: Evidence = { entries: [], console: [], ids: {}, step: 'F4' }
    await startRecorder(page, evidence)
    const email = `p4-f4-${Date.now()}@example.com`
    await registerUser(page, email)

    await openCreateForm(page)
    await page.locator('#trip-title').fill('无效输入场景')
    await selectRegion(page, '广东省', '广州')
    const start = futureDate(1)
    const end = futureDate(3)
    await page.locator('#start-date').fill(start)
    await page.locator('#end-date').fill(end)

    // Unselected free text with a time set must not submit an anchor.
    await page.getByPlaceholder('搜索到达站（如：广州南站）').fill('广州南站')
    await page.locator('#arrival-time').fill('14:30')
    await page.getByRole('button', { name: '保存并开始规划' }).click()
    await expect(page.getByRole('alert')).toContainText('请从列表中选择到达地点')

    // REGION/SUGGESTION rows must not produce a lockable POI.
    await page.getByPlaceholder('搜索到达站（如：广州南站）').fill('广州南站')
    const results = page.getByTestId('poi-results')
    await results.waitFor({ timeout: 15_000 })
    const suggestionRows = results.getByTestId('poi-suggestion-row')
    if ((await suggestionRows.count()) > 0) {
      await suggestionRows.first().click()
      await expect(page.getByPlaceholder('搜索到达站（如：广州南站）')).toBeVisible()
    }

    // A missing arrival time while a POI is selected must be rejected.
    await page.getByPlaceholder('搜索到达站（如：广州南站）').fill('广州南站')
    const results2 = page.getByTestId('poi-results')
    await results2.waitFor({ timeout: 15_000 })
    await results2.getByTestId('poi-row').first().click()
    await page.locator('#arrival-date').fill(start)
    await page.locator('#arrival-time').fill('')
    await page.getByRole('button', { name: '保存并开始规划' }).click()
    await expect(page.getByRole('alert')).toContainText('请从列表中选择到达地点，并完整填写到达日期和时间')

    // Past start date is rejected by the backend date policy.
    await page.getByRole('button', { name: '重新选择' }).first().click()
    await page.locator('#arrival-time').fill('')
    await page.locator('#start-date').fill(futureDate(-2))
    await page.locator('#end-date').fill(futureDate(2))
    await page.getByRole('button', { name: '保存并开始规划' }).click()
    await expect(page.getByRole('alert')).toBeVisible()
    writeEvidence(evidence, 'f4-evidence.json')
  })
})
