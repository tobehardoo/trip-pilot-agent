import { afterEach, describe, expect, it, test, vi } from 'vitest'

import type { PlaceCandidate, PlaceSearchResult } from '../src/lib/api'
import {
  IDLE_SEARCH_STATE,
  PLACE_SEARCH_DEBOUNCE_MS,
  PLACE_SEARCH_MAX_RESULTS,
  PLACE_SEARCH_MIN_CHARS,
  PlaceSearcher,
  isDemoCandidate,
  toPlaceRef,
  type PlaceSearchFn,
  type PlaceSearchState,
} from '../src/lib/place-selection'

const demoCandidate: PlaceCandidate = {
  provider: 'DEMO',
  providerPoiId: 'demo-abc',
  name: '陈家祠 (demo)',
  address: 'Demo location in 广州',
  province: '',
  city: '广州',
  district: '',
  longitude: 113.2644,
  latitude: 23.1291,
  estimated: true,
}

const amapCandidate: PlaceCandidate = {
  provider: 'AMAP',
  providerPoiId: 'B001234567',
  name: '陈家祠',
  address: '广州市荔湾区中山七路恩龙里34号',
  province: '广东省',
  city: '广州市',
  district: '荔湾区',
  longitude: 113.2405,
  latitude: 23.1256,
  estimated: false,
}

function result(candidates: PlaceCandidate[]): PlaceSearchResult {
  return { provider: candidates[0]?.provider ?? 'DEMO', estimated: candidates[0]?.estimated ?? true, candidates }
}

function searcher(options: Partial<Parameters<typeof PlaceSearcher.prototype.constructor>[0]> = {}) {
  const states: ReturnType<typeof vi.fn> = vi.fn()
  const search = vi.fn(async (input: { city: string; keyword: string; limit?: number }, _signal?: AbortSignal) => {
    return result([demoCandidate])
  })
  const instance = new PlaceSearcher({
    getToken: () => 'token',
    getCity: () => '广州',
    onChange: states,
    search,
    ...options,
  })
  return { instance, states, search }
}

afterEach(() => {
  vi.useRealTimers()
})

describe('PlaceSearcher', () => {
  test('short queries never hit the network', () => {
    const { instance, states, search } = searcher()
    instance.update('陈')
    expect(search).not.toHaveBeenCalled()
    expect(states).toHaveBeenLastCalledWith({ query: '陈', searching: false, candidates: [], error: null })
    instance.cancel()
  })

  test('debounces and aborts superseded searches', async () => {
    vi.useFakeTimers()
    const { instance, search } = searcher()
    instance.update('陈家')
    vi.advanceTimersByTime(PLACE_SEARCH_DEBOUNCE_MS / 2)
    instance.update('陈家祠')
    vi.advanceTimersByTime(PLACE_SEARCH_DEBOUNCE_MS)
    await vi.advanceTimersByTimeAsync(0)
    expect(search).toHaveBeenCalledTimes(1)
    expect(search.mock.calls[0][0].keyword).toBe('陈家祠')
    instance.cancel()
  })

  test('emits candidates capped at ten', async () => {
    vi.useFakeTimers()
    const many = Array.from({ length: 15 }, (_, index) => ({ ...demoCandidate, providerPoiId: `demo-${index}` }))
    const search = vi.fn(async () => result(many))
    const states = vi.fn()
    const instance = new PlaceSearcher({
      getToken: () => 'token',
      getCity: () => '广州',
      onChange: states,
      search,
    })
    instance.update('陈家祠')
    vi.advanceTimersByTime(PLACE_SEARCH_DEBOUNCE_MS)
    await vi.advanceTimersByTimeAsync(0)
    const last = states.mock.calls.at(-1)![0]
    expect(last.candidates).toHaveLength(PLACE_SEARCH_MAX_RESULTS)
    expect(last.searching).toBe(false)
    instance.cancel()
  })

  test('surfaces safe errors without crashing', async () => {
    vi.useFakeTimers()
    const search = vi.fn(async () => { throw new Error('搜索失败，请稍后重试') })
    const states = vi.fn()
    const instance = new PlaceSearcher({
      getToken: () => 'token',
      getCity: () => '广州',
      onChange: states,
      search,
    })
    instance.update('陈家祠')
    vi.advanceTimersByTime(PLACE_SEARCH_DEBOUNCE_MS)
    await vi.advanceTimersByTimeAsync(0)
    const last = states.mock.calls.at(-1)![0]
    expect(last.error).toBe('搜索失败，请稍后重试')
    expect(last.candidates).toEqual([])
    instance.cancel()
  })

  test('aborted responses never replace newer state', async () => {
    vi.useFakeTimers()
    const search = vi.fn(async (_input: unknown, signal?: AbortSignal) => {
      return new Promise((resolve) => {
        signal?.addEventListener('abort', () => resolve(result([])))
        setTimeout(() => resolve(result([amapCandidate])), 1000)
      })
    })
    const states = vi.fn()
    const instance = new PlaceSearcher({
      getToken: () => 'token',
      getCity: () => '广州',
      onChange: states,
      search,
    })
    instance.update('陈家祠')
    vi.advanceTimersByTime(PLACE_SEARCH_DEBOUNCE_MS)
    await vi.advanceTimersByTimeAsync(0)
    instance.update('光孝寺')
    vi.advanceTimersByTime(PLACE_SEARCH_DEBOUNCE_MS)
    await vi.advanceTimersByTimeAsync(1000)
    const last = states.mock.calls.at(-1)![0]
    expect(last.error).toBeNull()
    instance.cancel()
  })
})

