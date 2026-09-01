import { describe, expect, test } from 'vitest'

import { DATA_SOURCE_LABELS, dataSourceLabel, isDemoSource } from '../src/lib/source-presentation'

describe('dataSourceLabel', () => {
  test('maps every known source to user language', () => {
    expect(dataSourceLabel('AMAP')).toBe('真实数据')
    expect(dataSourceLabel('DEMO')).toBe('演示数据')
    expect(dataSourceLabel('MIXED')).toBe('混合数据')
    expect(dataSourceLabel('PLANNER')).toBe('规划器数据')
  })

  test('never leaks an unknown or missing enum onto the surface', () => {
    expect(dataSourceLabel('CARTOGRAPHY_STARTUP')).toBeNull()
    expect(dataSourceLabel('')).toBeNull()
    expect(dataSourceLabel(null)).toBeNull()
    expect(dataSourceLabel(undefined)).toBeNull()
  })

  test('has no label that renders a raw enum value', () => {
    for (const [key, label] of Object.entries(DATA_SOURCE_LABELS)) {
      expect(label).not.toBe(key)
    }
  })
})

describe('isDemoSource', () => {
  test('flags only the demo source', () => {
    expect(isDemoSource('DEMO')).toBe(true)
    expect(isDemoSource('AMAP')).toBe(false)
    expect(isDemoSource('MIXED')).toBe(false)
    expect(isDemoSource(undefined)).toBe(false)
  })
})
