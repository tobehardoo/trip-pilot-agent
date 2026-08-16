import {
  searchPlaces,
  type PlaceCandidate,
  type PlaceRef,
  type PlaceSearchInput,
  type PlaceSearchResult,
} from './api'

export const PLACE_SEARCH_MIN_CHARS = 2
export const PLACE_SEARCH_DEBOUNCE_MS = 250
export const PLACE_SEARCH_MAX_RESULTS = 10

export interface PlaceSearchState {
  query: string
  searching: boolean
  candidates: PlaceCandidate[]
  error: string | null
}

export const IDLE_SEARCH_STATE: PlaceSearchState = {
  query: '',
  searching: false,
  candidates: [],
  error: null,
}

export type PlaceSearchFn = (
  input: PlaceSearchInput,
  signal?: AbortSignal,
) => Promise<PlaceSearchResult>

export interface PlaceSearcherOptions {
  getToken: () => string
  getCity: () => string
  onChange: (state: PlaceSearchState) => void
  search?: PlaceSearchFn
  debounceMs?: number
}

/**
 * B13-D: debounced, abortable place search with stale-response guarding.
 * Queries shorter than two characters never hit the network; results are
 * capped at 10 candidates.
 */
export class PlaceSearcher {
  private readonly search: PlaceSearchFn
  private readonly debounceMs: number
  private timer: ReturnType<typeof setTimeout> | null = null
  private controller: AbortController | null = null
  private sequence = 0
  private lastEmitted: PlaceSearchState = IDLE_SEARCH_STATE

  constructor(private readonly options: PlaceSearcherOptions) {
    const defaultSearch: PlaceSearchFn = (input, signal) =>
      searchPlaces(options.getToken(), input, signal)
    this.search = options.search ?? defaultSearch
    this.debounceMs = options.debounceMs ?? PLACE_SEARCH_DEBOUNCE_MS
  }

  update(query: string) {
    const trimmed = query.trim()
    this.lastEmitted = { query, searching: false, candidates: [], error: null }
    if (trimmed.length < PLACE_SEARCH_MIN_CHARS) {
      this.clearPending()
      this.options.onChange(this.lastEmitted)
      return
    }
    if (this.timer !== null) clearTimeout(this.timer)
    this.timer = setTimeout(() => {
      this.timer = null
      void this.run(trimmed)
    }, this.debounceMs)
  }

  cancel() {
    this.clearPending()
    this.options.onChange({ ...this.lastEmitted, searching: false })
  }

  private clearPending() {
    if (this.timer !== null) {
      clearTimeout(this.timer)
      this.timer = null
    }
    if (this.controller !== null) {
      this.controller.abort()
      this.controller = null
    }
  }

  private async run(keyword: string) {
    if (this.controller !== null) this.controller.abort()
    const controller = new AbortController()
    this.controller = controller
    const sequence = ++this.sequence
    this.options.onChange({
      query: keyword,
      searching: true,
      candidates: [],
      error: null,
    })
    try {
      const result = await this.search(
        {
          city: this.options.getCity(),
          keyword,
          limit: PLACE_SEARCH_MAX_RESULTS,
        },
        controller.signal,
      )
      if (sequence !== this.sequence || controller.signal.aborted) return
      this.options.onChange({
        query: keyword,
        searching: false,
        candidates: result.candidates.slice(0, PLACE_SEARCH_MAX_RESULTS),
        error: null,
      })
    } catch (cause) {
      if (controller.signal.aborted || sequence !== this.sequence) return
      this.options.onChange({
        query: keyword,
        searching: false,
        candidates: [],
        error: cause instanceof Error ? cause.message : '搜索失败，请稍后重试',
      })
    }
  }
}

/** Keep the server-issued selection token so the save can canonicalize. */
export function toPlaceRef(candidate: PlaceCandidate): PlaceRef {
  return {
    provider: candidate.provider,
    providerPoiId: candidate.providerPoiId,
    name: candidate.name,
    address: candidate.address,
    province: candidate.province,
    city: candidate.city,
    district: candidate.district,
    longitude: candidate.longitude,
    latitude: candidate.latitude,
    selectionToken: candidate.selectionToken,
  }
}

export function isDemoCandidate(candidate: PlaceCandidate): boolean {
  return candidate.provider === 'DEMO' || candidate.estimated
}
