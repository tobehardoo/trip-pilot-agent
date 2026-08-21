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
  arrival?: { placeName: string; time: string; placeRef?: PlaceRef } | null
  departure?: { placeName: string; time: string; placeRef?: PlaceRef } | null
  accommodation?: { placeName: string; placeRef?: PlaceRef } | null
  mustVisitPlaces?: string[]
  avoidPlaces?: string[]
  mustVisitPlaceRefs?: PlaceRef[]
  avoidPlaceRefs?: PlaceRef[]
  mealWindows?: Array<{
    mealType: 'BREAKFAST' | 'LUNCH' | 'DINNER'
    startTime: string
    endTime: string
    source?: 'DEFAULT' | 'USER' | 'DISABLED'
  }>
  mobilityLevel?: 'STANDARD' | 'REDUCED' | 'STEP_FREE'
  schemaVersion?: number
}

/**
 * B13-D: structured place reference from a real search candidate.
 * Candidates carry provider provenance and an estimated flag — they are
 * never verification evidence.
 *
 * B13_FIX R5: `selectionToken` is the server-issued, owner-scoped opaque
 * token from the place-search endpoint.  It travels back on save so the
 * server can canonicalize the ref; it is never displayed and never
 * persisted server-side.
 */
export interface PlaceRef {
  provider: 'AMAP' | 'DEMO'
  providerPoiId: string
  name: string
  address: string
  province: string
  city: string
  district: string
  longitude: number
  latitude: number
  estimated?: boolean
  selectionToken?: string
}

export interface PlaceCandidate extends PlaceRef {
  estimated: boolean
}

export interface PlaceSearchResult {
  provider: string
  estimated: boolean
  candidates: PlaceCandidate[]
}

export interface PlaceSearchInput {
  city: string
  keyword: string
  limit?: number
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
  archivedAt: string | null
  region?: RegionRef | null
  planningCoverage?: 'FULL' | 'PARTIAL' | 'BASIC' | 'UNSUPPORTED'
  arrivalAt?: string | null
  departureAt?: string | null
}

export interface RegionRef {
  provinceCode: string
  cityCode: string
  districtCodes: string[]
  provinceName: string
  cityName: string
  districtNames: string[]
  datasetVersion: string
}

export interface TripSearch {
  destination?: string
  status?: string
  startDate?: string
  endDate?: string
  includeArchived?: boolean
  page?: number
  size?: number
}

export interface TripPage {
  items: Trip[]
  page: number
  size: number
  totalElements: number
  totalPages: number
}

export interface CreateTripInput {
  title?: string
  destination: string
  region?: RegionRef
  arrivalAt: string
  departureAt: string
  constraints: Omit<TripConstraints, 'schemaVersion'>
}

export interface UpdateTripMetadataInput {
  expectedVersion: number
  title?: string
}

export interface UpdateTripConstraintsInput extends Omit<TripConstraints, 'schemaVersion'> {
  version: number
}

export interface PlanningTask {
  taskId: string
  tripId: string
  taskType: string
  status: PlanningTaskStatus
  baselineTripVersion: number
  baselineItineraryVersionId?: string | null
  candidateType?: 'EDIT' | 'ROLLBACK' | null
  eventStreamUrl: string
  errorCode?: string | null
  errorCategory?: ProviderErrorCategory | null
  provider?: ProviderSource | null
  operation?: ProviderOperation | null
  retryable?: boolean | null
  retryCount?: number | null
  fallbackAttempted?: boolean | null
  fallbackSucceeded?: boolean | null
  safeMessage?: string | null
  safeProviderCode?: string | null
  requestedProviderMode?: ProviderExecutionMode | null
  primaryProvider?: ProviderSource | null
  actualProviders?: ProviderSource[] | null
  fallbackReason?: string | null
  fallbackOperations?: ProviderFallbackOperation[] | null
  conflicts?: PlanningConflict[] | null
  relaxationSuggestions?: PlanningRelaxationSuggestion[] | null
  feasibilityReport?: unknown
  candidateItinerary?: unknown
  evaluation?: PlanEvaluation | null
  createdAt: string
  updatedAt: string
}

export interface PlanningConflict {
  code: string
  message: string
  affected?: string[]
}

