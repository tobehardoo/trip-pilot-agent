// 约束展示层（F-UI-3）：约束字段名与枚举值的唯一词汇源。
// Agent 约束板（agent-slots）与行程页/右栏的只读呈现共用同一张表，
// 内部枚举（RELAXED / SOLO / CONFIRMED …）不得直接上屏。

import type { TripConstraints } from './api'

export type PaceValue = 'RELAXED' | 'BALANCED' | 'INTENSIVE'
export type MobilityValue = 'STANDARD' | 'REDUCED' | 'STEP_FREE'
export type TravelerTypeValue = 'SOLO' | 'COUPLE' | 'FAMILY' | 'FRIENDS' | 'BUSINESS'

const FIELD_LABELS: Record<string, string> = {
  destination: '目的地',
  start_date: '出发日期',
  end_date: '返程日期',
  travelers: '出行人数',
  budget: '总预算',
  pace: '旅行节奏',
  must_visit: '必去地点',
  avoid: '避开地点',
  accommodation: '住宿位置',
  arrival: '抵达安排',
  departure: '返程安排',
  mobility: '行动能力',
  preferences: '偏好标签',
  fixed_schedules: '固定安排',
}

const PACE_LABELS: Record<string, string> = {
  RELAXED: '轻松',
  BALANCED: '均衡',
  INTENSIVE: '紧凑',
}

const MOBILITY_LABELS: Record<string, string> = {
  STANDARD: '标准步行',
  REDUCED: '减少步行',
  STEP_FREE: '尽量无台阶',
}

const TRAVELER_TYPE_LABELS: Record<string, string> = {
  SOLO: '独自出行',
  COUPLE: '伴侣同行',
  FAMILY: '家庭出行',
  FRIENDS: '朋友同行',
  BUSINESS: '商务出行',
}

// 住宿锚点解析结果：UNRESOLVED 表示系统没有编造位置，只登记了用户诉求。
const ACCOMMODATION_STATUS_LABELS: Record<string, string> = {
  CONFIRMED: '已确认',
  AREA_ESTIMATED: '区域估计',
  UNRESOLVED: '未定位',
}

export interface ChoiceOption<T extends string> {
  value: T
  label: string
}

export const PACE_OPTIONS: Array<ChoiceOption<PaceValue>> = [
  { value: 'RELAXED', label: PACE_LABELS.RELAXED },
  { value: 'BALANCED', label: PACE_LABELS.BALANCED },
  { value: 'INTENSIVE', label: PACE_LABELS.INTENSIVE },
]

export const MOBILITY_OPTIONS: Array<ChoiceOption<MobilityValue>> = [
  { value: 'STANDARD', label: MOBILITY_LABELS.STANDARD },
  { value: 'REDUCED', label: MOBILITY_LABELS.REDUCED },
  { value: 'STEP_FREE', label: `${MOBILITY_LABELS.STEP_FREE}（车行接驳，场地需确认）` },
]

export const TRAVELER_TYPE_OPTIONS: Array<ChoiceOption<TravelerTypeValue>> = [
  { value: 'SOLO', label: TRAVELER_TYPE_LABELS.SOLO },
  { value: 'COUPLE', label: TRAVELER_TYPE_LABELS.COUPLE },
  { value: 'FAMILY', label: TRAVELER_TYPE_LABELS.FAMILY },
  { value: 'FRIENDS', label: TRAVELER_TYPE_LABELS.FRIENDS },
  { value: 'BUSINESS', label: TRAVELER_TYPE_LABELS.BUSINESS },
]

function enumLabel(table: Record<string, string>, value: unknown): string {
  const key = String(value ?? '').toUpperCase()
  return table[key] ?? String(value ?? '')
}

export function constraintLabel(field: string): string {
  return FIELD_LABELS[field] ?? field
}

export function paceLabel(pace: unknown): string {
  return enumLabel(PACE_LABELS, pace)
}

export function mobilityLabel(level: unknown): string {
  return enumLabel(MOBILITY_LABELS, level)
}

export function travelerTypeLabel(type: unknown): string {
  return enumLabel(TRAVELER_TYPE_LABELS, type)
}

export function accommodationStatusLabel(status: string | null | undefined): string {
  return status ? (ACCOMMODATION_STATUS_LABELS[status] ?? status) : ''
}

function formatBudget(amount: number | null | undefined): string {
  return amount === null || amount === undefined ? '' : `¥${amount}`
}

export interface ConstraintRow {
  key: string
  label: string
  value: string
}

/**
 * TripConstraints → 只读摘要行。未设置的可选约束不占行（行程页摘要与右栏
 * 环境节共用这一份口径），必选字段（出行人数、旅行节奏）始终成行。
 */
export function formatConstraintRows(constraints: TripConstraints): ConstraintRow[] {
  const rows: ConstraintRow[] = []
  const budget = formatBudget(constraints.budgetAmount)
  if (budget) {
    rows.push({ key: 'budget', label: constraintLabel('budget'), value: budget })
  }
  rows.push({
    key: 'travelers',
    label: constraintLabel('travelers'),
    value: `${constraints.travelers} 人 · ${travelerTypeLabel(constraints.travelerType)}`,
  })
  rows.push({ key: 'pace', label: constraintLabel('pace'), value: paceLabel(constraints.pace) })
  if (constraints.accommodation?.placeName) {
    rows.push({
      key: 'accommodation',
      label: constraintLabel('accommodation'),
      value: constraints.accommodation.placeName,
    })
  }
  if (constraints.preferences.length) {
    rows.push({
      key: 'preferences',
      label: constraintLabel('preferences'),
      value: constraints.preferences.join('、'),
    })
  }
  const mustVisit = constraints.mustVisitPlaces ?? []
  if (mustVisit.length) {
    rows.push({
      key: 'must_visit',
      label: constraintLabel('must_visit'),
      value: mustVisit.join('、'),
    })
  }
  for (const key of ['arrival', 'departure'] as const) {
    const placeName = constraints[key]?.placeName
    if (placeName) {
      rows.push({ key, label: constraintLabel(key), value: placeName })
    }
  }
  return rows
}
