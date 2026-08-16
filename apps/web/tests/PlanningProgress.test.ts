import { cleanup, render } from '@testing-library/vue'
import { afterEach, expect, test } from 'vitest'

import PlanningProgress from '../src/components/PlanningProgress.vue'

afterEach(() => cleanup())

test('renders the current planning stage from an SSE progress event', () => {
  const view = render(PlanningProgress, {
    props: {
      planningState: 'queued',
      progress: {
        stage: 'CONSTRAINTS_SOLVING',
        sequence: 4,
        progress: 65,
        message: 'Solving time, budget, and mobility constraints',
        statistics: { tripDays: 3 },
        occurredAt: '2026-07-27T08:00:00Z',
      },
      progressHistory: [
        {
          stage: 'TASK_ACCEPTED',
          sequence: 1,
          progress: 5,
          message: 'Planning task accepted by the worker',
          statistics: { tripDays: 3 },
          occurredAt: '2026-07-27T08:00:00Z',
        },
        {
          stage: 'CONSTRAINTS_SOLVING',
          sequence: 4,
          progress: 65,
          message: 'Solving time, budget, and mobility constraints',
          statistics: {},
          occurredAt: '2026-07-27T08:00:03Z',
        },
      ],
    },
  })

  expect(view.getByTestId('planning-current-stage').textContent)
    .toContain('正在协调时间、预算与偏好')
  expect(view.getByTestId('planning-stage-CONSTRAINTS_SOLVING').textContent)
    .toContain('进行中')
  expect(view.getByTestId('planning-stage-POI_RECALLING').textContent)
    .toContain('未触发')
})

test('renders a terminal success instead of stale publishing progress', () => {
  const view = render(PlanningProgress, {
    props: {
      planningState: 'succeeded',
      progress: {
        stage: 'RESULT_PUBLISHING',
        sequence: 10,
        progress: 95,
        message: 'Publishing planning result',
        statistics: {},
        occurredAt: '2026-07-27T08:00:10Z',
      },
      progressHistory: [],
    },
  })

  expect(view.getByTestId('planning-current-stage').textContent)
    .toContain('行程规划已完成')
  expect(view.queryByText('95%')).toBeNull()
})

test('renders a bounded repair attempt as the active pipeline stage', () => {
  const view = render(PlanningProgress, {
    props: {
      planningState: 'queued',
      progress: {
        eventId: 12,
        stage: 'REPAIRING',
        sequence: 8,
        progress: 75,
        message: 'Applying bounded repair attempt 2',
        statistics: { attemptIndex: 2, actionCount: 3 },
        occurredAt: '2026-08-13T08:00:00Z',
      },
      progressHistory: [],
    },
  })

  expect(view.getByTestId('planning-stage-REPAIRING').textContent)
    .toContain('进行中')
  expect(view.getByTestId('planning-current-stage').textContent)
    .toContain('有界修复')
  expect(view.getByText('attemptIndex: 2')).toBeTruthy()
})
