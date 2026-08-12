import { cleanup, render, screen } from '@testing-library/vue'
import { afterEach, expect, test } from 'vitest'

import PlanningReviewPanel from '../src/components/PlanningReviewPanel.vue'
import type { CandidateItinerary, FeasibilityReport } from '../src/lib/feasibility'

afterEach(() => cleanup())

function makeReport(status: 'NEEDS_REPAIR' | 'UNVERIFIED'): FeasibilityReport {
  return {
    schemaVersion: 1,
    reportId: 'c9c467cc-65c4-8ff1-e175-4af42f2ed545',
    validatorVersion: 'hard-validator-v4',
    itineraryFingerprint: 'a'.repeat(64),
    status,
    validatedAt: '2026-08-10T12:00:00Z',
    requiredRuleIds: ['OPENING_HOURS'],
    missingRequiredRuleIds: [],
    summary: {
      totalCount: 1,
      passCount: 0,
      failCount: status === 'NEEDS_REPAIR' ? 1 : 0,
      unknownCount: status === 'UNVERIFIED' ? 1 : 0,
      notApplicableCount: 0,
      missingRequiredCount: 0,
    },
    ruleResults: [{
      ruleId: 'OPENING_HOURS',
      ruleVersion: 'hard-rule-v1',
      outcome: status === 'NEEDS_REPAIR' ? 'FAIL' : 'UNKNOWN',
      reasonCode: status === 'NEEDS_REPAIR' ? 'VENUE_CLOSED' : 'OPENING_HOURS_UNVERIFIED',
      message: status === 'NEEDS_REPAIR' ? '景点在行程时间关闭' : '营业时间未知',
      affectedDates: ['2026-08-01'],
      affectedEntityRefs: [],
      evidenceRefs: [],
      repairable: true,
    }],
    repairAttempts: [],
  }
}

function makeCandidate(): CandidateItinerary {
  return {
    title: 'Benchmark itinerary',
    days: [{
      date: '2026-08-01',
      dayType: null,
      activities: [{
        activityId: '3d76fb9e-362e-4b28-8a9e-18e8ac7050ae',
        title: 'Activity 1',
        startTime: '2026-08-01T09:00:00Z',
        endTime: '2026-08-01T10:00:00Z',
        estimatedCost: 0,
        source: 'DEMO',
        providerPoiId: null,
        coordinates: null,
        address: null,
        typeCode: null,
        typeName: null,
        kind: null,
        timeFixed: null,
      }],
      transitLegs: [],
    }],
    estimatedTotalCost: 500,
  }
}

test('shows 规划需要确认 title and candidate not formal', () => {
  render(PlanningReviewPanel, {
    props: {
      report: makeReport('NEEDS_REPAIR'),
      candidate: makeCandidate(),
      currentItinerary: null,
    },
  })
  expect(screen.getByText('规划需要确认')).toBeTruthy()
  expect(screen.getByText(/候选行程尚未成为正式版本/)).toBeTruthy()
})

test('renders authoritative feasibility report panel for NEEDS_REPAIR', () => {
  render(PlanningReviewPanel, {
    props: {
      report: makeReport('NEEDS_REPAIR'),
      candidate: makeCandidate(),
      currentItinerary: null,
    },
  })
  expect(screen.getByText('待修复')).toBeTruthy()
  expect(screen.getByText('硬可行性验证')).toBeTruthy()
})

test('renders candidate itinerary title and cost', () => {
  render(PlanningReviewPanel, {
    props: {
      report: makeReport('NEEDS_REPAIR'),
      candidate: makeCandidate(),
      currentItinerary: null,
    },
  })
  expect(screen.getByText('Benchmark itinerary')).toBeTruthy()
  expect(screen.getByText('¥500')).toBeTruthy()
})

test('renders candidate day activity summary', () => {
  render(PlanningReviewPanel, {
    props: {
      report: makeReport('NEEDS_REPAIR'),
      candidate: makeCandidate(),
      currentItinerary: null,
    },
  })
  expect(screen.getByText('Activity 1')).toBeTruthy()
  // Candidate times are UTC on the wire and rendered in the local timezone.
  expect(screen.getByText(/17:00/)).toBeTruthy()
})

test('shows no formal version message when currentItinerary is null', () => {
  render(PlanningReviewPanel, {
    props: {
      report: makeReport('UNVERIFIED'),
      candidate: makeCandidate(),
      currentItinerary: null,
    },
  })
  expect(screen.getByText(/当前尚无正式版本/)).toBeTruthy()
})

test('compares candidate against current formal itinerary without claiming equality', () => {
  render(PlanningReviewPanel, {
    props: {
      report: makeReport('NEEDS_REPAIR'),
      candidate: makeCandidate(),
      currentItinerary: {
        title: 'Formal route',
        estimatedTotalCost: 800,
        days: [{ date: '2026-08-01', activities: [{ title: 'Formal Activity' }] }],
      },
    },
  })
  expect(screen.getByText('Formal route')).toBeTruthy()
  expect(screen.getByText('Formal Activity')).toBeTruthy()
  expect(screen.getByText('¥800')).toBeTruthy()
})

test('never offers accept / force save / skip verification buttons', () => {
  render(PlanningReviewPanel, {
    props: {
      report: makeReport('NEEDS_REPAIR'),
      candidate: makeCandidate(),
      currentItinerary: null,
    },
  })
  expect(screen.queryByText(/接受/)).toBeNull()
  expect(screen.queryByText(/强制保存/)).toBeNull()
  expect(screen.queryByText(/忽略验证/)).toBeNull()
  expect(screen.queryByText(/跳过验证/)).toBeNull()
})

