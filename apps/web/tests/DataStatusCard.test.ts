import { cleanup, fireEvent, render } from '@testing-library/vue'
import { afterEach, expect, test } from 'vitest'

import DataStatusCard from '../src/components/DataStatusCard.vue'
import type { ItineraryFactImpact } from '../src/lib/api'

afterEach(() => cleanup())

function fact(partial: Partial<ItineraryFactImpact>): ItineraryFactImpact {
  return {
    factId: 'f1', category: 'OPENING_HOURS', date: null, effect: 'AFFECTS_SCHEDULE',
    targetPoiId: null, targetName: null, reason: 'r', sourceName: 'AMap',
    sourceType: 'OFFICIAL', sourceUrl: null, reliabilityLevel: 'OFFICIAL',
    checkedAt: '2026-08-01T00:00:00Z', evidence: 'e',
    stale: false, conflicted: false, refreshFailed: false,
    ...partial,
  }
}

test('shows healthy summary when every fact is clean', () => {
  const view = render(DataStatusCard, {
    props: { facts: [fact({ factId: 'a' }), fact({ factId: 'b', sourceName: 'QWeather', category: 'WEATHER' })] },
  })
  expect(view.getByText('真实数据 ✓')).toBeTruthy()
  expect(view.getByText('核心路线、地点和规划数据已获取。')).toBeTruthy()
})

test('shows待确认 count for a single degraded fact', () => {
  const view = render(DataStatusCard, {
    props: { facts: [fact({ factId: 'a', stale: true })] },
  })
  expect(view.getByText('数据基本完整，1 项待确认')).toBeTruthy()
  expect(view.getByText('1 个地点营业时间建议出发前确认')).toBeTruthy()
})

test('summaries count matches the underlying fact count exactly', () => {
  const facts = [
    fact({ factId: 'a', stale: true }),
    fact({ factId: 'b', conflicted: true }),
    fact({ factId: 'c', refreshFailed: true }),
    fact({ factId: 'd', category: 'WEATHER', sourceName: 'QWeather', refreshFailed: true }),
  ]
  const view = render(DataStatusCard, { props: { facts } })
  expect(view.getByText('数据基本完整，4 项待确认')).toBeTruthy()
})

test('10+ identical provider facts collapse into a single user issue', () => {
  const many = Array.from({ length: 12 }, (_, i) =>
    fact({ factId: `w${i}`, category: 'WEATHER', sourceName: 'QWeather', stale: true }))
  const view = render(DataStatusCard, { props: { facts: many } })

  // 用户层只看到一条天气提醒，而不是 12 张卡片。
  expect(view.getByText('部分天气辅助数据未同步')).toBeTruthy()
  expect(view.getAllByText('部分天气辅助数据未同步')).toHaveLength(1)
})

test('multiple providers aggregate into separate diagnostics groups', async () => {
  const facts = [
    fact({ factId: 'a', category: 'WEATHER', sourceName: 'QWeather', stale: true }),
    fact({ factId: 'b', category: 'WEATHER', sourceName: 'AMap', stale: true }),
    fact({ factId: 'c', category: 'OPENING_HOURS', sourceName: 'AMap', conflicted: true }),
  ]
  const view = render(DataStatusCard, { props: { facts } })

  await fireEvent.click(view.getByTestId('open-data-explainer'))
  await fireEvent.click(view.getByTestId('toggle-diagnostics'))
  expect(view.getByText('QWeather')).toBeTruthy()
  // AMap 同时出现在天气与营业时间两组（按 category+source 聚合）。
  expect(view.getAllByText('AMap')).toHaveLength(2)
})

test('unknown categories surface as待确认 with an action and stay visible in diagnostics', async () => {
  const view = render(DataStatusCard, {
    props: { facts: [fact({ factId: 'a', category: 'POI_DETAILS', sourceName: 'AMap', refreshFailed: true })] },
  })
  expect(view.getByText(/POI_DETAILS/)).toBeTruthy()
  expect(view.getByText('建议出发前自行核实相关信息。')).toBeTruthy()

  await fireEvent.click(view.getByTestId('open-data-explainer'))
  await fireEvent.click(view.getByTestId('toggle-diagnostics'))
  expect(view.getByText('刷新失败降级')).toBeTruthy()
})

test('advanced diagnostics are collapsed by default and reveal details on demand', async () => {
  const view = render(DataStatusCard, {
    props: { facts: [fact({ factId: 'a', stale: true })] },
  })

  // 默认：主页面不显示诊断内容。
  expect(view.queryByTestId('diagnostics-content')).toBeNull()

  await fireEvent.click(view.getByTestId('open-data-explainer'))
  // Drawer 内高级诊断默认折叠。
  expect(view.queryByTestId('diagnostics-content')).toBeNull()
  await fireEvent.click(view.getByTestId('toggle-diagnostics'))
  expect(view.getByTestId('diagnostics-content')).toBeTruthy()
})

test('severe issues are not downgraded in the summary', () => {
  const view = render(DataStatusCard, {
    props: { facts: [fact({ factId: 'a', category: 'ROUTE', stale: true, refreshFailed: true })] },
  })
  expect(view.getByText('数据基本完整，1 项待确认')).toBeTruthy()
  expect(view.getByText(/部分路线信息使用估算/)).toBeTruthy()
})
