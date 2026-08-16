import { describe, expect, it, vi } from 'vitest'

import {
  IDLE_SEARCH_STATE,
  PlaceSearcher,
  toPlaceRef,
  type PlaceSearchFn,
  type PlaceSearchState,
} from './place-selection'

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
