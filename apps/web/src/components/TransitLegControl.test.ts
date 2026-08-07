import { cleanup, fireEvent, render } from '@testing-library/vue'
import { afterEach, describe, expect, it } from 'vitest'

import type { ItineraryTransitLeg } from '../lib/api'
import TransitLegControl from './TransitLegControl.vue'

afterEach(() => cleanup())

function makeLeg(overrides: Partial<ItineraryTransitLeg> = {}): ItineraryTransitLeg {
  return {
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
    ...overrides,
  }
}

function renderLeg(props: Record<string, unknown>) {
  const view = render(TransitLegControl, {
    props: { leg: makeLeg(), fromTitle: 'Museum', toTitle: 'Tower', selectedMode: 'WALKING', ...props },
  })
  return view
}

describe('TransitLegControl', () => {
  it('keeps public transit and taxi selections to be submitted for backend recalculation', async () => {
    const view = renderLeg({})
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

  // T1: availableSeconds = 20min, walking = 10min, transit = 35min.
  it('keeps a slower mode selectable and marks it as requiring replan (T1)', async () => {
    const view = renderLeg({
      leg: makeLeg({ mode: 'WALKING', durationSeconds: 600, distanceMeters: 9_240 }),
      availableSeconds: 1200,
    })
    await fireEvent.click(view.getByTestId('transit-leg-open-leg-1'))

    const walking = view.container.querySelector(
      '[data-testid="transit-option-WALKING"]',
    ) as HTMLButtonElement
    const transit = view.container.querySelector(
      '[data-testid="transit-option-TRANSIT"]',
    ) as HTMLButtonElement

    // 步行 10 分钟 <= 20 分钟：AVAILABLE，可选。
    expect(walking.disabled).toBe(false)
    // 公交约 35 分钟 > 20 分钟：REQUIRES_REPLAN，仍然可选，不是 disabled。
    expect(transit.disabled).toBe(false)
    expect(transit.textContent).toContain('需要调整行程')

    await fireEvent.click(transit)

    // 选中后显示"需要调整后续行程"提示（比空档多约 15 分钟）。
    const note = view.getByTestId('transit-requires-replan-note')
    expect(note.textContent).toContain('15')
    expect(view.emitted().select).toEqual([['TRANSIT']])
  })

  // T2: 用户显式锁定后，其他方式才真正禁用。
  it('disables other modes only when the user explicitly locks the leg (T2)', async () => {
    const view = renderLeg({ locked: true })
    await fireEvent.click(view.getByTestId('transit-leg-open-leg-1'))

    const walking = view.container.querySelector(
      '[data-testid="transit-option-WALKING"]',
    ) as HTMLButtonElement
    const transit = view.container.querySelector(
      '[data-testid="transit-option-TRANSIT"]',
    ) as HTMLButtonElement

    expect(walking.disabled).toBe(false) // 当前方式仍可选
    expect(transit.disabled).toBe(true) // 锁定后其他方式禁用
  })

  // T3: locked=false、规划器默认 DRIVING，所有方式仍可选。
  it('keeps all modes selectable when unlocked even if the planner default is DRIVING (T3)', async () => {
    const view = renderLeg({ selectedMode: 'DRIVING', locked: false })
    await fireEvent.click(view.getByTestId('transit-leg-open-leg-1'))

    for (const mode of ['WALKING', 'TRANSIT', 'DRIVING', 'TAXI']) {
      const button = view.container.querySelector(
        `[data-testid="transit-option-${mode}"]`,
      ) as HTMLButtonElement
      expect(button.disabled).toBe(false)
    }
  })

  // T4: AUTO 只推荐，不自动锁定。
  it('AUTO recommends a mode without locking the leg (T4)', async () => {
    const view = renderLeg({
      leg: makeLeg({ mode: 'DRIVING', durationSeconds: 600, distanceMeters: 3_000 }),
      selectedMode: 'DRIVING',
    })
    await fireEvent.click(view.getByTestId('transit-leg-open-leg-1'))
    await fireEvent.click(view.getByTestId('transit-option-AUTO'))

    // 该距离下推荐公交；AUTO 只是推荐，不触发锁定。
    expect(view.emitted().select).toEqual([['TRANSIT']])
    expect(view.emitted().lock).toBeUndefined()
  })

  // T5: 选择比时间空档更长的方式会正常发出选择（进入 requires-replan 流程）。
  it('selecting a slower mode emits select and enters the requires-replan state (T5)', async () => {
    const view = renderLeg({
      leg: makeLeg({ mode: 'WALKING', durationSeconds: 600, distanceMeters: 9_240 }),
      availableSeconds: 1200,
    })
    await fireEvent.click(view.getByTestId('transit-leg-open-leg-1'))
    await fireEvent.click(view.container.querySelector(
      '[data-testid="transit-option-TRANSIT"]',
    ) as HTMLButtonElement)

    expect(view.emitted().select).toEqual([['TRANSIT']])
    expect(view.getByTestId('transit-requires-replan-note')).toBeTruthy()
  })
})
