import { describe, expect, test } from 'vitest'

import { buildMapModel, projectMapCoordinate, type MapCoordinate } from '../src/lib/map'

const coordinate = (longitude: number, latitude: number): MapCoordinate => ({ longitude, latitude })

describe('itinerary map model', () => {
  test('flattens activities and transit legs while preserving day order', () => {
    const model = buildMapModel({
      days: [
        {
          date: '2026-07-18',
          activities: [
            { id: 'a', title: '沙面', coordinates: coordinate(113.24, 23.11) },
            { id: 'b', title: '早茶', coordinates: coordinate(113.25, 23.12) },
          ],
          transitLegs: [{ id: 'l1', legOrder: 0, fromActivityId: 'a', toActivityId: 'b', mode: 'WALKING', distanceMeters: 800, durationSeconds: 600, provider: 'DEMO', estimated: true, polyline: [coordinate(113.24, 23.11), coordinate(113.25, 23.12)] }],
        },
      ],
    })

    expect(model.activities.map((activity) => activity.id)).toEqual(['a', 'b'])
    expect(model.legs.map((leg) => leg.id)).toEqual(['l1'])
    expect(model.bounds).toEqual({ minLongitude: 113.24, maxLongitude: 113.25, minLatitude: 23.11, maxLatitude: 23.12 })
  })

  test('projects a coordinate into a stable 0..100 overview viewport', () => {
    const bounds = { minLongitude: 113, maxLongitude: 114, minLatitude: 22, maxLatitude: 23 }

    expect(projectMapCoordinate(coordinate(113, 22), bounds)).toEqual({ x: 8, y: 92 })
    expect(projectMapCoordinate(coordinate(114, 23), bounds)).toEqual({ x: 92, y: 8 })
  })

  test('ignores activities without coordinates and tolerates legacy days without transit legs', () => {
    const model = buildMapModel({
      days: [{ date: '2026-07-18', activities: [{ id: 'a', title: '无坐标', coordinates: null }] }],
    })

    expect(model.activities).toEqual([])
    expect(model.legs).toEqual([])
    expect(model.bounds).toBeNull()
  })
})
