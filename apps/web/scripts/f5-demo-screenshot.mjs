// F-5 Demo 验证：登录 + workspace + 真实 trip 页面截图。
import { chromium } from '@playwright/test'

const BASE = process.env.SHELL_BASE_URL ?? process.argv[2] ?? 'http://127.0.0.1:38080'
const OUT = 'output/screenshots'
const tripId = process.argv[3] ?? 'bd897a90-b559-4483-85d9-a8c97db4a632' // 杭州 · AI 行程

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

// 1. 登录
await page.goto(`${BASE}/login`, { waitUntil: 'load' })
await page.waitForSelector('#email', { timeout: 8000 })
await page.waitForTimeout(500)
await page.locator('#email').fill('admin@admin.com')
await page.locator('#password').fill('Admin123456')
await page.locator('button[type="submit"]').click()
await page.waitForFunction(() => !location.pathname.startsWith('/login'), { timeout: 10000 })
console.log(`login ok, current url: ${page.url()}`)

// 2. workspace 主页（等更长让 trip 列表加载）
await page.waitForTimeout(6000)
await page.screenshot({ path: `${OUT}/f5-demo-workspace.png` })
await page.screenshot({ path: `${OUT}/f5-demo-workspace-full.png`, fullPage: true })
console.log(`workspace captured`)

// 3. 直接进真实 trip 页面（杭州 · AI 行程）
await page.goto(`${BASE}/workspace/trips/${tripId}`, { waitUntil: 'load' })
await page.waitForTimeout(5000)
await page.screenshot({ path: `${OUT}/f5-demo-trip.png` })
await page.screenshot({ path: `${OUT}/f5-demo-trip-full.png`, fullPage: true })
console.log(`trip page captured, url: ${page.url()}`)

console.log(`\nfinal url: ${page.url()}`)
console.log(`title: ${await page.title()}`)

await browser.close()
