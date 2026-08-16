import { cleanup, fireEvent, render } from '@testing-library/vue'
import { afterEach, expect, test } from 'vitest'

import TravelStyleEditor from '../src/components/TravelStyleEditor.vue'
import { createConstraintEditorModel } from '../src/lib/constraint-editor'

afterEach(() => cleanup())

test('B13-G merges pace, mobility and preferences into one region', () => {
  const model = createConstraintEditorModel()
  const view = render(TravelStyleEditor, {
    props: { model, preferenceOptions: ['岭南文化', '本地美食'] },
  })

  // One single titled region carries all three field groups.
  expect(view.getByLabelText('旅行方式与偏好')).toBeTruthy()
  expect(view.getByLabelText('行动能力')).toBeTruthy()
  expect(view.getByLabelText('舒缓')).toBeTruthy()
  expect(view.getByLabelText('均衡')).toBeTruthy()
  expect(view.getByLabelText('紧凑')).toBeTruthy()
  expect(view.getByText('岭南文化')).toBeTruthy()
  expect(view.getByText('本地美食')).toBeTruthy()
})

test('B13-G keeps pace, mobility and preferences as independent fields', async () => {
  const model = createConstraintEditorModel()
  const view = render(TravelStyleEditor, {
    props: { model, preferenceOptions: ['岭南文化'] },
  })

  await fireEvent.click(view.getByLabelText('舒缓'))
  expect(model.pace).toBe('RELAXED')
  expect(model.mobilityLevel).toBe('STANDARD')
  expect(model.preferences).toEqual([])

  await fireEvent.update(view.getByLabelText('行动能力'), 'REDUCED')
  expect(model.mobilityLevel).toBe('REDUCED')
  expect(model.pace).toBe('RELAXED')

  await fireEvent.click(view.getByText('岭南文化'))
  expect(model.preferences).toEqual(['岭南文化'])
  expect(model.pace).toBe('RELAXED')
  expect(model.mobilityLevel).toBe('REDUCED')
})

test('B13-G serialization keeps the domain fields independent', () => {
  const model = createConstraintEditorModel()
  model.pace = 'INTENSIVE'
  model.mobilityLevel = 'STEP_FREE'
  model.preferences.push('夜间活动')

  expect(model.pace).toBe('INTENSIVE')
  expect(model.mobilityLevel).toBe('STEP_FREE')
  expect(model.preferences).toEqual(['夜间活动'])
})
