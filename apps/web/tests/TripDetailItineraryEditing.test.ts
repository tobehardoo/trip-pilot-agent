import { cleanup, fireEvent, render, waitFor } from '@testing-library/vue'
import { afterEach, expect, test, vi } from 'vitest'

import TripDetail from '../src/components/TripDetail.vue'
import type { Itinerary, Trip, User } from '../src/lib/api'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

const user: User = {
  id: 'user-1',
  email: 'traveler@example.com',
  displayName: 'Traveler',
}

const trip: Trip = {
  id: 'trip-1',
  title: 'Guangzhou day trip',
  destination: 'Guangzhou',
  startDate: '2026-08-01',
  endDate: '2026-08-01',
  status: 'READY',
  version: 0,
  constraints: {
    budgetAmount: 1000,
    travelers: 2,
    travelerType: 'FRIENDS',
    pace: 'BALANCED',
    preferences: [],
    fixedSchedules: [],
  },
  createdAt: '2026-07-24T00:00:00Z',
  updatedAt: '2026-07-24T00:00:00Z',
}

const itinerary: Itinerary = {
  versionId: '11111111-1111-1111-1111-111111111111',
  versionNumber: 1,
  parentVersionId: null,
  title: 'Guangzhou route',
  estimatedTotalCost: 100,
  provider: 'AMAP',
  days: [{
    date: '2026-08-01',
    activities: [{
      id: '22222222-2222-2222-2222-222222222222',
      title: 'Museum',
      startTime: '2026-08-01T09:00:00+08:00',
      endTime: '2026-08-01T11:00:00+08:00',
      estimatedCost: 0,
      source: 'AMAP',
      providerPoiId: 'museum-poi',
      coordinates: null,
      address: 'Museum Road',
      locked: false,
    }],
    transitLegs: [],
  }],
  knowledge: {
    status: 'UNAVAILABLE',
    query: '',
    citations: [],
    freshness: { status: 'UNAVAILABLE', checkedAt: null, staleReason: null },
    message: null,
  },
  createdAt: '2026-07-24T00:00:00Z',
}

const itineraryWithMissingTransit: Itinerary = {
  ...itinerary,
  days: [{
    ...itinerary.days[0]!,
    activities: [
      ...itinerary.days[0]!.activities,
      {
        ...itinerary.days[0]!.activities[0]!,
        id: '33333333-3333-3333-3333-333333333333',
        title: 'Tower',
        startTime: '2026-08-01T13:00:00+08:00',
        endTime: '2026-08-01T15:00:00+08:00',
      },
    ],
    transitLegs: [],
  }],
}

const itineraryWithTransit: Itinerary = {
  ...itineraryWithMissingTransit,
  days: [{
    ...itineraryWithMissingTransit.days[0]!,
    transitLegs: [{
      id: '44444444-4444-4444-4444-444444444444',
      legOrder: 0,
      fromActivityId: itineraryWithMissingTransit.days[0]!.activities[0]!.id,
      toActivityId: itineraryWithMissingTransit.days[0]!.activities[1]!.id,
      mode: 'WALKING',
      locked: false,
      distanceMeters: 2400,
      durationSeconds: 1920,
      provider: 'AMAP',
      estimated: false,
      polyline: [],
    }],
  }],
}

const itineraryWithThreeActivities: Itinerary = {
  ...itinerary,
  days: [{
    ...itinerary.days[0]!,
    activities: [
      itinerary.days[0]!.activities[0]!,
      {
        ...itinerary.days[0]!.activities[0]!,
        id: '33333333-3333-3333-3333-333333333333',
        title: 'Gallery',
        startTime: '2026-08-01T13:00:00+08:00',
        endTime: '2026-08-01T15:00:00+08:00',
      },
      {
        ...itinerary.days[0]!.activities[0]!,
        id: '55555555-5555-5555-5555-555555555555',
        title: 'Tower',
        startTime: '2026-08-01T17:00:00+08:00',
        endTime: '2026-08-01T19:00:00+08:00',
      },
    ],
    transitLegs: [],
  }],
}

test.each([
  ['AMAP', '真实数据'],
  ['DEMO', '演示数据'],
  ['MIXED', '混合数据'],
] as const)('shows the %s itinerary provider as %s', (provider, label) => {
  const view = render(TripDetail, {
    props: {
      user,
      trip,
      busy: false,
      error: null,
      itinerary: { ...itinerary, provider },
      itineraryBusy: false,
      itineraryError: null,
      planningState: 'idle',
      planningError: null,
      startPlanning: async () => {},
      cancelPlanning: async () => {},
      updateConstraints: async () => {},
      reloadTrip: async () => true,
    },
  })

  expect(view.getByText(label)).toBeTruthy()
})

