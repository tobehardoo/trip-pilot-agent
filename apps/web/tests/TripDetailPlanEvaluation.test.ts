import { cleanup, fireEvent, render } from '@testing-library/vue'
import { afterEach, expect, test, vi } from 'vitest'

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

function props(
  planningState: 'idle' | 'queued' | 'succeeded' | 'waiting_user' | 'failed' | 'cancelled',
  value?: PlanEvaluation | null,
) {
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

const reviewReport = {
  schemaVersion: 1,
  reportId: '33333333-3333-4333-8333-333333333333',
  validatorVersion: 'hard-validator-v4',
  itineraryFingerprint: 'a'.repeat(64),
  status: 'UNVERIFIED',
  validatedAt: '2026-08-01T00:00:00Z',
  requiredRuleIds: ['OPENING_HOURS'],
  missingRequiredRuleIds: [],
  summary: {
    totalCount: 1,
    passCount: 0,
    failCount: 0,
    unknownCount: 1,
    notApplicableCount: 0,
    missingRequiredCount: 0,
  },
  ruleResults: [{
    ruleId: 'OPENING_HOURS',
    ruleVersion: 'hard-rule-v1',
    outcome: 'UNKNOWN',
    reasonCode: 'OPENING_HOURS_UNVERIFIED',
    message: 'opening hours are not verified',
    affectedDates: ['2026-08-01'],
    affectedEntityRefs: ['activity:22222222-2222-4222-8222-222222222222'],
    evidenceRefs: [],
    repairable: false,
  }],
  repairAttempts: [],
}

const reviewCandidate = {
  title: '广州预览方案',
  days: [{
    date: '2026-08-01',
    dayType: null,
    activities: [{
      activityId: '22222222-2222-4222-8222-222222222222',
      title: '博物馆',
      startTime: '2026-08-01T09:00:00+08:00',
      endTime: '2026-08-01T11:00:00+08:00',
      estimatedCost: 0,
      source: 'AMAP',
      providerPoiId: 'museum-poi',
      coordinates: null,
      address: '博物馆路',
      typeCode: null,
      typeName: null,
      kind: null,
      timeFixed: null,
    }],
    transitLegs: [],
  }],
  estimatedTotalCost: 100,
}

test('shows the current version evaluation after reopening an idle workspace', () => {
  const view = render(TripDetail, { props: props('idle', evaluation) })

  expect(view.getByText('行程质量')).toBeTruthy()
  expect(view.getByText('97/100')).toBeTruthy()
  expect(view.queryByText('该版本生成时尚未启用质量评估')).toBeNull()
})

test('shows legacy compatibility copy for a linked legacy version after reopening', () => {
  const view = render(TripDetail, { props: props('idle', null) })

  expect(view.getByText('该版本生成时尚未启用质量评估')).toBeTruthy()
})

test('does not show evaluation or legacy copy when the current version has no linked task', () => {
  const view = render(TripDetail, { props: props('failed', undefined) })

  expect(view.queryByText('行程质量')).toBeNull()
  expect(view.queryByText('该版本生成时尚未启用质量评估')).toBeNull()
})

test('keeps the current version evaluation visible when a newer planning attempt fails', () => {
  const view = render(TripDetail, { props: props('failed', evaluation) })

  expect(view.getByText('97/100')).toBeTruthy()
  expect(view.getByText('Planning failed')).toBeTruthy()
})

test('verification action scrolls to the guide intelligence evidence tools', async () => {
  const scrollSpy = vi.fn()
  Element.prototype.scrollIntoView = scrollSpy
  const value = props('waiting_user')
  const view = render(TripDetail, {
    props: {
      ...value,
      feasibilityReport: reviewReport,
      candidateItinerary: reviewCandidate,
    },
  })

  await fireEvent.click(view.getByTestId('verify-evidence'))
  expect(scrollSpy).toHaveBeenCalledWith({ block: 'start', behavior: 'smooth' })
  expect(view.getByRole('heading', { name: '攻略情报' })).toBeTruthy()
})
