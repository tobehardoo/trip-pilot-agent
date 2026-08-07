import { fireEvent, render, type RenderResult } from '@testing-library/vue'
import { describe, expect, it } from 'vitest'

import DestinationRegionSelector from './DestinationRegionSelector.vue'

/**
 * P4-F3 regression: switching province (or re-selecting the same province)
 * while the city is not yet chosen emits a null back to the parent; the
 * parent echoes that null back as modelValue. The selector must keep the
 * province selection and only clear the city/districts, otherwise the city
 * dropdown stays disabled and the user cannot complete the switch.
 */
describe('DestinationRegionSelector', () => {
  it('keeps the province when the parent echoes null after a province change', async () => {
    const view: RenderResult = render(DestinationRegionSelector, {
      props: { modelValue: null },
    })
    const province = view.container.querySelector('#region-province') as HTMLSelectElement
    const city = view.container.querySelector('#region-city') as HTMLSelectElement

    // Select 广东省 -> onProvinceChange clears the city, emitRegion emits
    // null because no city is selected yet.
    await fireEvent.change(province, { target: { value: '广东省' } })
    expect(province.value).toBe('广东省')

    // Parent echoes null (destinationRegion cleared while city pending).
    await view.rerender({ modelValue: null })

    // Province must survive; the city must be cleared but stay enabled.
    expect(province.value).toBe('广东省')
    expect(city.value).toBe('')
    expect(city.disabled).toBe(false)
  })

  it('clears everything only when province is also unset', async () => {
    const view: RenderResult = render(DestinationRegionSelector, {
      props: { modelValue: null },
    })
    const province = view.container.querySelector('#region-province') as HTMLSelectElement
    const city = view.container.querySelector('#region-city') as HTMLSelectElement

    expect(province.value).toBe('')
    expect(city.disabled).toBe(true)
  })

  it('still backfills a full region from props (edit flow)', async () => {
    const view: RenderResult = render(DestinationRegionSelector, {
      props: {
        modelValue: {
          provinceCode: '440000',
          provinceName: '广东省',
          cityCode: '440100',
          cityName: '广州',
          districts: [{ districtCode: '440106', districtName: '天河区' }],
        },
      },
    })
    const province = view.container.querySelector('#region-province') as HTMLSelectElement
    const city = view.container.querySelector('#region-city') as HTMLSelectElement
    expect(province.value).toBe('广东省')
    expect(city.value).toBe('广州')
    expect(city.disabled).toBe(false)
  })
})
