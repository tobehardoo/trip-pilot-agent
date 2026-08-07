import { fireEvent, render, type RenderResult } from '@testing-library/vue'
import { describe, expect, it } from 'vitest'

import type { Trip } from '../lib/api'
import TripConstraintForm from './TripConstraintForm.vue'

function makeTrip(overrides: Partial<Trip> = {}): Trip {
  return {
    id: 'trip-1',
    title: '时区回填',
    destination: '广州',
    destinationRegion: {
      provinceCode: '440000',
      provinceName: '广东省',
      cityCode: '440100',
      cityName: '广州',
      districts: [],
    },
    startDate: '2026-08-08',
    endDate: '2026-08-10',
    status: 'DRAFT',
    version: 0,
    constraints: {
      budgetAmount: null,
      travelers: 1,
      travelerType: 'SOLO',
      pace: 'BALANCED',
      mobilityLevel: 'STANDARD',
      preferences: [],
      mustVisitPlaces: [],
      avoidPlaces: [],
      fixedSchedules: [],
      mealWindows: [
        { mealType: 'BREAKFAST', startTime: '08:00', endTime: '09:00', source: 'SYSTEM_DEFAULT' },
        { mealType: 'LUNCH', startTime: '12:00', endTime: '13:00', source: 'SYSTEM_DEFAULT' },
        { mealType: 'DINNER', startTime: '18:00', endTime: '19:00', source: 'SYSTEM_DEFAULT' },
      ],
      arrival: {
        placeName: '广州南站',
        // UTC instant of 2026-08-08T14:30:00+08:00. Backend stores UTC.
        time: '2026-08-08T06:30:00Z',
        poi: {
          name: '广州南站', providerPoiId: 'B00140VAP3', fullAddress: '南站北路',
          longitude: 113.269097, latitude: 22.988344, city: '广州', district: '番禺区',
          provinceCode: '440000', cityCode: '440100', districtCode: null,
          provider: 'AMAP', category: '火车站', categoryCode: '150200',
        },
      },
      departure: {
        placeName: '广州白云国际机场',
        time: '2026-08-10T08:00:00Z',
        poi: {
          name: '广州白云国际机场', providerPoiId: 'B00140NZIQ', fullAddress: null,
          longitude: 113.304651, latitude: 23.377894, city: '广州', district: '花都区',
          provinceCode: '440000', cityCode: '440100', districtCode: null,
          provider: 'AMAP', category: '飞机场', categoryCode: '150104',
        },
      },
      accommodation: null,
    },
    createdAt: '2026-08-01T00:00:00Z',
    updatedAt: '2026-08-01T00:00:00Z',
    archivedAt: null,
    ...overrides,
  }
}

describe('TripConstraintForm timezone round-trip (P4.6 regression)', () => {
  it('backfills arrival/departure times in Beijing time from UTC storage', async () => {
    const view: RenderResult = render(TripConstraintForm, {
      props: { initial: makeTrip() },
    })
    const arrivalTime = view.container.querySelector('#arrival-time') as HTMLInputElement
    const departureTime = view.container.querySelector('#departure-time') as HTMLInputElement
    const arrivalDate = view.container.querySelector('#arrival-date') as HTMLInputElement
    const departureDate = view.container.querySelector('#departure-date') as HTMLInputElement

    // 06:30Z == 14:30+08:00; 08:00Z == 16:00+08:00.
    expect(arrivalTime.value).toBe('14:30')
    expect(departureTime.value).toBe('16:00')
    expect(arrivalDate.value).toBe('2026-08-08')
    expect(departureDate.value).toBe('2026-08-10')
  })

  it('treats an unparseable time as absent instead of crashing', async () => {
    const view: RenderResult = render(TripConstraintForm, {
      props: { initial: makeTrip({ constraints: { ...makeTrip().constraints, arrival: null, departure: null } }) },
    })
    const arrivalTime = view.container.querySelector('#arrival-time') as HTMLInputElement
    const departureTime = view.container.querySelector('#departure-time') as HTMLInputElement
    expect(arrivalTime.value).toBe('')
    expect(departureTime.value).toBe('')
  })
})

describe('TripConstraintForm arrival keyword validation (P5)', () => {
  it('blocks submit when a keyword is typed but no POI is selected', async () => {
    const view: RenderResult = render(TripConstraintForm, {
      props: {
        initial: makeTrip({ constraints: { ...makeTrip().constraints, arrival: null, departure: null } }),
      },
    })
    const searchInput = view.container.querySelector(
      'input[data-testid="poi-search-input"]',
    ) as HTMLInputElement
    await fireEvent.update(searchInput, '广州南')
    await fireEvent.click(view.container.querySelector('button[type="submit"]') as HTMLButtonElement)

    expect(await view.findByText(/请从列表中选择到达地点，并完整填写到达日期和时间/)).toBeTruthy()
    expect(view.emitted('submit')).toBeUndefined()
  })

  it('submits when the typed keyword has been replaced by a selected POI', async () => {
    const poi = makeTrip().constraints.arrival!.poi!
    const suggest = async () => ({
      items: [
        {
          itemType: 'POI' as const,
          provider: 'AMAP',
          providerPoiId: poi.providerPoiId,
          name: poi.name,
          category: poi.category,
          categoryCode: poi.categoryCode,
          provinceCode: poi.provinceCode,
          cityCode: poi.cityCode,
          districtCode: poi.districtCode,
          fullAddress: poi.fullAddress,
          districtName: poi.district,
          longitude: poi.longitude,
          latitude: poi.latitude,
        },
      ],
    })
    const view: RenderResult = render(TripConstraintForm, {
      props: {
        initial: makeTrip({ constraints: { ...makeTrip().constraints, arrival: null, departure: null } }),
        suggestPlaces: suggest,
      },
    })
    const searchInput = view.container.querySelector(
      'input[data-testid="poi-search-input"]',
    ) as HTMLInputElement
    await fireEvent.update(searchInput, '广州南')
    const poiRow = await view.findByTestId('poi-row')
    await fireEvent.click(poiRow)
    await fireEvent.update(
      view.container.querySelector('#arrival-time') as HTMLInputElement,
      '14:30',
    )
    await fireEvent.click(view.container.querySelector('button[type="submit"]') as HTMLButtonElement)

    const emittedArgs = view.emitted('submit')?.[0] as unknown[] | undefined
    const payload = emittedArgs?.[0] as { constraints: { arrival: { poi: { providerPoiId: string } } } } | undefined
    expect(payload?.constraints.arrival.poi.providerPoiId).toBe(poi.providerPoiId)
  })
})
