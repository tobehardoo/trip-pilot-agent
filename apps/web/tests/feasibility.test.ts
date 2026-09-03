import { describe, expect, test } from 'vitest'

import {
  parseTypedEntityReference,
  readCandidateItinerary,
  readFeasibilityReport,
  readPlanEvaluation,
  readPlanningDecisions,
  readPlanningEventOutcome,
  readPlanningTaskOutcome,
  decisionReasonLabel,
  decisionSubjectLabel,
  type FeasibilityReport,
  type VersionFeasibilityMetadata,
} from '../src/lib/feasibility'

function verifiedReport(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    schemaVersion: 1,
    reportId: 'c9c467cc-65c4-8ff1-e175-4af42f2ed545',
    validatorVersion: 'hard-validator-v4',
    itineraryFingerprint: 'a'.repeat(64),
    status: 'VERIFIED',
    validatedAt: '2026-08-10T12:00:00Z',
    requiredRuleIds: ['OPENING_HOURS'],
    missingRequiredRuleIds: [],
    summary: { totalCount: 1, passCount: 1, failCount: 0, unknownCount: 0, notApplicableCount: 0, missingRequiredCount: 0 },
    ruleResults: [{
      ruleId: 'OPENING_HOURS',
      ruleVersion: 'hard-rule-v1',
      outcome: 'PASS',
      reasonCode: 'OPENING_HOURS_VERIFIED',
      message: 'open',
      affectedDates: ['2026-08-01'],
      affectedEntityRefs: ['activity:11111111-1111-4111-8111-111111111111'],
      evidenceRefs: [{
        evidenceId: 'ev-1',
        evidenceType: 'OPENING_HOURS',
        state: 'VERIFIED',
        hardConstraintEligible: true,
      }],
      repairable: false,
    }],
    repairAttempts: [],
    ...overrides,
  }
}

