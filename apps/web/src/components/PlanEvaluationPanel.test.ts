import { render, screen } from '@testing-library/vue'
import { describe, expect, it } from 'vitest'

import PlanEvaluationPanel from './PlanEvaluationPanel.vue'
import type { PlanEvaluation } from '../lib/api'

function evaluation(): PlanEvaluation {
  return {
    schemaVersion: 2,
    evaluatorVersion: 'rule-v3',
    feasible: true,
    overallScore: 82,
    dimensions: {
      constraintSatisfaction: 90,
      timeFeasibility: 80,
      budgetFit: null,
      routeEfficiency: 75,
      interestMatch: 85,
    },
    warnings: [],
    decisions: [],
    summary: 'sum',
    evaluatedAt: '2026-08-09T12:00:00Z',
  }
}

describe('PlanEvaluationPanel', () => {
  it('shows the experience score and soft dimensions', () => {
    render(PlanEvaluationPanel, { props: { evaluation: evaluation() } })

    expect(screen.getByText('体验评分')).toBeTruthy()
    expect(screen.getByText('82/100')).toBeTruthy()
    // five dimension rows (constraint, time, budget, route, interest)
    const rows = document.querySelectorAll('.dimension-row')
    expect(rows.length).toBe(5)
  })

  it('does not claim the itinerary is verified', () => {
    render(PlanEvaluationPanel, { props: { evaluation: evaluation() } })

    expect(screen.queryByText('行程可执行：已验证')).toBeNull()
    expect(screen.queryByText('硬约束校验通过')).toBeNull()
  })

  it('does not render anything when evaluation is absent', () => {
    const { container } = render(PlanEvaluationPanel, { props: { evaluation: null } })

    expect(container.querySelector('.plan-evaluation-panel')).toBeNull()
  })
})
