import { cleanup, render, screen } from '@testing-library/vue'
import { afterEach, describe, expect, test } from 'vitest'

import PlanningReviewPanel from '../src/components/PlanningReviewPanel.vue'
import type { CandidateItinerary, FeasibilityReport, FeasibilityRuleResult } from '../src/lib/feasibility'

afterEach(() => cleanup())

function makeReport(status: 'NEEDS_REPAIR' | 'UNVERIFIED', rules: FeasibilityRuleResult[]): FeasibilityReport {
  const failCount = rules.filter((r) => r.outcome === 'FAIL').length
  const unknownCount = rules.filter((r) => r.outcome === 'UNKNOWN').length
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
      totalCount: rules.length,
      passCount: rules.length - failCount - unknownCount,
      failCount,
      unknownCount,
      notApplicableCount: 0,
      missingRequiredCount: 0,
    },
    ruleResults: rules,
    repairAttempts: [],
  }
}

function ruleResult(partial: Partial<FeasibilityRuleResult> & { ruleId: string; outcome: FeasibilityRuleResult['outcome'] }): FeasibilityRuleResult {
  return {
    ruleVersion: 'hard-rule-v1',
    reasonCode: 'X',
    message: 'raw english message',
    affectedDates: [],
    affectedEntityRefs: [],
    evidenceRefs: [],
    repairable: false,
    ...partial,
  }
}

function makeCandidate(days = 1): CandidateItinerary {
  const dayActivities = Array.from({ length: days }, (_, d) => ({
    activityId: `00000000-0000-4000-8000-00000000000${d}`,
    title: `地点${d + 1}`,
    startTime: '2026-08-17T00:45:00Z',
    endTime: '2026-08-17T10:49:00Z',
    estimatedCost: 0,
    source: 'DEMO',
    providerPoiId: null,
    coordinates: null,
    address: null,
    typeCode: null,
    typeName: null,
    kind: null,
    timeFixed: null,
  }))
  return {
    title: '北京行程建议',
    days: Array.from({ length: days }, (_, d) => ({
      date: `2026-08-1${7 + d}`,
      dayType: null,
      activities: [dayActivities[d]],
      transitLegs: [],
    })),
    estimatedTotalCost: 500,
  }
}

function makeCandidateWithTransit(): CandidateItinerary {
  return {
    title: '北京行程建议',
    days: [{
      date: '2026-08-17',
      dayType: null,
      activities: [
        {
          activityId: '00000000-0000-4000-8000-000000000001',
          title: '故宫博物院',
          startTime: '2026-08-17T00:45:00Z',
          endTime: '2026-08-17T03:00:00Z',
          estimatedCost: 60,
          source: 'AMAP',
          providerPoiId: null,
          coordinates: null,
          address: null,
          typeCode: null,
          typeName: null,
          kind: null,
          timeFixed: null,
        },
        {
          activityId: '00000000-0000-4000-8000-000000000002',
          title: '奥华餐厅',
          startTime: '2026-08-17T05:00:00Z',
          endTime: '2026-08-17T06:00:00Z',
          estimatedCost: 120,
          source: 'AMAP',
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
        mode: 'TAXI',
        distanceMeters: 5000,
        durationSeconds: 1500,
        provider: 'AMAP',
        estimated: true,
        polyline: [],
        estimatedCost: null,
        costSource: null,
      }],
    }],
    estimatedTotalCost: 500,
  }
}

// ── R1: internal content leakage ──────────────────────────────────────────

