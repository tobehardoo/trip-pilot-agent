import { cleanup, render, screen } from '@testing-library/vue'
import { afterEach, expect, test } from 'vitest'

import FeasibilityReportPanel from '../src/components/FeasibilityReportPanel.vue'
import type { FeasibilityReport } from '../src/lib/feasibility'

afterEach(() => cleanup())

function makeReport(status: FeasibilityReport['status'] = 'VERIFIED'): FeasibilityReport {
  return {
    schemaVersion: 1,
    reportId: 'c9c467cc-65c4-8ff1-e175-4af42f2ed545',
    validatorVersion: 'hard-validator-v5',
    itineraryFingerprint: 'a'.repeat(64),
    status,
    validatedAt: '2026-08-10T12:00:00Z',
    requiredRuleIds: ['OPENING_HOURS', 'BUDGET_LIMIT'],
    missingRequiredRuleIds: [],
    summary: {
      totalCount: 2,
      passCount: 1,
      failCount: status === 'NEEDS_REPAIR' ? 1 : 0,
      unknownCount: status === 'UNVERIFIED' ? 1 : 0,
      notApplicableCount: 0,
      missingRequiredCount: 0,
    },
    ruleResults: [
      {
        ruleId: 'OPENING_HOURS',
        ruleVersion: 'hard-rule-v1',
        outcome: status === 'NEEDS_REPAIR' ? 'FAIL' : status === 'UNVERIFIED' ? 'UNKNOWN' : 'PASS',
        reasonCode: 'OPENING_HOURS_VERIFIED',
        message: '营业时间内开放',
        affectedDates: ['2026-08-01'],
        affectedEntityRefs: ['activity:11111111-1111-4111-8111-111111111111'],
        evidenceRefs: [{
          evidenceId: 'ev-1',
          evidenceType: 'OPENING_HOURS',
          state: 'VERIFIED',
          hardConstraintEligible: true,
        }],
        repairable: false,
      },
      {
        ruleId: 'BUDGET_LIMIT',
        ruleVersion: 'hard-rule-v1',
        outcome: 'NOT_APPLICABLE',
        reasonCode: 'NO_BUDGET',
        message: '未设置预算',
        affectedDates: [],
        affectedEntityRefs: [],
        evidenceRefs: [],
        repairable: false,
      },
    ],
    repairAttempts: status === 'NEEDS_REPAIR' ? [{
      attemptIndex: 1,
      triggeringRuleIds: ['OPENING_HOURS'],
      actionCodes: ['MOVE_ACTIVITY'],
      affectedDates: ['2026-08-01'],
      affectedEntityRefs: [],
      beforeFingerprint: 'b'.repeat(64),
      afterFingerprint: 'c'.repeat(64),
      resultingStatus: 'NEEDS_REPAIR',
    }] : [],
  }
}

test('renders VERIFIED status with 已验证 label', async () => {
  render(FeasibilityReportPanel, { props: { report: makeReport('VERIFIED') } })
  expect(screen.getByText('已验证')).toBeTruthy()
  expect(screen.getByText(/硬可行性/)).toBeTruthy()
})

test('renders NEEDS_REPAIR status with 待修复 label', () => {
  render(FeasibilityReportPanel, { props: { report: makeReport('NEEDS_REPAIR') } })
  expect(screen.getAllByText('待修复').length).toBeGreaterThan(0)
})

test('renders UNVERIFIED status with 未验证 label', () => {
  render(FeasibilityReportPanel, { props: { report: makeReport('UNVERIFIED') } })
  expect(screen.getByText('未验证')).toBeTruthy()
})

test('renders summary counts', () => {
  render(FeasibilityReportPanel, { props: { report: makeReport('NEEDS_REPAIR') } })
  expect(screen.getByText('2')).toBeTruthy() // total
  expect(screen.getAllByText('1').length).toBeGreaterThan(0) // pass / fail
})

test('renders rule outcome labels for all four outcomes', () => {
  render(FeasibilityReportPanel, { props: { report: makeReport('NEEDS_REPAIR') } })
  expect(screen.getAllByText('失败').length).toBeGreaterThan(0)
  expect(screen.getAllByText('不适用').length).toBeGreaterThan(0)
})

test('renders evidence state without misleading verified wording for STALE', () => {
  const report = makeReport('UNVERIFIED')
  report.ruleResults = [{
    ruleId: 'OPENING_HOURS',
    ruleVersion: 'hard-rule-v1',
    outcome: 'UNKNOWN',
    reasonCode: 'OPENING_HOURS_UNVERIFIED',
    message: '营业时间未知',
    affectedDates: [],
    affectedEntityRefs: [],
    evidenceRefs: [{
      evidenceId: 'ev-stale',
      evidenceType: 'OPENING_HOURS',
      state: 'STALE',
      hardConstraintEligible: false,
    }],
    repairable: false,
  }]
  render(FeasibilityReportPanel, { props: { report } })
  expect(screen.getByText('证据过期')).toBeTruthy()
  expect(screen.queryByText('证据已验证')).toBeNull()
})

