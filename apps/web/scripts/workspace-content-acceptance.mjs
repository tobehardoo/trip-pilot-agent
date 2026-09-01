// F-UI-10 内容层交互验收（Playwright，浏览器实测）：
// 核心模型转换（用户 §16）：Agent Execution 是消息，不是 Card；
// Tool Call 是消息的附加详情；Timeline 是辅助；旅行攻略是完成后的主内容。
//
// 验收组：
//   1. 无大长方框（智能体执行过程 Card 已删除）
//   2. Agent 像在和用户说话（对话流：用户消息 + Agent 消息）
//   3. Tool Call 默认隐藏（消息内的可展开详情）
//   4. 规划完成用户第一眼看到攻略（结果优先）
//   5. completed 完成消息 + 底部"查看智能体规划过程"折叠
//   6. 编辑约束 / Command Bar 等既有闭环回归
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

// 幂等：先加载清空 localStorage，再重载进入干净状态（不影响"刷新恢复"验收）
await page.goto(`${BASE}/workspace`, { waitUntil: 'load' })
await page.evaluate(() => localStorage.clear())
await page.reload({ waitUntil: 'load' })
await page.waitForSelector('[data-testid="workspace-shell"]')
await page.waitForTimeout(800)

// ── 上海 planning：对话流 ──
check('5a 规划态显示旅行标题',
  (await page.locator('main h1').first().innerText()) === '上海三日旅行')
check('5b 显示"TripPilot 正在规划你的旅行"摘要',
  (await page.locator('[data-testid="planning-status-line"]').innerText()).includes('正在规划你的旅行'))

// ⑪ 规划态地图区（§17 planning）：显示"路线正在生成"，绝不伪造路线
check('11a 规划态有旅行概览 + 旅行路线区块',
  (await page.locator('[data-testid="plan-header-meta"]').count()) === 1 &&
  (await page.locator('[data-testid="trip-route-section"]').count()) === 1)
check('11b 规划态地图区显示"路线正在生成"占位',
  (await page.locator('[data-testid="trip-route-placeholder"]').innerText()).includes('路线正在生成'))
check('11c 规划态不伪造路线（无 marker、无路线摘要、无统计）',
  (await page.locator('.amap-marker-pin').count()) === 0 &&
  (await page.locator('[data-testid="trip-route-line"]').count()) === 0 &&
  (await page.locator('[data-testid="trip-route-stats"]').count()) === 0)

// ① 大长方框已删除：旧折叠 Card 头不存在
check('1a 旧"智能体执行过程"Card 头已删除',
  (await page.locator('[data-testid="agent-timeline-toggle"]').count()) === 0)
check('1b 主区是对话流容器（agent-conversation）',
  (await page.locator('[data-testid="agent-conversation"]').count()) === 1)

// ② Agent 像在和用户说话：用户消息 + Agent 消息
check('2a 用户消息可见（初始需求）',
  (await page.locator('[data-testid="user-message"]').innerText()).includes('帮我规划一个上海三日旅行'))
check('2b 历史步骤为简洁行（Agent 消息，无 Card）',
  (await page.locator('[data-testid="agent-message-understand"]').innerText()).includes('已理解旅行需求'))
check('2c 当前运行步骤为完整 Agent 消息（正在优化旅行路线）',
  (await page.locator('[data-testid="agent-message-solving"]').innerText()).includes('正在优化旅行路线'))
check('2d 运行消息含正文（正在检查候选地点之间的交通时间）',
  (await page.locator('[data-testid="agent-message-solving"]').innerText()).includes('正在检查候选地点之间的交通时间'))

// ③ Tool Call 默认隐藏：消息内的可展开详情，不是独立 Card
check('3a Tool 详情默认收起（panel 不可见）',
  (await page.locator('[data-testid="tool-detail-panel"]').count()) === 0)
check('3b 有"查看路线优化详情"轻链接',
  (await page.locator('[data-testid="tool-detail-toggle"]').innerText()).includes('查看路线优化详情'))
await page.click('[data-testid="tool-detail-toggle"]')
await page.waitForTimeout(150)
const detailPanel = page.locator('[data-testid="tool-detail-panel"]')
check('3c 展开后可见工具详情（OR-Tools）',
  (await detailPanel.innerText()).includes('OR-Tools'))
