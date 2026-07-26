import { cleanup, fireEvent, render, waitFor } from '@testing-library/vue'
import { afterEach, expect, test, vi } from 'vitest'

import TripDetail from '../src/components/TripDetail.vue'
import type { Itinerary, Trip, User } from '../src/lib/api'

afterEach(() => cleanup())

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

test('previews an activity deletion before applying it', async () => {
  const previewEdit = vi.fn(async () => ({
    operation: 'DELETE_ACTIVITY' as const,
    canApply: true,
    impactedDates: ['2026-08-01'],
    impactedActivityIds: ['22222222-2222-2222-2222-222222222222'],
    warnings: ['Transit routes will be refreshed'],
    blockingReasons: [],
  }))
  const applyEdit = vi.fn(async () => {})
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
      applyItineraryEdit: applyEdit,
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
  expect(applyEdit).toHaveBeenCalledWith({
    baseVersionId: itinerary.versionId,
    operation: 'DELETE_ACTIVITY',
    activityId: itinerary.days[0]!.activities[0]!.id,
  })
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

test('persists commute mode and lock changes through itinerary edits', async () => {
  const applyEdit = vi.fn(async () => {})
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
      applyItineraryEdit: applyEdit,
    },
  })

  await fireEvent.click(view.getAllByTestId('transit-leg-open-44444444-4444-4444-4444-444444444444')[0]!)
  await fireEvent.click(view.getByTestId('transit-option-DRIVING'))
  await fireEvent.click(view.getByTestId('transit-lock-44444444-4444-4444-4444-444444444444'))

  expect(applyEdit).toHaveBeenNthCalledWith(1, expect.objectContaining({
    operation: 'UPDATE_TRANSIT_LEG',
    transitLegId: '44444444-4444-4444-4444-444444444444',
    transitMode: 'DRIVING',
  }))
  expect(applyEdit).toHaveBeenNthCalledWith(2, expect.objectContaining({
    operation: 'UPDATE_TRANSIT_LEG',
    transitLegId: '44444444-4444-4444-4444-444444444444',
    transitLocked: true,
  }))
})

test('reverts a commute mode when persistence fails', async () => {
  const applyEdit = vi.fn(async () => {
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
      applyItineraryEdit: applyEdit,
    },
  })

  await fireEvent.click(view.getByTestId('transit-leg-open-44444444-4444-4444-4444-444444444444'))
  await fireEvent.click(view.getByTestId('transit-option-DRIVING'))

  await waitFor(() => {
    expect(view.getByTestId('transit-option-DRIVING').getAttribute('aria-pressed')).toBe('false')
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
