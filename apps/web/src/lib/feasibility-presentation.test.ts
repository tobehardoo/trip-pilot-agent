import { describe, expect, test } from 'vitest'
import {
  countAffectedEntities,
  formatChineseDate,
  formatChineseDateList,
  ruleIssueSummary,
  type RuleIssueSummary,
} from './feasibility-presentation'
import type { FeasibilityRuleResult } from './feasibility'

function rule(partial: Partial<FeasibilityRuleResult> & { ruleId: string; outcome: FeasibilityRuleResult['outcome'] }): FeasibilityRuleResult {
  return {
    ruleVersion: 'hard-rule-v1',
    reasonCode: 'X',
    message: 'raw english message that must never surface',
    affectedDates: [],
    affectedEntityRefs: [],
    evidenceRefs: [],
    repairable: false,
    ...partial,
  }
}

describe('ruleIssueSummary', () => {
  test('OPENING_HOURS UNKNOWN with 7 activity refs shows count summary', () => {
    const refs = Array.from({ length: 7 }, (_, i) => `activity:00000000-0000-4000-8000-00000000000${i}`)
    const summary = ruleIssueSummary(rule({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN', affectedEntityRefs: refs }))
    expect(summary.label).toBe('营业时间')
    expect(summary.text).toBe('7个地点的营业时间采用系统建议，建议出发前确认')
    expect(summary.kind).toBe('unknown')
  })

  test('VISIT_DURATION UNKNOWN with 4 poi refs shows count summary', () => {
    const refs = Array.from({ length: 4 }, (_, i) => `poi:B00${i}`)
    const summary = ruleIssueSummary(rule({ ruleId: 'VISIT_DURATION', outcome: 'UNKNOWN', affectedEntityRefs: refs }))
    expect(summary.text).toBe('4个地点采用估算游玩时长，建议出发前确认')
  })

  test('ACTIVITY_OVERLAP FAIL shows conflict summary without raw message', () => {
    const summary = ruleIssueSummary(rule({ ruleId: 'ACTIVITY_OVERLAP', outcome: 'FAIL' }))
    expect(summary.text).toBe('部分活动时间发生重叠')
    expect(summary.kind).toBe('fail')
    expect(summary.text).not.toContain('raw english')
  })

  test('BUDGET_LIMIT FAIL shows budget summary', () => {
    const summary = ruleIssueSummary(rule({ ruleId: 'BUDGET_LIMIT', outcome: 'FAIL' }))
    expect(summary.text).toBe('当前方案可能超出预算')
  })

  test('MUST_VISIT_COVERAGE FAIL shows coverage summary', () => {
    const summary = ruleIssueSummary(rule({ ruleId: 'MUST_VISIT_COVERAGE', outcome: 'FAIL' }))
    expect(summary.text).toBe('部分必去地点尚未安排')
  })

  test('OPENING_HOURS FAIL without refs uses safe no-count fallback', () => {
    const summary = ruleIssueSummary(rule({ ruleId: 'OPENING_HOURS', outcome: 'FAIL', affectedEntityRefs: [] }))
    expect(summary.text).toBe('部分地点的营业时间与行程安排冲突')
  })

  test('UNKNOWN with no refs uses generic safe text', () => {
    const summary = ruleIssueSummary(rule({ ruleId: 'MEAL_WINDOW', outcome: 'UNKNOWN', affectedEntityRefs: [] }))
    expect(summary.text).toBe('该项信息采用系统估算，建议出发前确认')
  })

  test('FAIL with no refs uses generic repair text', () => {
    const summary = ruleIssueSummary(rule({ ruleId: 'MEAL_WINDOW', outcome: 'FAIL', affectedEntityRefs: [] }))
    expect(summary.text).toBe('该项安排需要调整')
  })

  test('unknown rule id degrades safely without leaking the code', () => {
    const summary = ruleIssueSummary(rule({ ruleId: 'SOME_INTERNAL_RULE', outcome: 'FAIL' }))
    expect(summary.text).toBe('该项安排需要调整')
    expect(summary.text).not.toContain('SOME_INTERNAL_RULE')
    const unknown = ruleIssueSummary(rule({ ruleId: 'SOME_INTERNAL_RULE', outcome: 'UNKNOWN' }))
    expect(unknown.text).toBe('该项信息采用系统估算，建议出发前确认')
  })

  test('count only counts activity/poi typed refs, never raw ref strings', () => {
    const refs = [
      'activity:00000000-0000-4000-8000-000000000001',
      'poi:B001',
      'text:自由文本',
      'unknown:junk',
    ]
    const summary = ruleIssueSummary(rule({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN', affectedEntityRefs: refs }))
    expect(summary.text).toBe('2个地点的营业时间采用系统建议，建议出发前确认')
    expect(summary.text).not.toContain('00000000')
    expect(summary.text).not.toContain('B001')
  })

  test('date list renders Chinese dates', () => {
    const summary = ruleIssueSummary(rule({
      ruleId: 'OPENING_HOURS',
      outcome: 'FAIL',
      affectedEntityRefs: [],
      affectedDates: ['2026-08-17', '2026-08-18'],
    }))
    expect(summary.dates).toBe('8月17日、8月18日')
  })

  test('single date renders Chinese date', () => {
    const summary = ruleIssueSummary(rule({
      ruleId: 'ACTIVITY_OVERLAP',
      outcome: 'FAIL',
      affectedEntityRefs: [],
      affectedDates: ['2026-08-17'],
    }))
    expect(summary.dates).toBe('8月17日')
  })

  test('no dates renders empty date string', () => {
    const summary = ruleIssueSummary(rule({ ruleId: 'ACTIVITY_OVERLAP', outcome: 'FAIL', affectedEntityRefs: [] }))
    expect(summary.dates).toBe('')
  })
})

describe('formatChineseDate', () => {
  test('formats ISO date to 8月17日', () => {
    expect(formatChineseDate('2026-08-17')).toBe('8月17日')
  })
  test('formats list with 、 separator', () => {
    expect(formatChineseDateList(['2026-08-17', '2026-08-18'])).toBe('8月17日、8月18日')
  })
})

// ── B15.1 R1: affected entity count dedup ────────────────────────────────

describe('B15.1 countAffectedEntities dedup', () => {
  test('identical activity refs repeated count once', () => {
    const refs = [
      'activity:00000000-0000-4000-8000-000000000001',
      'activity:00000000-0000-4000-8000-000000000001',
    ]
    expect(countAffectedEntities(refs)).toBe(1)
  })

  test('three refs with only two unique entities count two', () => {
    const refs = [
      'activity:00000000-0000-4000-8000-000000000001',
      'activity:00000000-0000-4000-8000-000000000002',
      'activity:00000000-0000-4000-8000-000000000001',
    ]
    expect(countAffectedEntities(refs)).toBe(2)
  })

  test('input order does not change the count', () => {
    const a = ['activity:00000000-0000-4000-8000-000000000001', 'activity:00000000-0000-4000-8000-000000000002', 'activity:00000000-0000-4000-8000-000000000001']
    const b = ['activity:00000000-0000-4000-8000-000000000002', 'activity:00000000-0000-4000-8000-000000000001', 'activity:00000000-0000-4000-8000-000000000001']
    expect(countAffectedEntities(a)).toBe(countAffectedEntities(b))
    expect(countAffectedEntities(a)).toBe(2)
  })

  test('same value as activity and poi counts as two different entities', () => {
    const refs = [
      'activity:00000000-0000-4000-8000-000000000001',
      'poi:00000000-0000-4000-8000-000000000001',
    ]
    expect(countAffectedEntities(refs)).toBe(2)
  })

  test('duplicate poi refs count once', () => {
    const refs = ['poi:B001', 'poi:B001', 'poi:B002']
    expect(countAffectedEntities(refs)).toBe(2)
  })

  test('empty value / unknown kind / non-typed ref never count', () => {
    const refs = [
      'activity:',
      'activity:   ',
      'unknown:junk',
      'plain-text',
      ':nokind',
      '',
    ]
    expect(countAffectedEntities(refs)).toBe(0)
  })

  test('missing or empty array returns 0 without throwing', () => {
    expect(countAffectedEntities(undefined as unknown as string[])).toBe(0)
    expect(countAffectedEntities([])).toBe(0)
    expect(countAffectedEntities(null as unknown as string[])).toBe(0)
  })

  test('does not mutate the caller array', () => {
    const refs = [
      'activity:00000000-0000-4000-8000-000000000001',
      'activity:00000000-0000-4000-8000-000000000001',
    ]
    const snapshot = [...refs]
    countAffectedEntities(refs)
    expect(refs).toEqual(snapshot)
  })

  test('ruleIssueSummary with duplicate refs shows deduped count', () => {
    const refs = [
      'activity:00000000-0000-4000-8000-000000000001',
      'activity:00000000-0000-4000-8000-000000000002',
      'activity:00000000-0000-4000-8000-000000000001',
    ]
    const summary = ruleIssueSummary(rule({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN', affectedEntityRefs: refs }))
    expect(summary.text).toBe('2个地点的营业时间采用系统建议，建议出发前确认')
  })
})

// ── B15.1 R2: stable date sorting ─────────────────────────────────────────

describe('B15.1 formatChineseDateList stable sort', () => {
  test('reversed dates sort ascending', () => {
    expect(formatChineseDateList(['2026-08-18', '2026-08-17'])).toBe('8月17日、8月18日')
  })

  test('duplicate dates dedupe', () => {
    expect(formatChineseDateList(['2026-08-17', '2026-08-17', '2026-08-18'])).toBe('8月17日、8月18日')
  })

  test('cross-month sorting', () => {
    expect(formatChineseDateList(['2026-08-02', '2026-07-31'])).toBe('7月31日、8月2日')
  })

  test('cross-year sorting includes year to avoid ambiguity', () => {
    expect(formatChineseDateList(['2026-01-02', '2025-12-31'])).toBe('2025年12月31日、2026年1月2日')
  })

  test('leap day sorting (2024-02-29)', () => {
    expect(formatChineseDateList(['2024-03-01', '2024-02-29'])).toBe('2月29日、3月1日')
  })

  test('different input order yields identical output', () => {
    const a = formatChineseDateList(['2026-08-18', '2026-08-17', '2026-08-19'])
    const b = formatChineseDateList(['2026-08-19', '2026-08-17', '2026-08-18'])
    expect(a).toBe(b)
    expect(a).toBe('8月17日、8月18日、8月19日')
  })

  test('malformed, empty-string and impossible dates are safely ignored', () => {
    expect(formatChineseDateList(['not-a-date', '', '2026-02-30', '2026-08-17'])).toBe('8月17日')
  })

  test('empty input returns safe empty state', () => {
    expect(formatChineseDateList([])).toBe('')
    expect(formatChineseDateList(undefined as unknown as string[])).toBe('')
  })

  test('does not mutate the input array', () => {
    const dates = ['2026-08-18', '2026-08-17']
    const snapshot = [...dates]
    formatChineseDateList(dates)
    expect(dates).toEqual(snapshot)
  })

  test('same-year dates use concise form, cross-year includes year', () => {
    expect(formatChineseDateList(['2026-01-01', '2026-12-31'])).toBe('1月1日、12月31日')
  })
})

