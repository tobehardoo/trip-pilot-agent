import { cleanup, render, screen } from '@testing-library/vue'
import { afterEach, describe, expect, test } from 'vitest'

import FeasibilityReportPanel from '../src/components/FeasibilityReportPanel.vue'
import type { FeasibilityReport } from '../src/lib/feasibility'

afterEach(() => cleanup())

function makeReport(status: 'VERIFIED' | 'NEEDS_REPAIR' | 'UNVERIFIED'): FeasibilityReport {
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
      passCount: status === 'VERIFIED' ? 1 : 0,
      failCount: status === 'NEEDS_REPAIR' ? 1 : 0,
      unknownCount: status === 'UNVERIFIED' ? 1 : 0,
      notApplicableCount: 0,
      missingRequiredCount: 0,
    },
    ruleResults: status === 'VERIFIED'
      ? [{ ruleId: 'OPENING_HOURS', ruleVersion: 'hard-rule-v1', outcome: 'PASS', reasonCode: 'X', message: 'raw english', affectedDates: [], affectedEntityRefs: [], evidenceRefs: [], repairable: false }]
      : [{ ruleId: 'OPENING_HOURS', ruleVersion: 'hard-rule-v1', outcome: status === 'UNVERIFIED' ? 'UNKNOWN' : 'FAIL', reasonCode: 'X', message: 'raw english', affectedDates: [], affectedEntityRefs: [], evidenceRefs: [], repairable: false }],
    repairAttempts: [],
  }
}

describe('B15 user-facing saved itinerary validation', () => {
  test('VERIFIED shows 行程已验证并保存 with 已保存 badge and auto-save note', () => {
    render(FeasibilityReportPanel, { props: { report: makeReport('VERIFIED') } })
    expect(screen.getByText('行程已验证并保存')).toBeTruthy()
    expect(screen.getByText('已保存')).toBeTruthy()
    expect(screen.getByText(/行程已通过全部检查并保存/)).toBeTruthy()
  })

  test('never renders Feasibility label or 硬可行性验证 title', () => {
    render(FeasibilityReportPanel, { props: { report: makeReport('VERIFIED') } })
    expect(screen.queryByText(/Feasibility/i)).toBeNull()
    expect(screen.queryByText(/硬可行性验证/)).toBeNull()
  })

  test('never renders rule statistics console', () => {
    render(FeasibilityReportPanel, { props: { report: makeReport('VERIFIED') } })
    expect(screen.queryByText(/规则总数/)).toBeNull()
    expect(screen.queryByText(/^通过$/)).toBeNull()
    expect(screen.queryByText(/^失败$/)).toBeNull()
    expect(screen.queryByText(/^未知$/)).toBeNull()
    expect(screen.queryByText(/^不适用$/)).toBeNull()
    expect(screen.queryByText(/缺失规则/)).toBeNull()
  })

  test('never renders validatorVersion / reasonCode / ruleId / schemaVersion / UUID', () => {
    render(FeasibilityReportPanel, { props: { report: makeReport('VERIFIED') } })
    expect(screen.queryByText(/hard-validator/i)).toBeNull()
    expect(screen.queryByText(/schemaVersion/i)).toBeNull()
    expect(screen.queryByText(/c9c467cc/i)).toBeNull()
    expect(screen.queryByText(/hard-rule-v1/)).toBeNull()
    expect(screen.queryByText(/raw english/)).toBeNull()
  })

  test('never offers technical details / validation details toggles', () => {
    render(FeasibilityReportPanel, { props: { report: makeReport('VERIFIED') } })
    expect(screen.queryByTestId('feasibility-technical-toggle')).toBeNull()
    expect(screen.queryByText(/查看技术详情/)).toBeNull()
    expect(screen.queryByText(/修复历史/)).toBeNull()
    expect(screen.queryByText(/规则明细/)).toBeNull()
  })

  test('null report shows neutral message, not UNVERIFIED', () => {
    render(FeasibilityReportPanel, { props: { report: null } })
    expect(screen.getByText(/暂无行程验证结果/)).toBeTruthy()
    expect(screen.queryByText('部分信息待核实')).toBeNull()
  })

  test('malformed report fails closed with safe message', () => {
    render(FeasibilityReportPanel, { props: { report: null, malformed: true } })
    expect(screen.getByText(/行程验证结果暂时无法读取/)).toBeTruthy()
  })

  test('B16 UNVERIFIED blocker-free report shows saved-with-warnings state', () => {
    // B16: Information Missing != Planning Failed.  A saved UNVERIFIED report
    // (no FAIL, no missing required rule) renders the PASS_WITH_WARNINGS
    // state: the itinerary was saved, but some facts still need confirmation.
    render(FeasibilityReportPanel, { props: { report: makeReport('UNVERIFIED') } })
    expect(screen.queryByText('行程已验证并保存')).toBeNull()
    expect(screen.getByText('行程已生成，部分信息仍待确认')).toBeTruthy()
    expect(screen.getByText('已保存')).toBeTruthy()
    expect(screen.getByText(/出发前请自行确认/)).toBeTruthy()
  })

  test('NEEDS_REPAIR blocker report never renders through this panel (defensive)', () => {
    // A blocker (FAIL present) can never be a saved completion; defensive:
    // blocker input must not fabricate a saved state.
    render(FeasibilityReportPanel, { props: { report: makeReport('NEEDS_REPAIR') } })
    expect(screen.queryByText('行程已验证并保存')).toBeNull()
    expect(screen.queryByText('行程已生成，部分信息仍待确认')).toBeNull()
    expect(screen.queryByText('已保存')).toBeNull()
  })
})
