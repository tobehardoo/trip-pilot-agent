import { fireEvent, render } from '@testing-library/vue'
import { describe, expect, it } from 'vitest'

import CityCascadePicker from './CityCascadePicker.vue'

describe('CityCascadePicker', () => {
  it('emits administrative codes with a city selection', async () => {
    const view = render(CityCascadePicker, {
      props: { districts: [] },
    })
    const selects = view.container.querySelectorAll('select')
    await fireEvent.update(selects[0], '广东省')
    const citySelect = view.container.querySelectorAll('select')[1]
    await fireEvent.update(citySelect, '广州')

    expect(view.emitted().change?.[0]).toEqual([{
      province: '广东省',
      provinceCode: '440000',
      city: '广州',
      cityCode: '440100',
      districts: ['全市'],
      districtCodes: [],
    }])
  })
})