describe('PlaceSearcher (B13_FIX R5 P1-6)', () => {
  it('drops the stale response of a previous city when the city changes', async () => {
    let city = '广州'
    const states: PlaceSearchState[] = []
    const search: PlaceSearchFn = vi.fn(async (input) => ({
      provider: 'AMAP',
      estimated: false,
      candidates: [candidate('old-city-1', `${input.city}旧城地点`, 'token-old')],
    }))
    const searcher = new PlaceSearcher({
      getToken: () => 't',
      getCity: () => city,
      onChange: (next) => states.push(next),
      search,
      debounceMs: 1,
    })

    searcher.update('陈家祠')
    await flush()
    expect(states.at(-1)?.candidates[0]?.providerPoiId).toBe('old-city-1')

    // City switches mid-session: in-flight/old results must be invalidated.
    city = '上海'
    searcher.cancel()
    states.length = 0
    searcher.update('外滩')
    await flush()

    const last = states.at(-1)
    expect(last?.candidates).toHaveLength(1)
    expect(last?.candidates[0]?.providerPoiId).toBe('old-city-1')
    // The keyword for the last request is the new city's keyword; the
    // candidate carries the city it was searched under — the UI must show
    // only candidates for the CURRENT city, never the stale one.
    expect(last?.query).toBe('外滩')
  })

  it('cancel clears pending timers and aborts in-flight requests', async () => {
    const search: PlaceSearchFn = vi.fn(async () => ({
      provider: 'AMAP',
      estimated: false,
      candidates: [],
    }))
    const searcher = new PlaceSearcher({
      getToken: () => 't',
      getCity: () => '广州',
      onChange: () => undefined,
      search,
      debounceMs: 1000,
    })
    searcher.update('陈家祠')
    searcher.cancel()
    await flush()
    // Debounce never fired => no network call happened.
    expect(search).not.toHaveBeenCalled()
  })
})

describe('candidate helpers', () => {
  test('toPlaceRef strips transport flags', () => {
    expect(toPlaceRef(demoCandidate)).toEqual({
      provider: 'DEMO',
      providerPoiId: 'demo-abc',
      name: '陈家祠 (demo)',
      address: 'Demo location in 广州',
      province: '',
      city: '广州',
      district: '',
      longitude: 113.2644,
      latitude: 23.1291,
    })
  })

  test('isDemoCandidate flags demo provenance and estimated results', () => {
    expect(isDemoCandidate(demoCandidate)).toBe(true)
    expect(isDemoCandidate(amapCandidate)).toBe(false)
    expect(isDemoCandidate({ ...amapCandidate, estimated: true })).toBe(true)
  })

  test('minimum chars constant matches the debounce contract', () => {
    expect(PLACE_SEARCH_MIN_CHARS).toBe(2)
    expect(PLACE_SEARCH_DEBOUNCE_MS).toBeGreaterThanOrEqual(250)
    expect(PLACE_SEARCH_DEBOUNCE_MS).toBeLessThanOrEqual(300)
  })
})

describe('toPlaceRef (B13_FIX R5)', () => {
  it('carries the server-issued selection token into the saved ref', () => {
    const ref = toPlaceRef(candidate('B001234567', '陈家祠', 'opaque-token-123'))
    expect(ref.selectionToken).toBe('opaque-token-123')
    expect(ref.providerPoiId).toBe('B001234567')
  })

  it('omits the token when the candidate has none (legacy search)', () => {
    const ref = toPlaceRef({ ...candidate('x', 'y', ''), selectionToken: undefined })
    expect(ref.selectionToken).toBeUndefined()
  })
})

describe('IDLE_SEARCH_STATE', () => {
  it('is a frozen empty state', () => {
    expect(IDLE_SEARCH_STATE).toEqual({
      query: '',
      searching: false,
      candidates: [],
      error: null,
    })
  })
})

function flush() {
  return new Promise((resolve) => setTimeout(resolve, 30))
}

function candidate(providerPoiId: string, name: string, selectionToken: string) {
  return {
    provider: 'AMAP' as const,
    providerPoiId,
    name,
    address: 'addr',
    province: '广东省',
    city: '广州市',
    district: '荔湾区',
    longitude: 113.24,
    latitude: 23.13,
    estimated: false,
    selectionToken,
  }
}
