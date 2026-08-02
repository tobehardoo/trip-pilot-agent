import { cleanup, render } from '@testing-library/vue'
import { afterEach, expect, test } from 'vitest'

import TripDetail from '../src/components/TripDetail.vue'
import type { Itinerary, PlanEvaluation, Trip, User } from '../src/lib/api'

afterEach(() => cleanup())

const user: User = { id: 'user-1', email: 'traveler@example.com', displayName: 'Traveler' }
const trip: Trip = {
  id: 'trip-1',
  title: 'Guangzhou trip',
  destination: 'Guangzhou',
  startDate: '2026-08-01',
  endDate: '2026-08-01',
  status: 'READY',
  version: 0,
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
const itinerary: Itinerary = {
  versionId: '11111111-1111-4111-8111-111111111111',
  versionNumber: 1,
  parentVersionId: null,
  title: 'Guangzhou route',
  estimatedTotalCost: 100,
  provider: 'AMAP',
  days: [{
    date: '2026-08-01',
    activities: [{
      id: '22222222-2222-4222-8222-222222222222',
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
  createdAt: '2026-08-01T00:00:00Z',
}
const evaluation: PlanEvaluation = {
  schemaVersion: 1,
  evaluatorVersion: 'rule-v1',
  feasible: true,
  overallScore: 97,
  dimensions: {
    constraintSatisfaction: 100,
    timeFeasibility: 100,
    budgetFit: 100,
    routeEfficiency: 100,
    interestMatch: 80,
  },
  warnings: [],
  decisions: [],
  summary: '行程整体质量 97/100。',
  evaluatedAt: '2026-08-02T00:00:00Z',
}

function props(planningState: 'succeeded' | 'failed', value?: PlanEvaluation | null) {
  return {
    user,
    trip,
    busy: false,
    error: null,
    itinerary,
    itineraryBusy: false,
    itineraryError: null,
    planningState,
    planningError: planningState === 'failed' ? 'Planning failed' : null,
    startPlanning: async () => {},
    cancelPlanning: async () => {},
    updateConstraints: async () => {},
    reloadTrip: async () => true,
    evaluation: value,
  }
}

test('shows evaluation for a succeeded task', () => {
  const view = render(TripDetail, { props: props('succeeded', evaluation) })

  expect(view.getByText('行程质量')).toBeTruthy()
  expect(view.getByText('97/100')).toBeTruthy()
  expect(view.queryByText('该版本生成时尚未启用质量评估')).toBeNull()
})

test('shows legacy compatibility copy for a succeeded task without evaluation', () => {
  const view = render(TripDetail, { props: props('succeeded', null) })

  expect(view.getByText('该版本生成时尚未启用质量评估')).toBeTruthy()
})

test('does not show evaluation or legacy copy for a failed task', () => {
  const view = render(TripDetail, { props: props('failed', evaluation) })

  expect(view.queryByText('行程质量')).toBeNull()
  expect(view.queryByText('该版本生成时尚未启用质量评估')).toBeNull()
})
