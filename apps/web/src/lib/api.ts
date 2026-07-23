export interface User {
  id: string
  email: string
  displayName: string
}

export interface AuthSession {
  user: User
  accessToken: string
  tokenType: string
  expiresIn: number
}

export interface TripConstraints {
  budgetAmount: number | null
  travelers: number
  travelerType: 'SOLO' | 'COUPLE' | 'FAMILY' | 'FRIENDS' | 'BUSINESS'
  pace: 'RELAXED' | 'BALANCED' | 'INTENSIVE'
  preferences: string[]
  fixedSchedules: Array<{
    placeName: string
    startTime: string
    endTime: string
  }>
  schemaVersion?: number
}

export interface Trip {
  id: string
  title: string
  destination: string
  startDate: string
  endDate: string
  status: string
  version: number
  constraints: TripConstraints
  createdAt: string
  updatedAt: string
}

export interface CreateTripInput {
  title: string
  destination: string
  startDate: string
  endDate: string
  constraints: Omit<TripConstraints, 'schemaVersion'>
}

export interface UpdateTripConstraintsInput extends Omit<TripConstraints, 'schemaVersion'> {
  version: number
}

export interface PlanningTask {
  taskId: string
  tripId: string
  taskType: string
  status: string
  baselineTripVersion: number
  eventStreamUrl: string
  createdAt: string
  updatedAt: string
}

export interface PlanningTaskEvent {
  eventId: number
  taskId: string
  eventType: string
  schemaVersion: number
  payload: {
    status?: string
    errorCode?: string
    errorMessage?: string
    message?: string
    conflicts?: Array<{
      code: string
      message: string
      affected: string[]
    }>
    relaxationSuggestions?: Array<{
      code: string
      message: string
    }>
    [key: string]: unknown
  }
  createdAt: string
}

export interface ItineraryActivity {
  id: string
  title: string
  startTime: string
  endTime: string
  estimatedCost: number
  source: 'AMAP' | 'DEMO'
  providerPoiId: string | null
  coordinates: {
    longitude: number
    latitude: number
  } | null
  address: string | null
}

export interface ItineraryTransitLeg {
  id: string
  legOrder: number
  fromActivityId: string
  toActivityId: string
  mode: 'WALKING'
  distanceMeters: number
  durationSeconds: number
  provider: 'AMAP' | 'DEMO'
  estimated: boolean
  polyline: Array<{
    longitude: number
    latitude: number
  }>
}

export interface ItineraryKnowledgeCitation {
  documentId: string
  documentVersion: number
  chunkId: string
  chunkIndex: number
  title: string
  sourceUrl: string
  sourceName: string
  collectedAt: string
  reliabilityLevel: string
  similarity: number
}

export interface ItineraryKnowledge {
  status: 'REAL' | 'DEMO' | 'UNAVAILABLE'
  query: string
  citations: ItineraryKnowledgeCitation[]
  freshness: {
    status: 'FRESH' | 'STALE' | 'UNAVAILABLE'
    checkedAt: string | null
    staleReason: string | null
  }
  message: string | null
}

export interface Itinerary {
  versionId: string
  versionNumber: number
  parentVersionId: string | null
  title: string
  estimatedTotalCost: number
  provider: 'AMAP' | 'DEMO'
  days: Array<{
    date: string
    activities: ItineraryActivity[]
    transitLegs: ItineraryTransitLeg[]
  }>
  knowledge: ItineraryKnowledge
  createdAt: string
}

export interface PlanningEventStreamOptions {
  lastEventId?: number
  signal?: AbortSignal
}

interface ApiErrorBody {
  code?: string
  message?: string
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message)
  }
}

