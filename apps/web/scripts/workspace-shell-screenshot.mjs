// Workspace Shell / Settings 视觉验收截图（Screenshot First Acceptance）。
// 仅截图，不修改任何页面状态。
//
// F-UI-11：新增 settings-page-desktop（方案 A：/workspace/settings 整页）。
// 全部视口统一经 Playwright route 拦截注入确定性数据（登录会话 + api-configs
// + 空 trips 列表），截图内容稳定、不依赖后端栈。
import { chromium } from '@playwright/test'

const BASE = process.env.SHELL_BASE_URL ?? 'http://localhost:5173'

const shots = [
  { name: 'workspace-shell-desktop', width: 1440, height: 900 },
  { name: 'workspace-shell-narrow', width: 1152, height: 800 },
  { name: 'workspace-shell-tablet', width: 900, height: 800 },
]

// F-UI-11：全部视口统一走 API stub。截图环境没有会话 Cookie，直连会渲染
// AuthView（登录页）；且任何漏网请求（如 /api/trips）会经 vite 代理打到真实
// 后端，拿假 token 返回 401，触发 withAccessToken 清空会话。因此必须拦截
// 全部 /api/** 并按 pathname 注入确定性数据，保证截图内容稳定、不依赖后端栈。
const SESSION_BODY = {
  user: { id: '11111111-1111-1111-1111-111111111111', email: 'traveler@example.com', displayName: '旅行者' },
  accessToken: 'screenshot-token',
  tokenType: 'Bearer',
  expiresIn: 900,
}
const API_CONFIGS_BODY = [
  { provider: 'PLANNER', apiKey: 'sk-****-demo', apiBaseUrl: 'https://api.example.com/v1', model: null, updatedAt: '2026-09-04T00:00:00Z' },
  { provider: 'KNOWLEDGE', apiKey: 'sk-****-demo', apiBaseUrl: 'https://dashscope.example.com/compatible-mode/v1', model: 'text-embedding-v4', updatedAt: '2026-09-04T00:00:00Z' },
]

function stubApi(page) {
  return page.route('**/api/**', (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path.endsWith('/api/auth/refresh')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SESSION_BODY) })
    }
    if (path.endsWith('/api/config/api-configs')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(API_CONFIGS_BODY) })
    }
    if (path.endsWith('/api/trips') && !path.includes('/trips/')) {
      // 工作台空态：无行程列表，页面渲染空态引导（确定性内容）。
      return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })
}

const browser = await chromium.launch()
for (const shot of shots) {
  const page = await browser.newPage({ viewport: { width: shot.width, height: shot.height } })
  await stubApi(page)
  await page.goto(`${BASE}/workspace`, { waitUntil: 'load' })
  await page.waitForTimeout(600)
  await page.screenshot({ path: `output/screenshots/${shot.name}.png` })
  await page.close()
  console.log(`captured ${shot.name} (${shot.width}x${shot.height})`)
}

// 设置页桌面视口（F-UI-11 方案 A：/workspace/settings 整页）
{
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  await stubApi(page)
  await page.goto(`${BASE}/workspace/settings`, { waitUntil: 'load' })
  await page.waitForTimeout(800)
  await page.screenshot({ path: 'output/screenshots/settings-page-desktop.png' })
  await page.close()
  console.log('captured settings-page-desktop (1440x900)')
}
await browser.close()
