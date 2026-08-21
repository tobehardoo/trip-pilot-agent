import { describe, expect, it } from 'vitest'

import type { EvaluationWarning } from './api'
import {
  groupEvaluationWarnings,
  summarizeWarnings,
  highestSeverity,
} from './plan-evaluation-presentation'

function warn(partial: Partial<EvaluationWarning> & { code: string }): EvaluationWarning {
  return {
    severity: 'WARNING',
    message: 'msg',
    entityType: 'PLAN',
    ...partial,
  }
}

describe('groupEvaluationWarnings', () => {
  it('returns [] for no warnings', () => {
    expect(groupEvaluationWarnings([])).toEqual([])
  })

  it('keeps a single warning as one group', () => {
    const groups = groupEvaluationWarnings([warn({ code: 'TRANSIT_BUFFER', message: '换乘缓冲不足' })])
    expect(groups).toHaveLength(1)
    expect(groups[0]).toMatchObject({ code: 'TRANSIT_BUFFER', count: 1, severity: 'WARNING', label: '换乘缓冲不足' })
  })

  it('groups multiple warnings with the same code', () => {
    const groups = groupEvaluationWarnings([
      warn({ code: 'TRANSIT_BUFFER', message: '换乘缓冲不足', dayIndex: 0 }),
      warn({ code: 'TRANSIT_BUFFER', message: '换乘缓冲不足', dayIndex: 1 }),
      warn({ code: 'TRANSIT_BUFFER', message: '换乘缓冲不足', dayIndex: 2 }),
      warn({ code: 'OPENING_HOURS', message: '营业时间冲突' }),
    ])
    expect(groups).toHaveLength(2)
    const buffer = groups.find((g) => g.code === 'TRANSIT_BUFFER')
    expect(buffer?.count).toBe(3)
    const opening = groups.find((g) => g.code === 'OPENING_HOURS')
    expect(opening?.count).toBe(1)
  })

  it('does not split on message text when the code is identical', () => {
    const groups = groupEvaluationWarnings([
      warn({ code: 'TIME_BUDGET', message: '活动 A 时间不足', dayIndex: 0, entityType: 'ACTIVITY', entityId: 'a' }),
      warn({ code: 'TIME_BUDGET', message: '活动 B 时间不足', dayIndex: 1, entityType: 'ACTIVITY', entityId: 'b' }),
    ])
    expect(groups).toHaveLength(1)
    expect(groups[0].count).toBe(2)
  })

  it('group severity is the highest within the group', () => {
    const groups = groupEvaluationWarnings([
      warn({ code: 'TRANSIT_BUFFER', severity: 'INFO' }),
      warn({ code: 'TRANSIT_BUFFER', severity: 'CRITICAL' }),
      warn({ code: 'TRANSIT_BUFFER', severity: 'WARNING' }),
    ])
    expect(groups[0].severity).toBe('CRITICAL')
  })

  it('keeps all items inside the group (nothing is dropped)', () => {
    const input = [
      warn({ code: 'A', dayIndex: 0, entityType: 'ACTIVITY', entityId: 'a1' }),
      warn({ code: 'A', dayIndex: 1, entityType: 'ACTIVITY', entityId: 'a2' }),
      warn({ code: 'B', dayIndex: 0 }),
    ]
    const groups = groupEvaluationWarnings(input)
    const total = groups.reduce((sum, g) => sum + g.items.length, 0)
    expect(total).toBe(input.length)
  })

  it('is stable across identical inputs (no order dependence on grouping result)', () => {
    const a = groupEvaluationWarnings([
      warn({ code: 'X', severity: 'INFO' }),
      warn({ code: 'Y', severity: 'CRITICAL' }),
    ])
    const b = groupEvaluationWarnings([
      warn({ code: 'Y', severity: 'CRITICAL' }),
      warn({ code: 'X', severity: 'INFO' }),
    ])
    expect(a.map((g) => g.code)).toEqual(b.map((g) => g.code))
  })
})

describe('summarizeWarnings', () => {
  it('reports zero groups/activities for empty input', () => {
    expect(summarizeWarnings([])).toEqual({ groupCount: 0, totalCount: 0, affectedActivityCount: 0 })
  })

  it('counts distinct groups and distinct affected activities', () => {
    const summary = summarizeWarnings([
      warn({ code: 'A', entityType: 'ACTIVITY', entityId: 'a1' }),
      warn({ code: 'A', entityType: 'ACTIVITY', entityId: 'a1' }),
      warn({ code: 'A', entityType: 'ACTIVITY', entityId: 'a2' }),
      warn({ code: 'B', entityType: 'PLAN' }),
    ])
    expect(summary).toEqual({ groupCount: 2, totalCount: 4, affectedActivityCount: 2 })
  })

  it('ignores entityId-less warnings when counting activities', () => {
    const summary = summarizeWarnings([
      warn({ code: 'A', entityType: 'ACTIVITY', entityId: null }),
      warn({ code: 'B', entityType: 'DAY' }),
    ])
    expect(summary.affectedActivityCount).toBe(0)
  })
})

describe('highestSeverity', () => {
  it('orders INFO < WARNING < CRITICAL', () => {
    expect(highestSeverity(['INFO', 'WARNING'])).toBe('WARNING')
    expect(highestSeverity(['WARNING', 'CRITICAL', 'INFO'])).toBe('CRITICAL')
    expect(highestSeverity([])).toBe('INFO')
  })
})
