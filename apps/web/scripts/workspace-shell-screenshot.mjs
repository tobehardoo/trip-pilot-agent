// Workspace Shell 视觉验收截图（Phase 1 Screenshot First Acceptance）。
// 仅截图，不修改任何页面状态。
import { chromium } from '@playwright/test'

const BASE = process.env.SHELL_BASE_URL ?? 'http://localhost:5173'

const shots = [
  { name: 'workspace-shell-desktop', width: 1440, height: 900 },
  { name: 'workspace-shell-narrow', width: 1152, height: 800 },
  { name: 'workspace-shell-tablet', width: 900, height: 800 },
]

const browser = await chromium.launch()
for (const shot of shots) {
  const page = await browser.newPage({ viewport: { width: shot.width, height: shot.height } })
  await page.goto(`${BASE}/workspace`, { waitUntil: 'load' })
  await page.waitForTimeout(600)
  await page.screenshot({ path: `output/screenshots/${shot.name}.png` })
  await page.close()
  console.log(`captured ${shot.name} (${shot.width}x${shot.height})`)
}
await browser.close()