export interface PlanningRelaxationSuggestion {
  code: string
  message: string
}

export type PlanningTaskStatus =
  | 'SUCCEEDED'
  | 'WAITING_USER'
  | 'QUEUED'
  | 'RUNNING'
  | 'FAILED'
  | 'CANCELLED'

export type ProviderExecutionMode =
  | 'DEMO_ONLY'
  | 'REAL_ONLY'
  | 'REAL_WITH_EXPLICIT_FALLBACK'

export type ProviderSource = 'AMAP' | 'DEMO' | 'MIXED' | 'PLANNER'

export type ProviderOperation =
  | 'CONFIGURATION'
  | 'PLANNING'
  | 'REPLANNING'
  | 'POI_SEARCH'
  | 'ROUTE'

export type ProviderErrorCategory =
  | 'CONFIGURATION_ERROR'
  | 'AUTHENTICATION_ERROR'
  | 'PERMISSION_DENIED'
  | 'QUOTA_EXCEEDED'
  | 'RATE_LIMITED'
  | 'TIMEOUT'
  | 'NETWORK_ERROR'
  | 'PROVIDER_UNAVAILABLE'
  | 'INVALID_REQUEST'
  | 'NO_RESULT'
  | 'UNSUPPORTED_MODE'
  | 'MALFORMED_RESPONSE'
  | 'DATA_QUALITY_ERROR'
  | 'PROVIDER_ADAPTER_ERROR'
  | 'PLANNING_INFEASIBLE'
  | 'INTERNAL_ERROR'

export interface ProviderFallbackOperation {
  operation: ProviderOperation
  transitId: string | null
  fromActivityId: string | null
  toActivityId: string | null
  requestedMode: ProviderExecutionMode
  actualProvider: ProviderSource
  errorCategory: ProviderErrorCategory
  errorCode: string
  retryCount: number
}

export type PlanningProgressStage =
  | 'TASK_ACCEPTED'
  | 'CONTEXT_VALIDATING'
  | 'CITY_FACTS_LOADING'
  | 'POI_RECALLING'
  | 'CANDIDATES_RANKING'
  | 'ROUTES_CALCULATING'
  | 'CONSTRAINTS_SOLVING'
  | 'REPAIRING'
  | 'KNOWLEDGE_RETRIEVING'
  | 'RESULT_EXPLAINING'
  | 'RESULT_PUBLISHING'
  | 'RESULT_PERSISTING'

export interface PlanningProgressUpdate {
  eventId: number
  stage: PlanningProgressStage
  sequence: number
  progress: number
  message: string
  statistics: Record<string, number>
  occurredAt: string
}

export interface PlanningTaskEvent {
  eventId: number
  taskId: string
  eventType: string
  schemaVersion: number
  payload: {
    status?: string
    stage?: PlanningProgressStage
    sequence?: number
    progress?: number
    statistics?: Record<string, number>
    errorCode?: string
    errorCategory?: ProviderErrorCategory
    provider?: ProviderSource
    operation?: ProviderOperation
    retryable?: boolean
    retryCount?: number
    fallbackAttempted?: boolean
    fallbackSucceeded?: boolean
    safeMessage?: string
    safeProviderCode?: string
    requestedProviderMode?: ProviderExecutionMode
    primaryProvider?: ProviderSource
    actualProviders?: ProviderSource[] | null
    fallbackReason?: string
    fallbackOperations?: ProviderFallbackOperation[] | null
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
    feasibilityReport?: unknown
    candidateItinerary?: unknown
    evaluation?: unknown
    [key: string]: unknown
  }
  createdAt: string
}

export interface PlanEvaluation {
  schemaVersion: number
  evaluatorVersion: string
  feasible: boolean
  overallScore: number
  dimensions: EvaluationDimensions
  warnings: EvaluationWarning[]
  decisions: DecisionExplanation[]
  summary: string
  evaluatedAt: string
}

export interface EvaluationDimensions {
  constraintSatisfaction: number
  timeFeasibility: number
  budgetFit: number | null
  routeEfficiency: number
  interestMatch: number | null
}