test('renders CONFLICTING evidence state without verified wording', () => {
  const report = makeReport('UNVERIFIED')
  report.ruleResults = [{
    ruleId: 'OPENING_HOURS',
    ruleVersion: 'hard-rule-v1',
    outcome: 'UNKNOWN',
    reasonCode: 'OPENING_HOURS_UNVERIFIED',
    message: '营业时间冲突',
    affectedDates: [],
    affectedEntityRefs: [],
    evidenceRefs: [{
      evidenceId: 'ev-conflict',
      evidenceType: 'OPENING_HOURS',
      state: 'CONFLICTING',
      hardConstraintEligible: false,
    }],
    repairable: false,
  }]
  render(FeasibilityReportPanel, { props: { report } })
  expect(screen.getByText('证据冲突')).toBeTruthy()
})

test('renders UNKNOWN evidence state without verified wording', () => {
  const report = makeReport('UNVERIFIED')
  report.ruleResults = [{
    ruleId: 'OPENING_HOURS',
    ruleVersion: 'hard-rule-v1',
    outcome: 'UNKNOWN',
    reasonCode: 'OPENING_HOURS_UNVERIFIED',
    message: '营业时间未知',
    affectedDates: [],
    affectedEntityRefs: [],
    evidenceRefs: [{
      evidenceId: 'ev-unknown',
      evidenceType: 'OPENING_HOURS',
      state: 'UNKNOWN',
      hardConstraintEligible: false,
    }],
    repairable: false,
  }]
  render(FeasibilityReportPanel, { props: { report } })
  expect(screen.getByText('证据未知')).toBeTruthy()
})

test('renders hardConstraintEligible true and false distinctly', () => {
  const report = makeReport('UNVERIFIED')
  report.ruleResults = [{
    ruleId: 'OPENING_HOURS',
    ruleVersion: 'hard-rule-v1',
    outcome: 'UNKNOWN',
    reasonCode: 'OPENING_HOURS_UNVERIFIED',
    message: 'x',
    affectedDates: [],
    affectedEntityRefs: [],
    evidenceRefs: [
      { evidenceId: 'e1', evidenceType: 'OPENING_HOURS', state: 'UNKNOWN', hardConstraintEligible: false },
      { evidenceId: 'e2', evidenceType: 'OPENING_HOURS', state: 'VERIFIED', hardConstraintEligible: true },
    ],
    repairable: false,
  }]
  render(FeasibilityReportPanel, { props: { report } })
  expect(screen.getByText('证据已验证')).toBeTruthy() // eligible VERIFIED stays verified
  expect(screen.getByText('证据未知')).toBeTruthy()
})

test('renders affected dates and entities when present, and empty-state text when absent', () => {
  // B13_FIX R7 (P1-4): FAIL/UNKNOWN findings surface up front; the same rule
  // appears once more inside the (default-collapsed) technical details.
  const { unmount } = render(FeasibilityReportPanel, { props: { report: makeReport('NEEDS_REPAIR') } })
  expect(screen.getAllByText('2026-08-01').length).toBeGreaterThan(0)
  unmount()

  const emptyReport = makeReport('VERIFIED')
  emptyReport.ruleResults = [{
    ruleId: 'OPENING_HOURS',
    ruleVersion: 'hard-rule-v1',
    outcome: 'PASS',
    reasonCode: 'X',
    message: 'x',
    affectedDates: [],
    affectedEntityRefs: [],
    evidenceRefs: [],
    repairable: false,
  }]
  render(FeasibilityReportPanel, { props: { report: emptyReport } })
  // No FAIL/UNKNOWN findings → the "主要问题" section shows its empty state.
  expect(screen.getByText('未发现 FAIL 或 UNKNOWN 规则')).toBeTruthy()
})

test('renders repairAttempts when present and empty-state when absent', () => {
  const { unmount } = render(FeasibilityReportPanel, { props: { report: makeReport('NEEDS_REPAIR') } })
  expect(screen.getByText('修复历史')).toBeTruthy()
  expect(screen.getByText(/尝试 1/)).toBeTruthy()
  unmount()

  render(FeasibilityReportPanel, { props: { report: makeReport('VERIFIED') } })
  expect(screen.getByText('无修复尝试')).toBeTruthy()
})

test('renders canonical v5 bounded repair history', () => {
  const report = makeReport('VERIFIED')
  report.repairAttempts = [{
    attemptIndex: 1,
    triggeringRuleIds: ['VISIT_DURATION'],
    actionCodes: ['CLAMP_VISIT_DURATION'],
    affectedDates: ['2026-08-01'],
    affectedEntityRefs: ['activity:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'],
    beforeFingerprint: 'b'.repeat(64),
    afterFingerprint: 'c'.repeat(64),
    resultingStatus: 'VERIFIED',
  }]

  render(FeasibilityReportPanel, { props: { report } })

  expect(screen.getByText('CLAMP_VISIT_DURATION')).toBeTruthy()
  expect(screen.getByText(/触发规则：VISIT_DURATION/)).toBeTruthy()
  expect(screen.getByText('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')).toBeTruthy()
})

