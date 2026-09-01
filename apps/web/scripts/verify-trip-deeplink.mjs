// F-5 深链接回归验证：整页导航（等价于刷新/深链接）到 /workspace/trips/:id 时，
// 中间区必须渲染真实 trip 数据；出现「未选择旅行」空状态即视为失败（exit 1）。
// 用法：node scripts/verify-trip-deeplink.mjs [BASE_URL] [TRIP_ID]
import { chromium } from '@playwright/test'

const BASE = process.env.SHELL_BASE_URL ?? process.argv[2] ?? 'http://127.0.0.1:38080'
const tripId = process.argv[3] ?? 'bd897a90-b559-4483-85d9-a8c97db4a632' // 杭州 · AI 行程

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
let failures = 0

// 1. 登录
await page.goto(`${BASE}/login`, { waitUntil: 'load' })
await page.waitForSelector('#email', { timeout: 8000 })
await page.locator('#email').fill('admin@admin.com')
await page.locator('#password').fill('Admin123456')
await page.locator('button[type="submit"]').click()
await page.waitForFunction(() => !location.pathname.startsWith('/login'), { timeout: 10000 })
await page.waitForTimeout(3000)
console.log(`step1 login ok, url=${page.url()}`)

// 2. 整页导航到 trip URL（模拟刷新/深链接）
await page.goto(`${BASE}/workspace/trips/${tripId}`, { waitUntil: 'load' })
await page.waitForTimeout(5000)

const mainText = await page.locator('[data-testid="workspace-main"]').innerText().catch(() => '')
const emptyCount = await page.getByText('未选择旅行').count()
const restoring = await page.locator('[data-testid="workspace-restoring"]').count()
const auth = await page.locator('[data-testid="workspace-auth"]').count()

console.log(`url: ${page.url()}`)
console.log(`main (first 200): ${JSON.stringify(mainText.slice(0, 200))}`)
console.log(`empty-state「未选择旅行」count: ${emptyCount} | restoring: ${restoring} | auth: ${auth}`)

if (auth > 0 || restoring > 0) {
  console.error('FAIL: 页面未进入已登录工作区')
  failures += 1
}
if (emptyCount > 0) {
  console.error('FAIL: trip 详情未加载，退化为「未选择旅行」空状态（深链接 bug 回归）')
  failures += 1
}
if (!mainText.includes('杭州')) {
  console.error('FAIL: main 区未渲染 trip 真实数据')
  failures += 1
}

await page.screenshot({ path: 'output/screenshots/verify-trip-deeplink.png' })
await browser.close()

if (failures > 0) {
  console.error(`\n${failures} failure(s)`)
  process.exit(1)
}
console.log('\nPASS: 深链接 trip 详情渲染真实数据')
