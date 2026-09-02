// Agent UX 2.0 Phase B：约束工作区的呈现规则。
// 内部枚举不得出现在任何用户可见文案中。

import { describe, expect, it } from 'vitest'

import { creationSummary, formatSlotValue, slotRows, slotStateLabel, slotTone } from '../src/lib/agent-slots'

describe('slot state presentation', () => {
  it('maps the five internal states to user language', () => {
    expect(slotStateLabel('CONFIRMED')).toBe('已确认')
    expect(slotStateLabel('USER_OVERRIDE')).toBe('已确认')
    expect(slotStateLabel('INFERRED')).toBe('AI 推测')
    expect(slotStateLabel('UNKNOWN')).toBe('待补充')
    expect(slotStateLabel('REJECTED')).toBe('已排除')
  })

  it('never leaks internal enum literals', () => {
    for (const state of ['UNKNOWN', 'INFERRED', 'CONFIRMED', 'REJECTED', 'USER_OVERRIDE']) {
      expect(slotStateLabel(state)).not.toBe(state)
    }
  })

  it('classifies tones for styling', () => {
    expect(slotTone('CONFIRMED')).toBe('confirmed')
    expect(slotTone('INFERRED')).toBe('inferred')
    expect(slotTone('UNKNOWN')).toBe('pending')
    expect(slotTone('REJECTED')).toBe('rejected')
  })
})

describe('formatSlotValue', () => {
  it('formats budget with the currency and travelers with the counter', () => {
    expect(formatSlotValue('budget', 5000)).toBe('¥5000')
    expect(formatSlotValue('travelers', 2)).toBe('2 位')
  })

  it('localizes pace and mobility', () => {
    expect(formatSlotValue('pace', 'RELAXED')).toBe('轻松')
    expect(formatSlotValue('mobility', 'STEP_FREE')).toBe('尽量无台阶')
  })

  it('joins arrays and renders anchors as place + time', () => {
    expect(formatSlotValue('must_visit', ['陈家祠', '沙面'])).toBe('陈家祠、沙面')
    expect(formatSlotValue('arrival', { place: '白云机场', time: '14:00' })).toBe('白云机场 14:00')
  })
})

describe('slotRows', () => {
  it('projects the completed payload in slot order, skipping empties', () => {
    const rows = slotRows({
      budget: { value: 5000, state: 'CONFIRMED' },
      destination: { value: '广州', state: 'CONFIRMED' },
      start_date: { value: null, state: 'UNKNOWN' },
      pace: { value: 'RELAXED', state: 'INFERRED' },
      avoid: { value: ['陈家祠'], state: 'REJECTED' },
    } as Record<string, { value: unknown; state: string }>)
    expect(rows.map((row) => row.name)).toEqual(['destination', 'budget', 'pace', 'avoid'])
    expect(rows[0].stateLabel).toBe('已确认')
    expect(rows[2].stateLabel).toBe('AI 推测')
    expect(rows[3].display).toBe('陈家祠')
  })
})

describe('creationSummary（Composer 创建摘要投影）', () => {
  const S = (value: unknown, state: string, source = 'USER_CONFIRMED') => ({ value, state, source })

  it('CONFIRMED 非 TRIP 槽位进入已了解；目的地/日期等 TRIP 事实不重复出现', () => {
    const summary = creationSummary({
      destination: S('广州', 'CONFIRMED', 'TRIP'),
      travelers: S(2, 'CONFIRMED'),
      budget: S(3000, 'CONFIRMED'),
      pace: S('RELAXED', 'CONFIRMED'),
    })
    expect(summary.known.map((row) => row.name)).toEqual(['travelers', 'budget', 'pace'])
    expect(summary.known[0].display).toBe('2 位')
    expect(summary.known[1].display).toBe('¥3000')
    expect(summary.pending).toEqual(['必去地点', '住宿位置', '抵达安排', '返程安排'])
  })

  it('INFERRED 槽位不进已了解，也不算已确认', () => {
    const summary = creationSummary({ travelers: S(2, 'INFERRED') })
    expect(summary.known).toEqual([])
    expect(summary.pending).toContain('出行人数')
  })

  it('空投影 → 已了解为空，待确认列全', () => {
    const summary = creationSummary(null)
    expect(summary.known).toEqual([])
    expect(summary.pending.length).toBeGreaterThan(0)
  })
})
