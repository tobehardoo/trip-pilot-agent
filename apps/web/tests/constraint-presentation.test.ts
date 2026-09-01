// 约束展示层（F-UI-3）：约束词汇的唯一来源。
// 反事实覆盖：内部枚举不得上屏、未设置的可选约束不占行、
// 且 Agent 约束板与行程页摘要必须同口径（同一张表，不是第二份文案）。

import { describe, expect, it } from 'vitest'

import type { TripConstraints } from '../src/lib/api'
import {
  MOBILITY_OPTIONS,
  PACE_OPTIONS,
  TRAVELER_TYPE_OPTIONS,
  accommodationStatusLabel,
  constraintLabel,
  formatConstraintRows,
  mobilityLabel,
  paceLabel,
  travelerTypeLabel,
} from '../src/lib/constraint-presentation'
import { formatSlotValue, slotRows } from '../src/lib/agent-slots'

function constraints(partial: Partial<TripConstraints> = {}): TripConstraints {
  return {
    budgetAmount: null,
    travelers: 2,
    travelerType: 'FRIENDS',
    pace: 'BALANCED',
    preferences: [],
    fixedSchedules: [],
    ...partial,
  }
}

describe('enum labels', () => {
  it('uses the unified pace wording', () => {
    expect(paceLabel('RELAXED')).toBe('轻松')
    expect(paceLabel('BALANCED')).toBe('均衡')
    expect(paceLabel('INTENSIVE')).toBe('紧凑')
  })

  it('never renders an internal enum literal', () => {
    for (const value of ['RELAXED', 'BALANCED', 'INTENSIVE']) {
      expect(paceLabel(value)).not.toBe(value)
    }
    for (const value of ['STANDARD', 'REDUCED', 'STEP_FREE']) {
      expect(mobilityLabel(value)).not.toBe(value)
    }
    for (const value of ['SOLO', 'COUPLE', 'FAMILY', 'FRIENDS', 'BUSINESS']) {
      expect(travelerTypeLabel(value)).not.toBe(value)
    }
  })

  it('is case-insensitive and keeps unknown values visible', () => {
    expect(paceLabel('relaxed')).toBe('轻松')
    expect(mobilityLabel(undefined)).toBe('')
    expect(travelerTypeLabel('SCHOOL_GROUP')).toBe('SCHOOL_GROUP')
  })

  it('labels the accommodation resolution states', () => {
    expect(accommodationStatusLabel('CONFIRMED')).toBe('已确认')
    expect(accommodationStatusLabel('AREA_ESTIMATED')).toBe('区域估计')
    expect(accommodationStatusLabel('UNRESOLVED')).toBe('未定位')
    expect(accommodationStatusLabel(null)).toBe('')
  })
})

describe('choice tables', () => {
  it('covers every enum value so no editor loses an option', () => {
    expect(PACE_OPTIONS.map((option) => option.value)).toEqual(['RELAXED', 'BALANCED', 'INTENSIVE'])
    expect(MOBILITY_OPTIONS.map((option) => option.value)).toEqual(['STANDARD', 'REDUCED', 'STEP_FREE'])
    expect(TRAVELER_TYPE_OPTIONS.map((option) => option.value)).toEqual([
      'SOLO',
      'COUPLE',
      'FAMILY',
      'FRIENDS',
      'BUSINESS',
    ])
  })

  it('keeps enum literals out of the option labels', () => {
    for (const option of [...PACE_OPTIONS, ...MOBILITY_OPTIONS, ...TRAVELER_TYPE_OPTIONS]) {
      expect(option.label).not.toBe(option.value)
    }
  })
})

describe('constraintLabel', () => {
  it('translates known fields and passes unknown ones through', () => {
    expect(constraintLabel('budget')).toBe('总预算')
    expect(constraintLabel('travelers')).toBe('出行人数')
    expect(constraintLabel('weather_window')).toBe('weather_window')
  })

  it('is the same vocabulary the agent constraint board uses', () => {
    const rows = slotRows({ budget: { value: 5000, state: 'CONFIRMED' }, pace: { value: 'RELAXED', state: 'INFERRED' } })
    expect(rows.map((row) => row.label)).toEqual([constraintLabel('budget'), constraintLabel('pace')])
    expect(formatSlotValue('pace', 'RELAXED')).toBe(paceLabel('RELAXED'))
  })
})

describe('formatConstraintRows', () => {
  it('always projects travelers and pace, and hides unset optionals', () => {
    const rows = formatConstraintRows(constraints())
    expect(rows.map((row) => row.key)).toEqual(['travelers', 'pace'])
    expect(rows[0]).toEqual({ key: 'travelers', label: '出行人数', value: '2 人 · 朋友同行' })
    expect(rows[1].value).toBe('均衡')
  })

  it('projects set optionals in stable order', () => {
    const rows = formatConstraintRows(
      constraints({
        budgetAmount: 5200,
        preferences: ['岭南文化', '本地美食'],
        mustVisitPlaces: ['陈家祠', '沙面'],
        accommodation: { placeName: '北京路附近酒店' },
        arrival: { placeName: '广州南站', time: '11:00' },
      }),
    )
    expect(rows.map((row) => row.key)).toEqual([
      'budget',
      'travelers',
      'pace',
      'accommodation',
      'preferences',
      'must_visit',
      'arrival',
    ])
    expect(rows[0].value).toBe('¥5200')
    expect(rows[3].value).toBe('北京路附近酒店')
    expect(rows[4].value).toBe('岭南文化、本地美食')
    expect(rows[5].value).toBe('陈家祠、沙面')
  })

  it('keeps arrival and departure as independent rows', () => {
    const rows = formatConstraintRows(
      constraints({
        departure: { placeName: '广州白云机场', time: '17:00' },
      }),
    )
    expect(rows.map((row) => row.key)).toEqual(['travelers', 'pace', 'departure'])
    expect(rows[2].label).toBe('返程安排')
  })

  it('renders an empty accommodation anchor as no row', () => {
    const rows = formatConstraintRows(constraints({ accommodation: { placeName: '' } }))
    expect(rows.map((row) => row.key)).toEqual(['travelers', 'pace'])
  })
})
