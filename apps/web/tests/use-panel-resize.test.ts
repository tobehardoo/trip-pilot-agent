// usePanelResize 单测：拖拽换算纯函数 + localStorage 比例读取。
// 拖拽换算是等比例布局的核心不变量：px 增量 → 比例增量，且被 clamp 在边界内。
import { beforeEach, describe, expect, it } from 'vitest'

import { PANEL_RATIOS, nextRatio, usePanelResize, type DragState } from '../src/workspace/layout/usePanelResize'

function dragState(key: DragState['key'], overrides: Partial<DragState> = {}): DragState {
  return {
    key,
    startX: 500,
    startRatio: PANEL_RATIOS[key].fallback,
    totalWidth: 1280,
    ...overrides,
  }
}

describe('nextRatio（拖拽换算）', () => {
  it('sidebar 向左拖 128px（1280 宽的 10%）→ 比例 +0.10', () => {
    const ratio = nextRatio(dragState('sidebar'), 500 - 128)
    expect(ratio).toBeCloseTo(PANEL_RATIOS.sidebar.fallback + 0.1, 5)
  })

  it('context 向右拖 128px → 比例 +0.10；小幅向左拖则减', () => {
    const wider = nextRatio(dragState('context'), 500 + 128)
    expect(wider).toBeCloseTo(PANEL_RATIOS.context.fallback + 0.1, 5)
    // 64px = 0.05 比例，0.2 - 0.05 = 0.15 仍在边界内
    const narrower = nextRatio(dragState('context'), 500 - 64)
    expect(narrower).toBeCloseTo(PANEL_RATIOS.context.fallback - 0.05, 5)
  })

  it('比例被 clamp 在面板边界内：超宽拖拽不会超过 max，过窄不会低于 min', () => {
    const ratio = nextRatio(dragState('sidebar', { startRatio: 0.27 }), 500 - 500)
    expect(ratio).toBe(PANEL_RATIOS.sidebar.max)
    const floored = nextRatio(dragState('context', { startRatio: 0.15 }), 500 - 500)
    expect(floored).toBe(PANEL_RATIOS.context.min)
  })

  it('totalWidth 为 0（容器未挂载）时不产生 Infinity：除数保护为 1，比例被 clamp 兜底', () => {
    const ratio = nextRatio(dragState('context', { totalWidth: 0 }), 500 + 100)
    expect(Number.isFinite(ratio)).toBe(true)
    expect(ratio).toBe(PANEL_RATIOS.context.max)
  })
})

describe('usePanelResize（初始比例读取）', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('无存储值时使用默认比例', () => {
    const { sidebarRatio, contextRatio } = usePanelResize()
    expect(sidebarRatio.value).toBe(PANEL_RATIOS.sidebar.fallback)
    expect(contextRatio.value).toBe(PANEL_RATIOS.context.fallback)
  })

  it('损坏/越界的存储值回落到默认值（旧版 px 值 224 亦作废）', () => {
    window.localStorage.setItem('tp-panel-ratio-sidebar', 'not-a-number')
    window.localStorage.setItem('tp-panel-ratio-context', '224')
    const { sidebarRatio, contextRatio } = usePanelResize()
    expect(sidebarRatio.value).toBe(PANEL_RATIOS.sidebar.fallback)
    expect(contextRatio.value).toBe(PANEL_RATIOS.context.fallback)
  })

  it('合理窗口内的存储值被读取，越出比例边界的部分被 clamp；明显非法（>0.6）回落默认', () => {
    window.localStorage.setItem('tp-panel-ratio-sidebar', '0.25')
    window.localStorage.setItem('tp-panel-ratio-context', '0.5')
    window.localStorage.setItem('tp-panel-ratio-other', '0.99')
    const { sidebarRatio, contextRatio } = usePanelResize()
    expect(sidebarRatio.value).toBe(0.25)
    // 0.5 在合理窗口(0.05~0.6)内但超出可拖边界 → clamp 到 max
    expect(contextRatio.value).toBe(PANEL_RATIOS.context.max)
    // 非法值回落：另开实例验证 0.99 → fallback
    window.localStorage.setItem('tp-panel-ratio-context', '0.99')
    const again = usePanelResize()
    expect(again.contextRatio.value).toBe(PANEL_RATIOS.context.fallback)
  })
})