test('filters the map from a weather date without scrolling to the itinerary timeline', async () => {
  const scrollIntoView = vi.fn()
  Object.defineProperty(Element.prototype, 'scrollIntoView', {
    configurable: true,
    value: scrollIntoView,
  })
  const view = render(TripDetail, {
    props: {
      user, trip, busy: false, error: null, itinerary, itineraryBusy: false, itineraryError: null,
      planningState: 'idle', planningError: null, startPlanning: async () => {}, cancelPlanning: async () => {},
      updateConstraints: async () => {}, reloadTrip: async () => true,
      guideImports: [{
        id: 'weather-guide', sourceType: 'CITY_INTELLIGENCE', sourceUrl: 'https://restapi.amap.com/',
        finalUrl: 'https://restapi.amap.com/', sourceHost: 'amap.com', title: '广州城市实时情报', excerpt: '',
        contentHash: 'a'.repeat(64), fetchedAt: '2026-08-01T01:00:00Z', enabled: true,
        facts: [{
          id: 'weather-fact', category: 'WEATHER', statement: '2026-08-01 广州市天气预报：白天晴 34℃，夜间多云 28℃。',
          evidence: 'weather', confidence: 0.9, observedAt: '2026-08-01T01:00:00Z', expiresAt: '2026-08-02T01:00:00Z',
        }],
      }],
    },
  })

  await fireEvent.click(view.getByRole('button', { name: '选择 2026-08-01 天气' }))

  expect(scrollIntoView).not.toHaveBeenCalled()
})

test('does not render weather from a disabled latest city intelligence import', () => {
  const view = render(TripDetail, {
    props: {
      user, trip, busy: false, error: null, itinerary, itineraryBusy: false, itineraryError: null,
      planningState: 'idle', planningError: null, startPlanning: async () => {}, cancelPlanning: async () => {},
      updateConstraints: async () => {}, reloadTrip: async () => true,
      guideImports: [{
        id: 'disabled-weather-guide', sourceType: 'CITY_INTELLIGENCE', sourceUrl: 'https://example.com/weather',
        finalUrl: 'https://example.com/weather', sourceHost: 'weather', title: '已停用天气', excerpt: '',
        contentHash: 'b'.repeat(64), fetchedAt: '2026-08-02T01:00:00Z', enabled: false,
        facts: [{
          id: 'disabled-weather-fact', category: 'WEATHER', statement: '2026-08-01 广州市天气预报：白天暴雪 34℃。',
          evidence: 'weather', confidence: 0.9, observedAt: '2026-08-01T01:00:00Z', expiresAt: '2026-08-02T01:00:00Z',
        }],
      }],
    },
  })

  expect(view.queryByText('暴雪')).toBeNull()
})

test('previews an activity deletion before applying it', async () => {
  const previewEdit = vi.fn(async () => ({
    operation: 'DELETE_ACTIVITY' as const,
    canApply: true,
    impactedDates: ['2026-08-01'],
    impactedActivityIds: ['22222222-2222-2222-2222-222222222222'],
    warnings: ['Transit routes will be refreshed'],
    blockingReasons: [],
  }))
  const commitEdits = vi.fn(async () => {})
  const view = render(TripDetail, {
    props: {
      user,
      trip,
      busy: false,
      error: null,
      itinerary,
      itineraryBusy: false,
      itineraryError: null,
      planningState: 'idle',
      planningError: null,
      startPlanning: async () => {},
      cancelPlanning: async () => {},
      updateConstraints: async () => {},
      reloadTrip: async () => true,
      previewItineraryEdit: previewEdit,
      commitItineraryEdits: commitEdits,
    },
  })

  await fireEvent.click(view.getAllByRole('button', { name: '删除活动 Museum' }).at(-1)!)

  expect(previewEdit).toHaveBeenCalledWith({
    baseVersionId: itinerary.versionId,
    operation: 'DELETE_ACTIVITY',
    activityId: itinerary.days[0]!.activities[0]!.id,
  })
  expect(view.getByRole('dialog', { name: '确认行程修改' })).toBeTruthy()
  expect(view.getByText('2026-08-01')).toBeTruthy()
  expect(view.getByText('Transit routes will be refreshed')).toBeTruthy()

  await fireEvent.click(view.getByRole('button', { name: '应用修改' }))
  expect(commitEdits).not.toHaveBeenCalled()
  expect(view.getByTestId('save-itinerary-draft')).toBeTruthy()
  await fireEvent.click(view.getByTestId('save-itinerary-draft'))
  expect(commitEdits).toHaveBeenCalledWith(itinerary.versionId, [{
    baseVersionId: itinerary.versionId,
    operation: 'DELETE_ACTIVITY',
    activityId: itinerary.days[0]!.activities[0]!.id,
  }])
})