export interface EvaluationWarning {
  code: string
  severity: 'INFO' | 'WARNING' | 'CRITICAL'
  message: string
  dayIndex?: number | null
  entityType: 'PLAN' | 'DAY' | 'ACTIVITY' | 'TRANSIT'
  entityId?: string | null
  metricKey?: string | null
  actualValue?: number | null
  threshold?: number | null
}

export interface DecisionExplanation {
  subjectType: 'PLAN' | 'DAY' | 'ACTIVITY' | 'TRANSIT'
  subjectId?: string | null
  summary: string
  reasonCodes: string[]
  reasons: string[]
  constraintRefs?: string[]
  evidence?: EvaluationEvidence[]
  dayIndex?: number | null
}

export interface EvaluationEvidence {
  key: string
  label: string
  value: string
}

export type GuideSourceType =
  | 'PUBLIC_GUIDE_URL'
  | 'PASTED_TEXT'
  | 'TEXT_FILE'
  | 'XIAOHONGSHU_SHARED_TEXT'
  | 'CITY_INTELLIGENCE'

export type GuideImportInput =
  | {
      sourceType: 'PUBLIC_GUIDE_URL'
      sourceUrl: string
    }
  | {
      sourceType: Exclude<GuideSourceType, 'PUBLIC_GUIDE_URL' | 'CITY_INTELLIGENCE'>
      title: string
      content: string
    }
  | {
      sourceType: 'CITY_INTELLIGENCE'
      city: string
      startDate: string
      endDate: string
    }

export interface GuideFact {
  id: string
  category:
    | 'ATTRACTION'
    | 'DINING'
    | 'TRANSPORT'
    | 'TIMING'
    | 'COST'
    | 'QUEUE'
    | 'RESERVATION'
    | 'LOCATION'
    | 'WEATHER'
    | 'TIP'
  statement: string
  evidence: string
  confidence: number
  observedAt: string
  expiresAt: string
  effectiveDate?: string | null
}

export interface GuideImport {
  id: string
  sourceType: GuideSourceType
  sourceUrl: string
  finalUrl: string
  sourceHost: string
  title: string
  excerpt: string
  contentHash: string
  fetchedAt: string
  enabled: boolean
  facts: GuideFact[]
  quality: GuideQuality | null
}

export interface GuideQuality {
  overall: number
  label: string
  dimensions: GuideQualityDimensions
}

export interface GuideQualityDimensions {
  factDensity: number
  categoryCoverage: number
  strongFactRatio: number
  conflictRate: number
  freshnessHealth: number
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
  locked: boolean
  typeCode: string | null
  typeName: string | null
  kind: 'ATTRACTION' | 'EXPERIENCE' | 'MEAL' | 'ACCOMMODATION' | 'ARRIVAL' | 'DEPARTURE' | null
  timeFixed: boolean | null
}

export interface ItineraryTransitLeg {
  id: string
  legOrder: number
  fromActivityId: string
  toActivityId: string
  mode: 'WALKING' | 'TRANSIT' | 'DRIVING' | 'TAXI'
  locked: boolean
  distanceMeters: number
  durationSeconds: number
  provider: 'AMAP' | 'DEMO'
  estimated: boolean
  estimatedCost: number
  providerRouteId: string | null
  calculatedAt: string
  stale: boolean
  modeLabel?: string
  routeDurationSeconds?: number
  waitSeconds?: number
  costSource?: 'PROVIDER' | 'RULE_ESTIMATE' | 'DEMO' | 'UNKNOWN'
  costMeaning?: 'NONE' | 'TRANSIT_FARE' | 'ROAD_TOLL' | 'TAXI_FARE_ESTIMATE'
  displayCost?: number | null
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
  provider: ProviderSource
  days: Array<{
    date: string
    dayType: 'ARRIVAL_DAY' | 'FULL_DAY' | 'DEPARTURE_DAY' | 'SPECIAL_ACTIVITY_DAY' | null
    activities: ItineraryActivity[]
    transitLegs: ItineraryTransitLeg[]
  }>
  knowledge: ItineraryKnowledge
  factImpacts?: ItineraryFactImpact[]
  rollbackFromVersionId?: string | null
  accommodationStatus?: 'CONFIRMED' | 'AREA_ESTIMATED' | 'UNRESOLVED' | null
  accommodationLabel?: string | null
  createdAt: string
}