test('malformed candidate shows stable error panel', () => {
  render(PlanningReviewPanel, {
    props: {
      report: makeReport('NEEDS_REPAIR'),
      candidate: { not: 'an itinerary' },
      currentItinerary: null,
    },
  })
  expect(screen.getByText(/候选行程暂时无法读取/)).toBeTruthy()
})

test('malformed report shows stable error without guessing status', () => {
  render(PlanningReviewPanel, {
    props: {
      report: null,
      malformedReport: true,
      candidate: makeCandidate(),
      currentItinerary: null,
    },
  })
  expect(screen.getByText(/验证结果暂时无法读取/)).toBeTruthy()
})

test('candidate does not replace the passed formal itinerary', () => {
  render(PlanningReviewPanel, {
    props: {
      report: makeReport('NEEDS_REPAIR'),
      candidate: makeCandidate(),
      currentItinerary: {
        title: 'Formal route',
        estimatedTotalCost: 800,
        days: [{ date: '2026-08-01', activities: [{ title: 'Formal Activity' }] }],
      },
    },
  })
  // Candidate title is distinct from formal title; both render.
  expect(screen.getByText('Benchmark itinerary')).toBeTruthy()
  expect(screen.getByText('Formal route')).toBeTruthy()
})

function makeCandidateWithTransit() {
  return {
    title: 'Benchmark itinerary',
    days: [{
      date: '2026-08-01',
      dayType: null,
      activities: [
        {
          activityId: '3d76fb9e-362e-4b28-8a9e-18e8ac7050ae',
          title: 'Activity 1',
          startTime: '2026-08-01T09:00:00Z',
          endTime: '2026-08-01T10:00:00Z',
          estimatedCost: 0,
          source: 'DEMO',
          providerPoiId: null,
          coordinates: null,
          address: null,
          typeCode: null,
          typeName: null,
          kind: null,
          timeFixed: null,
        },
        {
          activityId: '4d76fb9e-362e-4b28-8a9e-18e8ac7050ae',
          title: 'Activity 2',
          startTime: '2026-08-01T10:30:00Z',
          endTime: '2026-08-01T12:00:00Z',
          estimatedCost: 0,
          source: 'DEMO',
          providerPoiId: null,
          coordinates: null,
          address: null,
          typeCode: null,
          typeName: null,
          kind: null,
          timeFixed: null,
        },
      ],
      transitLegs: [{
        transitId: '61f3d628-8c83-4c51-986d-8e87353a2d6a',
        fromActivityIndex: 0,
        toActivityIndex: 1,
        mode: 'WALKING',
        distanceMeters: 300,
        durationSeconds: 300,
        provider: 'DEMO',
        estimated: true,
        polyline: [],
      }],
    }],
    estimatedTotalCost: 500,
  }
}

test('renders the full start–end time window for each candidate activity', () => {
  render(PlanningReviewPanel, {
    props: {
      report: makeReport('NEEDS_REPAIR'),
      candidate: makeCandidate(),
      currentItinerary: null,
    },
  })
  // Wire times are UTC; the panel renders Asia/Shanghai local times.
  expect(screen.getByText(/17:00–18:00/)).toBeTruthy()
})

test('renders candidate transit summary with resolved activity titles', () => {
  render(PlanningReviewPanel, {
    props: {
      report: makeReport('NEEDS_REPAIR'),
      candidate: makeCandidateWithTransit(),
      currentItinerary: null,
    },
  })
  expect(screen.getByText(/Activity 1 → Activity 2 · 步行（估算） · 5 分钟 · 300 米/)).toBeTruthy()
})

test('renders current formal itinerary transit summary in the comparison', () => {
  render(PlanningReviewPanel, {
    props: {
      report: makeReport('NEEDS_REPAIR'),
      candidate: makeCandidateWithTransit(),
      currentItinerary: {
        title: 'Formal route',
        estimatedTotalCost: 800,
        days: [{
          date: '2026-08-01',
          activities: [
            { id: 'f-1', title: 'Formal A' },
            { id: 'f-2', title: 'Formal B' },
          ],
          transitLegs: [{
            fromActivityId: 'f-1',
            toActivityId: 'f-2',
            mode: 'TRANSIT',
            distanceMeters: 2400,
            durationSeconds: 1200,
            estimated: false,
          }],
        }],
      },
    },
  })
  expect(screen.getByText(/Formal A → Formal B · 公共交通 · 20 分钟 · 2.4 公里/)).toBeTruthy()
})

test('candidate props are never mutated into the current itinerary', () => {
  const candidate = makeCandidateWithTransit()
  const current = {
    title: 'Formal route',
    estimatedTotalCost: 800,
    days: [{ date: '2026-08-01', activities: [{ id: 'f-1', title: 'Formal A' }] }],
  }
  render(PlanningReviewPanel, {
    props: {
      report: makeReport('NEEDS_REPAIR'),
      candidate,
      currentItinerary: current,
    },
  })
  // Both shapes render independently; neither object is written back.
  expect(screen.getByText('Benchmark itinerary')).toBeTruthy()
  expect(screen.getByText('Formal route')).toBeTruthy()
  expect((candidate as { title: string }).title).toBe('Benchmark itinerary')
  expect(current.title).toBe('Formal route')
})