test('offers local replanning when a day has activities but no transit legs', async () => {
  const startReplanning = vi.fn(async () => {})
  const view = render(TripDetail, {
    props: {
      user,
      trip,
      busy: false,
      error: null,
      itinerary: itineraryWithMissingTransit,
      itineraryBusy: false,
      itineraryError: null,
      planningState: 'idle',
      planningError: null,
      startPlanning: async () => {},
      startReplanning,
      cancelPlanning: async () => {},
      updateConstraints: async () => {},
      reloadTrip: async () => true,
    },
  })

  await fireEvent.click(view.container.querySelector('.secondary-planning-button')!)

  expect(startReplanning).toHaveBeenCalledWith({
    baseVersionId: itinerary.versionId,
    dates: ['2026-08-01'],
  })
})

test('keeps a selected commute mode in the itinerary timeline', async () => {
  const view = render(TripDetail, {
    props: {
      user,
      trip,
      busy: false,
      error: null,
      itinerary: itineraryWithTransit,
      itineraryBusy: false,
      itineraryError: null,
      planningState: 'idle',
      planningError: null,
      startPlanning: async () => {},
      cancelPlanning: async () => {},
      updateConstraints: async () => {},
      reloadTrip: async () => true,
    },
  })

  await fireEvent.click(view.getByTestId('transit-leg-open-44444444-4444-4444-4444-444444444444'))
  await fireEvent.click(view.getByTestId('transit-option-DRIVING'))

  expect(view.getByTestId('transit-option-DRIVING').getAttribute('aria-pressed')).toBe('true')
})

test('stages the recommended transit as a reviewed default instead of retaining a 70-minute walk', async () => {
  const longWalk = {
    ...itineraryWithTransit,
    days: [{
      ...itineraryWithTransit.days[0]!,
      transitLegs: [{ ...itineraryWithTransit.days[0]!.transitLegs[0]!, distanceMeters: 5250, durationSeconds: 70 * 60 }],
    }],
  }
  const commitEdits = vi.fn(async () => {})
  const view = render(TripDetail, {
    props: {
      user, trip, busy: false, error: null, itinerary: longWalk, itineraryBusy: false, itineraryError: null,
      planningState: 'idle', planningError: null, startPlanning: async () => {}, cancelPlanning: async () => {},
      updateConstraints: async () => {}, reloadTrip: async () => true, commitItineraryEdits: commitEdits,
    },
  })
  await fireEvent.click(view.getByTestId('transit-leg-open-44444444-4444-4444-4444-444444444444'))
  await waitFor(() => {
    expect(view.getByTestId('transit-option-TRANSIT').getAttribute('aria-pressed')).toBe('true')
    expect(view.getByTestId('save-itinerary-draft')).toBeTruthy()
  })

  await fireEvent.click(view.getByTestId('save-itinerary-draft'))
  expect(commitEdits).toHaveBeenCalledWith(longWalk.versionId, [expect.objectContaining({
    operation: 'UPDATE_TRANSIT_LEG',
    transitLegId: '44444444-4444-4444-4444-444444444444',
    transitMode: 'TRANSIT',
  })])
})

test('moves an activity up by one position instead of moving it to the top', async () => {
  const previewEdit = vi.fn(async () => ({
    operation: 'MOVE_ACTIVITY' as const,
    canApply: true,
    impactedDates: ['2026-08-01'],
    impactedActivityIds: [],
    warnings: [],
    blockingReasons: [],
  }))
  const view = render(TripDetail, {
    props: {
      user,
      trip,
      busy: false,
      error: null,
      itinerary: itineraryWithThreeActivities,
      itineraryBusy: false,
      itineraryError: null,
      planningState: 'idle',
      planningError: null,
      startPlanning: async () => {},
      cancelPlanning: async () => {},
      updateConstraints: async () => {},
      reloadTrip: async () => true,
      previewItineraryEdit: previewEdit,
    },
  })

  const towerMoveButton = view.getAllByRole('button', { name: /Tower/ })
    .find((button) => button.getAttribute('aria-label')?.includes('\u524d\u79fb'))
  await fireEvent.click(towerMoveButton!)

  expect(previewEdit).toHaveBeenCalledWith(expect.objectContaining({
    activityId: '55555555-5555-5555-5555-555555555555',
    targetOrder: 1,
  }))
})

