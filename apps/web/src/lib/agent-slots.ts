// Constraint Workspace 的槽位呈现（Agent UX 2.0 §6）。
// 内部枚举（UNKNOWN/INFERRED/CONFIRMED/REJECTED/USER_OVERRIDE）禁止上屏。
// F-UI-3：字段与枚举文案统一取自 constraint-presentation，与行程页摘要同一口径。
import { constraintLabel, mobilityLabel, paceLabel } from './constraint-presentation'

export interface SlotViewLike {
  value: unknown
  state: string
  /** 向导通道携带来源（TRIP = 来自行程，锁定）。run 通道可缺省。 */
  source?: string
}

export type SlotTone = 'confirmed' | 'inferred' | 'pending' | 'rejected'

export function slotTone(state: string): SlotTone {
  switch (state) {
    case 'CONFIRMED':
    case 'USER_OVERRIDE':
      return 'confirmed'
    case 'INFERRED':
      return 'inferred'
    case 'REJECTED':
      return 'rejected'
    default:
      return 'pending'
  }
}

export function slotStateLabel(state: string): string {
  switch (slotTone(state)) {
    case 'confirmed':
      return '已确认'
    case 'inferred':
      return 'AI 推测'
    case 'rejected':
      return '已排除'
    default:
      return '待补充'
  }
}

export const SLOT_ORDER = [
  'destination',
  'start_date',
  'end_date',
  'travelers',
  'budget',
  'pace',
  'must_visit',
  'avoid',
  'accommodation',
  'arrival',
  'departure',
  'mobility',
  'preferences',
  'fixed_schedules',
] as const

function formatScalar(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'object') {
    const record = value as Record<string, unknown>
    const place = record.place ?? record.placeName ?? ''
    const time = record.time ?? ''
    return [String(place), String(time)].filter(Boolean).join(' ')
  }
  return String(value)
}

export function formatSlotValue(name: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  if (name === 'budget') {
    const amount = Number(value)
    return Number.isFinite(amount) ? `¥${amount}` : String(value)
  }
  if (name === 'travelers') {
    const count = Number(value)
    return Number.isFinite(count) ? `${count} 位` : String(value)
  }
  if (name === 'pace') return paceLabel(String(value))
  if (name === 'mobility') return mobilityLabel(String(value))
  if (Array.isArray(value)) return value.map((item) => formatScalar(item)).filter(Boolean).join('、')
  return formatScalar(value)
}

export interface SlotRowView {
  name: string
  label: string
  display: string
  state: string
  tone: SlotTone
  stateLabel: string
  source?: string
}

/** COMPLETED 事件的 slots 投影 → 约束区行视图（只收值非空的槽位）。 */
export function slotRows(slots: Record<string, SlotViewLike>): SlotRowView[] {
  const rows: SlotRowView[] = []
  for (const name of SLOT_ORDER) {
    const slot = slots[name]
    if (!slot || slot.value === null || slot.value === undefined || slot.value === '') continue
    rows.push({
      name,
      label: constraintLabel(name),
      display: formatSlotValue(name, slot.value),
      state: slot.state,
      tone: slotTone(slot.state),
      stateLabel: slotStateLabel(slot.state),
      source: slot.source,
    })
  }
  return rows
}

/** 创建对话中向导会主动询问的槽位（tier-0 + tier-1；tier-2 永不主动问，不进"待确认"）。 */
const CREATION_AUTO_ASKED = [
  'travelers',
  'budget',
  'pace',
  'must_visit',
  'accommodation',
  'arrival',
  'departure',
] as const

export interface CreationSummary {
  /** 已了解：CONFIRMED 且非 TRIP 来源（目的地/日期由 Required Context 展示）。 */
  known: SlotRowView[]
  /** 待确认：向导会问但还没确认的槽位标签。 */
  pending: string[]
}

/** 创建对话 slots 投影 → 右侧"旅行需求"摘要（纯投影，不持有状态）。 */
export function creationSummary(slots: Record<string, SlotViewLike> | null | undefined): CreationSummary {
  const known: SlotRowView[] = []
  const confirmed = new Set<string>()
  for (const name of SLOT_ORDER) {
    const slot = slots?.[name]
    if (!slot) continue
    const filled = slot.value !== null && slot.value !== undefined && slot.value !== ''
    if (slotTone(slot.state) === 'confirmed' && filled) {
      confirmed.add(name)
      if (slot.source === 'TRIP') continue
      known.push({
        name,
        label: constraintLabel(name),
        display: formatSlotValue(name, slot.value),
        state: slot.state,
        tone: 'confirmed',
        stateLabel: '已确认',
        source: slot.source,
      })
    }
  }
  const pending = CREATION_AUTO_ASKED.filter((name) => !confirmed.has(name)).map((name) => constraintLabel(name))
  return { known, pending }
}
