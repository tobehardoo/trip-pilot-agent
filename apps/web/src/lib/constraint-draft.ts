/**
 * 约束草稿状态：前端编辑约束的中间模型。
 *
 * 作用是追踪每个字段的值来源（用户输入 / 规则推断 / 默认值），
 * 最终转换为 CreateTripInput 提交给后端。
 */
import type { CreateTripInput } from './api'

export type ValueSource = 'explicit' | 'inferred' | 'default' | 'ambiguous' | 'unset'

export interface FieldMeta<T> {
  value: T
  source: ValueSource
}

export interface StructuredDestination {
  province: string
  city: string
  districts: string[]
}

export interface ConstraintDraft {
  destination: FieldMeta<string | StructuredDestination>
  startDate: FieldMeta<string>
  endDate: FieldMeta<string>
  travelers: FieldMeta<number>
  budgetAmount: FieldMeta<number | null>
  preferences: FieldMeta<string[]>
  mustVisitPlaces: FieldMeta<string[]>
  pace: FieldMeta<string>
}

/** 从今天起算默认日期（明天出发、玩两天）。 */
function defaultDates(now: Date): { startDate: string; endDate: string } {
  const tzOffset = 8 * 60 * 60 * 1000 // Asia/Shanghai
  const today = new Date(now.getTime() + tzOffset)
  const tomorrow = new Date(today)
  tomorrow.setUTCDate(today.getUTCDate() + 1)
  const dayAfter = new Date(tomorrow)
  dayAfter.setUTCDate(tomorrow.getUTCDate() + 1)
  return {
    startDate: toDateString(tomorrow),
    endDate: toDateString(dayAfter),
  }
}

function toDateString(d: Date) {
  return d.toISOString().slice(0, 10)
}

export function createDefaultDraft(): ConstraintDraft {
  const now = new Date()
  const dates = defaultDates(now)
  return {
    destination: { value: '', source: 'unset' },
    startDate: { value: dates.startDate, source: 'default' },
    endDate: { value: dates.endDate, source: 'default' },
    travelers: { value: 1, source: 'default' },
    budgetAmount: { value: 3000, source: 'default' },
    preferences: { value: [], source: 'unset' },
    mustVisitPlaces: { value: [], source: 'unset' },
    pace: { value: 'BALANCED', source: 'default' },
  }
}

/** 将结构化目的地转为后端字符串。 */
export function destinationToString(dest: string | StructuredDestination): string {
  if (typeof dest === 'string') return dest
  const parts = [dest.province, dest.city]
  if (dest.districts.length && !dest.districts.includes('全市')) {
    parts.push(dest.districts.join('、'))
  }
  return parts.join(' ')
}

/** 将草稿转换为 CreateTripInput。 */
export function toCreateTripInput(draft: ConstraintDraft, title: string): CreateTripInput {
  return {
    title,
    destination: destinationToString(draft.destination.value),
    startDate: draft.startDate.value,
    endDate: draft.endDate.value,
    constraints: {
      budgetAmount: draft.budgetAmount.value,
      travelers: draft.travelers.value,
      travelerType: 'SOLO',
      pace: draft.pace.value as CreateTripInput['constraints']['pace'],
      preferences: [...draft.preferences.value],
      fixedSchedules: [],
      arrival: null,
      departure: null,
      accommodation: null,
      mustVisitPlaces: [...draft.mustVisitPlaces.value],
      avoidPlaces: [],
      mealWindows: [],
      mobilityLevel: 'STANDARD',
    },
  }
}