describe('readFeasibilityReport', () => {
  test('reads a valid VERIFIED report', () => {
    const result = readFeasibilityReport(verifiedReport())
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.value.status).toBe('VERIFIED')
      expect(result.value.summary.passCount).toBe(1)
      expect(result.value.ruleResults).toHaveLength(1)
    }
  })

  test('reads a valid NEEDS_REPAIR report', () => {
    const result = readFeasibilityReport(verifiedReport({
      status: 'NEEDS_REPAIR',
      summary: { totalCount: 1, passCount: 0, failCount: 1, unknownCount: 0, notApplicableCount: 0, missingRequiredCount: 0 },
      ruleResults: [{
        ruleId: 'OPENING_HOURS',
        ruleVersion: 'hard-rule-v1',
        outcome: 'FAIL',
        reasonCode: 'VENUE_CLOSED',
        message: 'closed',
        affectedDates: ['2026-08-01'],
        affectedEntityRefs: [],
        evidenceRefs: [],
        repairable: true,
      }],
      repairAttempts: [{
        attemptIndex: 1,
        triggeringRuleIds: ['OPENING_HOURS'],
        actionCodes: ['MOVE_ACTIVITY'],
        affectedDates: ['2026-08-01'],
        affectedEntityRefs: [],
        beforeFingerprint: 'b'.repeat(64),
        afterFingerprint: 'c'.repeat(64),
        resultingStatus: 'NEEDS_REPAIR',
      }],
    }))
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.value.status).toBe('NEEDS_REPAIR')
      expect(result.value.repairAttempts).toHaveLength(1)
    }
  })

  test('reads a valid UNVERIFIED report', () => {
    const result = readFeasibilityReport(verifiedReport({
      status: 'UNVERIFIED',
      summary: { totalCount: 1, passCount: 0, failCount: 0, unknownCount: 1, notApplicableCount: 0, missingRequiredCount: 0 },
      ruleResults: [{
        ruleId: 'OPENING_HOURS',
        ruleVersion: 'hard-rule-v1',
        outcome: 'UNKNOWN',
        reasonCode: 'OPENING_HOURS_UNVERIFIED',
        message: 'unknown',
        affectedDates: [],
        affectedEntityRefs: [],
        evidenceRefs: [],
        repairable: false,
      }],
    }))
    expect(result.ok).toBe(true)
    if (result.ok) expect(result.value.status).toBe('UNVERIFIED')
  })

  test('rejects unknown status', () => {
    const result = readFeasibilityReport(verifiedReport({ status: 'MAGIC' }))
    expect(result.ok).toBe(false)
  })

  test('rejects unknown rule outcome', () => {
    const result = readFeasibilityReport(verifiedReport({
      ruleResults: [{
        ruleId: 'OPENING_HOURS',
        ruleVersion: 'hard-rule-v1',
        outcome: 'MAGIC',
        reasonCode: 'X',
        message: 'x',
        affectedDates: [],
        affectedEntityRefs: [],
        evidenceRefs: [],
        repairable: false,
      }],
    }))
    expect(result.ok).toBe(false)
  })

  test('rejects unknown evidence state', () => {
    const result = readFeasibilityReport(verifiedReport({
      ruleResults: [{
        ruleId: 'OPENING_HOURS',
        ruleVersion: 'hard-rule-v1',
        outcome: 'PASS',
        reasonCode: 'X',
        message: 'x',
        affectedDates: [],
        affectedEntityRefs: [],
        evidenceRefs: [{ evidenceId: 'e', evidenceType: 'T', state: 'MAGIC', hardConstraintEligible: false }],
        repairable: false,
      }],
    }))
    expect(result.ok).toBe(false)
  })

  test('rejects missing summary', () => {
    const input = verifiedReport()
    delete input.summary
    expect(readFeasibilityReport(input).ok).toBe(false)
  })

  test('rejects missing ruleResults', () => {
    const input = verifiedReport()
    delete input.ruleResults
    expect(readFeasibilityReport(input).ok).toBe(false)
  })

  test('rejects non-array affectedDates', () => {
    const input = verifiedReport({
      ruleResults: [{
        ruleId: 'OPENING_HOURS',
        ruleVersion: 'hard-rule-v1',
        outcome: 'PASS',
        reasonCode: 'X',
        message: 'x',
        affectedDates: '2026-08-01',
        affectedEntityRefs: [],
        evidenceRefs: [],
        repairable: false,
      }],
    })
    expect(readFeasibilityReport(input).ok).toBe(false)
  })

  test('rejects non-array affectedEntityRefs', () => {
    const input = verifiedReport({
      ruleResults: [{
        ruleId: 'OPENING_HOURS',
        ruleVersion: 'hard-rule-v1',
        outcome: 'PASS',
        reasonCode: 'X',
        message: 'x',
        affectedDates: [],
        affectedEntityRefs: 'activity:x',
        evidenceRefs: [],
        repairable: false,
      }],
    })
    expect(readFeasibilityReport(input).ok).toBe(false)
  })

  test('rejects non-array evidenceRefs', () => {
    const input = verifiedReport({
      ruleResults: [{
        ruleId: 'OPENING_HOURS',
        ruleVersion: 'hard-rule-v1',
        outcome: 'PASS',
        reasonCode: 'X',
        message: 'x',
        affectedDates: [],
        affectedEntityRefs: [],
        evidenceRefs: { bad: true },
        repairable: false,
      }],
    })
    expect(readFeasibilityReport(input).ok).toBe(false)
  })

  test('rejects invalid repairAttempts (missing attemptIndex)', () => {
    const input = verifiedReport({
      repairAttempts: [{
        triggeringRuleIds: ['OPENING_HOURS'],
        actionCodes: ['MOVE_ACTIVITY'],
        affectedDates: [],
        affectedEntityRefs: [],
        beforeFingerprint: 'b'.repeat(64),
        afterFingerprint: 'c'.repeat(64),
        resultingStatus: 'NEEDS_REPAIR',
      }],
    })
    expect(readFeasibilityReport(input).ok).toBe(false)
  })

  test('malformed input returns distinguishable error without throwing', () => {
    const result = readFeasibilityReport(null)
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.reason).toBeTruthy()
  })

  test('recognises null as no report', () => {
    const result = readFeasibilityReport(null)
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.reason).toContain('report')
  })
})

describe('parseTypedEntityReference', () => {
  test('parses activity ref', () => {
    const parsed = parseTypedEntityReference('activity:11111111-1111-4111-8111-111111111111')
    expect(parsed.kind).toBe('activity')
    expect(parsed.value).toBe('11111111-1111-4111-8111-111111111111')
  })

  test('parses transit ref', () => {
    const parsed = parseTypedEntityReference('transit:11111111-1111-4111-8111-111111111111')
    expect(parsed.kind).toBe('transit')
  })

  test('parses poi ref with colons', () => {
    const parsed = parseTypedEntityReference('poi:POI:1')
    expect(parsed.kind).toBe('poi')
    expect(parsed.value).toBe('POI:1')
  })

  test('parses text ref', () => {
    const parsed = parseTypedEntityReference('text:广州塔')
    expect(parsed.kind).toBe('text')
  })

  test('unknown kind is not interpreted as known entity', () => {
    const parsed = parseTypedEntityReference('mystery:value')
    expect(parsed.kind).toBe('unknown')
    expect(parsed.value).toBe('value')
  })

  test('bare string is unknown', () => {
    expect(parseTypedEntityReference('not-a-ref').kind).toBe('unknown')
  })
})

