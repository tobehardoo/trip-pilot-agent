import { cleanup, fireEvent, render, screen } from '@testing-library/vue'
import { afterEach, expect, test, vi } from 'vitest'

import PlaceSearchField from '../src/components/PlaceSearchField.vue'
import type { PlaceSuggestItem, StructuredPoi } from '../src/lib/api'

afterEach(cleanup)

const poiItem: PlaceSuggestItem = {
  itemType: 'POI',
  provider: 'AMAP',
  providerPoiId: 'BV10019725',
  name: '广州南站',
  category: '高铁站',
  categoryCode: '150302',
  provinceCode: '440000',
  cityCode: '440100',
  districtCode: '440113',
  districtName: '番禺区',
  fullAddress: '广州市番禺区南站北路',
  longitude: 113.269,
  latitude: 22.988,
}

const suggestionItem: PlaceSuggestItem = {
  itemType: 'SUGGESTION',
  name: '广州南站',
}

const regionItem: PlaceSuggestItem = {
  itemType: 'REGION',
  name: '番禺区',
  category: '区县',
  cityCode: '440100',
}

/** 等待防抖 + 请求完成并渲染下拉。 */
async function waitForResults() {
  await new Promise((resolve) => setTimeout(resolve, 350))
  await screen.findByTestId('poi-results')
}

test('selecting a POI locks it with category and codes as a trusted anchor', async () => {
  const suggestPlaces = vi.fn(async () => ({ items: [poiItem] }))
  const view = render(PlaceSearchField, {
    props: { modelValue: null, city: '广州', cityCode: '440100', scene: 'ARRIVAL', suggestPlaces },
  })

  await fireEvent.update(screen.getByTestId('poi-search-input'), '广州南站')
  await waitForResults()
  expect(suggestPlaces).toHaveBeenCalledWith('广州南站', '440100', 'ARRIVAL', expect.anything())

  await fireEvent.click(screen.getByRole('button', { name: /广州南站/ }))

  const selected = view.emitted('update:modelValue')?.at(-1)?.[0] as StructuredPoi
  expect(selected).toMatchObject({
    name: '广州南站',
    provider: 'AMAP',
    providerPoiId: 'BV10019725',
    category: '高铁站',
    categoryCode: '150302',
    cityCode: '440100',
    districtCode: '440113',
    city: '广州',
  })
  // 父组件回写后锁定卡片显示分类与区县。
  await view.rerender({ modelValue: selected })
  await screen.findByText('高铁站 · 番禺区')
})

test('a SUGGESTION row refills the keyword and re-searches instead of becoming an anchor', async () => {
  const suggestPlaces = vi.fn(async () => ({ items: [suggestionItem, poiItem] }))
  const view = render(PlaceSearchField, {
    props: { modelValue: null, city: '广州', cityCode: '440100', scene: 'ARRIVAL', suggestPlaces },
  })

  await fireEvent.update(screen.getByTestId('poi-search-input'), '广州南')
  await waitForResults()

  await fireEvent.click(screen.getAllByTestId('poi-suggestion-row')[0])

  expect((screen.getByTestId('poi-search-input') as HTMLInputElement).value).toBe('广州南站')
  expect(suggestPlaces).toHaveBeenCalledTimes(2)
  expect(view.emitted('update:modelValue')).toBeUndefined()
})

test('a REGION row refills the keyword and re-searches instead of becoming an anchor', async () => {
  const suggestPlaces = vi.fn(async () => ({ items: [regionItem, poiItem] }))
  const view = render(PlaceSearchField, {
    props: { modelValue: null, city: '广州', cityCode: '440100', scene: 'HOTEL', suggestPlaces },
  })

  await fireEvent.update(screen.getByTestId('poi-search-input'), '番禺')
  await waitForResults()

  await fireEvent.click(screen.getAllByTestId('poi-suggestion-row')[0])

  expect((screen.getByTestId('poi-search-input') as HTMLInputElement).value).toBe('番禺区')
  expect(suggestPlaces).toHaveBeenCalledTimes(2)
  expect(view.emitted('update:modelValue')).toBeUndefined()
})

test('does not search a keyword shorter than two characters', async () => {
  const suggestPlaces = vi.fn(async () => ({ items: [poiItem] }))
  render(PlaceSearchField, {
    props: { modelValue: null, city: '广州', cityCode: '440100', scene: 'ARRIVAL', suggestPlaces },
  })

  await fireEvent.update(screen.getByTestId('poi-search-input'), '广')
  await new Promise((resolve) => setTimeout(resolve, 350))

  expect(suggestPlaces).not.toHaveBeenCalled()
  await screen.findByText('请输入至少 2 个字符后搜索')
})

test('a provider failure degrades to a retry message, never a trusted free-text place', async () => {
  const suggestPlaces = vi.fn(async () => {
    throw new Error('provider down')
  })
  render(PlaceSearchField, {
    props: { modelValue: null, city: '广州', cityCode: '440100', scene: 'ARRIVAL', suggestPlaces },
  })

  await fireEvent.update(screen.getByTestId('poi-search-input'), '广州南站')
  await new Promise((resolve) => setTimeout(resolve, 350))

  await screen.findByText(/地点搜索暂时不可用/)
})

test('重新选择 unlocks the field and clears the trusted anchor', async () => {
  const suggestPlaces = vi.fn(async () => ({ items: [poiItem] }))
  const view = render(PlaceSearchField, {
    props: { modelValue: null, city: '广州', cityCode: '440100', scene: 'ARRIVAL', suggestPlaces },
  })

  await fireEvent.update(screen.getByTestId('poi-search-input'), '广州南站')
  await waitForResults()
  await fireEvent.click(screen.getByRole('button', { name: /广州南站/ }))
  const selected = view.emitted('update:modelValue')?.at(-1)?.[0] as StructuredPoi
  await view.rerender({ modelValue: selected })
  await screen.findByText('重新选择')

  await fireEvent.click(screen.getByRole('button', { name: /重新选择/ }))
  await view.rerender({ modelValue: null })

  expect(view.emitted('update:modelValue')?.at(-1)).toEqual([null])
  expect((screen.getByTestId('poi-search-input') as HTMLInputElement).disabled).toBe(false)
})

test('switching the destination city discards stale results without emitting a cross-city anchor', async () => {
  const suggestPlaces = vi.fn(async () => ({ items: [poiItem] }))
  const view = render(PlaceSearchField, {
    props: { modelValue: null, city: '广州', cityCode: '440100', scene: 'ARRIVAL', suggestPlaces },
  })

  await fireEvent.update(screen.getByTestId('poi-search-input'), '广州南站')
  await waitForResults()
  await view.rerender({ city: '深圳', cityCode: '440300' })

  expect(screen.queryByTestId('poi-results')).toBeNull()
  expect(view.emitted('update:modelValue')).toBeUndefined()
})
