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
