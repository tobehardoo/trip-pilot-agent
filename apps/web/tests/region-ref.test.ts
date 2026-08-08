import { describe, expect, it } from 'vitest'

import {
  destinationToRegionRef,
  toCreateTripInput,
  type ConstraintDraft,
} from '../src/lib/constraint-draft'

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
    const draft = {
      destination: { value: '拉萨', source: 'explicit' },
      startDate: { value: '2026-08-01', source: 'explicit' },
      endDate: { value: '2026-08-02', source: 'explicit' },
      travelers: { value: 1, source: 'default' },
      budgetAmount: { value: 3000, source: 'default' },
      preferences: { value: [], source: 'unset' },
      mustVisitPlaces: { value: [], source: 'unset' },
      pace: { value: 'BALANCED', source: 'default' },
    } satisfies ConstraintDraft

    expect(toCreateTripInput(draft, '拉萨之旅').region).toBeUndefined()
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
})