describe('R1 internal content leakage', () => {
  test('never renders REVIEW / FEASIBILITY / ITINERARY labels', () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' })]),
        candidate: makeCandidate(),
        currentItinerary: null,
      },
    })
    expect(screen.queryByText(/REVIEW/i)).toBeNull()
    expect(screen.queryByText(/FEASIBILITY/i)).toBeNull()
    expect(screen.queryByText(/ITINERARY/i)).toBeNull()
  })

  test('never renders validator version / reasonCode / ruleId / schemaVersion / UUID', () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' })]),
        candidate: makeCandidate(),
        currentItinerary: null,
      },
    })
    expect(screen.queryByText(/hard-validator/i)).toBeNull()
    expect(screen.queryByText(/reasonCode|reason-code/i)).toBeNull()
    expect(screen.queryByText(/schemaVersion/i)).toBeNull()
    expect(screen.queryByText(/c9c467cc/i)).toBeNull()
    expect(screen.queryByText(/00000000-0000-4000-8000/i)).toBeNull()
  })

  test('never renders raw english rule message or rule statistics console', () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [
          ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN', message: 'Opening hours unverified for venues' }),
        ]),
        candidate: makeCandidate(),
        currentItinerary: null,
      },
    })
    expect(screen.queryByText(/Opening hours unverified/)).toBeNull()
    expect(screen.queryByText(/规则总数/)).toBeNull()
    expect(screen.queryByText(/^通过$/)).toBeNull()
    expect(screen.queryByText(/^失败$/)).toBeNull()
    expect(screen.queryByText(/^不适用$/)).toBeNull()
    expect(screen.queryByText(/缺失规则/)).toBeNull()
  })

  test('does not offer a technical details toggle', () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' })]),
        candidate: makeCandidate(),
        currentItinerary: null,
      },
    })
    expect(screen.queryByTestId('validation-details-toggle')).toBeNull()
    expect(screen.queryByTestId('feasibility-technical-toggle')).toBeNull()
    expect(screen.queryByText(/查看验证详情/)).toBeNull()
    expect(screen.queryByText(/查看技术详情/)).toBeNull()
  })

  test('keeps necessary proper nouns like place names', () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' })]),
        candidate: makeCandidateWithTransit(),
        currentItinerary: null,
      },
    })
    expect(screen.getByText(/故宫博物院/)).toBeTruthy()
    expect(screen.getByText(/奥华餐厅/)).toBeTruthy()
  })
})

// ── R2: status and actions ────────────────────────────────────────────────

describe('R2 status and actions', () => {
  test('UNVERIFIED shows Chinese title, badge, description and two actions', () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' })]),
        candidate: makeCandidate(),
        currentItinerary: null,
      },
    })
    expect(screen.getByText('方案还需要完善')).toBeTruthy()
    expect(screen.getByText('部分信息待核实')).toBeTruthy()
    expect(screen.getByText(/已生成一份预览方案，但部分信息暂时无法核实，因此还不能保存/)).toBeTruthy()
    expect(screen.getByText('修改要求')).toBeTruthy()
    expect(screen.getByText('放弃本方案')).toBeTruthy()
  })

  test('NEEDS_REPAIR shows Chinese title, badge, description and two actions', () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('NEEDS_REPAIR', [ruleResult({ ruleId: 'ACTIVITY_OVERLAP', outcome: 'FAIL' })]),
        candidate: makeCandidate(),
        currentItinerary: null,
      },
    })
    expect(screen.getByText('方案需要调整')).toBeTruthy()
    expect(screen.getByText('存在需要处理的问题')).toBeTruthy()
    expect(screen.getByText(/当前安排存在冲突，请修改旅行要求后重新规划/)).toBeTruthy()
    expect(screen.getByText('修改要求')).toBeTruthy()
    expect(screen.getByText('放弃本方案')).toBeTruthy()
  })

  test('never offers confirm / accept / save-candidate buttons', () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('NEEDS_REPAIR', [ruleResult({ ruleId: 'ACTIVITY_OVERLAP', outcome: 'FAIL' })]),
        candidate: makeCandidate(),
        currentItinerary: null,
      },
    })
    expect(screen.queryByText(/确认/)).toBeNull()
    expect(screen.queryByText(/接受/)).toBeNull()
    expect(screen.queryByText(/仍然保存/)).toBeNull()
    expect(screen.queryByText(/保存候选/)).toBeNull()
    expect(screen.queryByText(/待确认/)).toBeNull()
    expect(screen.queryByText(/候选待确认/)).toBeNull()
    expect(screen.queryByText(/规划需要确认/)).toBeNull()
  })

  test('malformed report fails closed with safe Chinese message', () => {
    render(PlanningReviewPanel, {
      props: {
        report: null,
        malformedReport: true,
        candidate: makeCandidate(),
        currentItinerary: null,
      },
    })
    expect(screen.getByText('暂时无法读取规划结果')).toBeTruthy()
    expect(screen.getByText('结果异常')).toBeTruthy()
    expect(screen.getByText(/系统无法安全读取本次规划结果，请重新规划/)).toBeTruthy()
  })

  test('修改要求 emits edit request without creating a task', async () => {
    const { emitted } = render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' })]),
        candidate: makeCandidate(),
        currentItinerary: null,
      },
    })
    await screen.getByTestId('edit-requirements').click()
    expect(emitted('edit')).toHaveLength(1)
    expect(emitted('start')).toBeUndefined()
  })

  test('evidence gaps offer an explicit verification path without claiming they passed', async () => {
    const { emitted } = render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [
          ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' }),
          ruleResult({ ruleId: 'VISIT_DURATION', outcome: 'UNKNOWN' }),
        ]),
        candidate: makeCandidate(),
        currentItinerary: null,
      },
    })

    expect(screen.getByText(/可先同步城市情报或补充可信攻略/)).toBeTruthy()
    expect(screen.getByText(/同步不会自动把未核实信息判为通过/)).toBeTruthy()
    await screen.getByTestId('verify-evidence').click()
    expect(emitted('verify')).toHaveLength(1)
    expect(screen.queryByText(/已经核实|行程已验证并保存/)).toBeNull()
  })

  test('放弃本方案 emits abandon and keeps saved itinerary wording', async () => {
    const { emitted } = render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' })]),
        candidate: makeCandidate(),
        currentItinerary: null,
      },
    })
    await screen.getByTestId('abandon-candidate').click()
    expect(emitted('abandon')).toHaveLength(1)
    expect(screen.getByText(/修改并保存要求后，可以重新开始规划/)).toBeTruthy()
  })

  test('abandon disables while busy and repeats safely', async () => {
    const { emitted } = render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' })]),
        candidate: makeCandidate(),
        currentItinerary: null,
        abandonBusy: true,
      },
    })
    expect((screen.getByTestId('abandon-candidate') as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByText('正在放弃…')).toBeTruthy()
    expect(emitted('abandon')).toBeUndefined()
  })

  test('action buttons meet the 44px minimum touch height (B15.1 R3)', () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' })]),
        candidate: makeCandidate(),
        currentItinerary: null,
      },
    })
    const edit = screen.getByTestId('edit-requirements') as HTMLButtonElement
    const abandon = screen.getByTestId('abandon-candidate') as HTMLButtonElement
    // h-12 = 48px >= 44px; the review actions must never regress below the
    // touch-target recommendation (B15 acceptance Minor 2).
    expect(edit.className).toMatch(/h-12/)
    expect(abandon.className).toMatch(/h-12/)
  })
})

