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

test('opens commute options without exposing a persistent driving choice', async () => {
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
  expect(view.queryByTestId('transit-option-DRIVING')).toBeNull()
  expect(view.getByTestId('transit-option-TRANSIT').getAttribute('disabled')).toBeNull()
  expect(view.getByTestId('transit-option-TAXI').getAttribute('disabled')).toBeNull()

  await fireEvent.click(view.getByTestId('transit-option-TAXI'))

  expect(view.emitted('select')).toEqual([['TAXI']])
  expect(view.getByTestId('transit-change-leg-1').textContent).toContain('保存后由路线服务计算')
  expect(view.getByTestId('transit-change-leg-1').textContent).not.toContain('¥')
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

test('emits AUTO without guessing a concrete recommendation', async () => {
  const view = render(TransitLegControl, {
    props: {
      leg,
      fromTitle: 'Museum',
      toTitle: 'Tower',
      selectedMode: 'WALKING',
    },
  })

  await fireEvent.click(view.getByTestId('transit-leg-open-leg-1'))
  expect(view.queryByText(/推荐 |最快 |最省钱 /)).toBeNull()
  await fireEvent.click(view.getByTestId('transit-option-AUTO'))

  expect(view.emitted('select')).toEqual([['AUTO']])
  expect(view.getByTestId('transit-leg-open-leg-1').textContent).toContain('自动推荐')
})

test('shows the persisted WALKING mode label initially', () => {
  const view = render(TransitLegControl, {
    props: {
      leg,
      fromTitle: 'Museum',
      toTitle: 'Tower',
      selectedMode: 'WALKING',
    },
  })

  // A persisted WALKING leg must display as 步行, not 驾车.
  expect(view.getByTestId('transit-leg-open-leg-1').textContent).toContain('步行')
  expect(view.getByTestId('transit-leg-open-leg-1').textContent).not.toContain('驾车')
})

test('shows the persisted TRANSIT mode label initially', () => {
  const view = render(TransitLegControl, {
    props: {
      leg: { ...leg, mode: 'TRANSIT' as const },
      fromTitle: 'Museum',
      toTitle: 'Tower',
      selectedMode: 'TRANSIT',
    },
  })

  // A persisted TRANSIT leg must display as 公交/地铁.
  expect(view.getByTestId('transit-leg-open-leg-1').textContent).toContain('公交/地铁')
})

test('presents persisted DRIVING as taxi and hides its road toll', () => {
  const view = render(TransitLegControl, {
    props: {
      leg: {
        ...leg,
        mode: 'DRIVING' as const,
        estimatedCost: 6.5,
        displayCost: null,
        costMeaning: 'ROAD_TOLL',
        modeLabel: '打车',
      },
      fromTitle: 'Museum',
      toTitle: 'Tower',
      selectedMode: 'DRIVING',
    },
  })

  const summary = view.getByTestId('transit-leg-open-leg-1').textContent ?? ''
  expect(summary).toContain('打车')
  expect(summary).not.toContain('驾车')
  expect(summary).not.toContain('¥')
})
