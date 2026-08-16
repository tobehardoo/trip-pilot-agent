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

  expect(view.getByLabelText('住宿锚点搜索')).toBeTruthy()
  expect(view.getByLabelText('到达地点搜索')).toBeTruthy()
  await fireEvent.click(view.getByText('本地美食'))
  expect(model.preferences).toEqual(['本地美食'])
})

// ── B13-F: meal window source three-state semantics ────────────────────────

test('legacy meal windows keep USER source and round-trip three states', () => {
  const model = createConstraintEditorModel({
    mealWindows: [{ mealType: 'LUNCH', startTime: '12:00', endTime: '13:00' }],
  })
  // Historical windows without a source must keep hard USER semantics.
  expect(model.lunchSource).toBe('USER')

  model.lunchSource = 'DEFAULT'
  let constraints = toTripConstraints(model, [])
  expect(constraints.mealWindows).toEqual([
    { mealType: 'BREAKFAST', startTime: '08:00', endTime: '09:00', source: 'DEFAULT' },
    { mealType: 'LUNCH', startTime: '12:00', endTime: '13:00', source: 'DEFAULT' },
    { mealType: 'DINNER', startTime: '18:00', endTime: '19:00', source: 'DEFAULT' },
  ])

  model.lunchSource = 'DISABLED'
  constraints = toTripConstraints(model, [])
  expect(constraints.mealWindows).toEqual([
    { mealType: 'BREAKFAST', startTime: '08:00', endTime: '09:00', source: 'DEFAULT' },
    { mealType: 'LUNCH', startTime: '12:00', endTime: '13:00', source: 'DISABLED' },
    { mealType: 'DINNER', startTime: '18:00', endTime: '19:00', source: 'DEFAULT' },
  ])

  model.lunchSource = 'USER'
  constraints = toTripConstraints(model, [])
  expect(constraints.mealWindows).toEqual([
    { mealType: 'BREAKFAST', startTime: '08:00', endTime: '09:00', source: 'DEFAULT' },
    { mealType: 'LUNCH', startTime: '12:00', endTime: '13:00', source: 'USER' },
    { mealType: 'DINNER', startTime: '18:00', endTime: '19:00', source: 'DEFAULT' },
  ])
})

test('DEFAULT and DISABLED meals emit the canonical default windows', () => {
  const model = createConstraintEditorModel()
  model.breakfastSource = 'DEFAULT'
  model.lunchSource = 'DEFAULT'
  model.dinnerSource = 'DISABLED'

  const constraints = toTripConstraints(model, [])

  expect(constraints.mealWindows).toEqual([
    { mealType: 'BREAKFAST', startTime: '08:00', endTime: '09:00', source: 'DEFAULT' },
    { mealType: 'LUNCH', startTime: '12:00', endTime: '13:00', source: 'DEFAULT' },
    { mealType: 'DINNER', startTime: '18:00', endTime: '19:00', source: 'DISABLED' },
  ])
})

test('fresh editor defaults all meals to the soft DEFAULT suggestion', () => {
  const model = createConstraintEditorModel()
  expect(model.breakfastSource).toBe('DEFAULT')
  expect(model.lunchSource).toBe('DEFAULT')
  expect(model.dinnerSource).toBe('DEFAULT')
  expect(validateConstraintEditor(model)).toBeNull()
})

test('validation requires times only for USER meals', () => {
  const model = createConstraintEditorModel()
  model.lunchSource = 'USER'
  expect(validateConstraintEditor(model)).toBe('请同时填写午餐窗口的开始和结束时间')
  model.lunchStart = '12:00'
  expect(validateConstraintEditor(model)).toBe('请同时填写午餐窗口的开始和结束时间')
  model.lunchEnd = '13:00'
  model.dinnerSource = 'DEFAULT'
  expect(validateConstraintEditor(model)).toBeNull()
  model.dinnerSource = 'DISABLED'
  expect(validateConstraintEditor(model)).toBeNull()
})

