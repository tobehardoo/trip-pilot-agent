import { cleanup, render } from '@testing-library/vue'
import { afterEach, expect, test } from 'vitest'

import TripDetail from '../src/components/TripDetail.vue'
import type { Itinerary, Trip, User } from '../src/lib/api'

afterEach(() => cleanup())

const user: User = {
  id: 'user-1',
  email: 'traveler@example.com',
  displayName: 'Traveler',
}

function baseTrip(overrides: Partial<Trip> = {}): Trip {
  return {
    id: 'trip-1',
    title: '广州周末',
    destination: '广州',
    startDate: '2026-09-01',
    endDate: '2026-09-03',
    status: 'READY',
    version: 0,
    constraints: {
      budgetAmount: 3000,
      travelers: 2,
      travelerType: 'COUPLE',
      pace: 'BALANCED',
      preferences: ['美食'],
      fixedSchedules: [],
      mealWindows: [
        { mealType: 'BREAKFAST', startTime: '08:00', endTime: '09:00', source: 'SYSTEM_DEFAULT' },
        { mealType: 'LUNCH', startTime: '12:00', endTime: '13:00', source: 'USER_SET' },
        { mealType: 'DINNER', startTime: '18:00', endTime: '19:00', source: 'SYSTEM_DEFAULT' },
      ],
    },
    createdAt: '2026-08-01T00:00:00Z',
    updatedAt: '2026-08-01T00:00:00Z',
    ...overrides,
  }
}

function baseItinerary(overrides: Partial<Itinerary> = {}): Itinerary {
  return {
    versionId: '11111111-1111-1111-1111-111111111111',
    versionNumber: 1,
    parentVersionId: null,
    title: '广州行程',
    estimatedTotalCost: 100,
    provider: 'DEMO',
    days: [],
    knowledge: {
      status: 'UNAVAILABLE',
      query: '',
      citations: [],
      freshness: { status: 'UNAVAILABLE', checkedAt: null, staleReason: null },
      message: null,
    },
    createdAt: '2026-08-01T00:00:00Z',
    ...overrides,
  }
}

function renderDetail(trip: Trip, itinerary: Itinerary) {
  return render(TripDetail, {
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
    },
  })
}

test('shows the stale warning when the itinerary is based on older constraints', () => {
  const view = renderDetail(baseTrip(), baseItinerary({ stale: true }))
  expect(view.getByText('约束已更新，当前行程仍基于上一版约束。')).toBeTruthy()
})

test('does not show the stale warning when the itinerary matches the current constraints', () => {
  const view = renderDetail(baseTrip(), baseItinerary({ stale: false }))
  expect(view.queryByText('约束已更新，当前行程仍基于上一版约束。')).toBeNull()
})

test('marks legacy free-text accommodation as awaiting re-confirmation', () => {
  const trip = baseTrip({
    constraints: {
      ...baseTrip().constraints,
      accommodation: { placeName: '老牌酒店' },
    },
  })
  const view = renderDetail(trip, baseItinerary())
  expect(view.getByText('老牌酒店')).toBeTruthy()
  expect(view.getByText('待重新确认')).toBeTruthy()
})

test('shows meal window sources and values', () => {
  const view = renderDetail(baseTrip(), baseItinerary())
  expect(view.getByText('08:00–09:00')).toBeTruthy()
  expect(view.getAllByText(/系统默认/).length).toBeGreaterThanOrEqual(2)
  expect(view.getAllByText(/用户设置/).length).toBeGreaterThanOrEqual(1)
})

test('hints that transit uses an estimated default start without trusted anchors', () => {
  const view = renderDetail(baseTrip(), baseItinerary())
  expect(view.getByText('首末段交通 按默认起点估算')).toBeTruthy()
})