check('3d 展开后可见输入指标（候选地点 24）',
  (await detailPanel.innerText()).includes('候选地点'))
check('3e 详情是轻量缩进（无独立 Card 容器 testid 旧契约 tool-execution-card）',
  (await page.locator('[data-testid="tool-execution-card"]').count()) === 0)
await page.click('[data-testid="tool-detail-toggle"]')
await page.waitForTimeout(150)
check('3f 再点收起（panel 不可见）',
  (await page.locator('[data-testid="tool-detail-panel"]').count()) === 0)
await page.screenshot({ path: `${OUT}/f-ui-10-planning.png` })

// ── 广州 completed：结果优先 + 完成消息 ──
await page.click('[data-testid="workspace-project-guangzhou"]')
await page.waitForURL('**/workspace/trips/guangzhou')
await page.waitForTimeout(300)
check('1c 广州攻略头部元信息（目的地·日期·天数·人数·预算）',
  (await page.locator('[data-testid="plan-header-meta"]').innerText()).includes('广州 · 9月6日 — 9月7日 · 2 天 · 2 人 · ¥2000'))
check('4a 完成态第一眼看到攻略（广州早茶）',
  (await page.locator('[data-testid="plan-activity-广州早茶 · 老字号茶楼"]').count()) === 1)
check('4b 完成态主区默认无 Agent 对话流（攻略优先，过程在底部折叠）',
  (await page.locator('main [data-testid="agent-conversation"]').count()) === 0)
check('4c Agent 完成消息可见（§10：旅行方案已经完成）',
  (await page.locator('[data-testid="agent-message-done"]').innerText()).includes('旅行方案已经完成'))
check('4d 完成消息像在说话（根据你的预算 ¥2000 安排行程）',
  (await page.locator('[data-testid="agent-message-done"]').innerText()).includes('预算¥2000'))
check('1b 广州攻略内容（沙面岛）',
  (await page.locator('main').innerText()).includes('沙面岛'))
check('1c 广州攻略内容（陈家祠）',
  (await page.locator('main').innerText()).includes('陈家祠'))

// ── ⑪ 地图恢复 + 中央内容层级（§19 A/B/F）──
const main = page.locator('[data-testid="workspace-main"]')
const resetScroll = async () => {
  await main.evaluate((el) => { el.scrollTop = 0 })
  await page.waitForTimeout(120)
}
const VH = 900 // 视口高度 = 第一屏

// 等真实高德 SDK 渲染 marker（不是降级 SVG 概览）
await page.waitForFunction(() => document.querySelectorAll('.amap-marker-pin').length > 0, null, { timeout: 20000 })
// 等底图瓦片渲染（PBF→canvas，需要时间）
await page.waitForTimeout(2500)
await resetScroll()

check('11d 地图真实显示（高德 SDK ready，非降级概览）',
  (await page.locator('[data-testid="trip-map"] span[aria-live]').textContent()).includes('高德地图') &&
  (await page.evaluate(() => typeof window.AMap !== 'undefined')))
check('11e 广州 8 个可定位地点 → 8 个 POI marker',
  (await page.locator('.amap-marker-pin').count()) === 8,
  `实际 ${await page.locator('.amap-marker-pin').count()} 个`)
check('11f 路线统计正确（8 个地点 · 2 天 · 预计交通）',
  (await page.locator('[data-testid="trip-route-stats"]').innerText()).includes('8 个地点 · 2 天 · 预计交通'))
check('11g 路线摘要首个地点为 ①广州早茶',
  (await page.locator('[data-testid="trip-route-place-0"]').innerText()).includes('广州早茶'))
check('11h 不可定位地点不打点（"返程预留"不在路线摘要中）',
  !(await page.locator('[data-testid="trip-route-line"]').innerText()).includes('返程预留'))

const mapBox = await page.locator('[data-testid="trip-route-map"]').boundingBox()
const mainBox = await main.boundingBox()
check('11i 地图高度在 320~420px（视觉锚点且不撑爆 Workspace）',
  mapBox.height >= 320 && mapBox.height <= 420, `${Math.round(mapBox.height)}px`)
check('11j 地图宽度不超出中间工作区（不遮挡页面）',
  mapBox.width <= mainBox.width && mapBox.x >= mainBox.x, `map ${Math.round(mapBox.width)} / main ${Math.round(mainBox.width)}`)

