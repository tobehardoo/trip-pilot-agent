import { cleanup, fireEvent, render, screen } from '@testing-library/vue'
import { afterEach, expect, test, vi } from 'vitest'

import ConstraintEditor from '../src/components/ConstraintEditor.vue'
import { createConstraintEditorModel } from '../src/lib/constraint-editor'

afterEach(() => cleanup())

test('two autocompletes each search and select independently', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/trips/places/search')) {
      const body = JSON.parse(String(init?.body))
      const keyword = body.keyword
      return new Response(JSON.stringify({
        provider: 'DEMO',
        estimated: true,
        candidates: [{
          provider: 'DEMO',
          providerPoiId: `demo-${keyword}`,
          name: keyword === '广州塔' ? '广州塔' : '陈家祠',
          address: 'Demo location in 广州',
          province: '',
          city: '广州',
          district: '',
          longitude: 113.2,
          latitude: 23.1,
          estimated: true,
        }],
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)

  const model = createConstraintEditorModel()
  const view = render(ConstraintEditor, {
    props: { model, mode: 'edit', preferenceOptions: [], city: '广州', getToken: () => 'token' },
  })

  await fireEvent.update(view.getByLabelText('必去地点搜索'), '陈家祠')
  await fireEvent.click(await view.findByRole('button', { name: /陈家祠/ }))
  expect(model.mustVisitEntries).toHaveLength(1)

  await fireEvent.update(view.getByLabelText('排除地点搜索'), '广州塔')
  await fireEvent.click(await view.findByRole('button', { name: /广州塔/ }))
  expect(model.avoidEntries).toHaveLength(1)
  expect(model.mustVisitEntries).toHaveLength(1)
  expect(model.avoidEntries).toHaveLength(1)
  expect(model.mustVisitEntries).toHaveLength(1)

  vi.unstubAllGlobals()
})

test('does not fetch for short queries and shows empty state', async () => {
  const fetchMock = vi.fn(async () => {
    throw new Error('should not fetch')
  })
  vi.stubGlobal('fetch', fetchMock)
  const model = createConstraintEditorModel()
  const view = render(ConstraintEditor, {
    props: { model, mode: 'edit', preferenceOptions: [], city: '广州', getToken: () => 'token' },
  })
  await fireEvent.update(view.getByLabelText('必去地点搜索'), '陈')
  expect(fetchMock).not.toHaveBeenCalled()
  vi.unstubAllGlobals()
})

test('renders the demo badge on demo candidates', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/trips/places/search')) {
      return new Response(JSON.stringify({
        provider: 'DEMO',
        estimated: true,
        candidates: [{
          provider: 'DEMO',
          providerPoiId: 'demo-x',
          name: '陈家祠',
          address: 'Demo location',
          province: '',
          city: '广州',
          district: '',
          longitude: 113.2,
          latitude: 23.1,
          estimated: true,
        }],
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  const model = createConstraintEditorModel()
  const view = render(ConstraintEditor, {
    props: { model, mode: 'edit', preferenceOptions: [], city: '广州', getToken: () => 'token' },
  })
  await fireEvent.update(view.getByLabelText('必去地点搜索'), '陈家祠')
  await fireEvent.click(await view.findByRole('button', { name: /陈家祠/ }))
  expect(view.getByText('演示')).toBeTruthy()
  vi.unstubAllGlobals()
})

test('selecting a candidate is reflected in the serialized constraints', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/trips/places/search')) {
      return new Response(JSON.stringify({
        provider: 'DEMO',
        estimated: true,
        candidates: [{
          provider: 'DEMO',
          providerPoiId: 'demo-x',
          name: '陈家祠',
          address: 'Demo location',
          province: '',
          city: '广州',
          district: '',
          longitude: 113.2,
          latitude: 23.1,
          estimated: true,
        }],
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  const model = createConstraintEditorModel()
  render(ConstraintEditor, {
    props: { model, mode: 'edit', preferenceOptions: [], city: '广州', getToken: () => 'token' },
  })
  await fireEvent.update(screen.getByLabelText('必去地点搜索'), '陈家祠')
  await fireEvent.click(await screen.findByRole('button', { name: /陈家祠/ }))
  expect(model.mustVisitEntries[0].placeRef?.providerPoiId).toBe('demo-x')
  vi.unstubAllGlobals()
})

// ── B13_FIX R7/R5: city-switch invalidation, clear, error and no-result ────

test('switching the city cancels the old search and resets the dropdown', async () => {
  const fetchMock = vi.fn(async () => {
    throw new Error('city switch must cancel in-flight searches')
  })
  vi.stubGlobal('fetch', fetchMock)
  const model = createConstraintEditorModel()
  const view = render(ConstraintEditor, {
    props: { model, mode: 'edit', preferenceOptions: [], city: '广州', getToken: () => 'token' },
  })
  await fireEvent.update(view.getByLabelText('必去地点搜索'), '陈家祠')
  await view.rerender({ city: '上海' })
  // The old query text is cleared and no stale candidates are shown.
  expect((view.getByLabelText('必去地点搜索') as HTMLInputElement).value).toBe('')
  expect(fetchMock).not.toHaveBeenCalled()
  vi.unstubAllGlobals()
})

test('clear button empties the selection and the query', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/trips/places/search')) {
      return new Response(JSON.stringify({
        provider: 'DEMO',
        estimated: true,
        candidates: [{
          provider: 'DEMO',
          providerPoiId: 'demo-x',
          name: '陈家祠',
          address: 'Demo location',
          province: '',
          city: '广州',
          district: '',
          longitude: 113.2,
          latitude: 23.1,
          estimated: true,
        }],
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  const model = createConstraintEditorModel()
  const view = render(ConstraintEditor, {
    props: { model, mode: 'edit', preferenceOptions: [], city: '广州', getToken: () => 'token' },
  })
  // Anchors hold their selection in modelValue, so the clear button renders.
  await fireEvent.update(view.getByLabelText('到达地点搜索'), '陈家祠')
  await fireEvent.click(await view.findByRole('button', { name: /陈家祠/ }))
  expect(model.arrivalRef?.providerPoiId).toBe('demo-x')
  // The clear button reacts to mousedown (so the input blur never fires first).
  await fireEvent.mouseDown(view.getByRole('button', { name: '清除到达地点选择' }))
  expect(model.arrivalRef).toBeUndefined()
  expect(model.arrivalPlace).toBe('')
  vi.unstubAllGlobals()
})

test('shows the error state when the search fails', async () => {
  const fetchMock = vi.fn(async () => {
    throw new Error('agent is down')
  })
  vi.stubGlobal('fetch', fetchMock)
  const model = createConstraintEditorModel()
  const view = render(ConstraintEditor, {
    props: { model, mode: 'edit', preferenceOptions: [], city: '广州', getToken: () => 'token' },
  })
  await fireEvent.update(view.getByLabelText('必去地点搜索'), '陈家祠')
  await view.findByRole('alert')
  expect(view.getByRole('alert').textContent).toContain('agent is down')
  vi.unstubAllGlobals()
})

test('shows the no-result state for a query with zero candidates', async () => {
  const fetchMock = vi.fn(async () => {
    return new Response(JSON.stringify({
      provider: 'DEMO',
      estimated: true,
      candidates: [],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetchMock)
  const model = createConstraintEditorModel()
  const view = render(ConstraintEditor, {
    props: { model, mode: 'edit', preferenceOptions: [], city: '广州', getToken: () => 'token' },
  })
  await fireEvent.update(view.getByLabelText('必去地点搜索'), '查无此地')
  await view.findByText('未找到匹配地点')
  expect(fetchMock).toHaveBeenCalled()
  vi.unstubAllGlobals()
})

test('editing the text after a selection invalidates the structured ref', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/trips/places/search')) {
      return new Response(JSON.stringify({
        provider: 'DEMO',
        estimated: true,
        candidates: [{
          provider: 'DEMO',
          providerPoiId: 'demo-x',
          name: '陈家祠',
          address: 'Demo location',
          province: '',
          city: '广州',
          district: '',
          longitude: 113.2,
          latitude: 23.1,
          estimated: true,
        }],
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  const model = createConstraintEditorModel()
  const view = render(ConstraintEditor, {
    props: { model, mode: 'edit', preferenceOptions: [], city: '广州', getToken: () => 'token' },
  })
  await fireEvent.update(view.getByLabelText('到达地点搜索'), '陈家祠')
  await fireEvent.click(await view.findByRole('button', { name: /陈家祠/ }))
  expect(model.arrivalRef?.providerPoiId).toBe('demo-x')
  // Typing anything that diverges from the selected name drops the ref:
  // the free text becomes a legacy text again and must not be saved as a
  // structured identity (B13_FIX R8 / P1-8).
  await fireEvent.update(view.getByLabelText('到达地点搜索'), '陈家祠（新馆）')
  expect(model.arrivalRef).toBeUndefined()
  vi.unstubAllGlobals()
})

test('clears the query text when the structured ref is reset externally', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/trips/places/search')) {
      return new Response(JSON.stringify({
        provider: 'DEMO',
        estimated: true,
        candidates: [{
          provider: 'DEMO',
          providerPoiId: 'demo-x',
          name: '陈家祠',
          address: 'Demo location',
          province: '',
          city: '广州',
          district: '',
          longitude: 113.2,
          latitude: 23.1,
          estimated: true,
        }],
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  const model = createConstraintEditorModel()
  const view = render(ConstraintEditor, {
    props: { model, mode: 'edit', preferenceOptions: [], city: '广州', getToken: () => 'token' },
  })
  // Select a candidate so modelValue transitions null → ref.
  await fireEvent.update(view.getByLabelText('到达地点搜索'), '陈家祠')
  await fireEvent.click(await view.findByRole('button', { name: /陈家祠/ }))
  expect(model.arrivalRef?.providerPoiId).toBe('demo-x')
  // Simulate a parent clearing the ref: the watcher must clear the text too.
  model.arrivalRef = null
  model.arrivalPlace = ''
  await view.rerender({ model: { ...model, arrivalRef: null, arrivalPlace: '' } })
  await new Promise((resolve) => setTimeout(resolve, 0))
  expect((view.getByLabelText('到达地点搜索') as HTMLInputElement).value).toBe('')
  vi.unstubAllGlobals()
})
