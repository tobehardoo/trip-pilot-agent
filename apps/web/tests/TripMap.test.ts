import { cleanup, fireEvent, render, screen } from '@testing-library/vue'
import { afterEach, expect, test, vi } from 'vitest'

import TripMap from '../src/components/TripMap.vue'

afterEach(() => {
  cleanup()
  delete window.AMap
  vi.unstubAllEnvs()
})

const itinerary = {
  days: [{
    date: '2026-07-18',
    activities: [
      { id: 'a', title: '沙面', startTime: '2026-07-18T01:00:00Z', endTime: '2026-07-18T03:00:00Z', estimatedCost: 0, source: 'DEMO' as const, providerPoiId: null, coordinates: { longitude: 113.24, latitude: 23.11 }, address: '广州' },
      { id: 'b', title: '早茶', startTime: '2026-07-18T04:00:00Z', endTime: '2026-07-18T05:00:00Z', estimatedCost: 100, source: 'DEMO' as const, providerPoiId: null, coordinates: { longitude: 113.25, latitude: 23.12 }, address: '广州' },
    ],
    transitLegs: [{ id: 'l1', legOrder: 0, fromActivityId: 'a', toActivityId: 'b', mode: 'WALKING' as const, distanceMeters: 800, durationSeconds: 600, provider: 'DEMO' as const, estimated: true, polyline: [{ longitude: 113.24, latitude: 23.11 }, { longitude: 113.25, latitude: 23.12 }] }],
  }],
}

test('renders a clickable route overview when the AMap JS key is absent', async () => {
  const result = render(TripMap, {
    props: {
      itinerary,
      selectedActivityId: 'a',
    },
  })

  expect(screen.getByRole('region', { name: '行程地图' })).toBeTruthy()
  expect(screen.getByLabelText('路线概览')).toBeTruthy()
  expect(screen.getByRole('button', { name: '定位 沙面' }).getAttribute('aria-pressed')).toBe('true')
  expect(screen.getByRole('button', { name: '定位 早茶' }).getAttribute('aria-pressed')).toBe('false')
  const hiddenMapCanvas = result.container.querySelector<HTMLElement>('.amap-canvas')
  expect(hiddenMapCanvas).not.toBeNull()
  expect(hiddenMapCanvas?.classList.contains('is-hidden')).toBe(true)
  expect(getComputedStyle(hiddenMapCanvas!).display).not.toBe('none')

  await fireEvent.click(screen.getByRole('button', { name: '定位 早茶' }))
  expect(result.emitted().selectActivity).toEqual([['b']])
})

test('renders AMap markers and polylines and releases the map on unmount', async () => {
  vi.stubEnv('VITE_AMAP_WEB_JS_KEY', 'browser-js-key')
  vi.stubEnv('VITE_AMAP_SECURITY_CODE', 'browser-security-code')
  const setFitView = vi.fn()
  const destroy = vi.fn()
  const markerSetMap = vi.fn()
  const polylineSetMap = vi.fn()
  const markerHandlers: Array<() => void> = []
  window.AMap = {
    Map: class {
      setFitView = setFitView
      destroy = destroy
    },
    Marker: class {
      setMap = markerSetMap
      on(_event: string, handler: () => void) { markerHandlers.push(handler) }
    },
    Polyline: class {
      setMap = polylineSetMap
    },
  }

  const result = render(TripMap, { props: { itinerary, selectedActivityId: 'a' } })
  expect(await screen.findByText('高德地图')).toBeTruthy()
  expect(markerSetMap).toHaveBeenCalledTimes(2)
  expect(polylineSetMap).toHaveBeenCalledTimes(1)
  expect(setFitView).toHaveBeenCalledTimes(1)

  markerHandlers[1]()
  expect(result.emitted().selectActivity).toEqual([['b']])
  result.unmount()
  expect(destroy).toHaveBeenCalledTimes(1)
})

test('does not select an unrelated marker when the timeline activity has no coordinate', () => {
  const activityWithoutCoordinates = {
    ...itinerary.days[0].activities[0],
    id: 'c',
    title: '室内休息',
    coordinates: null,
  }
  render(TripMap, {
    props: {
      itinerary: { days: [{ ...itinerary.days[0], activities: [...itinerary.days[0].activities, activityWithoutCoordinates] }] },
      selectedActivityId: 'c',
    },
  })

  expect(screen.getByRole('button', { name: '定位 沙面' }).getAttribute('aria-pressed')).toBe('false')
  expect(screen.getByRole('button', { name: '定位 早茶' }).getAttribute('aria-pressed')).toBe('false')
})

test('destroys a partially initialized map when an overlay fails to render', async () => {
  vi.stubEnv('VITE_AMAP_WEB_JS_KEY', 'browser-js-key')
  vi.stubEnv('VITE_AMAP_SECURITY_CODE', 'browser-security-code')
  const destroy = vi.fn()
  window.AMap = {
    Map: class {
      setFitView() {}
      destroy = destroy
    },
    Marker: class {
      constructor() { throw new Error('marker construction failed') }
      setMap() {}
    },
    Polyline: class {
      setMap() {}
    },
  }

  render(TripMap, { props: { itinerary: { days: [{ ...itinerary.days[0], transitLegs: [] }] }, selectedActivityId: 'a' } })

  expect(await screen.findByText('高德地图暂时无法加载，已切换为路线概览')).toBeTruthy()
  expect(destroy).toHaveBeenCalledTimes(1)
})
