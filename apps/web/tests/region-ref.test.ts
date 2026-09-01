import { describe, expect, it } from 'vitest'

import { destinationToRegionRef } from '../src/lib/constraint-draft'

describe('structured destination region references', () => {
  it('creates a canonical region reference when administrative codes are present', () => {
    const destination = {
      province: '广东省',
      provinceCode: '440000',
      city: '广州市',
      cityCode: '440100',
      districts: ['天河区'],
      districtCodes: ['440106'],
    }

    expect(destinationToRegionRef(destination)).toEqual({
      provinceCode: '440000',
      cityCode: '440100',
      districtCodes: ['440106'],
      provinceName: '广东省',
      cityName: '广州市',
      districtNames: ['天河区'],
      datasetVersion: '2023-06-30',
    })
  })

  it('keeps string-only destinations backward compatible', () => {
    // Legacy free-text destinations never fabricate administrative codes.
    expect(destinationToRegionRef('拉萨')).toBeUndefined()
    expect(destinationToRegionRef('')).toBeUndefined()
  })

  it('requires both province and city codes on structured destinations', () => {
    expect(destinationToRegionRef({
      province: '广东省',
      city: '广州市',
      districts: ['天河区'],
      districtCodes: ['440106'],
    })).toBeUndefined()
    expect(destinationToRegionRef({
      province: '广东省',
      provinceCode: '440000',
      city: '广州市',
      districts: ['天河区'],
      districtCodes: ['440106'],
    })).toBeUndefined()
  })

  it('treats missing district codes as an empty leaf list', () => {
    expect(destinationToRegionRef({
      province: '广东省',
      provinceCode: '440000',
      city: '广州市',
      cityCode: '440100',
      districts: [],
    })?.districtCodes).toEqual([])
  })

  it('accepts municipality districts under the municipality city code', () => {
    const region = destinationToRegionRef({
      province: '北京市',
      provinceCode: '110000',
      city: '北京市',
      cityCode: '110000',
      districts: ['东城区'],
      districtCodes: ['110101'],
    })

    expect(region?.districtCodes).toEqual(['110101'])
  })

  it('rejects province codes that are not province-level administrative codes', () => {
    // B13_FIX R8 (P1-8): branch coverage for administrative-code shape.
    expect(destinationToRegionRef({
      province: '广东省',
      provinceCode: '440100',
      city: '广州市',
      cityCode: '440100',
      districts: ['天河区'],
      districtCodes: ['440106'],
    })).toBeUndefined()
  })

  it('rejects province/city prefixes that do not match', () => {
    expect(destinationToRegionRef({
      province: '广东省',
      provinceCode: '440000',
      city: '上海市',
      cityCode: '310000',
      districts: ['黄浦区'],
      districtCodes: ['310101'],
    })).toBeUndefined()
  })

  it('rejects malformed or non-leaf district codes', () => {
    const base = {
      province: '广东省',
      provinceCode: '440000',
      city: '广州市',
      cityCode: '440100',
      districts: ['天河区'],
    }
    // Not six digits.
    expect(destinationToRegionRef({ ...base, districtCodes: ['4401'] })).toBeUndefined()
    // The district code equals the city code.
    expect(destinationToRegionRef({ ...base, districtCodes: ['440100'] })).toBeUndefined()
    // A district code ending in 00 is a city-level code, not a leaf district.
    expect(destinationToRegionRef({ ...base, districtCodes: ['440000'] })).toBeUndefined()
    // A district outside the city's prefix.
    expect(destinationToRegionRef({ ...base, districtCodes: ['310101'] })).toBeUndefined()
    // A mix where one entry is invalid rejects the whole destination.
    expect(destinationToRegionRef({
      ...base,
      districts: ['天河区', '越秀区'],
      districtCodes: ['440106', '4401049'],
    })).toBeUndefined()
  })
})