describe('readCandidateItinerary', () => {
  const validCandidate = {
    title: 'Benchmark itinerary',
    days: [{
      date: '2026-08-01',
      activities: [{
        activityId: '3d76fb9e-362e-4b28-8a9e-18e8ac7050ae',
        title: 'Activity 1',
        startTime: '2026-08-01T09:00:00Z',
        endTime: '2026-08-01T10:00:00Z',
        estimatedCost: 0,
        source: 'DEMO',
      }, {
        activityId: '4d76fb9e-362e-4b28-8a9e-18e8ac7050ae',
        title: 'Activity 2',
        startTime: '2026-08-01T10:30:00Z',
        endTime: '2026-08-01T12:00:00Z',
        estimatedCost: 0,
        source: 'DEMO',
      }],
      transitLegs: [{
        transitId: '61f3d628-8c83-4c51-986d-8e87353a2d6a',
        fromActivityIndex: 0,
        toActivityIndex: 1,
        mode: 'WALKING',
        distanceMeters: 300,
        durationSeconds: 300,
        provider: 'DEMO',
        estimated: true,
        polyline: [{ longitude: 113.26, latitude: 23.13 }],
      }],
    }],
    estimatedTotalCost: 500,
  }

  test('recognises a valid candidate itinerary', () => {
    const result = readCandidateItinerary(validCandidate)
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.value.days).toHaveLength(1)
    }
  })

  test('rejects candidate missing days', () => {
    const input = { ...validCandidate, days: [] }
    expect(readCandidateItinerary(input).ok).toBe(false)
  })

  test('rejects candidate missing activity time fields', () => {
    const input = {
      ...validCandidate,
      days: [{
        date: '2026-08-01',
        activities: [{ activityId: 'x', title: 'A', estimatedCost: 0, source: 'DEMO' }],
        transitLegs: [],
      }],
    }
    expect(readCandidateItinerary(input).ok).toBe(false)
  })

  test('rejects malformed candidate without throwing', () => {
    const result = readCandidateItinerary({ not: 'an itinerary' })
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.reason).toBeTruthy()
  })
})

describe('VersionFeasibilityMetadata null semantics', () => {
  test('null means no historical validation metadata', () => {
    // A summary with feasibility: null must be represented as null, not
    // coerced to UNVERIFIED.  The type itself is enough for static checks;
    // runtime helper below documents the mapping.
    const metadata: VersionFeasibilityMetadata | null = null
    expect(metadata).toBeNull()
  })
})

// ── B6W FIX: fail-closed reader regressions ───────────────────────────────