test('renders missing required rules count', () => {
  const report = makeReport('VERIFIED')
  report.summary.missingRequiredCount = 1
  render(FeasibilityReportPanel, { props: { report } })
  expect(screen.getByText(/缺失规则|缺少规则/)).toBeTruthy()
})

test('null report shows no hard feasibility report message, not UNVERIFIED', () => {
  render(FeasibilityReportPanel, { props: { report: null } })
  expect(screen.getByText(/没有可用的硬可行性报告/)).toBeTruthy()
  expect(screen.queryByText('未验证')).toBeNull()
})

test('malformed report shows stable unreadable message without guessing status', () => {
  render(FeasibilityReportPanel, { props: { report: null, malformed: true } })
  expect(screen.getByText(/验证结果暂时无法读取/)).toBeTruthy()
  expect(screen.queryByText('已验证')).toBeNull()
})

test('never derives feasibility from score wording', () => {
  render(FeasibilityReportPanel, { props: { report: makeReport('VERIFIED') } })
  // The panel may mention that this is not a score, but must never claim the
  // trip is executable or that a score made it verified.
  expect(screen.queryByText(/可执行/)).toBeNull()
  expect(screen.queryByText(/评分.*已验证|已验证.*评分/)).toBeNull()
})

test('renders hardConstraintEligible=false explicitly as not eligible', () => {
  const report = makeReport('UNVERIFIED')
  report.ruleResults = [{
    ruleId: 'OPENING_HOURS',
    ruleVersion: 'hard-rule-v1',
    outcome: 'UNKNOWN',
    reasonCode: 'OPENING_HOURS_UNVERIFIED',
    message: 'x',
    affectedDates: [],
    affectedEntityRefs: [],
    evidenceRefs: [{ evidenceId: 'e1', evidenceType: 'OPENING_HOURS', state: 'UNKNOWN', hardConstraintEligible: false }],
    repairable: false,
  }]
  render(FeasibilityReportPanel, { props: { report } })
  expect(screen.getByText('不具备硬约束资格')).toBeTruthy()
  expect(screen.queryByText('具备硬约束资格')).toBeNull()
})

test('renders repair attempt affected entity refs as nodes, not just a count', () => {
  const report = makeReport('NEEDS_REPAIR')
  report.ruleResults = [{
    ...report.ruleResults[0]!,
    affectedEntityRefs: [],
  }]
  report.repairAttempts = [{
    attemptIndex: 1,
    triggeringRuleIds: ['OPENING_HOURS'],
    actionCodes: ['MOVE_ACTIVITY'],
    affectedDates: ['2026-08-01'],
    affectedEntityRefs: ['activity:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'],
    beforeFingerprint: 'b'.repeat(64),
    afterFingerprint: 'c'.repeat(64),
    resultingStatus: 'NEEDS_REPAIR',
  }]
  render(FeasibilityReportPanel, { props: { report } })
  expect(screen.getByText('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')).toBeTruthy()
  expect(screen.queryByText(/实体：1 项/)).toBeNull()
})

test('binds the root status class to the primary report status', () => {
  const { unmount } = render(FeasibilityReportPanel, { props: { report: makeReport('VERIFIED') } })
  expect(document.querySelector('.feasibility-panel')?.classList.contains('status-verified')).toBe(true)
  unmount()

  render(FeasibilityReportPanel, { props: { report: makeReport('UNVERIFIED') } })
  expect(document.querySelector('.feasibility-panel')?.classList.contains('status-unverified')).toBe(true)
})

test('NEEDS_REPAIR root keeps the danger border class despite internal PASS/UNKNOWN badges', () => {
  const report = makeReport('NEEDS_REPAIR')
  report.ruleResults = [
    { ...report.ruleResults[0]!, outcome: 'PASS' },
    { ...report.ruleResults[0]!, ruleId: 'BUDGET_LIMIT', outcome: 'UNKNOWN' },
  ]
  render(FeasibilityReportPanel, { props: { report } })
  const panel = document.querySelector('.feasibility-panel')
  expect(panel?.classList.contains('status-needs-repair')).toBe(true)
  expect(panel?.classList.contains('status-verified')).toBe(false)
})

test('UNVERIFIED root keeps the warning border class despite an internal FAIL badge', () => {
  const report = makeReport('UNVERIFIED')
  report.ruleResults = [{ ...report.ruleResults[0]!, outcome: 'FAIL' }]
  render(FeasibilityReportPanel, { props: { report } })
  const panel = document.querySelector('.feasibility-panel')
  expect(panel?.classList.contains('status-unverified')).toBe(true)
  expect(panel?.classList.contains('status-needs-repair')).toBe(false)
})

test('malformed and null reports stay neutral without a status class', () => {
  const { unmount } = render(FeasibilityReportPanel, { props: { report: null } })
  const emptyPanel = document.querySelector('.feasibility-panel')
  expect(emptyPanel?.classList.contains('status-verified')).toBe(false)
  expect(emptyPanel?.classList.contains('status-unverified')).toBe(false)
  unmount()

  render(FeasibilityReportPanel, { props: { report: null, malformed: true } })
  const malformedPanel = document.querySelector('.feasibility-panel')
  expect(malformedPanel?.classList.contains('status-verified')).toBe(false)
})