const h1Box = await page.locator('main h1').first().boundingBox()
const doneBox = await page.locator('[data-testid="agent-message-done"]').boundingBox()
const day0Box = await page.locator('[data-testid="plan-day-0"]').boundingBox()
check('11k 第一屏可见 旅行标题 + 旅行摘要 + 地图（§19 A）',
  h1Box.y < VH && doneBox.y < VH && mapBox.y < VH, `h1 ${Math.round(h1Box.y)} / 摘要 ${Math.round(doneBox.y)} / 地图 ${Math.round(mapBox.y)}`)
check('11l 阅读顺序：概览 → 地图 → 每日行程（§19 F）',
  h1Box.y < mapBox.y && mapBox.y < day0Box.y)

// §7 地图与行程联动：点击行程地点 → marker 与路线摘要同步高亮
await page.click('[data-testid="plan-activity-locate-陈家祠"]')
await page.waitForTimeout(500)
check('11m 点击行程地点 → 路线摘要同一地点高亮（④陈家祠 → index 3）',
  (await page.locator('[data-testid="trip-route-place-3"]').getAttribute('aria-pressed')) === 'true')
check('11n 点击行程地点 → 地图 marker 高亮（is-selected 唯一）',
  (await page.locator('.amap-marker-pin.is-selected').count()) === 1)
await page.click('[data-testid="plan-activity-locate-陈家祠"]')
await page.waitForTimeout(400)
check('11o 再点同一地点 → 取消高亮（不残留选中态）',
  (await page.locator('.amap-marker-pin.is-selected').count()) === 0)

// §12 旅行注意事项降级为默认收起
const notesToggle = page.locator('[data-testid="trip-notes-toggle"]')
check('11p 旅行注意事项默认收起',
  (await notesToggle.getAttribute('aria-expanded')) === 'false' &&
  (await page.locator('[data-testid="trip-notes-panel"]').count()) === 0)
await notesToggle.click()
await page.waitForTimeout(150)
check('11q 展开后注意事项可见',
  (await page.locator('[data-testid="trip-notes-panel"]').count()) === 1)
await notesToggle.click()
await page.waitForTimeout(150)
check('11r 再点收起注意事项',
  (await page.locator('[data-testid="trip-notes-panel"]').count()) === 0)
await resetScroll()
await page.screenshot({ path: `${OUT}/f-ui-10-map-guangzhou.png` })

// 附加：地点攻略折叠（信息量大时收起）
const gzToggle = page.locator('[data-testid="activity-guide-toggle-广州塔"]')
check('6a 广州塔有"查看攻略"折叠入口', (await gzToggle.count()) === 1)
await gzToggle.click()
await page.waitForTimeout(150)
check('6b 展开后显示推荐理由',
  (await page.locator('main').innerText()).includes('塔顶观景层视野覆盖老城与新城'))
await gzToggle.click()
await page.waitForTimeout(150)
check('6c 再点收起（推荐理由隐藏）',
  !(await page.locator('main').innerText()).includes('塔顶观景层视野覆盖老城与新城'))

// ⑤ 完成态底部：查看智能体规划过程（默认折叠，展开为对话流简洁行）
const gzProcessToggle = page.locator('[data-testid="toggle-agent-process"]')
check('9a 完成态"查看智能体规划过程"默认收起',
  (await gzProcessToggle.getAttribute('aria-expanded')) === 'false')
await gzProcessToggle.click()
await page.waitForTimeout(150)
check('9b 展开后对话流可见（9 条 Agent 消息）',
  (await page.locator('main [data-testid="agent-conversation"]').count()) === 1)
check('9c 折叠区内用户消息可见',
  (await page.locator('main [data-testid="user-message"]').count()) === 1)
check('9d 步骤以简洁行呈现（已理解旅行需求）',
  (await page.locator('[data-testid="agent-message-understand"]').innerText()).includes('已理解旅行需求'))
check('9e 步骤列表完整（生成最终旅行方案）',
  (await page.locator('main').innerText()).includes('生成最终旅行方案'))
await gzProcessToggle.click()
await page.waitForTimeout(150)
check('9f 再点收起',
  (await page.locator('main [data-testid="agent-conversation"]').count()) === 0)