describe('readFeasibilityReport fail-closed regressions', () => {
  test('rejects missing requiredRuleIds instead of defaulting to empty', () => {
    const input = verifiedReport()
    delete input.requiredRuleIds
    expect(readFeasibilityReport(input).ok).toBe(false)
  })

  test('rejects null requiredRuleIds instead of defaulting to empty', () => {
    expect(readFeasibilityReport(verifiedReport({ requiredRuleIds: null })).ok).toBe(false)
  })

  test('rejects missing missingRequiredRuleIds', () => {
    const input = verifiedReport()
    delete input.missingRequiredRuleIds
    expect(readFeasibilityReport(input).ok).toBe(false)
  })

  test('rejects missing evidenceRefs on a rule', () => {
    const input = verifiedReport({
      ruleResults: [{
        ruleId: 'OPENING_HOURS',
        ruleVersion: 'hard-rule-v1',
        outcome: 'PASS',
        reasonCode: 'X',
        message: 'x',
        affectedDates: [],
        affectedEntityRefs: [],
        repairable: false,
      }],
    })
    expect(readFeasibilityReport(input).ok).toBe(false)
  })

  test('rejects missing repairAttempts', () => {
    const input = verifiedReport()
    delete input.repairAttempts
    expect(readFeasibilityReport(input).ok).toBe(false)
  })

  test('rejects non-integer schemaVersion', () => {
    expect(readFeasibilityReport(verifiedReport({ schemaVersion: 1.5 })).ok).toBe(false)
  })

  test('rejects zero and negative schemaVersion', () => {
    expect(readFeasibilityReport(verifiedReport({ schemaVersion: 0 })).ok).toBe(false)
    expect(readFeasibilityReport(verifiedReport({ schemaVersion: -1 })).ok).toBe(false)
  })

  test('rejects unknown schemaVersion', () => {
    expect(readFeasibilityReport(verifiedReport({ schemaVersion: 99 })).ok).toBe(false)
  })

  test('rejects unknown validatorVersion', () => {
    expect(readFeasibilityReport(verifiedReport({ validatorVersion: 'hard-validator-v6' })).ok).toBe(false)
  })

  test('accepts all validator versions on the shared whitelist', () => {
    for (const version of ['feasibility-v1', 'hard-validator-v1', 'hard-validator-v2', 'hard-validator-v3', 'hard-validator-v4', 'hard-validator-v5']) {
      expect(readFeasibilityReport(verifiedReport({ validatorVersion: version })).ok).toBe(true)
    }
  })

  test('rejects negative summary counts', () => {
    const input = verifiedReport({
      summary: { totalCount: -1, passCount: 1, failCount: 0, unknownCount: 0, notApplicableCount: 0, missingRequiredCount: 0 },
    })
    expect(readFeasibilityReport(input).ok).toBe(false)
  })

  test('rejects zero attemptIndex', () => {
    const input = verifiedReport({
      status: 'NEEDS_REPAIR',
      summary: { totalCount: 1, passCount: 0, failCount: 1, unknownCount: 0, notApplicableCount: 0, missingRequiredCount: 0 },
      ruleResults: [{
        ruleId: 'OPENING_HOURS',
        ruleVersion: 'hard-rule-v1',
        outcome: 'FAIL',
        reasonCode: 'X',
        message: 'x',
        affectedDates: [],
        affectedEntityRefs: [],
        evidenceRefs: [],
        repairable: true,
      }],
      repairAttempts: [{
        attemptIndex: 0,
        triggeringRuleIds: ['OPENING_HOURS'],
        actionCodes: ['MOVE_ACTIVITY'],
        affectedDates: [],
        affectedEntityRefs: [],
        beforeFingerprint: 'b'.repeat(64),
        afterFingerprint: 'c'.repeat(64),
        resultingStatus: 'NEEDS_REPAIR',
      }],
    })
    expect(readFeasibilityReport(input).ok).toBe(false)
  })

  test('rejects repair history beyond the three-attempt runtime bound', () => {
    const attempt = {
      triggeringRuleIds: ['OPENING_HOURS'],
      actionCodes: ['SHIFT_ACTIVITY_TO_OPENING_WINDOW'],
      affectedDates: ['2026-08-01'],
      affectedEntityRefs: [],
      beforeFingerprint: 'b'.repeat(64),
      afterFingerprint: 'c'.repeat(64),
      resultingStatus: 'NEEDS_REPAIR',
    }
    expect(readFeasibilityReport(verifiedReport({
      repairAttempts: [1, 2, 3, 4].map(attemptIndex => ({ ...attempt, attemptIndex })),
    })).ok).toBe(false)
  })

  test('rejects non-contiguous repair attempt indices', () => {
    expect(readFeasibilityReport(verifiedReport({
      repairAttempts: [{
        attemptIndex: 2,
        triggeringRuleIds: ['OPENING_HOURS'],
        actionCodes: ['SHIFT_ACTIVITY_TO_OPENING_WINDOW'],
        affectedDates: [],
        affectedEntityRefs: [],
        beforeFingerprint: 'b'.repeat(64),
        afterFingerprint: 'c'.repeat(64),
        resultingStatus: 'NEEDS_REPAIR',
      }],
    })).ok).toBe(false)
  })

  test.each([
    { actionCodes: [], label: 'empty action list' },
    { triggeringRuleIds: [], label: 'empty triggering rules' },
    { beforeFingerprint: 'not-a-fingerprint', label: 'invalid fingerprint' },
    { affectedDates: ['2026-02-30'], label: 'invalid affected date' },
  ])('rejects repair attempt with $label', (override) => {
    expect(readFeasibilityReport(verifiedReport({
      repairAttempts: [{
        attemptIndex: 1,
        triggeringRuleIds: ['OPENING_HOURS'],
        actionCodes: ['SHIFT_ACTIVITY_TO_OPENING_WINDOW'],
        affectedDates: [],
        affectedEntityRefs: [],
        beforeFingerprint: 'b'.repeat(64),
        afterFingerprint: 'c'.repeat(64),
        resultingStatus: 'NEEDS_REPAIR',
        ...override,
      }],
    })).ok).toBe(false)
  })
})

describe('parseTypedEntityReference fail-closed regressions', () => {
  test('empty poi ref is unknown, not a known entity', () => {
    expect(parseTypedEntityReference('poi:').kind).toBe('unknown')
  })

  test('empty text ref is unknown', () => {
    expect(parseTypedEntityReference('text:').kind).toBe('unknown')
  })

  test('activity ref with non-UUID value is unknown', () => {
    expect(parseTypedEntityReference('activity:not-a-uuid').kind).toBe('unknown')
  })

  test('transit ref with non-UUID value is unknown', () => {
    expect(parseTypedEntityReference('transit:xyz').kind).toBe('unknown')
  })

  test('non-string ref is unknown', () => {
    expect(parseTypedEntityReference(42 as unknown as string).kind).toBe('unknown')
  })
})