test('renders three meal source states and swaps time inputs', async () => {
  const model = createConstraintEditorModel()
  const view = render(ConstraintEditor, {
    props: { model, mode: 'create', preferenceOptions: [] },
  })

  const select = view.getByLabelText('午餐安排方式') as HTMLSelectElement
  expect(select.value).toBe('DEFAULT')
  expect(view.getByText('12:00–13:00')).toBeTruthy()

  await fireEvent.update(select, 'USER')
  expect(view.getByLabelText('午餐开始时间')).toBeTruthy()
  expect(view.getByLabelText('午餐结束时间')).toBeTruthy()

  await fireEvent.update(select, 'DISABLED')
  expect(view.queryByLabelText('午餐开始时间')).toBeNull()
  expect(view.getByText('不在行程中安排')).toBeTruthy()
})

// ── B13-D: structured place entries ─────────────────────────────────────────

const amapRef = {
  provider: 'AMAP' as const,
  providerPoiId: 'B001234567',
  name: '陈家祠',
  address: '广州市荔湾区中山七路恩龙里34号',
  province: '广东省',
  city: '广州市',
  district: '荔湾区',
  longitude: 113.2405,
  latitude: 23.1256,
}

test('structured place refs round-trip in parallel arrays', () => {
  const model = createConstraintEditorModel({
    mustVisitPlaces: ['陈家祠'],
    mustVisitPlaceRefs: [amapRef],
    avoidPlaces: ['广州塔'],
  })

  expect(model.mustVisitEntries).toEqual([{ name: '陈家祠', placeRef: amapRef }])
  expect(model.avoidEntries).toEqual([{ name: '广州塔', placeRef: undefined }])

  const constraints = toTripConstraints(model, [])
  expect(constraints.mustVisitPlaces).toEqual(['陈家祠'])
  expect(constraints.mustVisitPlaceRefs).toEqual([amapRef])
  // A legacy entry without a ref suppresses the whole parallel refs array.
  expect(constraints.avoidPlaceRefs).toBeUndefined()
  expect(constraints.avoidPlaces).toEqual(['广州塔'])
})

test('legacy names keep no refs and never fabricate them', () => {
  const model = createConstraintEditorModel({
    mustVisitPlaces: ['陈家祠', '光孝寺'],
  })

  expect(model.mustVisitEntries.every((entry) => entry.placeRef === undefined)).toBe(true)

  const constraints = toTripConstraints(model, [])
  expect(constraints.mustVisitPlaces).toEqual(['陈家祠', '光孝寺'])
  expect(constraints.mustVisitPlaceRefs).toBeUndefined()
})

test('all-structured lists emit refs; mixed lists stay legacy', () => {
  const model = createConstraintEditorModel()
  model.mustVisitEntries.push({ name: '陈家祠', placeRef: amapRef })
  model.mustVisitEntries.push({ name: '光孝寺' })

  const constraints = toTripConstraints(model, [])
  expect(constraints.mustVisitPlaces).toEqual(['陈家祠', '光孝寺'])
  expect(constraints.mustVisitPlaceRefs).toBeUndefined()

  model.mustVisitEntries[1] = {
    name: '光孝寺',
    placeRef: { ...amapRef, providerPoiId: 'B0G1X002', name: '光孝寺' },
  }
  const structured = toTripConstraints(model, [])
  expect(structured.mustVisitPlaceRefs).toHaveLength(2)
})

test('remove buttons splice the exact entry out of the must-visit list', async () => {
  // B13_FIX R8 (P1-8): the removeEntry handler must be exercised through the
  // real button, not only through model mutations.
  const model = createConstraintEditorModel()
  model.mustVisitEntries.push({ name: '陈家祠', placeRef: amapRef })
  model.mustVisitEntries.push({ name: '光孝寺' })
  model.avoidEntries.push({ name: '广州塔' })
  const view = render(ConstraintEditor, {
    props: { model, mode: 'edit', preferenceOptions: [] },
  })

  await fireEvent.click(view.getByRole('button', { name: '移除必去地点 陈家祠' }))
  expect(model.mustVisitEntries.map((entry) => entry.name)).toEqual(['光孝寺'])
  expect(model.mustVisitEntries[0]?.placeRef).toBeUndefined()

  await fireEvent.click(view.getByRole('button', { name: '移除排除地点 广州塔' }))
  expect(model.avoidEntries).toHaveLength(0)
})

