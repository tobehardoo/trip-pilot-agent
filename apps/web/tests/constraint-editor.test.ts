import { cleanup, fireEvent, render } from '@testing-library/vue'
import { afterEach, expect, test } from 'vitest'

import ConstraintEditor from '../src/components/ConstraintEditor.vue'
import {
  createConstraintEditorModel,
  toTripConstraints,
  validateConstraintEditor,
} from '../src/lib/constraint-editor'

afterEach(() => cleanup())

test('uses one model and validation path for create and edit constraints', () => {
  const model = createConstraintEditorModel({
    budgetAmount: null,
    travelers: 2,
    travelerType: 'COUPLE',
    pace: 'RELAXED',
    preferences: ['本地美食'],
    fixedSchedules: [],
    arrival: { placeName: '广州南站', time: '2026-08-01T11:00:00+08:00' },
  })

  expect(model.budgetAmount).toBe('')
  expect(model.arrivalPlace).toBe('广州南站')
  expect(validateConstraintEditor(model)).toBeNull()

  model.departurePlace = '白云机场'
  expect(validateConstraintEditor(model)).toBe('请同时填写返程地点和返程时间')
  model.departureTime = '2026-08-03T17:00'

  const constraints = toTripConstraints(model, [])
  expect(constraints.budgetAmount).toBeNull()
  expect(constraints.departure).toEqual({
    placeName: '白云机场',
    time: '2026-08-03T17:00:00+08:00',
  })
})

test('renders the same complete fields and preference behavior in create mode', async () => {
  const model = createConstraintEditorModel()
  const view = render(ConstraintEditor, {
    props: {
      model,
      mode: 'create',
      preferenceOptions: ['本地美食'],
    },
  })

  expect(view.getByLabelText('住宿锚点')).toBeTruthy()
  expect(view.getByLabelText('到达地点')).toBeTruthy()
  await fireEvent.click(view.getByText('本地美食'))
  expect(model.preferences).toEqual(['本地美食'])
})
