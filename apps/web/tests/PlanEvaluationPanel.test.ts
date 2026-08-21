import { cleanup, fireEvent, render } from '@testing-library/vue'
import { afterEach, expect, test } from 'vitest'

import PlanEvaluationPanel from '../src/components/PlanEvaluationPanel.vue'
import type { PlanEvaluation } from '../src/lib/api'

afterEach(() => cleanup())

const evaluation: PlanEvaluation = {
  schemaVersion: 1,
  evaluatorVersion: 'rule-v1',
  feasible: true,
  overallScore: 68,
  dimensions: {
    constraintSatisfaction: 100,
    timeFeasibility: 67,
    budgetFit: 88,
    routeEfficiency: 65,
    interestMatch: 80,
  },
  warnings: [
    {
      code: 'ESTIMATED_TRANSIT',
      severity: 'INFO',
      message: '此路段使用估算路线',
      entityType: 'TRANSIT',
    },
    {
      code: 'HIGH_DAILY_LOAD',
      severity: 'WARNING',
      message: '第 1 天有 5 个活动',
      entityType: 'DAY',
    },
    {
      code: 'LOW_TIME_BUFFER',
      severity: 'CRITICAL',
      message: '活动间缓冲时间严重不足',
      entityType: 'TRANSIT',
    },
  ],
  decisions: [{
    subjectType: 'TRANSIT',
    summary: '此路段使用 Demo 数据，因为真实路线服务不可用',
    reasonCodes: ['PROVIDER_CONSTRAINT'],
    reasons: ['Provider 错误: TIMEOUT'],
  }],
  summary: '行程整体质量 68/100。',
  evaluatedAt: '2026-08-02T00:00:00Z',
}

test('renders score dimensions severity labels and decision explanations', async () => {
  const view = render(PlanEvaluationPanel, { props: { evaluation } })

  expect(view.getByText('68/100').classList.contains('score-low')).toBe(true)
  expect(view.getByText('体验评分')).toBeTruthy()
  expect(view.getByText('约束满足')).toBeTruthy()
  expect(view.getByText('路线效率')).toBeTruthy()
  expect(view.getByText('提示')).toBeTruthy()
  expect(view.getByText('注意')).toBeTruthy()
  expect(view.getByText('严重')).toBeTruthy()
  expect(view.getByText('行程整体质量 68/100。')).toBeTruthy()

  await fireEvent.click(view.getByText('决策解释 (1)'))
  expect(view.getByText('路段')).toBeTruthy()
  expect(view.getByText('此路段使用 Demo 数据，因为真实路线服务不可用')).toBeTruthy()
})

test('renders the explicit legacy message only when requested', () => {
  const legacy = render(PlanEvaluationPanel, {
    props: { evaluation: null, showLegacy: true },
  })
  expect(legacy.getByText('该版本生成时尚未启用质量评估')).toBeTruthy()
})

test('renders not-applicable dimensions explicitly', () => {
  const notApplicableEvaluation = {
    ...evaluation,
    schemaVersion: 2,
    evaluatorVersion: 'rule-v2',
    dimensions: {
      ...evaluation.dimensions,
      budgetFit: null,
      interestMatch: null,
    },
  } as unknown as PlanEvaluation

  const view = render(PlanEvaluationPanel, {
    props: { evaluation: notApplicableEvaluation },
  })

  expect(view.getAllByText('未适用')).toHaveLength(2)
})

test('labels the score as experience quality, not hard feasibility', () => {
  const view = render(PlanEvaluationPanel, { props: { evaluation } })

  expect(view.getByText('仅代表体验质量，不代表硬可行性验证')).toBeTruthy()
})

test('never renders hard feasibility status words', () => {
  const view = render(PlanEvaluationPanel, { props: { evaluation } })

  expect(view.queryByText('已验证')).toBeNull()
  expect(view.queryByText('待修复')).toBeNull()
  expect(view.queryByText('未验证')).toBeNull()
})

// ---------------------------------------------------------------------------
// UI 收口：warning 聚合展示（摘要 + 分组 + 展开明细，语义不丢失）
// ---------------------------------------------------------------------------

test('shows an aggregated risk summary instead of raw flat listing', () => {
  const view = render(PlanEvaluationPanel, { props: { evaluation } })

  // 3 个不同 code -> 3 类风险；默认只显示摘要行与分组行（3 组各 ×1）。
  expect(view.getByText(/发现 3 类风险，共 3 条/)).toBeTruthy()
  expect(view.getAllByText('× 1')).toHaveLength(3)
})

test('group rows carry the highest severity of each group', () => {
  const view = render(PlanEvaluationPanel, { props: { evaluation } })

  // LOW_TIME_BUFFER 是 CRITICAL 组 -> 分组行徽章为「严重」且可见（折叠态只显示分组行）。
  expect(view.getByText('严重')).toBeTruthy()
})

test('expanding a group reveals every original warning item', async () => {
  const many = {
    ...evaluation,
    warnings: [
      { code: 'LOW_TIME_BUFFER', severity: 'CRITICAL', message: '活动间缓冲时间严重不足', entityType: 'TRANSIT' },
      { code: 'LOW_TIME_BUFFER', severity: 'CRITICAL', message: '活动间缓冲时间严重不足', entityType: 'TRANSIT' },
      { code: 'LOW_TIME_BUFFER', severity: 'WARNING', message: '活动间缓冲时间不足', entityType: 'TRANSIT' },
      { code: 'ESTIMATED_TRANSIT', severity: 'INFO', message: '此路段使用估算路线', entityType: 'TRANSIT' },
    ],
  } as unknown as PlanEvaluation
  const view = render(PlanEvaluationPanel, { props: { evaluation: many } })

  // 同 code 聚合：LOW_TIME_BUFFER × 3，ESTIMATED_TRANSIT × 1。
  expect(view.getByText('发现 2 类风险，共 4 条')).toBeTruthy()
  expect(view.getByText('× 3')).toBeTruthy()

  // 折叠态：明细条目不在 DOM（分组行只显示代表 label，不显示逐条）。
  expect(view.queryAllByTestId('warning-item')).toHaveLength(0)

  await fireEvent.click(view.getByText('活动间缓冲时间严重不足'))
  // 展开该组后 3 条明细全部可见（数量不丢失）。
  expect(view.getAllByTestId('warning-item')).toHaveLength(3)
  await fireEvent.click(view.getByText('此路段使用估算路线'))
  // 再展开另一组后共 4 条明细，与原始 warnings 数量一致。
  expect(view.getAllByTestId('warning-item')).toHaveLength(4)
})

test('renders nothing in the risk area when there are no warnings', () => {
  const clean = { ...evaluation, warnings: [] } as unknown as PlanEvaluation
  const view = render(PlanEvaluationPanel, { props: { evaluation: clean } })

  expect(view.queryByText(/发现 .* 类风险/)).toBeNull()
})

test('shows day context inside expanded warning details', async () => {
  const withDay = {
    ...evaluation,
    warnings: [
      { code: 'HIGH_DAILY_LOAD', severity: 'WARNING', message: '第 1 天有 5 个活动', entityType: 'DAY', dayIndex: 0 },
    ],
  } as unknown as PlanEvaluation
  const view = render(PlanEvaluationPanel, { props: { evaluation: withDay } })

  expect(view.getByText('发现 1 类风险，共 1 条')).toBeTruthy()
  await fireEvent.click(view.getByText('第 1 天有 5 个活动'))
  expect(view.getByText('Day 1')).toBeTruthy()
})