// ── B13_FIX.1 R2: free-text anchors require a selected candidate ───────────

function modelWithArrival(place: string, ref?: typeof amapRef) {
  const model = createConstraintEditorModel()
  model.arrivalPlace = place
  model.arrivalTime = '2026-08-01T10:00'
  model.arrivalRef = ref ? { ...ref } : undefined
  return model
}

test('R2 create: free-text arrival without a candidate is rejected', () => {
  const model = modelWithArrival('随便输入的车站名XYZ')
  expect(validateConstraintEditor(model, 'create')).toBe('请从搜索结果中选择有效地点')
})

test('R2 create: selected candidate arrival passes', () => {
  const model = modelWithArrival('陈家祠', amapRef)
  expect(validateConstraintEditor(model, 'create')).toBeNull()
})

test('R2 create: empty optional anchors still pass', () => {
  const model = createConstraintEditorModel()
  expect(validateConstraintEditor(model, 'create')).toBeNull()
})

test('R2 edit: unchanged legacy anchor is allowed', () => {
  const model = createConstraintEditorModel({
    travelers: 1,
    travelerType: 'SOLO',
    pace: 'BALANCED',
    preferences: [],
    fixedSchedules: [],
    arrival: { placeName: '旧站名', time: '2026-08-01T10:00:00+08:00' },
  })
  model.arrivalTime = '2026-08-01T10:00'
  expect(validateConstraintEditor(model, 'edit')).toBeNull()
})

test('R2 edit: changed legacy anchor without a candidate is rejected', () => {
  const model = createConstraintEditorModel({
    travelers: 1,
    travelerType: 'SOLO',
    pace: 'BALANCED',
    preferences: [],
    fixedSchedules: [],
    arrival: { placeName: '旧站名', time: '2026-08-01T10:00:00+08:00' },
  })
  model.arrivalPlace = '新站名'
  model.arrivalTime = '2026-08-01T10:00'
  expect(validateConstraintEditor(model, 'edit')).toBe('请从搜索结果中选择有效地点')
})

test('R2 edit: changed structured anchor then picked candidate passes', () => {
  const model = createConstraintEditorModel({
    travelers: 1,
    travelerType: 'SOLO',
    pace: 'BALANCED',
    preferences: [],
    fixedSchedules: [],
    arrival: {
      placeName: '陈家祠',
      time: '2026-08-01T10:00:00+08:00',
      placeRef: { ...amapRef },
    },
  })
  model.arrivalPlace = '光孝寺'
  model.arrivalRef = { ...amapRef, providerPoiId: 'B0G1X002', name: '光孝寺' }
  model.arrivalTime = '2026-08-01T10:00'
  expect(validateConstraintEditor(model, 'edit')).toBeNull()
})

test('R2 edit: structured anchor whose text changed loses the ref and is rejected', () => {
  const model = createConstraintEditorModel({
    travelers: 1,
    travelerType: 'SOLO',
    pace: 'BALANCED',
    preferences: [],
    fixedSchedules: [],
    arrival: {
      placeName: '陈家祠',
      time: '2026-08-01T10:00:00+08:00',
      placeRef: { ...amapRef },
    },
  })
  // Simulates typeAnchor(): text edited, ref cleared.
  model.arrivalPlace = '陈氏书院'
  model.arrivalRef = undefined
  model.arrivalTime = '2026-08-01T10:00'
  expect(validateConstraintEditor(model, 'edit')).toBe('请从搜索结果中选择有效地点')
})

test('R2 create: cleared optional accommodation passes', () => {
  const model = createConstraintEditorModel()
  expect(validateConstraintEditor(model, 'create')).toBeNull()
})

test('R2 create: free-text must-visit entry is rejected', () => {
  const model = createConstraintEditorModel()
  model.mustVisitEntries.push({ name: '自由文本必去' })
  expect(validateConstraintEditor(model, 'create')).toBe('请从搜索结果中选择有效地点')
})
