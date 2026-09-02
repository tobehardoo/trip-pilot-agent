// Workspace 展示层派生（F-UI-11 Phase 1）。
//
// 所有文案都从真实 Trip / Itinerary（lib/api.ts）派生，不允许存在第二份
// fixture 展示模型。日期/时间格式统一 Asia/Shanghai。
import type { Trip, TripConstraints } from '../../lib/api'

export function formatChinaMoney(amount: number | null | undefined): string {
  return amount === null || amount === undefined ? '未设置' : `¥${amount}`
}

function parseDate(value: string): Date {
  return new Date(`${value.slice(0, 10)}T00:00:00+08:00`)
}

/** "2026-09-12" → "9月12日"（跨年带年份） */
export function formatChinaDate(value: string): string {
  const date = parseDate(value)
  const sameYear = date.getFullYear() === new Date().getFullYear()
  const md = `${date.getMonth() + 1}月${date.getDate()}日`
  return sameYear ? md : `${date.getFullYear()}年${md}`
}

/** "2026-09-12" → "2026/09/12"（功能④：具体日期，含年份） */
export function formatSlashDate(value: string): string {
  const parts = value.slice(0, 10).split('-')
  return parts.length === 3 ? `${parts[0]}/${parts[1]}/${parts[2]}` : (value ?? '')
}

/** "2026-09-12".."2026-09-14" → "9月12日 — 9月14日"（跨年自动带年份） */
export function formatDateRange(startDate: string, endDate: string): string {
  if (!startDate || !endDate) return '待定'
  const start = parseDate(startDate)
  const end = parseDate(endDate)
  const sameYear = start.getFullYear() === end.getFullYear()
  const md = (date: Date) => `${date.getMonth() + 1}月${date.getDate()}日`
  const startText = sameYear ? md(start) : `${start.getFullYear()}年${md(start)}`
  return `${startText} — ${md(end)}`
}

/** ISO 时刻 → "HH:mm"（Asia/Shanghai） */
export function formatChinaTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

export function travelersLabel(trip: Trip): string {
  return `${trip.constraints.travelers} 人`
}

export function preferencesLabel(constraints: TripConstraints): string {
  return constraints.preferences.length ? constraints.preferences.join(' · ') : '未填写'
}

export function mustVisitLabel(constraints: TripConstraints): string {
  return constraints.mustVisitPlaces?.length ? constraints.mustVisitPlaces.join('、') : '未设置'
}

/** 左侧列表/头部副标题：目的地 · 日期 */
export function tripSubtitle(trip: Trip): string {
  return [trip.destination, formatDateRange(trip.startDate, trip.endDate)].filter(Boolean).join(' · ')
}

/** 日期跨度天数（含首尾）；无法解析返回 null */
export function daySpanOfRange(startDate: string, endDate: string): number | null {
  if (!startDate || !endDate) return null
  const start = parseDate(startDate)
  const end = parseDate(endDate)
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return null
  const days = Math.round((end.getTime() - start.getTime()) / 86_400_000) + 1
  return days >= 1 ? days : null
}

// F-UI-9 自动命名（保留既有行为与单测）：上海 + 3 天 → "上海三日旅行"
const CN_DAY = ['零', '一', '两', '三', '四', '五', '六', '七', '八', '九', '十', '十一', '十二', '十三', '十四', '十五', '十六', '十七', '十八', '十九', '二十']

/** 从 "9月12日 — 9月14日" 解析跨度天数（新建抽屉的展示串）；无法解析返回 null */
export function daySpanOf(dates: string): number | null {
  const m = dates.match(/(\d{1,2})月(\d{1,2})日\s*[—\-]\s*(\d{1,2})月(\d{1,2})日/)
  if (!m) return null
  const start = new Date(2026, Number(m[1]) - 1, Number(m[2]))
  const end = new Date(2026, Number(m[3]) - 1, Number(m[4]))
  if (end < start) end.setFullYear(2027) // 跨年（如 12月30日 — 1月2日）
  const days = Math.round((end.getTime() - start.getTime()) / 86_400_000) + 1
  return days >= 1 && days < CN_DAY.length ? days : null
}

/** 自动展示名：目的地 + 天数（上海 + 9月12日—9月14日 → "上海三日旅行"） */
export function composeTripTitle(destination: string, dates: string): string {
  const dest = destination.trim() || '未命名'
  const days = daySpanOf(dates)
  return days ? `${dest}${CN_DAY[days]}日旅行` : `${dest}旅行`
}

/** 同行人数 → 出行类型（新建抽屉只收集人数，类型按人数推导） */
export function travelerTypeOf(people: number): TripConstraints['travelerType'] {
  if (people <= 1) return 'SOLO'
  if (people === 2) return 'COUPLE'
  if (people <= 4) return 'FAMILY'
  return 'FRIENDS'
}

export interface ContextRow {
  label: string
  value: string
}

/** draft 视图与右侧 Inspector 共用的约束行（全部真实字段派生） */
export function constraintRows(trip: Trip): ContextRow[] {
  const constraints = trip.constraints
  return [
    { label: '目的地', value: trip.destination || '待定' },
    { label: '日期', value: formatDateRange(trip.startDate, trip.endDate) },
    { label: '人数', value: travelersLabel(trip) },
    { label: '预算', value: formatChinaMoney(constraints.budgetAmount) },
    { label: '旅行偏好', value: preferencesLabel(constraints) },
    { label: '必去地点', value: mustVisitLabel(constraints) },
  ]
}
