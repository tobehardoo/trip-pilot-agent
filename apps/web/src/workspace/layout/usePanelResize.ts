// 工作台三栏可拖拽宽度（F-UI-12，Codex 式）：
// 栏宽以「占三栏总宽的比例」存储（而非固定 px），渲染为 CSS clamp(px下限, N%, px上限)
// ——窗口尺寸变化时 % 自动等比缩放（不同屏幕上三栏比例一致），px 上下限兜底；
// 拖动分隔把手时把 px 增量换算为比例增量；比例持久化到 localStorage。
// 不引入第三方分栏库——交互只有「横向拖拽 + clamp + 存取」三件事。
import { onBeforeUnmount, ref } from 'vue'

export type PanelKey = 'sidebar' | 'context'

/** 比例默认值与可拖拽边界（占三栏容器宽度的比例）。 */
export const PANEL_RATIOS: Record<PanelKey, { fallback: number; min: number; max: number }> = {
  // 默认值 ≈ 1440px 窗口下 259px / 288px（原固定 224/256 的自然放大档）。
  sidebar: { fallback: 0.18, min: 0.12, max: 0.28 },
  context: { fallback: 0.2, min: 0.14, max: 0.32 },
}

/** 渲染用 CSS clamp 的 px 上下限：窄屏不低于下限（防挤死），宽屏不高于上限（防虚胖）。 */
export const PANEL_PX_BOUNDS: Record<PanelKey, { lower: number; upper: number }> = {
  sidebar: { lower: 180, upper: 360 },
  context: { lower: 200, upper: 400 },
}

/** 拖拽把手需要知道把手指向哪一栏、起点与容器宽。 */
export interface DragState {
  key: PanelKey
  startX: number
  startRatio: number
  totalWidth: number
}

/**
 * 拖拽换算（纯函数，便于单测）：
 * 左栏向左拖 = 变宽；右栏向右拖 = 变宽。px 增量 → 比例增量 → clamp。
 */
export function nextRatio(state: DragState, clientX: number): number {
  const delta = clientX - state.startX
  const raw =
    state.startRatio + (state.key === 'sidebar' ? -delta : delta) / Math.max(state.totalWidth, 1)
  const { min, max } = PANEL_RATIOS[state.key]
  return Math.min(Math.max(raw, min), max)
}

function readStoredRatio(panel: PanelKey): number {
  const { fallback, min, max } = PANEL_RATIOS[panel]
  try {
    const raw = window.localStorage.getItem(`tp-panel-ratio-${panel}`)
    const parsed = raw === null ? Number.NaN : Number.parseFloat(raw)
    return Number.isFinite(parsed) && parsed >= 0.05 && parsed <= 0.6
      ? Math.min(Math.max(parsed, min), max)
      : fallback
  } catch {
    // localStorage 不可用（隐私模式等）：退回默认比例，仅失去持久化。
    return fallback
  }
}

export function usePanelResize() {
  const sidebarRatio = ref(readStoredRatio('sidebar'))
  const contextRatio = ref(readStoredRatio('context'))

  /** 三栏容器（flex 行）——拖拽换算需要实测总宽。 */
  const panesEl = ref<HTMLElement | null>(null)

  let dragging: DragState | null = null
  let prevBodyCursor = ''
  let prevBodyUserSelect = ''

  function onPointerMove(event: PointerEvent): void {
    if (!dragging) return
    const ratio = nextRatio(dragging, event.clientX)
    if (dragging.key === 'sidebar') sidebarRatio.value = ratio
    else contextRatio.value = ratio
  }

  function onPointerUp(): void {
    if (!dragging) return
    const key = dragging.key
    dragging = null
    document.body.style.cursor = prevBodyCursor
    document.body.style.userSelect = prevBodyUserSelect
    const value = key === 'sidebar' ? sidebarRatio.value : contextRatio.value
    try {
      window.localStorage.setItem(`tp-panel-ratio-${key}`, String(value))
    } catch {
      /* 存储写入失败不阻断交互 */
    }
  }

  /** 把手 pointerdown：进入拖拽态（move/up 监听常驻，dragging 为 null 时空转）。 */
  function startResize(event: PointerEvent, key: PanelKey): void {
    if (dragging) return
    dragging = {
      key,
      startX: event.clientX,
      startRatio: key === 'sidebar' ? sidebarRatio.value : contextRatio.value,
      totalWidth: panesEl.value?.clientWidth ?? window.innerWidth,
    }
    prevBodyCursor = document.body.style.cursor
    prevBodyUserSelect = document.body.style.userSelect
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }

  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp)
  onBeforeUnmount(() => {
    window.removeEventListener('pointermove', onPointerMove)
    window.removeEventListener('pointerup', onPointerUp)
    document.body.style.cursor = prevBodyCursor
    document.body.style.userSelect = prevBodyUserSelect
  })

  return { panesEl, sidebarRatio, contextRatio, startResize }
}
