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
  | 'IMAGE_OCR'
  | 'CITY_INTELLIGENCE'

export interface GuideImageInput {
  dataBase64: string
  fileName?: string
  contentType?: string
}

export type GuideImportInput =
  | {
      sourceType: 'PUBLIC_GUIDE_URL'
      sourceUrl: string
    }
  | {
      sourceType: Exclude<
        GuideSourceType,
        'PUBLIC_GUIDE_URL' | 'CITY_INTELLIGENCE' | 'IMAGE_OCR'
      >
      title: string
      content: string
    }
  | {
      sourceType: 'IMAGE_OCR'
      images: GuideImageInput[]
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
  /** B1 费用来源：真实价格(PROVIDER) 或估算(RULE/CATEGORY/CITY_ESTIMATE/DEMO/UNKNOWN) */
  costSource?:
    | 'PROVIDER'
    | 'RULE_ESTIMATE'
    | 'CATEGORY_ESTIMATE'
    | 'CITY_ESTIMATE'
    | 'DEMO'
    | 'UNKNOWN'
  /** 活动描述（来自攻略/智能体生成） */
  description?: string | null
  /** 推荐理由 */
  reason?: string | null
  /** 游览建议 */
  tips?: string | null
  /** 交通提示 */
  transportNote?: string | null
  /** 注意事项 */
  precaution?: string | null
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
  | 'REPLACE_ACTIVITY'
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
  // 功能① REPLACE_ACTIVITY：新地点（真实 POI 搜索结果）
  newTitle?: string
  newPoiId?: string
  newLongitude?: number | null
  newLatitude?: number | null
  newAddress?: string | null
  newTypeName?: string | null
  newKind?: string | null
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
      costSource?: string
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
 * Agent dialog (Plan B v0.1): chat turns + clarification cards.
 * Conversation state lives in the agent service; each call returns the full
 * transcript and the current slot view.
 */
export interface AgentDialogAnchor {
  place: string
  time: string
}

export interface AgentDialogOption {
  action: 'SET' | 'CONFIRM' | 'EDIT' | 'SKIP' | 'ASK'
  label: string
  value?: string | number | string[] | AgentDialogAnchor | null
}

export interface AgentDialogMessage {
  role: 'user' | 'agent'
  text: string
  kind: 'TEXT' | 'CLARIFY' | 'SUMMARY'
  options: AgentDialogOption[]
}

export interface AgentDialogSlotView {
  value: string | number | string[] | AgentDialogAnchor | null
  state: 'UNKNOWN' | 'INFERRED' | 'CONFIRMED'
  source: 'TRIP' | 'USER_EXPLICIT' | 'USER_CONFIRMED' | 'LLM_INFERRED'
}

export interface AgentDialogReply {
  phase: 'COLLECTING' | 'READY'
  ready: boolean
  messages: AgentDialogMessage[]
  slots: Record<string, AgentDialogSlotView>
}

/** 创建模式首轮种子：目的地 + 日期作为 TRIP 事实注入对话（服务端锁定，Agent 不再询问）。 */
export interface AgentDialogTripContext {
  destination: string
  startDate?: string | null
  endDate?: string | null
  /** Composer 右下出行设置：人数/预算随每轮 tripContext 提交（服务端按 USER_EXPLICIT 种入）。 */
  travelers?: number | null
  budgetAmount?: number | null
}

export interface AgentDialogInput {
  message?: string
  option?: AgentDialogOption
  reset?: boolean
  tripContext?: AgentDialogTripContext
}

export function sendAgentDialogue(
  accessToken: string,
  tripId: string,
  input: AgentDialogInput,
): Promise<AgentDialogReply> {
  return request(`/api/trips/${encodeURIComponent(tripId)}/agent-dialogue`, {
    method: 'POST',
    body: JSON.stringify(input),
  }, accessToken)
}

/** Plan C: trip-less creation dialog, keyed by a client-generated sessionId. */
export function sendAgentCreateDialogue(
  accessToken: string,
  sessionId: string,
  input: AgentDialogInput,
): Promise<AgentDialogReply> {
  return request('/api/agent/dialogue', {
    method: 'POST',
    body: JSON.stringify({ sessionId, ...input }),
  }, accessToken)
}

/** Create the trip from the dialog's confirmed slots (server-pulled truth). */
export function createTripFromAgent(accessToken: string, sessionId: string): Promise<Trip> {
  return request('/api/agent/trips', {
    method: 'POST',
    body: JSON.stringify({ sessionId }),
  }, accessToken)
}

// ── P2.8b: agent-path dialog runs (SSE-driven) ──────────────────────

export interface AgentStepView {
  seq: number
  tool: string
  ok: boolean
  summary: string
  errorCode?: string | null
}

export interface AgentSlotViewWire {
  value: string | number | string[] | Record<string, unknown> | null
  state: string
}

export interface AgentCompletedView {
  summary: string
  itinerary: Record<string, unknown>
  slots?: Record<string, AgentSlotViewWire> | null
}

export interface AgentAskUserView {
  question: string
  options?: string[] | null
  expectedType?: string | null
}

export interface AgentRunFinishedView {
  status: 'STOPPED' | 'FAILED' | 'EXPIRED' | 'ANSWERED'
  reasonCode: string
  message: string
}

export type AgentDialogEventView = {
  eventId: number
  tripId: string
  runId: string
  eventType: 'AGENT_ASK_USER'
  payload: AgentAskUserView
} | {
  eventId: number
  tripId: string
  runId: string
  eventType: 'AGENT_STEP'
  payload: AgentStepView
} | {
  eventId: number
  tripId: string
  runId: string
  eventType: 'AGENT_COMPLETED'
  payload: AgentCompletedView
} | {
  eventId: number
  tripId: string
  runId: string
  eventType: 'AGENT_RUN_FINISHED'
  payload: AgentRunFinishedView
}

export interface AgentEventStreamOptions {
  lastMessageId?: number
  signal?: AbortSignal
}

export interface AgentCommandQueued {
  eventId: string
  status: string
}

/**
 * Stream the trip's agent dialog events (SSE with Bearer auth; the server
 * replays history after `lastMessageId`).  Uses the shared SSE client.
 */
export function streamAgentDialogEvents(
  accessToken: string,
  tripId: string,
  onEvent: (event: AgentDialogEventView, messageId: number) => void,
  options: AgentEventStreamOptions = {},
): Promise<number> {
  const url = `/api/trips/${encodeURIComponent(tripId)}/agent-dialogue/events`
  return streamSseEvents(
    accessToken,
    url,
    (event) => onEvent(event as unknown as AgentDialogEventView, event.eventId),
    { lastEventId: options.lastMessageId, signal: options.signal },
  )
}

/** Open a dialog run: queue an AGENT_START command via the outbox. */
export function startAgentRun(
  accessToken: string,
  tripId: string,
  message: string,
  idempotencyKey?: string,
): Promise<AgentCommandQueued> {
  return request(`/api/trips/${encodeURIComponent(tripId)}/agent-dialogue/runs`, {
    method: 'POST',
    headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined,
    body: JSON.stringify({ message }),
  }, accessToken)
}

/** Continue a WAITING_USER run: queue an AGENT_RESUME command. */
export function answerAgentRun(
  accessToken: string,
  tripId: string,
  runId: string,
  answer: string,
  idempotencyKey?: string,
): Promise<AgentCommandQueued> {
  return request(
    `/api/trips/${encodeURIComponent(tripId)}/agent-dialogue/runs/${encodeURIComponent(runId)}/answers`,
    {
      method: 'POST',
      headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined,
      body: JSON.stringify({ answer }),
    },
    accessToken,
  )
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

export function getPlanningTask(accessToken: string, taskId: string): Promise<PlanningTask> {
  return request(`/api/planning-tasks/${encodeURIComponent(taskId)}`, {}, accessToken)
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

export async function streamSseEvents(
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
