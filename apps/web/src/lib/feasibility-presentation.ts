import type { FeasibilityRuleResult, TypedEntityReference } from './feasibility'
import { parseTypedEntityReference } from './feasibility'

/**
 * B15: user-facing presentation of feasibility findings.
 *
 * Pure display helper — never re-derives feasibility, never surfaces raw
 * backend messages, codes, validator versions or UUIDs.  Counts come from
 * typed affectedEntityRefs (activity/poi) and are used only for display.
 */

export interface RuleIssueSummary {
  /** Chinese rule name (stable mapping). */
  label: string
  /** Chinese user summary without raw message/codes/UUIDs. */
  text: string
  /** 'fail' | 'unknown' — drives visual tone only. */
  kind: 'fail' | 'unknown'
  /** Chinese date list, e.g. "8月17日、8月18日"; '' when absent. */
  dates: string
}

const RULE_NAMES: Record<string, string> = {
  TRIP_DATE_RANGE: '行程日期',
  FIXED_SCHEDULE_COVERAGE: '固定安排',
  BUDGET_LIMIT: '预算',
  DUPLICATE_POI: '重复地点',
  ACTIVITY_OVERLAP: '时间安排',
  MUST_VISIT_COVERAGE: '必去地点',
  ROUTE_ENDPOINT_CONTINUITY: '行程起止衔接',
  CROSS_DAY_CONTINUITY: '跨日衔接',
  OPENING_HOURS: '营业时间',
  VISIT_DURATION: '游玩时长',
  MEAL_WINDOW: '用餐时间',
}

const FALLBACK_UNKNOWN = '该项信息采用系统估算，建议出发前确认'
const FALLBACK_FAIL = '该项安排需要调整'

export function ruleName(ruleId: string): string {
  return RULE_NAMES[ruleId] ?? ''
}

/**
 * Counts unique activity/poi typed entity refs for display; ignores
 * text/unknown refs and never surfaces raw values.  Dedup uses the canonical
 * typed identity (kind, value) so the same value under different kinds
 * counts as two different entities (B15.1 R1).
 */
export function countAffectedEntities(refs: string[]): number {
  if (!Array.isArray(refs)) return 0
  const seen = new Set<string>()
  for (const ref of refs) {
    if (typeof ref !== 'string') continue
    const parsed = parseTypedEntityReference(ref)
    if (parsed.kind === 'activity' || parsed.kind === 'poi') {
      if (parsed.value.trim().length === 0) continue
      seen.add(`${parsed.kind}:${parsed.value}`)
    }
  }
  return seen.size
}

const ISO_DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/

/**
 * Validates a strict YYYY-MM-DD date numerically (no local-timezone Date
 * parsing).  Returns [year, month, day] or null when malformed/impossible.
 */
function parseIsoDate(value: string): [number, number, number] | null {
  if (typeof value !== 'string') return null
  const match = ISO_DATE_PATTERN.exec(value.trim())
  if (!match) return null
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  if (month < 1 || month > 12 || day < 1 || day > 31) return null
  // Leap-year aware day check without Date parsing.
  const daysInMonth = [
    31, (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0 ? 29 : 28,
    31, 30, 31, 30, 31, 31, 30, 31, 30, 31,
  ]
  if (day > daysInMonth[month - 1]) return null
  return [year, month, day]
}

export function formatChineseDate(value: string): string {
  const parsed = parseIsoDate(value)
  if (!parsed) return ''
  const [year, month, day] = parsed
  return `${month}月${day}日`
}

/**
 * Formats dates as a stable, ascending, deduplicated Chinese list.  Same-year
 * dates use the concise "M月D日" form; cross-year lists include the year to
 * avoid ambiguity (B15.1 R2).  Malformed/impossible values are safely
 * ignored; the input array is never mutated.
 */
export function formatChineseDateList(dates: string[]): string {
  if (!Array.isArray(dates) || dates.length === 0) return ''
  const seen = new Map<string, [number, number, number]>()
  for (const value of dates) {
    const parsed = parseIsoDate(value)
    if (!parsed) continue
    seen.set(`${parsed[0]}-${String(parsed[1]).padStart(2, '0')}-${String(parsed[2]).padStart(2, '0')}`, parsed)
  }
  const unique = [...seen.values()].sort((a, b) => {
    if (a[0] !== b[0]) return a[0] - b[0]
    if (a[1] !== b[1]) return a[1] - b[1]
    return a[2] - b[2]
  })
  const spansMultipleYears = unique.length > 0
    && (unique[unique.length - 1][0] !== unique[0][0])
  return unique.map(([year, month, day]) =>
    spansMultipleYears ? `${year}年${month}月${day}日` : `${month}月${day}日`,
  ).join('、')
}

/** Builds a Chinese summary for a FAIL/UNKNOWN rule result. */
export function ruleIssueSummary(rule: FeasibilityRuleResult): RuleIssueSummary {
  const label = ruleName(rule.ruleId)
  const kind: 'fail' | 'unknown' = rule.outcome === 'FAIL' ? 'fail' : 'unknown'
  const entityCount = countAffectedEntities(rule.affectedEntityRefs ?? [])
  const dates = formatChineseDateList(rule.affectedDates ?? [])

  let text: string
  if (kind === 'unknown') {
    // B16: Information Missing != Planning Failed.  UNKNOWN rules never block
    // saving; the plan proceeds with system suggestions, and the message
    // tells the user to confirm the specific fact before departure.
    switch (rule.ruleId) {
      case 'OPENING_HOURS':
        text = entityCount > 0
          ? `${entityCount}个地点的营业时间采用系统建议，建议出发前确认`
          : '部分地点的营业时间采用系统建议，建议出发前确认'
        break
      case 'VISIT_DURATION':
        text = entityCount > 0
          ? `${entityCount}个地点采用估算游玩时长，建议出发前确认`
          : '部分地点采用估算游玩时长，建议出发前确认'
        break
      default:
        text = FALLBACK_UNKNOWN
    }
  } else {
    switch (rule.ruleId) {
      case 'OPENING_HOURS':
        text = '部分地点的营业时间与行程安排冲突'
        break
      case 'ACTIVITY_OVERLAP':
        text = '部分活动时间发生重叠'
        break
      case 'BUDGET_LIMIT':
        text = '当前方案可能超出预算'
        break
      case 'MUST_VISIT_COVERAGE':
        text = '部分必去地点尚未安排'
        break
      default:
        text = FALLBACK_FAIL
    }
  }
  return { label, text, kind, dates }
}

/** Resolves a typed entity ref to a display name when safe; never UUIDs. */
export function entityDisplayName(ref: string, activityTitles: string[]): string | null {
  const parsed: TypedEntityReference = parseTypedEntityReference(ref)
  if (parsed.kind === 'activity') {
    const title = activityTitles[Number(parsed.value)] ?? activityTitles.find((t) => t.includes(parsed.value))
    return title ?? null
  }
  if (parsed.kind === 'poi') {
    return activityTitles.find((t) => t.includes(parsed.value)) ?? null
  }
  return null
}
