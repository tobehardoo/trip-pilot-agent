// F-UI-8 交互验收（Playwright，非静态截图）：
//   A 旅行切换 A→B→C→A（数据上下文 + URL 同步 + 刷新恢复）
//   B 新建旅行完整闭环（抽屉 → 表单 → 创建 → 列表新增 + 自动选中 + draft 空态）
//   C Agent 执行过程默认折叠（展开可看过程）
//   D Tool Call 详情二级折叠（默认收起）
//   E 规划完成默认攻略（completed 态显示攻略，Agent 过程折叠于底部）
//   F 命令条提交 → 指令写入当前旅行上下文（诚实反馈）
import { chromium } from '@playwright/test'
import { mkdirSync } from 'node:fs'

const BASE = process.env.SHELL_BASE_URL ?? 'http://localhost:5173'
const OUT = 'output/screenshots'
mkdirSync(OUT, { recursive: true })

const results = []
let failed = 0

function check(name, cond, extra = '') {
  const ok = !!cond
  results.push({ name, ok })
  if (!ok) failed++
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? `  — ${extra}` : ''}`)
}

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
// 幂等：先加载一次清空 localStorage，再重载进入干净状态（避免残留上次新建的旅行）。
// 注意：不能用 addInitScript —— 它会在每次刷新时执行，反而破坏"刷新恢复"验收。
await page.goto(`${BASE}/workspace`, { waitUntil: 'load' })
await page.evaluate(() => localStorage.clear())
await page.reload({ waitUntil: 'load' })
await page.waitForSelector('[data-testid="workspace-shell"]')
await page.waitForTimeout(800)
check('A0 默认选中上海（侧边栏 aria-current）',
  (await page.locator('[data-testid="workspace-project-shanghai"]').getAttribute('aria-current')) === 'true')
check('A1 Header 状态 = 规划中',
  (await page.locator('[data-testid="header-agent-state"]').innerText()).includes('规划中'))
check('C1 Agent 过程默认折叠（aria-expanded=false）',
  (await page.locator('[data-testid="agent-timeline-toggle"]').getAttribute('aria-expanded')) === 'false')
check('C2 收起时时间线步骤不可见',
  (await page.locator('[data-testid="step-solving"]').count()) === 0)

// 展开 Agent 过程
await page.click('[data-testid="agent-timeline-toggle"]')
await page.waitForTimeout(200)
check('C3 展开后时间线步骤可见',
  (await page.locator('[data-testid="step-solving"]').count()) === 1)
check('C4 求解器工具卡可见',
  (await page.locator('[data-testid="tool-execution-card"]').count()) === 1)
check('D1 Tool Call 详情默认收起（aria-expanded=false）',
  (await page.locator('[data-testid="tool-execution-toggle"]').getAttribute('aria-expanded')) === 'false')
await page.click('[data-testid="agent-timeline-toggle"]') // 收回，不影响后续

// ── 2. 切换 → 广州（completed）──
await page.click('[data-testid="workspace-project-guangzhou"]')
await page.waitForURL('**/workspace/trips/guangzhou')
check('A2 URL 同步 → /workspace/trips/guangzhou', true)
check('A3 Header 状态 = 已完成',
  (await page.locator('[data-testid="header-agent-state"]').innerText()).includes('已完成'))
check('E1 完成态显示攻略（广州·沙面岛）',
  (await page.locator('[data-testid="plan-activity-沙面岛"]').count()) === 1)
check('E2 完成态主区无 Agent 时间线折叠头',
  (await page.locator('[data-testid="agent-timeline-toggle"]').count()) === 0)
check('E3 完成态 Agent 过程默认收起（aria-expanded=false）',
  (await page.locator('[data-testid="toggle-agent-process"]').getAttribute('aria-expanded')) === 'false')
check('A4 右栏数据上下文 = 广州（目的地）',
  (await page.locator('aside').innerText()).includes('广州'))
await page.screenshot({ path: `${OUT}/f-ui-8-guangzhou.png` })

// ── 3. 切换 → 北京 ──
await page.click('[data-testid="workspace-project-beijing"]')
await page.waitForURL('**/workspace/trips/beijing')
check('A5 URL 同步 → /workspace/trips/beijing', true)
check('A6 显示北京攻略（故宫博物院）',
  (await page.locator('[data-testid="plan-activity-故宫博物院"]').count()) === 1)

// ── 4. 切回 → 上海 ──
await page.click('[data-testid="workspace-project-shanghai"]')
await page.waitForURL('**/workspace/trips/shanghai')
check('A7 切回上海 → Header 规划中',
  (await page.locator('[data-testid="header-agent-state"]').innerText()).includes('规划中'))
check('A8 切回后攻略消失（回到时间线态）',
  (await page.locator('[data-testid="plan-activity-故宫博物院"]').count()) === 0)
await page.screenshot({ path: `${OUT}/f-ui-8-shanghai.png` })

// ── 5. 新建旅行完整闭环 ──
await page.click('[data-testid="workspace-new-trip"]')
await page.waitForSelector('[data-testid="new-trip-form"]')
check('B1 新建旅行抽屉打开', true)
await page.fill('[data-testid="new-trip-title"]', '杭州周末游')
await page.fill('[data-testid="new-trip-destination"]', '杭州')
await page.fill('[data-testid="new-trip-dates"]', '9月20日 — 9月22日')
await page.fill('[data-testid="new-trip-people"]', '2 人')
await page.fill('[data-testid="new-trip-budget"]', '¥2000')
await page.fill('[data-testid="new-trip-preferences"]', '自然风光')
await page.screenshot({ path: `${OUT}/f-ui-8-new-trip-form.png` })
await page.click('[data-testid="new-trip-submit"]')
await page.waitForURL('**/workspace/trips/trip-*')
await page.waitForTimeout(400)
check('B2 创建后 URL → /workspace/trips/trip-*', true)
check('B3 新旅行出现在左侧列表',
  (await page.locator('[data-testid^="workspace-project-trip-"]').count()) === 1)
check('B4 Header = 杭州周末游',
  (await page.locator('header').innerText()).includes('杭州周末游'))
check('B5 Header 状态 = 未规划',
  (await page.locator('[data-testid="header-agent-state"]').innerText()).includes('未规划'))
check('B6 中间区 draft 空态可见',
  (await page.locator('[data-testid="workspace-draft-empty"]').count()) === 1)
check('B7 右栏目的地 = 杭州',
  (await page.locator('aside').innerText()).includes('杭州'))
await page.screenshot({ path: `${OUT}/f-ui-8-new-trip-created.png` })

// ── 6. 刷新恢复（URL → 数据上下文）──
await page.reload({ waitUntil: 'load' })
await page.waitForSelector('[data-testid="workspace-shell"]')
await page.waitForTimeout(600)
check('A9 刷新后仍选中新旅行（Header = 杭州周末游）',
  (await page.locator('header').innerText()).includes('杭州周末游'))

// ── 7. 切回上海（新旅行保留）──
await page.click('[data-testid="workspace-project-shanghai"]')
await page.waitForURL('**/workspace/trips/shanghai')
check('B8 新建旅行保留在列表',
  (await page.locator('[data-testid^="workspace-project-trip-"]').count()) === 1)

// ── 8. Command Bar 指令记录 ──
await page.fill('[data-testid="workspace-command-input"]', '把第一天的晚餐换成西湖醋鱼老字号')
await page.click('[data-testid="workspace-command-send"]')
await page.waitForSelector('[data-testid="command-channel-hint"]')
const hint = await page.locator('[data-testid="command-channel-hint"]').innerText()
check('F1 指令提交有记录反馈', hint.includes('已记录指令'), hint)
await page.screenshot({ path: `${OUT}/f-ui-8-command-recorded.png` })

await browser.close()
console.log(`\n${results.length - failed}/${results.length} 项验收通过`)
process.exit(failed ? 1 : 0)