test('accumulates commute mode and lock changes until the user saves one draft version', async () => {
  const commitEdits = vi.fn(async () => {})
  const view = render(TripDetail, {
    props: {
      user,
      trip,
      busy: false,
      error: null,
      itinerary: itineraryWithTransit,
      itineraryBusy: false,
      itineraryError: null,
      planningState: 'idle',
      planningError: null,
      startPlanning: async () => {},
      cancelPlanning: async () => {},
      updateConstraints: async () => {},
      reloadTrip: async () => true,
      commitItineraryEdits: commitEdits,
    },
  })

  await fireEvent.click(view.getAllByTestId('transit-leg-open-44444444-4444-4444-4444-444444444444')[0]!)
  await fireEvent.click(view.getByTestId('transit-option-DRIVING'))
  await fireEvent.click(view.getByTestId('transit-lock-44444444-4444-4444-4444-444444444444'))

  expect(commitEdits).not.toHaveBeenCalled()
  await fireEvent.click(view.getByTestId('save-itinerary-draft'))
  expect(commitEdits).toHaveBeenCalledWith(itinerary.versionId, [expect.objectContaining({
    operation: 'UPDATE_TRANSIT_LEG',
    transitLegId: '44444444-4444-4444-4444-444444444444',
    transitMode: 'DRIVING',
    transitLocked: true,
  })])
})

test('keeps a draft visible when saving it fails', async () => {
  const commitEdits = vi.fn(async () => {
    throw new Error('save failed')
  })
  const view = render(TripDetail, {
    props: {
      user,
      trip,
      busy: false,
      error: null,
      itinerary: itineraryWithTransit,
      itineraryBusy: false,
      itineraryError: null,
      planningState: 'idle',
      planningError: null,
      startPlanning: async () => {},
      cancelPlanning: async () => {},
      updateConstraints: async () => {},
      reloadTrip: async () => true,
      commitItineraryEdits: commitEdits,
    },
  })

  await fireEvent.click(view.getByTestId('transit-leg-open-44444444-4444-4444-4444-444444444444'))
  await fireEvent.click(view.getByTestId('transit-option-DRIVING'))

  await fireEvent.click(view.getByTestId('save-itinerary-draft'))
  await waitFor(() => {
    expect(view.getByTestId('transit-option-DRIVING').getAttribute('aria-pressed')).toBe('true')
    expect(view.getByTestId('save-itinerary-draft')).toBeTruthy()
    expect(view.getByRole('alert')).toBeTruthy()
  })
})

test('shows a visible error when the edit preview fails', async () => {
  const previewEdit = vi.fn(async () => {
    throw new Error('preview service unavailable')
  })
  const view = render(TripDetail, {
    props: {
      user,
      trip,
      busy: false,
      error: null,
      itinerary,
      itineraryBusy: false,
      itineraryError: null,
      planningState: 'idle',
      planningError: null,
      startPlanning: async () => {},
      cancelPlanning: async () => {},
      updateConstraints: async () => {},
      reloadTrip: async () => true,
      previewItineraryEdit: previewEdit,
    },
  })

  await fireEvent.click(view.getAllByRole('button', { name: '删除活动 Museum' }).at(-1)!)

  expect(view.getByRole('dialog', { name: '确认行程修改' })).toBeTruthy()
  expect(view.getByRole('alert').textContent).toContain('无法预览本次修改')
})

test('explains stale conflicted facts with evidence and a safe source link', async () => {
  const itineraryWithEvidence: Itinerary = {
    ...itinerary,
    factImpacts: [{
      factId: 'fact-weather-1',
      category: 'WEATHER',
      date: '2026-08-01',
      effect: 'OUTDOOR_POI_DOWNRANKED',
      targetPoiId: null,
      targetName: '广州塔',
      reason: '对应日期预计降雨，露天候选降低优先级',
      sourceName: '高德天气',
      sourceType: 'WEATHER_PROVIDER',
      sourceUrl: 'https://restapi.amap.com/',
      reliabilityLevel: 'PROVIDER',
      checkedAt: '2026-07-26T08:30:00Z',
      evidence: '8 月 1 日预计有雨',
      stale: true,
      conflicted: true,
      refreshFailed: true,
    }],
  }
  const view = render(TripDetail, {
    props: {
      user,
      trip,
      busy: false,
      error: null,
      itinerary: itineraryWithEvidence,
      itineraryBusy: false,
      itineraryError: null,
      planningState: 'idle',
      planningError: null,
      startPlanning: async () => {},
      cancelPlanning: async () => {},
      updateConstraints: async () => {},
      reloadTrip: async () => true,
    },
  })

  expect(view.getByText('1 条天气影响')).toBeTruthy()
  expect(view.getByText('1 条有冲突')).toBeTruthy()
  expect(view.getByText('1 条刷新失败降级')).toBeTruthy()
  await fireEvent.click(view.getByText('查看来源与核验信息'))
  expect(view.getByText('原句证据：8 月 1 日预计有雨')).toBeTruthy()
  expect(view.getByRole('link', { name: '查看安全来源' }).getAttribute('href'))
    .toBe('https://restapi.amap.com/')
})
