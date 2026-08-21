import { cleanup, fireEvent, render } from '@testing-library/vue'
import { afterEach, expect, test } from 'vitest'

import TripDetail from '../src/components/TripDetail.vue'
import type { Itinerary, Trip, User } from '../src/lib/api'

afterEach(() => cleanup())

const user: User = { id: 'user-1', email: 'traveler@example.com', displayName: 'Traveler' }
const trip: Trip = {
  id: 'trip-1',
  title: 'Guangzhou trip',
  destination: 'Guangzhou',
  startDate: '2026-08-01',
  endDate: '2026-08-02',
  status: 'READY',
  version: 1,
  constraints: {
    budgetAmount: 1000,
    travelers: 1,
    travelerType: 'SOLO',
    pace: 'BALANCED',
    preferences: [],
    fixedSchedules: [],
  },
  createdAt: '2026-08-01T00:00:00Z',
  updatedAt: '2026-08-01T00:00:00Z',
}

function makeItinerary(dates: string[], factImpacts: Itinerary['factImpacts'] = []): Itinerary {
  return {
    versionId: '11111111-1111-4111-8111-111111111111',
    versionNumber: 1,
    parentVersionId: null,
    title: 'Guangzhou route',
    estimatedTotalCost: 100,
    provider: 'AMAP',
    days: dates.map((date, i) => ({
      date,
      activities: [{
        id: `22222222-2222-4222-8222-22222222222${i}`,
        title: `Activity ${i}`,
        startTime: `${date}T09:00:00+08:00`,
        endTime: `${date}T11:00:00+08:00`,
        estimatedCost: 0,
        source: 'AMAP',
        providerPoiId: 'poi',
        coordinates: null,
        address: 'Road',
        locked: false,
      }],
      transitLegs: [],
    })),
    knowledge: {
      status: 'UNAVAILABLE',
      query: '',
      citations: [],
      freshness: { status: 'UNAVAILABLE', checkedAt: null, staleReason: null },
      message: null,
    },
    factImpacts,
    createdAt: '2026-08-01T00:00:00Z',
  }
}

function baseProps(overrides: Record<string, unknown> = {}) {
  return {
    user,
    trip,
    busy: false,
    error: null,
    itinerary,
    itineraryBusy: false,
    itineraryError: null,
    planningState: 'succeeded',
    planningError: null,
    startPlanning: async () => {},
    cancelPlanning: async () => {},
    updateConstraints: async () => {},
    reloadTrip: async () => true,
    evaluation: undefined,
    ...overrides,
  }
}

const itinerary = makeItinerary(['2026-08-01', '2026-08-02'])

test('renders in-page anchor navigation when a trip is loaded', () => {
  const view = render(TripDetail, { props: baseProps() })

  expect(view.getByRole('navigation', { name: '页面导航' })).toBeTruthy()
  const links = ['概览', '行程', '地图', '质量', '版本与导出']
  for (const label of links) {
    expect(view.getByRole('link', { name: label })).toBeTruthy()
  }
})

test('anchor targets exist for overview / itinerary / map / evidence / versions', () => {
  const view = render(TripDetail, { props: baseProps() })

  for (const id of ['trip-overview', 'trip-itinerary', 'trip-map', 'trip-evidence', 'trip-versions']) {
    expect(view.container.querySelector(`#${id}`)).not.toBeNull()
  }
})

test('shows day navigation for multi-day itineraries', () => {
  const view = render(TripDetail, { props: baseProps() })

  expect(view.getByRole('navigation', { name: '日期导航' })).toBeTruthy()
  expect(view.getByRole('link', { name: /Day 1/ })).toBeTruthy()
  expect(view.getByRole('link', { name: /Day 2/ })).toBeTruthy()
})

test('hides day navigation for single-day itineraries', () => {
  const singleDay = makeItinerary(['2026-08-01'])
  const view = render(TripDetail, { props: baseProps({ itinerary: singleDay }) })

  expect(view.queryByRole('navigation', { name: '日期导航' })).toBeNull()
})

test('data status shows 真实数据 when all facts are healthy', () => {
  const healthy = makeItinerary(['2026-08-01'], [{
    factId: 'f1', category: 'OPENING_HOURS', effect: 'AFFECTS_SCHEDULE',
    applicableDate: '2026-08-01', reason: 'open', reliabilityLevel: 'OFFICIAL',
    sourceName: 'AMap', sourceType: 'OFFICIAL', checkedAt: '2026-08-01T00:00:00Z',
    evidence: 'e', stale: false, conflicted: false, refreshFailed: false,
  }])
  const view = render(TripDetail, { props: baseProps({ itinerary: healthy }) })

  expect(view.getByText('真实数据 ✓')).toBeTruthy()
  expect(view.getByText('核心路线、地点和规划数据已获取。')).toBeTruthy()
})

test('data status flags degraded state with user-facing issues, details stay in diagnostics', async () => {
  const degraded = makeItinerary(['2026-08-01'], [
    { factId: 'f1', category: 'OPENING_HOURS', effect: 'AFFECTS_SCHEDULE',
      applicableDate: '2026-08-01', reason: 'r', reliabilityLevel: 'OFFICIAL',
      sourceName: 'AMap', sourceType: 'OFFICIAL', checkedAt: '2026-08-01T00:00:00Z',
      evidence: 'e', stale: true, conflicted: false, refreshFailed: false },
    { factId: 'f2', category: 'WEATHER', effect: 'AFFECTS_SCHEDULE',
      applicableDate: '2026-08-01', reason: 'r', reliabilityLevel: 'COMMUNITY',
      sourceName: 'QWeather', sourceType: 'COMMUNITY', checkedAt: '2026-08-01T00:00:00Z',
      evidence: 'e', stale: false, conflicted: false, refreshFailed: true },
  ])
  const view = render(TripDetail, { props: baseProps({ itinerary: degraded }) })

  // 用户层：主页面摘要 + 可行动建议（营业时间出发前确认 / 天气未同步）。
  expect(view.getByText('数据基本完整，2 项待确认')).toBeTruthy()
  expect(view.getByText('1 个地点营业时间建议出发前确认')).toBeTruthy()
  expect(view.getByText('部分天气辅助数据未同步')).toBeTruthy()

  // 系统级 flag（已过期 / 刷新失败降级）仍可通过「数据说明」高级诊断核验。
  await fireEvent.click(view.getByTestId('open-data-explainer'))
  await fireEvent.click(view.getByTestId('toggle-diagnostics'))
  expect(view.getByText('已过期')).toBeTruthy()
  expect(view.getByText('刷新失败降级')).toBeTruthy()
})
