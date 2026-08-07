import { cleanup, fireEvent, render, screen } from '@testing-library/vue'
import { afterEach, expect, test } from 'vitest'

import DestinationRegionSelector from '../src/components/DestinationRegionSelector.vue'

afterEach(cleanup)

test('selecting a province then a city emits a structured region', async () => {
  const view = render(DestinationRegionSelector, {
    props: { modelValue: null },
  })

  await fireEvent.update(screen.getByLabelText('省份'), '广东省')
  await fireEvent.update(screen.getByLabelText('城市'), '广州')

  expect(view.emitted('update:modelValue')?.at(-1)).toEqual([{
    provinceCode: '440000',
    provinceName: '广东省',
    cityCode: '440100',
    cityName: '广州',
    districts: [],
  }])
})

test('toggling a district adds it to the region and changing the city clears districts', async () => {
  const view = render(DestinationRegionSelector, {
    props: { modelValue: null },
  })

  await fireEvent.update(screen.getByLabelText('省份'), '广东省')
  await fireEvent.update(screen.getByLabelText('城市'), '广州')
  await fireEvent.click(screen.getByText('天河区'))

  expect(view.emitted('update:modelValue')?.at(-1)).toEqual([{
    provinceCode: '440000',
    provinceName: '广东省',
    cityCode: '440100',
    cityName: '广州',
    districts: [{ districtCode: '440106', districtName: '天河区' }],
  }])

  await fireEvent.update(screen.getByLabelText('城市'), '深圳')
  expect(view.emitted('update:modelValue')?.at(-1)).toEqual([{
    provinceCode: '440000',
    provinceName: '广东省',
    cityCode: '440300',
    cityName: '深圳',
    districts: [],
  }])
})

test('a city without catalogued codes does not emit a forged region', async () => {
  const view = render(DestinationRegionSelector, {
    props: { modelValue: null },
  })

  await fireEvent.update(screen.getByLabelText('省份'), '湖南省')
  await fireEvent.update(screen.getByLabelText('城市'), '长沙')

  expect(view.emitted('update:modelValue')?.at(-1)).toEqual([null])
})

test('backfills an existing region', () => {
  render(DestinationRegionSelector, {
    props: {
      modelValue: {
        provinceCode: '110000',
        provinceName: '北京市',
        cityCode: '110000',
        cityName: '北京',
        districts: [{ districtCode: '110105', districtName: '朝阳区' }],
      },
    },
  })

  expect((screen.getByLabelText('省份') as HTMLSelectElement).value).toBe('北京市')
  expect((screen.getByLabelText('城市') as HTMLSelectElement).value).toBe('北京')
  expect((screen.getByRole('checkbox', { name: '朝阳区' }) as HTMLInputElement).checked).toBe(true)
})
