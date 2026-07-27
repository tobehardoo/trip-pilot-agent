import { cleanup, fireEvent, render } from '@testing-library/vue'
import { afterEach, expect, test } from 'vitest'

import TransitLegControl from '../src/components/TransitLegControl.vue'

afterEach(() => cleanup())

const leg = {
  id: 'leg-1',
  legOrder: 0,
  fromActivityId: 'a',
  toActivityId: 'b',
  mode: 'WALKING' as const,
  distanceMeters: 2400,
  durationSeconds: 1920,
  provider: 'AMAP' as const,
  estimated: false,
  estimatedCost: 0,
  providerRouteId: null,
  calculatedAt: '2026-07-27T06:00:00Z',
  stale: false,
  polyline: [],
}

test('opens commute options and emits the selected mode with a visible time delta', async () => {
  const view = render(TransitLegControl, {
    props: {
      leg,
      fromTitle: 'Museum',
      toTitle: 'Tower',
      selectedMode: 'WALKING',
    },
  })

  await fireEvent.click(view.getByTestId('transit-leg-open-leg-1'))
  expect(view.getByTestId('transit-option-TRANSIT')).toBeTruthy()
  expect(view.getByTestId('transit-option-TAXI')).toBeTruthy()
  expect(view.getByTestId('transit-option-TRANSIT').getAttribute('disabled')).toBeNull()
  expect(view.getByTestId('transit-option-TAXI').getAttribute('disabled')).toBeNull()

  await fireEvent.click(view.getByTestId('transit-option-DRIVING'))

  expect(view.emitted('select')).toEqual([['DRIVING']])
  expect(view.getByTestId('transit-change-leg-1').textContent).toContain('分钟')
  expect(view.getByTestId('transit-change-leg-1').textContent).toContain('¥')
})

test('does not allow a locked leg to switch modes', async () => {
  const view = render(TransitLegControl, {
    props: {
      leg,
      fromTitle: 'Museum',
      toTitle: 'Tower',
      selectedMode: 'WALKING',
      locked: true,
    },
  })

  await fireEvent.click(view.getByTestId('transit-leg-open-leg-1'))
  await fireEvent.click(view.getByTestId('transit-option-TRANSIT'))

  expect(view.emitted('select')).toBeUndefined()
  expect(view.getByTestId('transit-option-TRANSIT').getAttribute('disabled')).not.toBeNull()
})
