import { describe, expect, test } from 'vitest'

import { defaultTripTitle } from '../src/lib/trip-title'

describe('defaultTripTitle', () => {
  test('matches the server format for a same-year range', () => {
    expect(defaultTripTitle('广州', '2026-08-20', '2026-08-21'))
      .toBe('2026年08月20日—08月21日 广州市旅行规划')
  })

  test('keeps both years for a cross-year range', () => {
    expect(defaultTripTitle('广州', '2026-12-30', '2027-01-02'))
      .toBe('2026年12月30日—2027年01月02日 广州市旅行规划')
  })

  test('preserves an existing city suffix', () => {
    expect(defaultTripTitle('北京市', '2026-08-20', '2026-08-21'))
      .toBe('2026年08月20日—08月21日 北京市旅行规划')
  })

  test('preserves other region suffixes', () => {
    expect(defaultTripTitle('延边朝鲜族自治州', '2026-08-20', '2026-08-21'))
      .toBe('2026年08月20日—08月21日 延边朝鲜族自治州旅行规划')
  })

  test('trims the city before use', () => {
    expect(defaultTripTitle(' 广州 ', '2026-08-20', '2026-08-21'))
      .toBe('2026年08月20日—08月21日 广州市旅行规划')
  })

  test('yields no city subject for a blank city', () => {
    expect(defaultTripTitle('   ', '2026-08-20', '2026-08-21'))
      .toBe('2026年08月20日—08月21日 旅行规划')
  })
})