// ── R3: Chinese issue summaries ───────────────────────────────────────────

describe('R3 issue summary', () => {
  test('UNVERIFIED issue section titled 待核实信息（N） with count', () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [ruleResult({
          ruleId: 'OPENING_HOURS',
          outcome: 'UNKNOWN',
          affectedEntityRefs: ['activity:00000000-0000-4000-8000-000000000001'],
        })]),
        candidate: makeCandidate(),
        currentItinerary: null,
      },
    })
    expect(screen.getByText('待核实信息（1）')).toBeTruthy()
    expect(screen.getByText('1个地点的营业时间采用系统建议，建议出发前确认')).toBeTruthy()
  })

  test('NEEDS_REPAIR issue section titled 需要调整（N） with summary', () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('NEEDS_REPAIR', [ruleResult({ ruleId: 'ACTIVITY_OVERLAP', outcome: 'FAIL' })]),
        candidate: makeCandidate(),
        currentItinerary: null,
      },
    })
    expect(screen.getByText('需要调整（1）')).toBeTruthy()
    expect(screen.getByText('部分活动时间发生重叠')).toBeTruthy()
  })

  test('only PASS/NOT_APPLICABLE rules render no issue section', () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [
          ruleResult({ ruleId: 'BUDGET_LIMIT', outcome: 'PASS' }),
          ruleResult({ ruleId: 'MEAL_WINDOW', outcome: 'NOT_APPLICABLE' }),
        ]),
        candidate: makeCandidate(),
        currentItinerary: null,
      },
    })
    expect(screen.queryByText(/待核实信息/)).toBeNull()
    expect(screen.queryByText(/需要调整/)).toBeNull()
  })

  test('renders Chinese dates in issues', () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('NEEDS_REPAIR', [ruleResult({
          ruleId: 'OPENING_HOURS',
          outcome: 'FAIL',
          affectedDates: ['2026-08-17', '2026-08-18'],
        })]),
        candidate: makeCandidate(),
        currentItinerary: null,
      },
    })
    expect(screen.getByText('8月17日、8月18日')).toBeTruthy()
    expect(screen.queryByText('2026-08-17')).toBeNull()
  })

  test('more than 3 issues collapse to 3 with 查看全部 N 项', () => {
    const rules = [
      ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' }),
      ruleResult({ ruleId: 'VISIT_DURATION', outcome: 'UNKNOWN' }),
      ruleResult({ ruleId: 'MEAL_WINDOW', outcome: 'UNKNOWN' }),
      ruleResult({ ruleId: 'BUDGET_LIMIT', outcome: 'UNKNOWN' }),
      ruleResult({ ruleId: 'DUPLICATE_POI', outcome: 'UNKNOWN' }),
    ]
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', rules),
        candidate: makeCandidate(),
        currentItinerary: null,
      },
    })
    expect(screen.getByText('待核实信息（5）')).toBeTruthy()
    expect(screen.getByText('查看全部 5 项')).toBeTruthy()
    // collapsed: exactly 3 issue cards rendered
    const issueCards = document.querySelectorAll('[data-testid^="issue-card-"]')
    expect(issueCards.length).toBe(3)
  })

  test('展开全部 shows all summaries', async () => {
    const rules = [
      ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' }),
      ruleResult({ ruleId: 'VISIT_DURATION', outcome: 'UNKNOWN' }),
      ruleResult({ ruleId: 'MEAL_WINDOW', outcome: 'UNKNOWN' }),
      ruleResult({ ruleId: 'BUDGET_LIMIT', outcome: 'UNKNOWN' }),
      ruleResult({ ruleId: 'DUPLICATE_POI', outcome: 'UNKNOWN' }),
    ]
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', rules),
        candidate: makeCandidate(),
        currentItinerary: null,
      },
    })
    await screen.getByText('查看全部 5 项').click()
    const issueCards = document.querySelectorAll('[data-testid^="issue-card-"]')
    expect(issueCards.length).toBe(5)
  })

  test('unknown rule id degrades without leaking code', () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('NEEDS_REPAIR', [ruleResult({ ruleId: 'INTERNAL_UNKNOWN_RULE', outcome: 'FAIL' })]),
        candidate: makeCandidate(),
        currentItinerary: null,
      },
    })
    expect(screen.getByText('该项安排需要调整')).toBeTruthy()
    expect(screen.queryByText(/INTERNAL_UNKNOWN_RULE/)).toBeNull()
  })
})