// ── 7. 编辑约束：预算 ¥2000 → ¥5000 全同步 ──
await page.click('[data-testid="context-edit-constraints"]')
await page.waitForSelector('[data-testid="constraint-edit-form"]')
check('7a 编辑约束抽屉打开', true)
await page.fill('[data-testid="constraint-edit-budget"]', '¥5000')
await page.screenshot({ path: `${OUT}/f-ui-10-constraint-edit.png` })
await page.click('[data-testid="constraint-edit-save"]')
await page.waitForTimeout(400)
const asideText = await page.locator('aside').innerText()
check('7b 右侧 Context 预算同步为 ¥5000', asideText.includes('¥5000'))
check('7c 中间攻略头部预算同步为 ¥5000',
  (await page.locator('[data-testid="plan-header-meta"]').innerText()).includes('¥5000'))

// ── 8. Command Bar：指令真实反馈 ──
await page.fill('[data-testid="workspace-command-input"]', '把第二天安排轻松一点')
await page.click('[data-testid="workspace-command-send"]')
await page.waitForSelector('[data-testid="command-channel-hint"]')
const hint = await page.locator('[data-testid="command-channel-hint"]').innerText()
check('8a 指令提交有真实反馈', hint.includes('已记录指令'), hint)
await page.screenshot({ path: `${OUT}/f-ui-10-guangzhou.png` })

// ── 2. 广州 → 北京：内容全变 ──
await page.click('[data-testid="workspace-project-beijing"]')
await page.waitForURL('**/workspace/trips/beijing')
await page.waitForTimeout(300)
check('2a 北京攻略头部元信息（含日期）',
  (await page.locator('[data-testid="plan-header-meta"]').innerText()).includes('北京 · 9月10日 — 9月12日 · 3 天 · 1 人 · ¥2800'))
check('2b 北京攻略（故宫博物院）',
  (await page.locator('[data-testid="plan-activity-故宫博物院"]').count()) === 1)
check('2c 北京完成消息（为你安排了3天）',
  (await page.locator('[data-testid="agent-message-done"]').innerText()).includes('3'))
check('2d 广州内容已消失',
  !(await page.locator('main').innerText()).includes('沙面岛'))

// §19 C/D：三天行程齐全 + 切换旅行时地图与行程一起变化
check('11s 北京三天行程全部存在（第一天/第二天/第三天）',
  (await page.locator('[data-testid="plan-day-0"]').count()) === 1 &&
  (await page.locator('[data-testid="plan-day-1"]').count()) === 1 &&
  (await page.locator('[data-testid="plan-day-2"]').count()) === 1)
await page.waitForFunction(() => document.querySelectorAll('.amap-marker-pin').length === 11, null, { timeout: 20000 })
await page.waitForTimeout(2500)
check('11t 切换旅行后地图联动（广州 8 → 北京 11 个 marker）',
  (await page.locator('.amap-marker-pin').count()) === 11)
check('11u 北京路线统计与首个地点同步（11 个地点 · 3 天 / ①故宫博物院）',
  (await page.locator('[data-testid="trip-route-stats"]').innerText()).includes('11 个地点 · 3 天') &&
  (await page.locator('[data-testid="trip-route-place-0"]').innerText()).includes('故宫博物院'))

await resetScroll()
const bjMapBox = await page.locator('[data-testid="trip-route-map"]').boundingBox()
const bjDay2Box = await page.locator('[data-testid="plan-day-2"]').boundingBox()
check('11v "第三天"不在第一屏（§8：第一屏是概览 + 地图）',
  bjDay2Box.y > VH && bjMapBox.y < VH, `第三天 y=${Math.round(bjDay2Box.y)} / 地图 y=${Math.round(bjMapBox.y)}`)
check('11w 完成态"查看智能体规划过程"默认收起（§19 E）',
  (await page.locator('[data-testid="toggle-agent-process"]').getAttribute('aria-expanded')) === 'false')
await page.screenshot({ path: `${OUT}/f-ui-10-map-beijing.png` })

// ── 3/6. 北京 → 成都（draft）──
await page.click('[data-testid="workspace-project-chengdu"]')
await page.waitForURL('**/workspace/trips/chengdu')
await page.waitForTimeout(300)
check('3a 成都 draft 视图可见',
  (await page.locator('[data-testid="trip-draft-view"]').count()) === 1)