export interface ItineraryFactImpact {
  factId: string
  category: string
  date: string | null
  effect: string
  targetPoiId: string | null
  targetName: string | null
  reason: string
  sourceName: string
  sourceType: string
  sourceUrl: string | null
  reliabilityLevel: string
  checkedAt: string
  evidence: string
  stale: boolean
  conflicted: boolean
  refreshFailed: boolean
}

export interface ItineraryVersionSummary {
  versionId: string
  versionNumber: number
  parentVersionId: string | null
  planningTaskId: string | null
  versionSource: 'PLANNING_TASK' | 'USER_EDIT' | 'LOCAL_REPLAN' | 'ROLLBACK'
  title: string
  estimatedTotalCost: number
  provider: 'AMAP' | 'DEMO'
  rollbackFromVersionId: string | null
  createdAt: string
  current: boolean
  feasibility: unknown
}

export interface ItineraryVersionDiff {
  fromVersionId: string
  toVersionId: string
  addedActivities: Array<{ key: string; title: string; date: string }>
  removedActivities: Array<{ key: string; title: string; date: string }>
  changedActivities: Array<{
    before: { key: string; title: string; date: string }
    after: { key: string; title: string; date: string }
    changes: string[]
  }>
  addedTransitLegs: ItineraryTransitDiff[]
  removedTransitLegs: ItineraryTransitDiff[]
  changedTransitLegs: Array<{
    before: ItineraryTransitDiff
    after: ItineraryTransitDiff
    changes: string[]
  }>
  addedFactImpacts: ItineraryFactImpact[]
  removedFactImpacts: ItineraryFactImpact[]
  changedFactImpacts: Array<{
    before: ItineraryFactImpact
    after: ItineraryFactImpact
    changes: string[]
  }>
  fromTotalCost: number
  toTotalCost: number
  budgetChange: number
}

export interface ItineraryTransitDiff {
  key: string
  date: string
  fromTitle: string
  toTitle: string
  mode: string
  distanceMeters: number
  durationSeconds: number
  provider: string
  estimated: boolean
  locked: boolean
  estimatedCost: number
  providerRouteId: string | null
  calculatedAt: string
  stale: boolean
}

export type ItineraryEditOperation =
  | 'DELETE_ACTIVITY'
  | 'LOCK_ACTIVITY'
  | 'UNLOCK_ACTIVITY'
  | 'MOVE_ACTIVITY'
  | 'UPDATE_TRANSIT_LEG'

export interface ItineraryEditInput {
  baseVersionId: string
  operation: ItineraryEditOperation
  activityId?: string
  transitLegId?: string
  targetDate?: string
  targetOrder?: number
  targetStartTime?: string
  targetEndTime?: string
  transitMode?: 'AUTO' | 'WALKING' | 'TRANSIT' | 'TAXI'
  transitLocked?: boolean
  /** Client-generated UUID for idempotency.  Reused on retry, regenerated on re-edit. */
  idempotencyKey?: string
}

export interface ItineraryEditPreview {
  operation: ItineraryEditOperation
  canApply: boolean
  requiresReplan: boolean
  transitSelectionState: 'AVAILABLE' | 'REQUIRES_REPLAN' | 'UNAVAILABLE' | 'USER_LOCKED' | null
  impactedDates: string[]
  impactedActivityIds: string[]
  warnings: string[]
  blockingReasons: Array<{
    code: string
    message: string
  }>
}

export interface ItineraryReplanInput {
  baseVersionId: string
  dates: string[]
}

export interface ItineraryShareStatus {
  id: string
  versionId: string
  expiresAt: string | null
  revokedAt: string | null
  createdAt: string
}

export interface CreatedItineraryShare extends ItineraryShareStatus {
  shareToken: string
}