// ── R4: candidate preview noise reduction ─────────────────────────────────

describe('R4 preview plan', () => {
  test('preview section titled 预览方案 without REVIEW or 真实地点', () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' })]),
        candidate: makeCandidate(),
        currentItinerary: null,
      },
    })
    expect(screen.getByText('预览方案')).toBeTruthy()
    expect(screen.queryByText(/REVIEW/i)).toBeNull()
    expect(screen.queryByText(/真实地点/)).toBeNull()
  })

  test('day card is collapsed by default showing date, count and time range', () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' })]),
        candidate: makeCandidate(),
        currentItinerary: null,
      },
    })
    expect(screen.getByText('8月17日 · 1项安排 · 08:45–18:49')).toBeTruthy()
    expect(screen.getByText('地点1')).toBeTruthy()
  })

  test('day card expands to full activities with costs and times', async () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' })]),
        candidate: makeCandidateWithTransit(),
        currentItinerary: null,
      },
    })
    const toggle = screen.getByTestId('candidate-day-toggle-2026-08-17')
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    await toggle.click()
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByText('故宫博物院')).toBeTruthy()
    expect(screen.getByText('奥华餐厅')).toBeTruthy()
    expect(screen.getByText('¥60')).toBeTruthy()
    expect(screen.getByText('¥120')).toBeTruthy()
  })

  test('transit shows summary by default and detail in nested expandable', async () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' })]),
        candidate: makeCandidateWithTransit(),
        currentItinerary: null,
      },
    })
    // transit summary visible on collapsed card
    expect(screen.getByText(/当天交通：1段 · 约25 分钟/)).toBeTruthy()
    await screen.getByTestId('candidate-day-toggle-2026-08-17').click()
    const legToggle = screen.getByTestId('candidate-leg-toggle-2026-08-17-0')
    expect(legToggle.getAttribute('aria-expanded')).toBe('false')
    await legToggle.click()
    expect(legToggle.getAttribute('aria-expanded')).toBe('true')
    // detail line shows full leg info
    expect(screen.getByText(/故宫博物院 → 奥华餐厅 · 打车（估算） · 25 分钟 · 5.0 公里/)).toBeTruthy()
  })

  test('keyboard operable: Enter toggles day card', async () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' })]),
        candidate: makeCandidate(),
        currentItinerary: null,
      },
    })
    const toggle = screen.getByTestId('candidate-day-toggle-2026-08-17')
    toggle.focus()
    toggle.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await new Promise((r) => setTimeout(r, 0))
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
  })

  test('highlight date expands and scrolls to the matching candidate day', async () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' })]),
        candidate: makeCandidate(2),
        highlightDate: '2026-08-18',
        currentItinerary: null,
      },
    })
    const toggle = screen.getByTestId('candidate-day-toggle-2026-08-18')
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByText('8月18日 · 1项安排 · 08:45–18:49')).toBeTruthy()
  })

  test('highlight only touches candidate day, never the saved itinerary', () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' })]),
        candidate: makeCandidate(1),
        highlightDate: '2026-08-17',
        currentItinerary: {
          title: '已保存行程',
          estimatedTotalCost: 800,
          days: [{ date: '2026-08-17', activities: [{ id: 'f-1', title: '已保存活动' }] }],
        },
      },
    })
    // candidate day highlighted/expanded; saved itinerary heading untouched
    expect(screen.getByTestId('candidate-day-toggle-2026-08-17').getAttribute('aria-expanded')).toBe('true')
    expect(screen.getAllByText('已保存行程').length).toBeGreaterThanOrEqual(1)
    // candidate title differs from saved title — both independent
    expect(screen.getByText('北京行程建议')).toBeTruthy()
  })
})

