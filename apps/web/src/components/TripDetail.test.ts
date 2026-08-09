import { render } from '@testing-library/vue'
import { describe, expect, it, vi } from 'vitest'

import type { Itinerary, ItineraryFactImpact, Trip } from '../lib/api'
import TripDetail from './TripDetail.vue'

const trip: Trip = {
  id: 'trip-1',
  title: 'Guangzhou trip',
  destination: 'Guangzhou',
  startDate: '2026-08-01',
  endDate: '2026-08-01',
  status: 'DRAFT',
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
  archivedAt: null,
}

const itinerary: Itinerary = {
  versionId: 'version-1',
  versionNumber: 1,
  parentVersionId: null,
  title: 'Guangzhou trip',
  estimatedTotalCost: 0,
  provider: 'AMAP',
  days: [{
    date: '2026-08-01',
    dayType: 'FULL_DAY',
    activities: [
      {
        id: 'activity-1', title: 'Museum', startTime: '2026-08-01T01:00:00Z',
        endTime: '2026-08-01T02:00:00Z', estimatedCost: 0, source: 'AMAP',
        providerPoiId: null, coordinates: null, address: null, locked: false,
        typeCode: null, typeName: null, kind: 'ATTRACTION', timeFixed: false,
      },
      {
        id: 'activity-2', title: 'Tower', startTime: '2026-08-01T04:00:00Z',
        endTime: '2026-08-01T05:00:00Z', estimatedCost: 0, source: 'AMAP',
        providerPoiId: null, coordinates: null, address: null, locked: false,
        typeCode: null, typeName: null, kind: 'ATTRACTION', timeFixed: false,
      },
    ],
    transitLegs: [{
      id: 'leg-1', legOrder: 0, fromActivityId: 'activity-1', toActivityId: 'activity-2',
      mode: 'WALKING', locked: false, distanceMeters: 5_000, durationSeconds: 4_020,
      provider: 'AMAP', estimated: false, estimatedCost: 0, providerRouteId: null,
      calculatedAt: '2026-08-01T00:00:00Z', stale: false, polyline: [],
    }],
  }],
  knowledge: {
    status: 'UNAVAILABLE', query: 'Guangzhou', citations: [],
    freshness: { status: 'UNAVAILABLE', checkedAt: null, staleReason: null },
    message: null,
  },
  createdAt: '2026-08-01T00:00:00Z',
}

describe('TripDetail', () => {
  it('does not queue a recommended transit edit while initializing an itinerary', () => {
    const view = render(TripDetail, {
      props: {
        user: { id: 'user-1', email: 'user@example.com', displayName: 'Traveler' },
        trip,
        busy: false,
        error: null,
        itinerary,
        itineraryBusy: false,
        itineraryError: null,
        planningState: 'succeeded',
        planningError: null,
        startPlanning: vi.fn(),
        cancelPlanning: vi.fn(),
        updateConstraints: vi.fn(),
        reloadTrip: vi.fn(),
      },
      global: {
        stubs: {
          GuideIntelligencePanel: true,
          ItineraryActionsPanel: true,
          ItineraryVersionPanel: true,
          PlanEvaluationPanel: true,
          PlanningProgress: true,
          TripMap: true,
          TripWeatherTimeline: true,
          TransitLegControl: true,
        },
      },
    })

    expect(view.queryByLabelText('行程修改草稿')).toBeNull()
    expect(view.getByText('我的要求')).toBeTruthy()
  })

  it('maps OPENING_HOURS_EVIDENCE_AVAILABLE to a neutral pending label', () => {
    const factImpact: ItineraryFactImpact = {
      factId: 'fact-1',
      category: 'OPENING_HOURS',
      date: null,
      effect: 'OPENING_HOURS_EVIDENCE_AVAILABLE',
      targetPoiId: null,
      targetName: null,
      reason: 'opening hours evidence linked',
      sourceName: 'city-guide',
      sourceType: 'OFFICIAL',
      sourceUrl: null,
      reliabilityLevel: 'OFFICIAL',
      checkedAt: '2026-08-01T00:00:00Z',
      evidence: 'opening hours 09:00-18:00',
      stale: false,
      conflicted: false,
      refreshFailed: false,
    }
    const itineraryWithImpact: Itinerary = {
      ...itinerary,
      factImpacts: [factImpact],
    }

    const view = render(TripDetail, {
      props: {
        user: { id: 'user-1', email: 'user@example.com', displayName: 'Traveler' },
        trip,
        busy: false,
        error: null,
        itinerary: itineraryWithImpact,
        itineraryBusy: false,
        itineraryError: null,
        planningState: 'succeeded',
        planningError: null,
        startPlanning: vi.fn(),
        cancelPlanning: vi.fn(),
        updateConstraints: vi.fn(),
        reloadTrip: vi.fn(),
      },
      global: {
        stubs: {
          GuideIntelligencePanel: true,
          ItineraryActionsPanel: true,
          ItineraryVersionPanel: true,
          PlanEvaluationPanel: true,
          PlanningProgress: true,
          TripMap: true,
          TripWeatherTimeline: true,
          TransitLegControl: true,
        },
      },
    })

    expect(view.getByText('营业时间证据待验证')).toBeTruthy()
    expect(view.queryByText('OPENING_HOURS_EVIDENCE_AVAILABLE')).toBeNull()
    expect(view.queryByText(/已核验开放时间/)).toBeNull()
    expect(view.queryByText(/硬约束校验通过/)).toBeNull()
  })

  it('maps legacy OPENING_HOURS_APPLIED to a neutral historical label', () => {
    const factImpact: ItineraryFactImpact = {
      factId: 'fact-2',
      category: 'OPENING_HOURS',
      date: null,
      effect: 'OPENING_HOURS_APPLIED',
      targetPoiId: null,
      targetName: null,
      reason: 'historical marker',
      sourceName: 'city-guide',
      sourceType: 'OFFICIAL',
      sourceUrl: null,
      reliabilityLevel: 'OFFICIAL',
      checkedAt: '2026-08-01T00:00:00Z',
      evidence: 'opening hours 09:00-18:00',
      stale: false,
      conflicted: false,
      refreshFailed: false,
    }
    const itineraryWithImpact: Itinerary = {
      ...itinerary,
      factImpacts: [factImpact],
    }

    const view = render(TripDetail, {
      props: {
        user: { id: 'user-1', email: 'user@example.com', displayName: 'Traveler' },
        trip,
        busy: false,
        error: null,
        itinerary: itineraryWithImpact,
        itineraryBusy: false,
        itineraryError: null,
        planningState: 'succeeded',
        planningError: null,
        startPlanning: vi.fn(),
        cancelPlanning: vi.fn(),
        updateConstraints: vi.fn(),
        reloadTrip: vi.fn(),
      },
      global: {
        stubs: {
          GuideIntelligencePanel: true,
          ItineraryActionsPanel: true,
          ItineraryVersionPanel: true,
          PlanEvaluationPanel: true,
          PlanningProgress: true,
          TripMap: true,
          TripWeatherTimeline: true,
          TransitLegControl: true,
        },
      },
    })

    expect(view.getByText('营业时间证据（历史标记，未重新验证）')).toBeTruthy()
    expect(view.queryByText('已核验开放时间')).toBeNull()
    expect(view.queryByText('OPENING_HOURS_APPLIED')).toBeNull()
  })
})