check('6a Draft 明确显示"还没有开始规划"',
  (await page.locator('[data-testid="trip-draft-view"]').innerText()).includes('还没有开始规划'))
check('3b Draft 显示约束（目的地 成都）',
  (await page.locator('[data-testid="trip-draft-view"]').innerText()).includes('成都'))
check('3c Draft 有"继续完善旅行"入口',
  (await page.locator('[data-testid="trip-draft-edit-constraints"]').count()) === 1)
check('3d 北京攻略已消失（页面内容全变）',
  (await page.locator('[data-testid="plan-activity-故宫博物院"]').count()) === 0)
check('11x draft 态不显示地图与虚假路线（§17 draft）',
  (await page.locator('[data-testid="trip-route-section"]').count()) === 0 &&
  (await page.locator('.amap-marker-pin').count()) === 0)
await page.screenshot({ path: `${OUT}/f-ui-10-draft.png` })

// Draft 内"继续完善旅行"→ 编辑约束抽屉
await page.click('[data-testid="trip-draft-edit-constraints"]')
await page.waitForSelector('[data-testid="constraint-edit-form"]')
check('6b Draft 引导按钮打开编辑约束抽屉', true)
await page.click('[data-testid="constraint-edit-cancel"]')
await page.waitForTimeout(200)

// ── 1. 切回上海（反向验证内容全变）──
await page.click('[data-testid="workspace-project-shanghai"]')
await page.waitForURL('**/workspace/trips/shanghai')
await page.waitForTimeout(300)
check('1d 切回上海 → 规划态摘要',
  (await page.locator('[data-testid="planning-status-line"]').innerText()).includes('正在规划你的旅行'))
check('1e draft 视图已消失',
  (await page.locator('[data-testid="trip-draft-view"]').count()) === 0)
check('1f 对话流仍在（planning 主区）',
  (await page.locator('[data-testid="agent-conversation"]').count()) === 1)

// ── 9. 新建旅行：轻量创建流程（F-UI-9 NewTripDrawer）──
// 用户核心目标：不是"填一张表"，而是"告诉它基本信息，然后开始规划"。
await page.click('[data-testid="workspace-new-trip"]')
await page.waitForSelector('[data-testid="new-trip-form"]')
const dialogText = await page.locator('[role="dialog"]').innerText()
check('10a 新建抽屉打开，轻说明文案',
  dialogText.includes('先记录这次旅行的基本信息，规划会在创建后开始'))
check('10b 旅行名称输入框已删除（不收集名称）',
  (await page.locator('[data-testid="new-trip-title"]').count()) === 0)
check('10c 目的地字段是首个输入（placeholder 例如：上海、广州、成都）',
  (await page.locator('[data-testid="new-trip-destination"]').getAttribute('placeholder')).includes('例如：上海、广州、成都'))
check('10d 底部按钮为"取消 | 开始规划"',
  (await page.locator('[data-testid="new-trip-submit"]').innerText()).includes('开始规划'))
check('10e 必填未填时按钮不可用且给一句提示（无逐字段噪音）',
  (await page.locator('[data-testid="new-trip-submit"]').isDisabled()) &&
  (await page.locator('[data-testid="new-trip-error"]').innerText()).includes('请填写目的地和日期'))
check('10f 有"+ 添加地点"入口（特别想去的地方）',
  (await page.locator('[data-testid="new-trip-must-visit-add"]').count()) === 1)
await page.screenshot({ path: `${OUT}/f-ui-9-new-trip-default.png` })

// 3. 填上海 → 4. 选日期 → 5. 设 2 人 → 6. 设 ¥3000 → 7. 选偏好 → 8. 加地点
await page.fill('[data-testid="new-trip-destination"]', '上海')
await page.fill('[data-testid="new-trip-start-date"]', '2026-09-12')
await page.fill('[data-testid="new-trip-end-date"]', '2026-09-14')
check('10g 人数默认 2 人', (await page.locator('[data-testid="new-trip-people"]').innerText()).includes('2'))
await page.click('[data-testid="new-trip-people-dec"]')
await page.click('[data-testid="new-trip-people-inc"]')
check('10h 人数 stepper 往返后仍为 2 人',
  (await page.locator('[data-testid="new-trip-people"]').innerText()).includes('2'))