export interface SharedItinerary {
  title: string
  estimatedTotalCost: number
  provider: 'AMAP' | 'DEMO'
  days: Array<{
    date: string
    activities: Array<{
      title: string
      startTime: string
      endTime: string
      estimatedCost: number
      address: string | null
    }>
    transitLegs: Array<{
      mode: string
      modeLabel?: string
      distanceMeters: number
      durationSeconds: number
      routeDurationSeconds?: number
      waitSeconds?: number
      estimatedCost?: number | null
      displayCost?: number | null
      costSource?: string
      costMeaning?: string
      provider: string
      estimated: boolean
      stale: boolean
    }>
  }>
  sources: Array<{
    title: string
    sourceName: string
    sourceUrl: string
    reliabilityLevel: string
  }>
  generatedAt: string
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

export function searchTrips(accessToken: string, search: TripSearch = {}): Promise<TripPage> {
  const query = new URLSearchParams()
  if (search.destination?.trim()) query.set('destination', search.destination.trim())
  if (search.status?.trim()) query.set('status', search.status.trim())
  if (search.startDate) query.set('startDate', search.startDate)
  if (search.endDate) query.set('endDate', search.endDate)
  query.set('includeArchived', String(search.includeArchived ?? false))
  query.set('page', String(search.page ?? 0))
  query.set('size', String(search.size ?? 100))
  return request(`/api/trips/search?${query}`, {}, accessToken)
}

export function archiveTrip(accessToken: string, tripId: string): Promise<void> {
  return request(`/api/trips/${encodeURIComponent(tripId)}/archive`, { method: 'POST' }, accessToken)
}

export function restoreTrip(accessToken: string, tripId: string): Promise<void> {
  return request(`/api/trips/${encodeURIComponent(tripId)}/restore`, { method: 'POST' }, accessToken)
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

export function updateTripMetadata(
  accessToken: string,
  tripId: string,
  input: UpdateTripMetadataInput,
): Promise<Trip> {
  return request(`/api/trips/${encodeURIComponent(tripId)}/metadata`, {
    method: 'PUT',
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

/**
 * B13-D: owner-authenticated place search proxy.  The browser never talks
 * to a map provider; candidates carry explicit demo/estimated flags.
 */
export function searchPlaces(
  accessToken: string,
  input: PlaceSearchInput,
  signal?: AbortSignal,
): Promise<PlaceSearchResult> {
  return request('/api/trips/places/search', {
    method: 'POST',
    body: JSON.stringify(input),
    signal,
  }, accessToken)
}

export function listGuideImports(accessToken: string, tripId: string): Promise<GuideImport[]> {
  return request(
    `/api/trips/${encodeURIComponent(tripId)}/guide-imports`,
    {},
    accessToken,
  )
}

export function createGuideImport(
  accessToken: string,
  tripId: string,
  input: GuideImportInput,
): Promise<GuideImport> {
  return request(`/api/trips/${encodeURIComponent(tripId)}/guide-imports`, {
    method: 'POST',
    body: JSON.stringify(input),
  }, accessToken)
}

export function updateGuideImportEnabled(
  accessToken: string,
  tripId: string,
  guideImportId: string,
  enabled: boolean,
): Promise<GuideImport> {
  return request(
    `/api/trips/${encodeURIComponent(tripId)}/guide-imports/${encodeURIComponent(guideImportId)}`,
    {
      method: 'PUT',
      body: JSON.stringify({ enabled }),
    },
    accessToken,
  )
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

export function getPlanningTask(accessToken: string, taskId: string): Promise<PlanningTask> {
  return request(`/api/planning-tasks/${encodeURIComponent(taskId)}`, {}, accessToken)
}

export function getLatestPlanningTask(
  accessToken: string,
  tripId: string,
): Promise<PlanningTask> {
  return request(`/api/trips/${encodeURIComponent(tripId)}/planning-tasks/latest`, {}, accessToken)
}

export function getCurrentItinerary(accessToken: string, tripId: string): Promise<Itinerary> {
  return request(`/api/trips/${encodeURIComponent(tripId)}/itinerary`, {}, accessToken)
}

export function listItineraryVersions(
  accessToken: string,
  tripId: string,
): Promise<ItineraryVersionSummary[]> {
  return request(`/api/trips/${encodeURIComponent(tripId)}/itinerary/versions`, {}, accessToken)
}

export function diffItineraryVersions(
  accessToken: string,
  tripId: string,
  fromVersionId: string,
  toVersionId: string,
): Promise<ItineraryVersionDiff> {
  const query = new URLSearchParams({ from: fromVersionId, to: toVersionId })
  return request(
    `/api/trips/${encodeURIComponent(tripId)}/itinerary/versions/diff?${query}`,
    {},
    accessToken,
  )
}

export function rollbackItinerary(
  accessToken: string,
  tripId: string,
  sourceVersionId: string,
  expectedCurrentVersionId: string,
  idempotencyKey: string = crypto.randomUUID(),
): Promise<PlanningTask> {
  return request(`/api/trips/${encodeURIComponent(tripId)}/itinerary/rollbacks`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ sourceVersionId, expectedCurrentVersionId }),
  }, accessToken)
}

export function previewItineraryEdit(
  accessToken: string,
  tripId: string,
  input: ItineraryEditInput,
): Promise<ItineraryEditPreview> {
  return request(`/api/trips/${encodeURIComponent(tripId)}/itinerary/edits/preview`, {
    method: 'POST',
    body: JSON.stringify(input),
  }, accessToken)
}

export function applyItineraryEdit(
  accessToken: string,
  tripId: string,
  input: ItineraryEditInput,
  idempotencyKey: string,
): Promise<PlanningTask> {
  return request(`/api/trips/${encodeURIComponent(tripId)}/itinerary/edits`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify(input),
  }, accessToken)
}

export function commitItineraryEdits(
  accessToken: string,
  tripId: string,
  baseVersionId: string,
  edits: ItineraryEditInput[],
  idempotencyKey: string,
): Promise<PlanningTask> {
  return request(`/api/trips/${encodeURIComponent(tripId)}/itinerary/edits/commit`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ baseVersionId, edits }),
  }, accessToken)
}

