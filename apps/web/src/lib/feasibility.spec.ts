import { describe, expect, it } from 'vitest'

import { decisionReasonLabel, readPlanEvaluation } from './feasibility'

describe('decisionReasonLabel', () => {
  it('maps the M0 evidence reason code to a Chinese label', () => {
    expect(decisionReasonLabel('EVIDENCE_STRENGTH')).toBe('证据充分度')
    expect(decisionReasonLabel('INTEREST_MATCH')).toBe('偏好匹配')
  })

  it('falls back to the raw code for unknown reason codes', () => {
    expect(decisionReasonLabel('UNKNOWN_NEW_CODE')).toBe('UNKNOWN_NEW_CODE')
  })
})

describe('readPlanEvaluation', () => {
  it('accepts the evidence strength dimension and disclosure decision', () => {
    const input = {
      schemaVersion: 2,
      evaluatorVersion: 'rule-v6',
      feasible: true,
      overallScore: 90,
      dimensions: {
        constraintSatisfaction: 100,
        timeFeasibility: 100,
        budgetFit: 100,
        routeEfficiency: 80,
        interestMatch: 100,
        evidenceStrength: 80,
      },
      warnings: [],
      decisions: [
        {
          subjectType: 'PLAN',
          subjectId: null,
          summary: '基于多源证据融合评估的充分度',
          reasonCodes: ['EVIDENCE_STRENGTH'],
          reasons: ['证据充分度评价 80/100'],
          constraintRefs: [],
          evidence: [{ key: 'evidence_strength', label: '证据充分度', value: '80' }],
          dayIndex: null,
        },
      ],
      summary: '行程整体质量 90/100。',
      evaluatedAt: '2026-09-01T00:00:00Z',
    }

    const result = readPlanEvaluation(input)

    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.value.dimensions.evidenceStrength).toBe(80)
      expect(result.value.decisions[0].reasonCodes).toContain('EVIDENCE_STRENGTH')
    }
  })

  it('accepts a legacy plan evaluation without the evidence dimension', () => {
    const input = {
      schemaVersion: 1,
      evaluatorVersion: 'rule-v1',
      feasible: true,
      overallScore: 90,
      dimensions: {
        constraintSatisfaction: 100,
        timeFeasibility: 100,
        budgetFit: 100,
        routeEfficiency: 80,
        interestMatch: 100,
      },
      warnings: [],
      decisions: [],
      summary: 'legacy',
      evaluatedAt: '2026-09-01T00:00:00Z',
    }

    const result = readPlanEvaluation(input)

    expect(result.ok).toBe(true)
  })
})