async function request<T>(path: string, options: RequestInit = {}, accessToken?: string): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> | undefined),
  }
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`

  const result = await fetch(path, { ...options, headers })
  let body: T | ApiErrorBody = {}
  try {
    body = (await result.json()) as T | ApiErrorBody
  } catch {
    // Security filters can return an empty 401/403 response.
  }
  if (!result.ok) {
    const error = body as ApiErrorBody
    throw new ApiError(result.status, error.code ?? 'REQUEST_FAILED', error.message ?? '请求失败')
  }
  return body as T
}

export function login(email: string, password: string): Promise<AuthSession> {
  return request('/api/auth/login', {
    method: 'POST',
    credentials: 'same-origin',
    body: JSON.stringify({ email, password }),
  })
}

export function register(email: string, password: string, displayName: string): Promise<AuthSession> {
  return request('/api/auth/register', {
    method: 'POST',
    credentials: 'same-origin',
    body: JSON.stringify({ email, password, displayName }),
  })
}

export function refreshSession(): Promise<AuthSession> {
  return request('/api/auth/refresh', {
    method: 'POST',
    credentials: 'same-origin',
  })
}

export function logoutSession(): Promise<void> {
  return request('/api/auth/logout', {
    method: 'POST',
    credentials: 'same-origin',
  })
}

export function listTrips(accessToken: string): Promise<Trip[]> {
  return request('/api/trips', {}, accessToken)
}

export function getTrip(accessToken: string, tripId: string): Promise<Trip> {
  return request(`/api/trips/${encodeURIComponent(tripId)}`, {}, accessToken)
}

export function createTrip(accessToken: string, input: CreateTripInput): Promise<Trip> {
  return request('/api/trips', {
    method: 'POST',
    body: JSON.stringify(input),
  }, accessToken)
}

export function updateTripConstraints(
  accessToken: string,
  tripId: string,
  input: UpdateTripConstraintsInput,
): Promise<Trip> {
  return request(`/api/trips/${encodeURIComponent(tripId)}/constraints`, {
    method: 'PUT',
    body: JSON.stringify(input),
  }, accessToken)
}

export function createPlanningTask(
  accessToken: string,
  tripId: string,
  idempotencyKey: string,
): Promise<PlanningTask> {
  return request(`/api/trips/${encodeURIComponent(tripId)}/planning-tasks`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
  }, accessToken)
}

export function cancelPlanningTask(accessToken: string, taskId: string): Promise<PlanningTask> {
  return request(`/api/planning-tasks/${encodeURIComponent(taskId)}`, {
    method: 'DELETE',
  }, accessToken)
}

export function getCurrentItinerary(accessToken: string, tripId: string): Promise<Itinerary> {
  return request(`/api/trips/${encodeURIComponent(tripId)}/itinerary`, {}, accessToken)
}

export async function streamPlanningTaskEvents(
  accessToken: string,
  eventStreamUrl: string,
  onEvent: (event: PlanningTaskEvent) => void,
  options: PlanningEventStreamOptions = {},
): Promise<number> {
  const headers: Record<string, string> = {
    Accept: 'text/event-stream',
    Authorization: `Bearer ${accessToken}`,
  }
  if (options.lastEventId !== undefined) headers['Last-Event-ID'] = options.lastEventId.toString()

  const result = await fetch(eventStreamUrl, { headers, signal: options.signal })
  if (!result.ok) {
    let error: ApiErrorBody = {}
    try {
      error = await result.json() as ApiErrorBody
    } catch {
      // Authentication filters can return an empty response.
    }
    throw new ApiError(result.status, error.code ?? 'REQUEST_FAILED', error.message ?? '请求失败')
  }
  if (!result.body) {
    throw new ApiError(502, 'EVENT_STREAM_UNAVAILABLE', '任务状态流不可用')
  }

  const reader = result.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let lastEventId = options.lastEventId ?? 0

  const dispatchBlock = (block: string) => {
    let id: number | undefined
    const dataLines: string[] = []
    for (const line of block.split(/\r?\n/)) {
      if (line === '' || line.startsWith(':')) continue
      const separator = line.indexOf(':')
      const field = separator >= 0 ? line.slice(0, separator) : line
      let value = separator >= 0 ? line.slice(separator + 1) : ''
      if (value.startsWith(' ')) value = value.slice(1)
      if (field === 'id' && /^\d+$/.test(value)) id = Number(value)
      if (field === 'data') dataLines.push(value)
    }
    if (dataLines.length === 0) return
    const event = JSON.parse(dataLines.join('\n')) as PlanningTaskEvent
    onEvent(event)
    lastEventId = id ?? event.eventId
  }

  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    let boundary = buffer.match(/\r?\n\r?\n/)
    while (boundary?.index !== undefined) {
      dispatchBlock(buffer.slice(0, boundary.index))
      buffer = buffer.slice(boundary.index + boundary[0].length)
      boundary = buffer.match(/\r?\n\r?\n/)
    }
    if (done) break
  }
  if (buffer.trim()) dispatchBlock(buffer)
  return lastEventId
}
