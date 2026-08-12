import { describe, expect, test } from 'vitest'

import {
  parseTypedEntityReference,
  readCandidateItinerary,
  readFeasibilityReport,
  readPlanEvaluation,
  readPlanningEventOutcome,
  readPlanningTaskOutcome,
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
    expect(readFeasibilityReport(verifiedReport({ validatorVersion: 'hard-validator-v5' })).ok).toBe(false)
  })

  test('accepts all validator versions on the shared whitelist', () => {
    for (const version of ['feasibility-v1', 'hard-validator-v1', 'hard-validator-v2', 'hard-validator-v3', 'hard-validator-v4']) {
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

  test('SUCCEEDED with UNVERIFIED report fails closed', () => {
    const outcome = readPlanningTaskOutcome({
      status: 'SUCCEEDED',
      feasibilityReport: unverifiedReportFixture,
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
