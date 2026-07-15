export const REFRESH_TOKEN_KEY = 'trip-pilot.refresh-token'

export interface User {
  id: string
  email: string
  displayName: string
}

export interface AuthSession {
  user: User
  accessToken: string
  refreshToken: string
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
    body: JSON.stringify({ email, password }),
  })
}

export function register(email: string, password: string, displayName: string): Promise<AuthSession> {
  return request('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, password, displayName }),
  })
}

export function refreshSession(refreshToken: string): Promise<AuthSession> {
  return request('/api/auth/refresh', {
    method: 'POST',
    body: JSON.stringify({ refreshToken }),
  })
}

export function logoutSession(refreshToken: string): Promise<void> {
  return request('/api/auth/logout', {
    method: 'POST',
    body: JSON.stringify({ refreshToken }),
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
