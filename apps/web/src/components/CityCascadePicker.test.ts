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

  it('emits same province/city code for Beijing municipality', async () => {
    const view = render(CityCascadePicker, {
      props: { districts: [] },
    })
    const selects = view.container.querySelectorAll('select')
    await fireEvent.update(selects[0], '北京市')
    const citySelect = view.container.querySelectorAll('select')[1]
    await fireEvent.update(citySelect, '北京')

    expect(view.emitted().change?.[0]).toEqual([{
      province: '北京市',
      provinceCode: '110000',
      city: '北京',
      cityCode: '110000',
      districts: ['全市'],
      districtCodes: [],
    }])
  })

  it('emits same province/city code for Chongqing municipality', async () => {
    const view = render(CityCascadePicker, {
      props: { districts: [] },
    })
    const selects = view.container.querySelectorAll('select')
    await fireEvent.update(selects[0], '重庆市')
    const citySelect = view.container.querySelectorAll('select')[1]
    await fireEvent.update(citySelect, '重庆')

    expect(view.emitted().change?.[0]).toEqual([{
      province: '重庆市',
      provinceCode: '500000',
      city: '重庆',
      cityCode: '500000',
      districts: ['全市'],
      districtCodes: [],
    }])
  })

  it('toggles a concrete district on and off with fallback to 全市', async () => {
    // B13_FIX R8 (P1-8): district toggle branches.
    const view = render(CityCascadePicker, {
      props: { districts: [] },
    })
    const selects = view.container.querySelectorAll('select')
    await fireEvent.update(selects[0], '广东省')
    const citySelect = view.container.querySelectorAll('select')[1]
    await fireEvent.update(citySelect, '广州')

    const districtButtons = view.container.querySelectorAll<HTMLButtonElement>('button')
    const tianhe = [...districtButtons].find((b) => b.textContent?.includes('天河'))
    expect(tianhe).toBeTruthy()

    // Toggle on: 全市 replaced by the concrete district.
    await fireEvent.click(tianhe!)
    const change = view.emitted().change
    expect(change?.[1]).toEqual([{
      province: '广东省',
      provinceCode: '440000',
      city: '广州',
      cityCode: '440100',
      districts: ['天河区'],
      districtCodes: ['440106'],
    }])

    // Toggle off again: empty selection falls back to 全市.
    await fireEvent.click(tianhe!)
    expect(view.emitted().change?.[2]).toEqual([{
      province: '广东省',
      provinceCode: '440000',
      city: '广州',
      cityCode: '440100',
      districts: ['全市'],
      districtCodes: [],
    }])
  })

  it('syncs province/city/districts from external props at setup', async () => {
    // syncFromProps runs once at mount: a preselected destination renders
    // with the province/city/district selects already populated.
    const view = render(CityCascadePicker, {
      props: {
        province: '北京市',
        city: '北京',
        districts: ['东城区'],
      },
    })
    const selects = view.container.querySelectorAll('select')
    expect((selects[0] as HTMLSelectElement).value).toBe('北京市')
    expect((selects[1] as HTMLSelectElement).value).toBe('北京')
    expect(view.getByText(/目的地：北京市 北京 · 东城区/)).toBeTruthy()
  })
})