await page.fill('[data-testid="new-trip-budget"]', '3000')
await page.click('[data-testid="new-trip-preference-历史文化"]')
await page.click('[data-testid="new-trip-preference-美食"]')
await page.fill('[data-testid="new-trip-must-visit-0"]', '上海博物馆')
await page.screenshot({ path: `${OUT}/f-ui-9-new-trip-filled.png` })

// 9. 点"开始规划"
await page.click('[data-testid="new-trip-submit"]')
await page.waitForTimeout(400)
check('10i Drawer 已关闭', (await page.locator('[data-testid="new-trip-form"]').count()) === 0)
check('10j 自动进入新旅行 URL', page.url().includes('/workspace/trips/trip-'))
check('10k 标题自动生成（上海 + 9月12日—9月14日 → 上海三日旅行）',
  (await page.locator('[data-testid="trip-draft-view"] h1').innerText()) === '上海三日旅行')
check('10l 左侧列表出现新旅行',
  (await page.locator('[data-testid^="workspace-project-trip-"]').count()) >= 1)
const draftText = await page.locator('[data-testid="trip-draft-view"]').innerText()
check('10m 中央 draft 展示 目的地/日期/人数/预算',
  draftText.includes('上海') && draftText.includes('9月12日 — 9月14日') && draftText.includes('2 人') && draftText.includes('¥3000'))
check('10n 中央 draft 展示 偏好/必去地点',
  draftText.includes('历史文化 · 美食') && draftText.includes('上海博物馆'))
const asideAfterCreate = await page.locator('aside').innerText()
check('10o 右侧 Context 全同步（标题/预算/偏好/必去）',
  asideAfterCreate.includes('上海三日旅行') && asideAfterCreate.includes('¥3000') &&
  asideAfterCreate.includes('历史文化 · 美食') && asideAfterCreate.includes('上海博物馆'))
await page.screenshot({ path: `${OUT}/f-ui-9-new-trip-created.png` })

// 15. 刷新后仍在
await page.reload({ waitUntil: 'load' })
await page.waitForSelector('[data-testid="workspace-shell"]')
await page.waitForTimeout(400)
check('10p 刷新后仍在新旅行 URL', page.url().includes('/workspace/trips/trip-'))
const draftAfterReload = await page.locator('[data-testid="trip-draft-view"]').innerText()
check('10q 刷新后数据仍在（标题 + 全约束）',
  draftAfterReload.includes('上海三日旅行') && draftAfterReload.includes('上海博物馆') &&
  draftAfterReload.includes('¥3000') && draftAfterReload.includes('历史文化 · 美食'))

// ── ⑫ 路线连线（polyline）真实性验证 ──
// AMap 2.0 把 Polyline 画在 canvas 上，DOM 里数不到，所以单靠主流程无法证明连线真的存在。
// 这里开一个独立页面拦截高德 SDK，强制 TripMap 走它原有的降级分支：
// 该分支用同一份 model.legs 渲染 <svg><polyline>，可以在 DOM 中直接计数，
// 从而证明连线数据真实存在并已送进地图组件（而不是"看起来有地图的空壳"）。
const probe = await browser.newPage({ viewport: { width: 1440, height: 900 } })
await probe.route('**webapi.amap.com/**', (route) => route.abort())
await probe.goto(`${BASE}/workspace/trips/beijing`, { waitUntil: 'load' })
await probe.waitForSelector('[data-testid="trip-route-map"]')
await probe.waitForFunction(() => document.querySelectorAll('.overview-marker').length > 0, null, { timeout: 15000 })
const legCount = await probe.locator('[data-testid="trip-route-map"] svg polyline').count()
const overviewMarkers = await probe.locator('.overview-marker').count()
check('12a 路线连线已恢复（北京 8 段 polyline = 3+3+2）', legCount === 8, `实际 ${legCount} 段`)
check('12b 降级概览仍显示全部 11 个地点', overviewMarkers === 11, `实际 ${overviewMarkers} 个`)
check('12c 地图不可用时明确告知已降级，不静默留白',
  (await probe.locator('[data-testid="trip-route-map"]').innerText()).includes('已切换为路线概览'))
await probe.screenshot({ path: `${OUT}/f-ui-10-map-fallback.png` })
await probe.close()

await browser.close()
console.log(`\n${results.length - failed}/${results.length} 项验收通过`)
process.exit(failed ? 1 : 0)