export function createItineraryReplan(
  accessToken: string,
  tripId: string,
  input: ItineraryReplanInput,
  idempotencyKey: string,
): Promise<PlanningTask> {
  return request(`/api/trips/${encodeURIComponent(tripId)}/itinerary/replans`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify(input),
  }, accessToken)
}

export function listItineraryShares(
  accessToken: string,
  tripId: string,
): Promise<ItineraryShareStatus[]> {
  return request(`/api/trips/${encodeURIComponent(tripId)}/itinerary/shares`, {}, accessToken)
}

export function createItineraryShare(
  accessToken: string,
  tripId: string,
  versionId: string,
  expiresAt?: string,
): Promise<CreatedItineraryShare> {
  return request(`/api/trips/${encodeURIComponent(tripId)}/itinerary/shares`, {
    method: 'POST',
    body: JSON.stringify({ versionId, ...(expiresAt ? { expiresAt } : {}) }),
  }, accessToken)
}

export function revokeItineraryShare(
  accessToken: string,
  tripId: string,
  shareId: string,
): Promise<void> {
  return request(`/api/trips/${encodeURIComponent(tripId)}/itinerary/shares/${encodeURIComponent(shareId)}`, {
    method: 'DELETE',
  }, accessToken)
}

export function getSharedItinerary(shareToken: string): Promise<SharedItinerary> {
  return request(`/api/shares/${encodeURIComponent(shareToken)}`)
}

export async function downloadItineraryExport(
  accessToken: string,
  tripId: string,
  versionId: string,
  format: 'ics' | 'pdf',
): Promise<void> {
  const query = new URLSearchParams({ versionId })
  const result = await fetch(
    `/api/trips/${encodeURIComponent(tripId)}/itinerary/exports/${format}?${query}`,
    { headers: { Authorization: `Bearer ${accessToken}` } },
  )
  if (!result.ok) {
    let body: ApiErrorBody = {}
    try {
      body = await result.json() as ApiErrorBody
    } catch {
      // Binary endpoints can fail before emitting a JSON error body.
    }
    throw new ApiError(result.status, body.code ?? 'REQUEST_FAILED', body.message ?? '导出失败')
  }
  const contentDisposition = result.headers.get('Content-Disposition') ?? ''
  const filename = contentDisposition.match(/filename\*?=(?:UTF-8''|"?)([^";]+)/i)?.[1]
    ?? `trip-pilot-itinerary.${format}`
  const objectUrl = URL.createObjectURL(await result.blob())
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = decodeURIComponent(filename)
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0)
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