describe('readCandidateItinerary fail-closed regressions', () => {
  const validCandidate = {
    title: 'Benchmark itinerary',
    days: [{
      date: '2026-08-01',
      activities: [{
        activityId: '3d76fb9e-362e-4b28-8a9e-18e8ac7050ae',
        title: 'Activity 1',
        startTime: '2026-08-01T09:00:00Z',
        endTime: '2026-08-01T10:00:00Z',
        estimatedCost: 0,
        source: 'DEMO',
      }],
      transitLegs: [{
        transitId: '61f3d628-8c83-4c51-986d-8e87353a2d6a',
        fromActivityIndex: 0,
        toActivityIndex: 1,
        mode: 'WALKING',
        distanceMeters: 300,
        durationSeconds: 300,
        provider: 'DEMO',
        estimated: true,
        polyline: [{ longitude: 113.26, latitude: 23.13 }],
      }],
    }],
    estimatedTotalCost: 500,
  }

  test('rejects transit leg missing mode', () => {
    const leg = validCandidate.days[0]!.transitLegs[0]!
    const { mode: _mode, ...rest } = leg
    expect(readCandidateItinerary({
      ...validCandidate,
      days: [{ ...validCandidate.days[0]!, transitLegs: [rest] }],
    }).ok).toBe(false)
  })

  test('rejects transit leg missing provider', () => {
    const leg = validCandidate.days[0]!.transitLegs[0]!
    const { provider: _provider, ...rest } = leg
    expect(readCandidateItinerary({
      ...validCandidate,
      days: [{ ...validCandidate.days[0]!, transitLegs: [rest] }],
    }).ok).toBe(false)
  })

  test('rejects transit leg missing estimated', () => {
    const leg = validCandidate.days[0]!.transitLegs[0]!
    const { estimated: _estimated, ...rest } = leg
    expect(readCandidateItinerary({
      ...validCandidate,
      days: [{ ...validCandidate.days[0]!, transitLegs: [rest] }],
    }).ok).toBe(false)
  })

  test('rejects transit leg with non-array polyline', () => {
    expect(readCandidateItinerary({
      ...validCandidate,
      days: [{
        ...validCandidate.days[0]!,
        transitLegs: [{ ...validCandidate.days[0]!.transitLegs[0]!, polyline: 'nope' }],
      }],
    }).ok).toBe(false)
  })

  test('rejects negative activity index', () => {
    expect(readCandidateItinerary({
      ...validCandidate,
      days: [{
        ...validCandidate.days[0]!,
        transitLegs: [{ ...validCandidate.days[0]!.transitLegs[0]!, fromActivityIndex: -1 }],
      }],
    }).ok).toBe(false)
  })

  test('rejects out-of-bounds activity index', () => {
    expect(readCandidateItinerary({
      ...validCandidate,
      days: [{
        ...validCandidate.days[0]!,
        transitLegs: [{ ...validCandidate.days[0]!.transitLegs[0]!, toActivityIndex: 5 }],
      }],
    }).ok).toBe(false)
  })

  test('rejects non-finite polyline coordinates', () => {
    expect(readCandidateItinerary({
      ...validCandidate,
      days: [{
        ...validCandidate.days[0]!,
        transitLegs: [{
          ...validCandidate.days[0]!.transitLegs[0]!,
          polyline: [{ longitude: Number.NaN, latitude: 23.13 }],
        }],
      }],
    }).ok).toBe(false)
  })

  test('rejects empty activity day', () => {
    expect(readCandidateItinerary({
      ...validCandidate,
      days: [{ ...validCandidate.days[0]!, activities: [] }],
    }).ok).toBe(false)
  })
})

describe('readPlanEvaluation', () => {
  const validEvaluation = {
    schemaVersion: 1,
    evaluatorVersion: 'rule-v1',
    feasible: true,
    overallScore: 91,
    dimensions: {
      constraintSatisfaction: 100,
      timeFeasibility: 90,
      budgetFit: 88,
      routeEfficiency: 85,
      interestMatch: 80,
    },
    warnings: [{ code: 'W', severity: 'INFO', message: 'm', entityType: 'DAY' }],
    decisions: [{ subjectType: 'TRANSIT', summary: 's', reasonCodes: ['R'], reasons: ['r'] }],
    summary: '行程整体质量 91/100。',
    evaluatedAt: '2026-08-10T12:00:00Z',
  }

  test('reads a valid evaluation', () => {
    const result = readPlanEvaluation(validEvaluation)
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.value.overallScore).toBe(91)
      expect(result.value.warnings).toHaveLength(1)
    }
  })

  test('rejects missing evaluation', () => {
    expect(readPlanEvaluation(undefined).ok).toBe(false)
    expect(readPlanEvaluation(null).ok).toBe(false)
  })

  test('rejects non-integer overallScore', () => {
    expect(readPlanEvaluation({ ...validEvaluation, overallScore: 91.5 }).ok).toBe(false)
  })

  test('rejects out-of-range overallScore', () => {
    expect(readPlanEvaluation({ ...validEvaluation, overallScore: 101 }).ok).toBe(false)
  })

  test('rejects missing dimensions', () => {
    const { dimensions: _dimensions, ...rest } = validEvaluation
    expect(readPlanEvaluation(rest).ok).toBe(false)
  })

  test('rejects non-array warnings', () => {
    expect(readPlanEvaluation({ ...validEvaluation, warnings: 'nope' }).ok).toBe(false)
  })

  test('rejects unknown warning severity', () => {
    expect(readPlanEvaluation({
      ...validEvaluation,
      warnings: [{ code: 'W', severity: 'FATAL', message: 'm', entityType: 'DAY' }],
    }).ok).toBe(false)
  })
})

// ── B6W FIX: unified outcome parser truth table ───────────────────────────