// ── R5: saved itinerary empty / present states ────────────────────────────

describe('R5 saved itinerary', () => {
  test('no saved itinerary shows lightweight auto-save note only', () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' })]),
        candidate: makeCandidate(),
        currentItinerary: null,
      },
    })
    expect(screen.getByText('方案验证通过后会自动保存为正式行程。')).toBeTruthy()
    expect(screen.queryByText(/当前正式版本/)).toBeNull()
    expect(screen.queryByText(/当前尚无正式版本/)).toBeNull()
    expect(screen.queryByText(/与当前正式版本对照/)).toBeNull()
    expect(screen.queryByText(/与已保存行程相比/)).toBeNull()
  })

  test('saved itinerary present uses 已保存行程 and comparison title', () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' })]),
        candidate: makeCandidate(),
        currentItinerary: {
          title: '已保存行程',
          estimatedTotalCost: 800,
          days: [{ date: '2026-08-17', activities: [{ id: 'f-1', title: '已保存活动' }] }],
        },
      },
    })
    expect(screen.getAllByText('已保存行程').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('与已保存行程相比')).toBeTruthy()
    expect(screen.queryByText(/正式版本/)).toBeNull()
  })

  test('comparison only renders reliable user-readable diffs', () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' })]),
        candidate: makeCandidate(1),
        currentItinerary: {
          title: '已保存行程',
          estimatedTotalCost: 800,
          days: [{ date: '2026-08-17', activities: [{ id: 'f-1', title: '已保存活动' }] }],
        },
      },
    })
    expect(screen.getByText(/新增1个地点/)).toBeTruthy()
  })

  test('abandon keeps saved itinerary (saved section still renders)', () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' })]),
        candidate: makeCandidate(),
        currentItinerary: {
          title: '已保存行程',
          estimatedTotalCost: 800,
          days: [{ date: '2026-08-17', activities: [{ id: 'f-1', title: '已保存活动' }] }],
        },
      },
    })
    expect(screen.getAllByText('已保存行程').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('放弃本方案')).toBeTruthy()
  })

  test('malformed candidate shows safe message', () => {
    render(PlanningReviewPanel, {
      props: {
        report: makeReport('UNVERIFIED', [ruleResult({ ruleId: 'OPENING_HOURS', outcome: 'UNKNOWN' })]),
        candidate: { not: 'an itinerary' },
        currentItinerary: null,
      },
    })
    expect(screen.getByText(/预览方案暂时无法读取/)).toBeTruthy()
  })
})
