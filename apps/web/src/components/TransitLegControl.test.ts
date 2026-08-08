import { fireEvent, render } from '@testing-library/vue'
import { describe, expect, it } from 'vitest'

import TransitLegControl from './TransitLegControl.vue'

describe('TransitLegControl', () => {
  it('allows public transit and taxi selections to be submitted for backend recalculation', async () => {
    const view = render(TransitLegControl, {
      props: {
        leg: {
          id: 'leg-1',
          legOrder: 0,
          fromActivityId: 'activity-1',
          toActivityId: 'activity-2',
          mode: 'WALKING',
          locked: false,
          distanceMeters: 5_000,
          durationSeconds: 4_020,
          provider: 'AMAP',
          estimated: false,
          estimatedCost: 0,
          providerRouteId: null,
          calculatedAt: '2026-07-27T06:00:00Z',
          stale: false,
          polyline: [],
        },
        fromTitle: 'Museum',
        toTitle: 'Tower',
        selectedMode: 'WALKING',
      },
    })

    await fireEvent.click(view.getByTestId('transit-leg-open-leg-1'))
    const transit = view.container.querySelector(
      '[data-testid="transit-option-TRANSIT"]',
    ) as HTMLButtonElement
    const taxi = view.getByTestId('transit-option-TAXI') as HTMLButtonElement

    expect(transit.disabled).toBe(false)
    expect(taxi.disabled).toBe(false)

    await fireEvent.click(transit)
    await fireEvent.click(taxi)

    expect(view.emitted().select).toEqual([['TRANSIT'], ['TAXI']])
  })

  it('allows a mode that exceeds the activity gap and marks it as requiring replanning', async () => {
    const view = render(TransitLegControl, {
      props: {
        leg: {
          id: 'leg-conflict',
          legOrder: 0,
          fromActivityId: 'activity-1',
          toActivityId: 'activity-2',
          mode: 'WALKING',
          locked: false,
          distanceMeters: 5_000,
          durationSeconds: 4_020,
          provider: 'AMAP',
          estimated: false,
          estimatedCost: 0,
          providerRouteId: null,
          calculatedAt: '2026-07-27T06:00:00Z',
          stale: false,
          polyline: [],
        },
        fromTitle: 'Museum',
        toTitle: 'Tower',
        selectedMode: 'WALKING',
        availableSeconds: 600,
      },
    })

    await fireEvent.click(view.getByTestId('transit-leg-open-leg-conflict'))
    const transit = view.container.querySelector<HTMLButtonElement>('[data-testid="transit-option-TRANSIT"]')
    expect(transit).not.toBeNull()
    if (!transit) throw new Error('Expected the transit option')
    expect(transit.disabled).toBe(false)
    expect(transit.dataset.availability).toBe('requires-replan')

    await fireEvent.click(transit)
    expect(view.emitted().select).toEqual([['TRANSIT']])
    expect(view.getByRole('alert').textContent).toContain('需要调整活动时间')
  })
})