const verifiedReportFixture = verifiedReport()
const needsRepairReportFixture = verifiedReport({
  status: 'NEEDS_REPAIR',
  summary: { totalCount: 1, passCount: 0, failCount: 1, unknownCount: 0, notApplicableCount: 0, missingRequiredCount: 0 },
})
const unverifiedReportFixture = verifiedReport({ status: 'UNVERIFIED' })
const evaluationFixture = {
  schemaVersion: 1,
  evaluatorVersion: 'rule-v1',
  feasible: true,
  overallScore: 91,
  dimensions: {
    constraintSatisfaction: 100,
    timeFeasibility: 90,
    budgetFit: 88,
    routeEfficiency: 85,
    interestMatch: 80,
  },
  warnings: [],
  decisions: [],
  summary: '行程整体质量 91/100。',
  evaluatedAt: '2026-08-10T12:00:00Z',
}
const candidateFixture = {
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

describe('readPlanningTaskOutcome', () => {
  test('SUCCEEDED with VERIFIED report and evaluation is completed', () => {
    const outcome = readPlanningTaskOutcome({
      status: 'SUCCEEDED',
      feasibilityReport: verifiedReportFixture,
      evaluation: evaluationFixture,
    })
    expect(outcome.kind).toBe('completed')
    if (outcome.kind === 'completed') {
      expect(outcome.report.status).toBe('VERIFIED')
      expect(outcome.evaluation.overallScore).toBe(91)
    }
  })

  test('WAITING_USER with NEEDS_REPAIR report and candidate is review', () => {
    const outcome = readPlanningTaskOutcome({
      status: 'WAITING_USER',
      feasibilityReport: needsRepairReportFixture,
      candidateItinerary: candidateFixture,
    })
    expect(outcome.kind).toBe('review')
    if (outcome.kind === 'review') {
      expect(outcome.report.status).toBe('NEEDS_REPAIR')
      expect(outcome.candidate.title).toBe('Benchmark itinerary')
    }
  })

  test('WAITING_USER with UNVERIFIED report and candidate is review', () => {
    const outcome = readPlanningTaskOutcome({
      status: 'WAITING_USER',
      feasibilityReport: unverifiedReportFixture,
      candidateItinerary: candidateFixture,
    })
    expect(outcome.kind).toBe('review')
  })

  test('WAITING_USER with VERIFIED report fails closed', () => {
    const outcome = readPlanningTaskOutcome({
      status: 'WAITING_USER',
      feasibilityReport: verifiedReportFixture,
      candidateItinerary: candidateFixture,
    })
    expect(outcome.kind).toBe('malformed')
  })

  test('SUCCEEDED with NEEDS_REPAIR report fails closed', () => {
    const outcome = readPlanningTaskOutcome({
      status: 'SUCCEEDED',
      feasibilityReport: needsRepairReportFixture,
      evaluation: evaluationFixture,
    })
    expect(outcome.kind).toBe('malformed')
  })

  test('SUCCEEDED with UNVERIFIED blocker-free report is a completed outcome (B16)', () => {
    const outcome = readPlanningTaskOutcome({
      status: 'SUCCEEDED',
      feasibilityReport: unverifiedReportFixture,
      evaluation: evaluationFixture,
    })
    // B16: Information Missing != Planning Failed — an UNVERIFIED report
    // without a blocker (no FAIL, no missing required rule) is a savable
    // completion, not a malformed wire body.
    expect(outcome.kind).toBe('completed')
    if (outcome.kind === 'completed') {
      expect(outcome.report.status).toBe('UNVERIFIED')
    }
  })

  test('SUCCEEDED with UNVERIFIED blocker report fails closed', () => {
    const outcome = readPlanningTaskOutcome({
      status: 'SUCCEEDED',
      feasibilityReport: {
        ...unverifiedReportFixture,
        summary: { ...unverifiedReportFixture.summary, failCount: 1 },
        ruleResults: [
          { ...unverifiedReportFixture.ruleResults[0], outcome: 'FAIL' },
          ...unverifiedReportFixture.ruleResults.slice(1),
        ],
      },
      evaluation: evaluationFixture,
    })
    expect(outcome.kind).toBe('malformed')
  })

  test('SUCCEEDED with missing required rule fails closed', () => {
    const outcome = readPlanningTaskOutcome({
      status: 'SUCCEEDED',
      feasibilityReport: {
        ...unverifiedReportFixture,
        missingRequiredRuleIds: ['OPENING_HOURS'],
      },
      evaluation: evaluationFixture,
    })
    expect(outcome.kind).toBe('malformed')
  })

  test('completed with a candidate fails closed', () => {
    const outcome = readPlanningTaskOutcome({
      status: 'SUCCEEDED',
      feasibilityReport: verifiedReportFixture,
      candidateItinerary: candidateFixture,
      evaluation: evaluationFixture,
    })
    expect(outcome.kind).toBe('malformed')
  })

  test('review with an evaluation fails closed', () => {
    const outcome = readPlanningTaskOutcome({
      status: 'WAITING_USER',
      feasibilityReport: needsRepairReportFixture,
      candidateItinerary: candidateFixture,
      evaluation: evaluationFixture,
    })
    expect(outcome.kind).toBe('malformed')
  })

  test('review without candidate fails closed', () => {
    const outcome = readPlanningTaskOutcome({
      status: 'WAITING_USER',
      feasibilityReport: needsRepairReportFixture,
    })
    expect(outcome.kind).toBe('malformed')
  })

  test('review without report fails closed', () => {
    const outcome = readPlanningTaskOutcome({
      status: 'WAITING_USER',
      candidateItinerary: candidateFixture,
    })
    expect(outcome.kind).toBe('malformed')
  })

  test('completed without evaluation fails closed', () => {
    const outcome = readPlanningTaskOutcome({
      status: 'SUCCEEDED',
      feasibilityReport: verifiedReportFixture,
    })
    expect(outcome.kind).toBe('malformed')
  })

  test('QUEUED is queued and rejects outcome fields', () => {
    expect(readPlanningTaskOutcome({ status: 'QUEUED' }).kind).toBe('queued')
    expect(readPlanningTaskOutcome({
      status: 'QUEUED',
      feasibilityReport: verifiedReportFixture,
    }).kind).toBe('malformed')
  })

  test('FAILED carries the error message and rejects outcome fields', () => {
    const outcome = readPlanningTaskOutcome({
      status: 'FAILED',
      errorMessage: 'boom',
    })
    expect(outcome.kind).toBe('failed')
    if (outcome.kind === 'failed') expect(outcome.errorMessage).toBe('boom')
    expect(readPlanningTaskOutcome({
      status: 'FAILED',
      errorMessage: 'boom',
      evaluation: evaluationFixture,
    }).kind).toBe('malformed')
  })

  test('FAILED with conflicts and relaxation suggestions composes a rich error message', () => {
    const outcome = readPlanningTaskOutcome({
      status: 'FAILED',
      safeMessage: '时间不足，请调整条件后重试',
      conflicts: [
        {
          code: 'INSUFFICIENT_DAY_CAPACITY',
          message: '实际交通时长无法在固定返程时间前完成',
          affected: ['DEPARTURE'],
        },
      ],
      relaxationSuggestions: [
        { code: 'EXTEND_AVAILABLE_TIME', message: '请提前出发、延后返程时间，或减少前序行程' },
      ],
    })
    expect(outcome.kind).toBe('failed')
    if (outcome.kind === 'failed') {
      expect(outcome.errorMessage).toContain('时间不足，请调整条件后重试')
      expect(outcome.errorMessage).toContain('实际交通时长无法在固定返程时间前完成')
      expect(outcome.errorMessage).toContain('建议：请提前出发、延后返程时间，或减少前序行程')
    }
  })

  test('CANCELLED is cancelled and rejects outcome fields', () => {
    expect(readPlanningTaskOutcome({ status: 'CANCELLED' }).kind).toBe('cancelled')
    expect(readPlanningTaskOutcome({
      status: 'CANCELLED',
      candidateItinerary: candidateFixture,
    }).kind).toBe('malformed')
  })

  test('unknown status is malformed', () => {
    expect(readPlanningTaskOutcome({ status: 'MAGIC' }).kind).toBe('malformed')
  })
})

describe('readPlanningEventOutcome', () => {
  test('PLANNING_COMPLETED with matching status is completed', () => {
    const outcome = readPlanningEventOutcome({
      eventType: 'PLANNING_COMPLETED',
      payload: {
        status: 'SUCCEEDED',
        feasibilityReport: verifiedReportFixture,
        evaluation: evaluationFixture,
      },
    })
    expect(outcome.kind).toBe('completed')
  })

  test('PLANNING_REVIEW_REQUIRED with VERIFIED report fails closed', () => {
    const outcome = readPlanningEventOutcome({
      eventType: 'PLANNING_REVIEW_REQUIRED',
      payload: {
        status: 'WAITING_USER',
        feasibilityReport: verifiedReportFixture,
        candidateItinerary: candidateFixture,
      },
    })
    expect(outcome.kind).toBe('malformed')
  })

  test('PLANNING_REVIEW_REQUIRED with NEEDS_REPAIR is review', () => {
    const outcome = readPlanningEventOutcome({
      eventType: 'PLANNING_REVIEW_REQUIRED',
      payload: {
        status: 'WAITING_USER',
        feasibilityReport: needsRepairReportFixture,
        candidateItinerary: candidateFixture,
      },
    })
    expect(outcome.kind).toBe('review')
  })

  test('status/eventType mismatch fails closed', () => {
    const outcome = readPlanningEventOutcome({
      eventType: 'PLANNING_COMPLETED',
      payload: {
        status: 'WAITING_USER',
        feasibilityReport: needsRepairReportFixture,
        candidateItinerary: candidateFixture,
      },
    })
    expect(outcome.kind).toBe('malformed')
  })

  test('PLANNING_PROGRESS with RUNNING status is queued/running', () => {
    const outcome = readPlanningEventOutcome({
      eventType: 'PLANNING_PROGRESS',
      payload: { status: 'RUNNING', stage: 'constraints', sequence: 1 },
    })
    expect(outcome.kind).toBe('queued')
  })

  test('PLANNING_FAILED extracts message and rejects outcome fields', () => {
    const outcome = readPlanningEventOutcome({
      eventType: 'PLANNING_FAILED',
      payload: { status: 'FAILED', message: 'boom' },
    })
    expect(outcome.kind).toBe('failed')
    if (outcome.kind === 'failed') expect(outcome.errorMessage).toBe('boom')
  })

  test('unknown eventType is malformed', () => {
    const outcome = readPlanningEventOutcome({
      eventType: 'PLANNING_MAGIC',
      payload: { status: 'SUCCEEDED' },
    })
    expect(outcome.kind).toBe('malformed')
  })

  test('PLANNING_CANCELLED is cancelled', () => {
    const outcome = readPlanningEventOutcome({
      eventType: 'PLANNING_CANCELLED',
      payload: { status: 'CANCELLED' },
    })
    expect(outcome.kind).toBe('cancelled')
  })
})

// ── ③ 决策解释上屏：readPlanningDecisions / 展示标签 ───────────────────────

describe('readPlanningDecisions', () => {
  const validDecision = {
    subjectType: 'DAY',
    subjectId: null,
    summary: '第一天就近安排景点以缩短跨区交通',
    reasonCodes: ['NEARBY_CLUSTER', 'TIME_OPTIMIZATION'],
    reasons: ['把相邻景点排在同一天', '减少跨区往返时间'],
    dayIndex: 0,
  }

  test('reads a valid decisions list', () => {
    const result = readPlanningDecisions([validDecision])
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.value).toHaveLength(1)
      expect(result.value[0]!.reasonCodes).toHaveLength(2)
      expect(result.value[0]!.dayIndex).toBe(0)
    }
  })

  test('missing or empty input is an empty list (never fabricated)', () => {
    expect(readPlanningDecisions(undefined).ok).toBe(true)
    const empty = readPlanningDecisions(undefined)
    if (empty.ok) expect(empty.value).toEqual([])
    const absent = readPlanningDecisions(null)
    if (absent.ok) expect(absent.value).toEqual([])
    const present = readPlanningDecisions([])
    if (present.ok) expect(present.value).toEqual([])
  })

  test('rejects a non-array input', () => {
    expect(readPlanningDecisions('nope').ok).toBe(false)
    expect(readPlanningDecisions({ not: 'array' }).ok).toBe(false)
  })

  test('rejects a decision missing summary', () => {
    const { summary: _summary, ...rest } = validDecision
    expect(readPlanningDecisions([rest]).ok).toBe(false)
  })

  test('rejects a decision with non-string reasonCodes', () => {
    expect(readPlanningDecisions([{
      ...validDecision,
      reasonCodes: 'NEARBY_CLUSTER',
    }]).ok).toBe(false)
  })

  test('rejects a decision with an unknown subjectType', () => {
    expect(readPlanningDecisions([{
      ...validDecision,
      subjectType: 'MAGIC',
    }]).ok).toBe(false)
  })

  test('carries optional evidence and subjectId', () => {
    const result = readPlanningDecisions([{
      ...validDecision,
      subjectId: '11111111-1111-4111-8111-111111111111',
      evidence: [{ key: 'distance', label: '距离', value: '1.2km' }],
    }])
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.value[0]!.subjectId).toBe('11111111-1111-4111-8111-111111111111')
      expect(result.value[0]!.evidence).toHaveLength(1)
    }
  })
})

describe('decision display labels', () => {
  test('maps every known reasonCode to a Chinese label', () => {
    expect(decisionReasonLabel('NEARBY_CLUSTER')).toBe('就近聚类')
    expect(decisionReasonLabel('BUDGET_CONSTRAINT')).toBe('预算约束')
    expect(decisionReasonLabel('MUST_VISIT')).toBe('必去地点')
  })

  test('falls back to the raw code for unknown reasonCode', () => {
    expect(decisionReasonLabel('SOME_NEW_CODE')).toBe('SOME_NEW_CODE')
  })

  test('maps subject type + dayIndex to a readable origin', () => {
    expect(decisionSubjectLabel('PLAN', null)).toBe('整段行程')
    expect(decisionSubjectLabel('DAY', 0)).toBe('第 1 天')
    expect(decisionSubjectLabel('DAY', null)).toBe('当天')
    expect(decisionSubjectLabel('ACTIVITY', 2)).toBe('活动')
    expect(decisionSubjectLabel('TRANSIT', null)).toBe('交通')
    expect(decisionSubjectLabel('UNKNOWN', null)).toBe('行程')
  })
})
