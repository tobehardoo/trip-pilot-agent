<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'

import AuthView, { type AuthSubmission } from '../components/AuthView.vue'
import TripDashboard from '../components/TripDashboard.vue'
import TripDetail from '../components/TripDetail.vue'
import { useAuthStore } from '../app/stores/auth'
import {
  ApiError,
  applyItineraryEdit,
  commitItineraryEdits,
  archiveTrip,
  cancelPlanningTask,
  createGuideImport,
  createItineraryShare,
  createItineraryReplan,
  createPlanningTask,
  createTrip,
  diffItineraryVersions,
  downloadItineraryExport,
  getCurrentItinerary,
  getLatestPlanningTask,
  getPlanningTask,
  getTrip,
  listTrips,
  searchTrips,
  listGuideImports,
  listItineraryVersions,
  listItineraryShares,
  login,
  logoutSession,
  previewItineraryEdit,
  refreshSession,
  register,
  rollbackItinerary,
  revokeItineraryShare,
  restoreTrip,
  streamPlanningTaskEvents,
  updateGuideImportEnabled,
  updateTripConstraints,
  type AuthSession,
  type CreateTripInput,
  type GuideImport,
  type GuideImportInput,
  type Itinerary,
  type ItineraryEditInput,
  type ItineraryEditPreview,
  type ItineraryReplanInput,
  type ItineraryShareStatus,
  type ItineraryVersionDiff,
  type ItineraryVersionSummary,
  type PlanEvaluation,
  type PlanningTask,
  type PlanningTaskEvent,
  type PlanningProgressStage,
  type PlanningProgressUpdate,
  type Trip,
  type UpdateTripConstraintsInput,
} from '../lib/api'
import {
  readPlanningEventOutcome,
  readPlanningTaskOutcome,
  type PlanningOutcome,
} from '../lib/feasibility'
import { tripDetailPath, type AppRoute } from '../lib/routes'

class SessionChangedError extends Error {}

const authStore = useAuthStore()
const { phase, user, accessToken } = storeToRefs(authStore)
const currentRoute = useRoute()
const router = useRouter()
const busy = ref(false)
const error = ref<string | null>(null)
const trips = ref<Trip[]>([])
const destinationSearch = ref('')
const includeArchived = ref(false)
const selectedTrip = ref<Trip | null>(null)
const route = computed<AppRoute>(() => {
  const tripId = typeof currentRoute.params.tripId === 'string'
    ? currentRoute.params.tripId
    : null

  if (tripId && ['trip-detail', 'trip-plan', 'trip-versions'].includes(String(currentRoute.name))) {
    return { name: 'trip-detail', tripId }
  }

  if (['login', 'register', 'trip-list', 'trip-create'].includes(String(currentRoute.name))) {
    return { name: 'trip-list' }
  }

  return { name: 'not-found' }
})
const detailBusy = ref(false)
const detailError = ref<string | null>(null)
const itinerary = ref<Itinerary | null>(null)
const itineraryBusy = ref(false)
const itineraryError = ref<string | null>(null)
const itineraryVersions = ref<ItineraryVersionSummary[]>([])
const evaluation = ref<PlanEvaluation | null | undefined>(undefined)
const evaluationBusy = ref(false)
const evaluationError = ref<string | null>(null)
const itineraryShares = ref<ItineraryShareStatus[]>([])
const versionBusy = ref(false)
const versionError = ref<string | null>(null)
const planningState = ref<'idle' | 'queued' | 'succeeded' | 'waiting_user' | 'failed' | 'cancelled'>('idle')
const planningError = ref<string | null>(null)
const planningProgress = ref<PlanningProgressUpdate | null>(null)
const planningProgressHistory = ref<PlanningProgressUpdate[]>([])
const authoritativeFeasibilityReport = ref<unknown>(null)
const candidateItinerary = ref<unknown>(null)
const feasibilityLoadState = ref<'idle' | 'loaded'>('idle')
const guideImports = ref<GuideImport[]>([])
const guideBusy = ref(false)
const guideError = ref<string | null>(null)
const activePlanningTaskId = ref<string | null>(null)
let sessionGeneration = 0
let detailRequestSequence = 0
let itineraryRequestSequence = 0
let versionRequestSequence = 0
let evaluationRequestSequence = 0
let shareRequestSequence = 0
let listRequestSequence = 0
let busyRequestSequence = 0
let planningRequestSequence = 0
let guideRequestSequence = 0
let refreshInFlight: Promise<void> | null = null
let planningStreamController: AbortController | null = null
let removeNavigationHook: (() => void) | null = null

function errorMessage(cause: unknown) {
  if (cause instanceof ApiError) return cause.message
  return '无法连接业务服务，请稍后重试'
}

function applySession(session: AuthSession) {
  authStore.applySession(session)
}

function beginBusy() {
  busyRequestSequence += 1
  busy.value = true
  return busyRequestSequence
}

function endBusy(requestSequence: number) {
  if (requestSequence === busyRequestSequence) busy.value = false
}

function isCurrentSession(generation: number) {
  return generation === sessionGeneration && phase.value === 'authenticated'
}

function assertCurrentSession(generation: number) {
  if (!isCurrentSession(generation)) throw new SessionChangedError('Session changed while request was in flight')
}

function clearLocalSession() {
  stopPlanningStream()
  sessionGeneration += 1
  detailRequestSequence += 1
  itineraryRequestSequence += 1
  versionRequestSequence += 1
  listRequestSequence += 1
  busyRequestSequence += 1
  refreshInFlight = null
  authStore.clearSession()
  busy.value = false
  trips.value = []
  destinationSearch.value = ''
  includeArchived.value = false
  selectedTrip.value = null
  detailBusy.value = false
  detailError.value = null
  itinerary.value = null
  itineraryBusy.value = false
  itineraryError.value = null
  itineraryVersions.value = []
  evaluationRequestSequence += 1
  evaluation.value = undefined
  evaluationBusy.value = false
  evaluationError.value = null
  itineraryShares.value = []
  versionBusy.value = false
  versionError.value = null
  guideImports.value = []
  guideBusy.value = false
  guideError.value = null
  guideRequestSequence += 1
  authoritativeFeasibilityReport.value = null
  candidateItinerary.value = null
  feasibilityLoadState.value = 'idle'
}

function stopPlanningStream(resetState = true) {
  planningRequestSequence += 1
  planningStreamController?.abort()
  planningStreamController = null
  if (resetState) {
    planningState.value = 'idle'
    planningError.value = null
    activePlanningTaskId.value = null
    planningProgress.value = null
    planningProgressHistory.value = []
    authoritativeFeasibilityReport.value = null
    candidateItinerary.value = null
    feasibilityLoadState.value = 'idle'
  }
}

function syncTripInList(loadedTrip: Trip) {
  listRequestSequence += 1
  trips.value = trips.value.map((trip) => trip.id === loadedTrip.id ? loadedTrip : trip)
}

async function loadTrips(forceSearch = false) {
  const requestSequence = ++listRequestSequence
  if (!forceSearch && !destinationSearch.value && !includeArchived.value) {
    const loadedTrips = await withAccessToken((token) => listTrips(token))
    if (requestSequence === listRequestSequence) trips.value = loadedTrips
    return
  }
  const loadedTrips = await withAccessToken((token) => searchTrips(token, {
    destination: destinationSearch.value,
    includeArchived: includeArchived.value,
    page: 0,
    size: 100,
  }))
  if (requestSequence === listRequestSequence) trips.value = loadedTrips.items
}

async function loadTrip(tripId: string, preserveCurrentTrip = false): Promise<boolean> {
  const requestSequence = ++detailRequestSequence
  const generation = sessionGeneration
  clearEvaluation()
  detailBusy.value = true
  detailError.value = null
  if (!preserveCurrentTrip) {
    selectedTrip.value = null
    itinerary.value = null
    itineraryError.value = null
    itineraryVersions.value = []
    itineraryShares.value = []
    versionError.value = null
    guideImports.value = []
    guideError.value = null
  }
  try {
    const loadedTrip = await withAccessToken((token) => getTrip(token, tripId))
    if (!isCurrentDetailRequest(requestSequence, tripId)) return false
    selectedTrip.value = loadedTrip
    syncTripInList(loadedTrip)
    await Promise.all([
      loadItinerary(tripId),
      loadGuideImportsForTrip(tripId),
      loadItineraryVersionsForTrip(tripId),
      loadItinerarySharesForTrip(tripId),
    ])
    if (!isCurrentDetailRequest(requestSequence, tripId) || !isCurrentSession(generation)) return false
    await loadEvaluationForCurrentVersion(tripId, requestSequence, generation)
    await hydrateLatestPlanningTask(tripId, requestSequence, generation)
    return true
  } catch (cause) {
    if (!isCurrentDetailRequest(requestSequence, tripId)) return false
    if (!preserveCurrentTrip) detailError.value = errorMessage(cause)
    return false
  } finally {
    if (requestSequence === detailRequestSequence) detailBusy.value = false
  }
}

async function loadItineraryVersionsForTrip(tripId: string): Promise<boolean> {
  const requestSequence = ++versionRequestSequence
  versionBusy.value = true
  versionError.value = null
  try {
    const loaded = await withAccessToken((token) => listItineraryVersions(token, tripId))
    if (!isCurrentVersionRequest(requestSequence, tripId)) return false
    itineraryVersions.value = loaded
    return true
  } catch (cause) {
    if (!isCurrentVersionRequest(requestSequence, tripId)) return false
    versionError.value = errorMessage(cause)
    return false
  } finally {
    if (requestSequence === versionRequestSequence) versionBusy.value = false
  }
}

async function loadItinerarySharesForTrip(tripId: string): Promise<boolean> {
  const requestSequence = ++shareRequestSequence
  try {
    const loaded = await withAccessToken((token) => listItineraryShares(token, tripId))
    if (requestSequence !== shareRequestSequence
      || route.value.name !== 'trip-detail'
      || route.value.tripId !== tripId) return false
    itineraryShares.value = loaded
    return true
  } catch {
    if (requestSequence === shareRequestSequence) itineraryShares.value = []
    return false
  }
}

function isCurrentVersionRequest(requestSequence: number, tripId: string) {
  return requestSequence === versionRequestSequence
    && route.value.name === 'trip-detail'
    && route.value.tripId === tripId
}

function clearEvaluation() {
  evaluationRequestSequence += 1
  evaluation.value = undefined
  evaluationBusy.value = false
  evaluationError.value = null
  authoritativeFeasibilityReport.value = null
  candidateItinerary.value = null
  feasibilityLoadState.value = 'idle'
}

/** Clears every terminal outcome value without touching planningState. */
function clearPlanningOutcome() {
  authoritativeFeasibilityReport.value = null
  candidateItinerary.value = null
  evaluation.value = undefined
  feasibilityLoadState.value = 'idle'
  evaluationError.value = null
}

/**
 * Single state application for every outcome source (Task API hydration,
 * SSE live, SSE replay).  The outcome parser has already fail-closed the
 * status/report/candidate/evaluation combination; this only maps the
 * discriminated result onto component state.
 */
function applyOutcomeState(outcome: PlanningOutcome) {
  switch (outcome.kind) {
    case 'completed':
      planningState.value = 'succeeded'
      authoritativeFeasibilityReport.value = outcome.report
      candidateItinerary.value = null
      evaluation.value = outcome.evaluation
      feasibilityLoadState.value = 'loaded'
      evaluationError.value = null
      break
    case 'review':
      planningState.value = 'waiting_user'
      authoritativeFeasibilityReport.value = outcome.report
      candidateItinerary.value = outcome.candidate
      evaluation.value = undefined
      feasibilityLoadState.value = 'loaded'
      evaluationError.value = null
      break
    case 'queued':
      planningState.value = 'queued'
      clearPlanningOutcome()
      break
    case 'failed':
      planningState.value = 'failed'
      planningError.value = outcome.errorMessage ?? '行程规划失败，请调整条件后重试'
      clearPlanningOutcome()
      break
    case 'cancelled':
      planningState.value = 'cancelled'
      planningError.value = null
      clearPlanningOutcome()
      break
    case 'malformed':
      planningState.value = 'failed'
      planningError.value = '规划结果无法安全读取，请重新规划'
      clearPlanningOutcome()
      break
  }
}

function isCurrentEvaluationOwner(tripId: string, detailSequence: number, generation: number) {
  return detailSequence === detailRequestSequence
    && isCurrentSession(generation)
    && route.value.name === 'trip-detail'
    && route.value.tripId === tripId
}

async function loadEvaluationForCurrentVersion(
  tripId: string,
  detailSequence = detailRequestSequence,
  generation = sessionGeneration,
): Promise<boolean> {
  if (!isCurrentEvaluationOwner(tripId, detailSequence, generation)) return false
  const requestSequence = ++evaluationRequestSequence
  evaluation.value = undefined
  evaluationBusy.value = false
  evaluationError.value = null
  const currentItinerary = itinerary.value
  const currentVersion = itineraryVersions.value.find((version) => (
    version.current && version.versionId === currentItinerary?.versionId
  ))
  if (!currentItinerary || !currentVersion?.planningTaskId) return true

  const taskId = currentVersion.planningTaskId
  evaluationBusy.value = true
  try {
    const task = await withAccessToken((token) => getPlanningTask(token, taskId))
    if (requestSequence !== evaluationRequestSequence
      || !isCurrentEvaluationOwner(tripId, detailSequence, generation)
      || itinerary.value?.versionId !== currentVersion.versionId) return false
    if (task.taskId !== taskId || task.tripId !== tripId) {
      evaluationError.value = '行程质量评估暂时无法加载，请稍后重试'
      return false
    }
    const outcome = readPlanningTaskOutcome(task)
    if (outcome.kind === 'malformed') {
      // The current version's task is corrupt: fail closed instead of
      // rendering a guessed status.  The evaluation area surfaces the error.
      evaluation.value = undefined
      evaluationError.value = '行程质量评估暂时无法加载，请稍后重试'
      clearPlanningOutcome()
      return false
    }
    if (outcome.kind === 'completed') {
      applyOutcomeState(outcome)
      return true
    }
    // A current version's task is expected to be SUCCEEDED.  QUEUED/RUNNING/
    // FAILED/CANCELLED or a (defensive) WAITING_USER never contributes a
    // report to the current formal version.
    clearPlanningOutcome()
    return true
  } catch {
    if (requestSequence === evaluationRequestSequence
      && isCurrentEvaluationOwner(tripId, detailSequence, generation)) {
      evaluation.value = undefined
      evaluationError.value = '行程质量评估暂时无法加载，请稍后重试'
    }
    return false
  } finally {
    if (requestSequence === evaluationRequestSequence) evaluationBusy.value = false
  }
}

async function reloadCurrentEvaluation(): Promise<boolean> {
  if (route.value.name !== 'trip-detail') return false
  return loadEvaluationForCurrentVersion(route.value.tripId)
}

/**
 * Discovers the newest planning task for the trip on page load.  The latest
 * task is NOT the current version's task: a WAITING_USER review never
 * creates a version, so the current VersionSummary.planningTaskId still
 * points at the old SUCCEEDED task.  Only the latest endpoint can recover a
 * review-required state after a browser refresh.
 */
async function hydrateLatestPlanningTask(
  tripId: string,
  detailSequence = detailRequestSequence,
  generation = sessionGeneration,
): Promise<void> {
  if (!isCurrentEvaluationOwner(tripId, detailSequence, generation)) return
  let latest: PlanningTask | null = null
  try {
    latest = await withAccessToken((token) => getLatestPlanningTask(token, tripId))
  } catch {
    // 404 means no task exists for this trip: the current version's
    // report/evaluation (if any) were already hydrated.  Other endpoint
    // errors must not break the formal itinerary; they only skip recovery.
    return
  }
  if (!isCurrentEvaluationOwner(tripId, detailSequence, generation)) return
  const outcome = readPlanningTaskOutcome(latest)
  if (outcome.kind === 'review') {
    // A review-required task is the newest task but has no version: show the
    // review panel while the formal itinerary stays untouched.
    applyOutcomeState(outcome)
    return
  }
  if (outcome.kind === 'queued') {
    // QUEUED/RUNNING task survived a refresh: resume progress subscription.
    planningState.value = 'queued'
    activePlanningTaskId.value = latest.taskId
    void attachPlanningStream(latest, planningRequestSequence, generation, tripId)
    return
  }
  if (outcome.kind === 'failed' || outcome.kind === 'cancelled') {
    planningState.value = outcome.kind === 'failed' ? 'failed' : 'cancelled'
    planningError.value = outcome.kind === 'failed'
      ? (outcome.errorMessage ?? '行程规划失败，请调整条件后重试')
      : null
    clearPlanningOutcome()
    return
  }
  if (outcome.kind === 'completed') {
    const currentItinerary = itinerary.value
    const currentVersion = itineraryVersions.value.find((version) => (
      version.current && version.versionId === currentItinerary?.versionId
    ))
    // Only a succeeded task that created the current version may back the
    // current formal report/evaluation.  An older/newer unrelated succeeded
    // task must not overwrite the current version's outcome.
    if (currentVersion?.planningTaskId === latest.taskId) applyOutcomeState(outcome)
    return
  }
  // malformed latest task: fail closed, keep the formal itinerary intact.
  planningState.value = 'failed'
  planningError.value = '规划结果无法安全读取，请重新规划'
  clearPlanningOutcome()
}

async function loadGuideImportsForTrip(tripId: string): Promise<boolean> {
  const requestSequence = ++guideRequestSequence
  guideBusy.value = true
  guideError.value = null
  try {
    const loaded = await withAccessToken((token) => listGuideImports(token, tripId))
    if (requestSequence !== guideRequestSequence
      || route.value.name !== 'trip-detail'
      || route.value.tripId !== tripId) return false
    guideImports.value = loaded
    return true
  } catch (cause) {
    if (requestSequence === guideRequestSequence) guideError.value = errorMessage(cause)
    return false
  } finally {
    if (requestSequence === guideRequestSequence) guideBusy.value = false
  }
}

async function loadItinerary(tripId: string): Promise<boolean> {
  const requestSequence = ++itineraryRequestSequence
  itineraryBusy.value = true
  itineraryError.value = null
  try {
    const loadedItinerary = await withAccessToken((token) => getCurrentItinerary(token, tripId))
    if (!isCurrentItineraryRequest(requestSequence, tripId)) return false
    itinerary.value = loadedItinerary
    return true
  } catch (cause) {
    if (!isCurrentItineraryRequest(requestSequence, tripId)) return false
    if (cause instanceof ApiError && cause.status === 404) {
      itinerary.value = null
      return true
    }
    itineraryError.value = errorMessage(cause)
    return false
  } finally {
    if (requestSequence === itineraryRequestSequence) itineraryBusy.value = false
  }
}

function isCurrentItineraryRequest(requestSequence: number, tripId: string) {
  return requestSequence === itineraryRequestSequence
    && route.value.name === 'trip-detail'
    && route.value.tripId === tripId
}

function isCurrentDetailRequest(requestSequence: number, tripId: string) {
  return requestSequence === detailRequestSequence
    && route.value.name === 'trip-detail'
    && route.value.tripId === tripId
}

async function loadCurrentRoute() {
  if (route.value.name === 'trip-detail') {
    await loadTrip(route.value.tripId)
    return
  }
  await loadTrips()
}

async function rotateSession() {
  if (refreshInFlight) return refreshInFlight
  const generation = sessionGeneration
  const refreshOperation = (async () => {
    const session = await refreshSession()
    if (generation !== sessionGeneration || phase.value !== 'authenticated') {
      try {
        await logoutSession()
      } catch {
        // A stale rotated token must never restore a locally ended session.
      }
      throw new ApiError(401, 'SESSION_CHANGED', '登录状态已变更')
    }
    applySession(session)
  })()
  refreshInFlight = refreshOperation
  try {
    await refreshOperation
  } finally {
    if (refreshInFlight === refreshOperation) refreshInFlight = null
  }
}

async function withAccessToken<T>(operation: (token: string) => Promise<T>): Promise<T> {
  const operationGeneration = sessionGeneration
  const execute = async () => {
    const result = await operation(accessToken.value)
    assertCurrentSession(operationGeneration)
    return result
  }
  try {
    return await execute()
  } catch (cause) {
    if (!isCurrentSession(operationGeneration)) throw new SessionChangedError('Session changed while request was in flight')
    if (!(cause instanceof ApiError) || cause.status !== 401) throw cause
  }
  try {
    await rotateSession()
  } catch (refreshCause) {
    if (!isCurrentSession(operationGeneration)) throw new SessionChangedError('Session changed while request was in flight')
    if (refreshCause instanceof ApiError && refreshCause.status === 401) clearLocalSession()
    throw refreshCause
  }
  try {
    return await execute()
  } catch (retryCause) {
    if (!isCurrentSession(operationGeneration)) throw new SessionChangedError('Session changed while request was in flight')
    if (retryCause instanceof ApiError && retryCause.status === 401) {
      clearLocalSession()
    }
    throw retryCause
  }
}

async function authenticate(submission: AuthSubmission) {
  const authenticationGeneration = sessionGeneration
  const busySequence = beginBusy()
  error.value = null
  try {
    const session = submission.mode === 'login'
      ? await login(submission.email, submission.password)
      : await register(submission.email, submission.password, submission.displayName)
    if (authenticationGeneration !== sessionGeneration || phase.value !== 'guest') {
      throw new SessionChangedError('Session changed while authentication was in flight')
    }
    applySession(session)
    await loadCurrentRoute()
  } catch (cause) {
    if (!(cause instanceof SessionChangedError) && authenticationGeneration === sessionGeneration) {
      error.value = errorMessage(cause)
    }
  } finally {
    endBusy(busySequence)
  }
}

async function restoreSession() {
  const restoreGeneration = sessionGeneration
  try {
    const session = await refreshSession()
    if (restoreGeneration !== sessionGeneration || phase.value !== 'restoring') {
      throw new SessionChangedError('Session changed while restoration was in flight')
    }
    applySession(session)
  } catch (cause) {
    if (!(cause instanceof SessionChangedError) && restoreGeneration === sessionGeneration) clearLocalSession()
    return
  }
  try {
    await loadCurrentRoute()
  } catch (cause) {
    if (!(cause instanceof SessionChangedError) && restoreGeneration === sessionGeneration) {
      error.value = errorMessage(cause)
    }
  }
}

async function navigate(path: string) {
  await router.push(path)
}

async function openTrip(tripId: string) {
  stopPlanningStream()
  await navigate(tripDetailPath(tripId))
}

async function backToTrips() {
  stopPlanningStream()
  await navigate('/trips')
}

async function handleRouteChange() {
  stopPlanningStream()
  if (phase.value !== 'authenticated') return
  const generation = sessionGeneration
  const busySequence = beginBusy()
  error.value = null
  try {
    await loadCurrentRoute()
  } catch (cause) {
    if (!(cause instanceof SessionChangedError) && generation === sessionGeneration) error.value = errorMessage(cause)
  } finally {
    endBusy(busySequence)
  }
}

async function handleCreateTrip(input: CreateTripInput) {
  error.value = null
  try {
    const created = await withAccessToken((token) => createTrip(token, input))
    if (destinationSearch.value || includeArchived.value) {
      await loadTrips(true)
    } else {
      listRequestSequence += 1
      trips.value = [created, ...trips.value]
    }
  } catch (cause) {
    if (cause instanceof SessionChangedError) return
    error.value = errorMessage(cause)
    throw cause
  }
}

async function refreshTripList() {
  const busySequence = beginBusy()
  error.value = null
  try {
    await loadTrips(true)
  } catch (cause) {
    error.value = errorMessage(cause)
  } finally {
    endBusy(busySequence)
  }
}

async function handleTripSearch(destination: string) {
  destinationSearch.value = destination
  await refreshTripList()
}

async function handleIncludeArchived(nextIncludeArchived: boolean) {
  includeArchived.value = nextIncludeArchived
  await refreshTripList()
}

async function handleArchiveTrip(tripId: string) {
  try {
    await withAccessToken((token) => archiveTrip(token, tripId))
    await refreshTripList()
  } catch (cause) {
    error.value = errorMessage(cause)
  }
}

async function handleRestoreTrip(tripId: string) {
  try {
    await withAccessToken((token) => restoreTrip(token, tripId))
    await refreshTripList()
  } catch (cause) {
    error.value = errorMessage(cause)
  }
}

async function handleUpdateConstraints(input: UpdateTripConstraintsInput) {
  if (!selectedTrip.value) return
  const tripId = selectedTrip.value.id
  const updated = await withAccessToken((token) => updateTripConstraints(token, tripId, input))
  syncTripInList(updated)
  if (route.value.name === 'trip-detail' && route.value.tripId === updated.id) selectedTrip.value = updated
}

async function handlePreviewItineraryEdit(input: ItineraryEditInput): Promise<ItineraryEditPreview> {
  if (!selectedTrip.value) throw new Error('No trip is selected')
  const tripId = selectedTrip.value.id
  return withAccessToken((token) => previewItineraryEdit(token, tripId, input))
}

async function handleApplyItineraryEdit(input: ItineraryEditInput) {
  if (!selectedTrip.value) throw new Error('No trip is selected')
  const tripId = selectedTrip.value.id
  const detailSequence = detailRequestSequence
  const generation = sessionGeneration
  const idempotencyKey = input.idempotencyKey ?? crypto.randomUUID()
  const updated = await withAccessToken(
      (token) => applyItineraryEdit(token, tripId, input, idempotencyKey))
  if (isCurrentEvaluationOwner(tripId, detailSequence, generation)) {
    clearEvaluation()
    itinerary.value = updated
    itineraryError.value = null
    await loadItineraryVersionsForTrip(tripId)
    await loadEvaluationForCurrentVersion(tripId, detailSequence, generation)
  }
}

async function handleCommitItineraryEdits(baseVersionId: string, edits: ItineraryEditInput[]) {
  if (!selectedTrip.value) throw new Error('No trip is selected')
  const tripId = selectedTrip.value.id
  const detailSequence = detailRequestSequence
  const generation = sessionGeneration
  const updated = await withAccessToken((token) => commitItineraryEdits(
    token, tripId, baseVersionId, edits, crypto.randomUUID(),
  ))
  if (isCurrentEvaluationOwner(tripId, detailSequence, generation)) {
    clearEvaluation()
    itinerary.value = updated
    itineraryError.value = null
    await loadItineraryVersionsForTrip(tripId)
    await loadEvaluationForCurrentVersion(tripId, detailSequence, generation)
  }
}

async function handleGetItineraryVersionDiff(
  fromVersionId: string,
  toVersionId: string,
): Promise<ItineraryVersionDiff> {
  if (!selectedTrip.value) throw new Error('No trip is selected')
  const tripId = selectedTrip.value.id
  return withAccessToken((token) => (
    diffItineraryVersions(token, tripId, fromVersionId, toVersionId)
  ))
}

async function handleRollbackItinerary(
  sourceVersionId: string,
  expectedCurrentVersionId: string,
  idempotencyKey: string,
) {
  if (!selectedTrip.value) throw new Error('No trip is selected')
  const tripId = selectedTrip.value.id
  const detailSequence = detailRequestSequence
  const generation = sessionGeneration
  const rolledBack = await withAccessToken((token) => rollbackItinerary(
    token,
    tripId,
    sourceVersionId,
    expectedCurrentVersionId,
    idempotencyKey,
  ))
  if (isCurrentEvaluationOwner(tripId, detailSequence, generation)) {
    clearEvaluation()
    itinerary.value = rolledBack
    itineraryError.value = null
    await loadItineraryVersionsForTrip(tripId)
    await loadEvaluationForCurrentVersion(tripId, detailSequence, generation)
  }
}

async function handleCreateItineraryShare(versionId: string, expiresAt?: string) {
  if (!selectedTrip.value) throw new Error('No trip is selected')
  const tripId = selectedTrip.value.id
  const created = await withAccessToken((token) => createItineraryShare(token, tripId, versionId, expiresAt))
  if (route.value.name === 'trip-detail' && route.value.tripId === tripId) {
    itineraryShares.value = [created, ...itineraryShares.value.filter((share) => share.id !== created.id)]
  }
  return created
}

async function handleRevokeItineraryShare(shareId: string) {
  if (!selectedTrip.value) throw new Error('No trip is selected')
  const tripId = selectedTrip.value.id
  await withAccessToken((token) => revokeItineraryShare(token, tripId, shareId))
  if (route.value.name === 'trip-detail' && route.value.tripId === tripId) {
    itineraryShares.value = itineraryShares.value.map((share) => (
      share.id === shareId ? { ...share, revokedAt: new Date().toISOString() } : share
    ))
  }
}

async function handleDownloadItineraryExport(versionId: string, format: 'ics' | 'pdf') {
  if (!selectedTrip.value) throw new Error('No trip is selected')
  return withAccessToken((token) => downloadItineraryExport(token, selectedTrip.value!.id, versionId, format))
}

async function handleImportGuide(input: GuideImportInput) {
  if (!selectedTrip.value) return
  const tripId = selectedTrip.value.id
  const generation = sessionGeneration
  const requestSequence = ++guideRequestSequence
  guideBusy.value = true
  guideError.value = null
  try {
    const imported = await withAccessToken((token) => (
      createGuideImport(token, tripId, input)
    ))
    if (!isCurrentGuideRequest(requestSequence, generation, tripId)) return
    guideImports.value = [
      imported,
      ...guideImports.value.filter((guide) => guide.id !== imported.id),
    ]
  } catch (cause) {
    if (!isCurrentGuideRequest(requestSequence, generation, tripId)) return
    guideError.value = errorMessage(cause)
    throw cause
  } finally {
    if (isCurrentGuideRequest(requestSequence, generation, tripId)) guideBusy.value = false
  }
}

async function handleSetGuideEnabled(guideImportId: string, enabled: boolean) {
  if (!selectedTrip.value) return
  const tripId = selectedTrip.value.id
  const generation = sessionGeneration
  const requestSequence = ++guideRequestSequence
  guideBusy.value = true
  guideError.value = null
  try {
    const updated = await withAccessToken((token) => (
      updateGuideImportEnabled(token, tripId, guideImportId, enabled)
    ))
    if (!isCurrentGuideRequest(requestSequence, generation, tripId)) return
    guideImports.value = guideImports.value.map((guide) => (
      guide.id === updated.id ? updated : guide
    ))
  } catch (cause) {
    if (!isCurrentGuideRequest(requestSequence, generation, tripId)) return
    guideError.value = errorMessage(cause)
  } finally {
    if (isCurrentGuideRequest(requestSequence, generation, tripId)) guideBusy.value = false
  }
}

function isCurrentGuideRequest(requestSequence: number, generation: number, tripId: string) {
  return requestSequence === guideRequestSequence
    && isCurrentSession(generation)
    && route.value.name === 'trip-detail'
    && route.value.tripId === tripId
}

async function reloadSelectedTrip(): Promise<boolean> {
  if (route.value.name !== 'trip-detail') return false
  return loadTrip(route.value.tripId, true)
}

function isCurrentPlanningRequest(requestSequence: number, generation: number, tripId: string) {
  return requestSequence === planningRequestSequence
    && isCurrentSession(generation)
    && route.value.name === 'trip-detail'
    && route.value.tripId === tripId
}

const planningProgressStages: PlanningProgressStage[] = [
  'TASK_ACCEPTED',
  'CONTEXT_VALIDATING',
  'CITY_FACTS_LOADING',
  'POI_RECALLING',
  'CANDIDATES_RANKING',
  'ROUTES_CALCULATING',
  'CONSTRAINTS_SOLVING',
  'REPAIRING',
  'KNOWLEDGE_RETRIEVING',
  'RESULT_EXPLAINING',
  'RESULT_PUBLISHING',
  'RESULT_PERSISTING',
]

function toPlanningProgressUpdate(event: PlanningTaskEvent): PlanningProgressUpdate | null {
  const { stage, sequence, progress, message, statistics } = event.payload
  if (!planningProgressStages.includes(stage as PlanningProgressStage)
    || typeof sequence !== 'number' || !Number.isSafeInteger(sequence) || sequence < 1
    || typeof progress !== 'number' || !Number.isSafeInteger(progress) || progress < 0 || progress > 100
    || typeof message !== 'string' || !message.trim()) {
    return null
  }
  const safeStatistics = Object.fromEntries(Object.entries(statistics ?? {}).filter(([, value]) => (
    Number.isSafeInteger(value) && value >= 0
  )))
  if (stage === 'REPAIRING' && (event.schemaVersion !== 2
    || !Number.isSafeInteger(safeStatistics.attemptIndex)
    || safeStatistics.attemptIndex < 1 || safeStatistics.attemptIndex > 3
    || !Number.isSafeInteger(safeStatistics.actionCount)
    || safeStatistics.actionCount < 1 || safeStatistics.actionCount > 16)) {
    return null
  }
  return {
    eventId: event.eventId,
    stage: stage as PlanningProgressStage,
    sequence,
    progress,
    message,
    statistics: safeStatistics,
    occurredAt: event.createdAt,
  }
}

/**
 * Attaches the SSE subscription with reconnect and applies every terminal
 * event through the unified outcome parser.  Live events and replay after
 * reconnection share this single handler.
 */
async function attachPlanningStream(
  task: PlanningTask,
  requestSequence: number,
  generation: number,
  tripId: string,
): Promise<void> {
  const controller = new AbortController()
  planningStreamController = controller
  let lastEventId: number | undefined
  let terminal = false
  let itineraryReload: Promise<boolean> | null = null
  const handleEvent = (event: PlanningTaskEvent) => {
    if (!isCurrentPlanningRequest(requestSequence, generation, tripId)) return
    lastEventId = event.eventId
    if (event.eventType === 'PLANNING_PROGRESS') {
      const update = toPlanningProgressUpdate(event)
      if (!update || (planningProgress.value && update.sequence <= planningProgress.value.sequence)) {
        return
      }
      planningProgress.value = update
      // Deduplicate by eventId to allow same-stage multiple updates (B3 fix).
      // Cap history to prevent unbounded growth on SSE reconnection replay.
      const MAX_HISTORY = 100
      const seenIds = new Set(planningProgressHistory.value.map((h) => h.eventId))
      if (!seenIds.has(update.eventId)) {
        planningProgressHistory.value = [
          ...planningProgressHistory.value.slice(-(MAX_HISTORY - 1)),
          update,
        ]
      }
      return
    }
    const outcome = readPlanningEventOutcome(event)
    if (outcome.kind === 'queued') return
    terminal = true
    activePlanningTaskId.value = null
    if (outcome.kind === 'malformed') {
      planningState.value = 'failed'
      planningError.value = '规划结果无法安全读取，请重新规划'
      clearPlanningOutcome()
      return
    }
    applyOutcomeState(outcome)
    if (outcome.kind === 'completed') {
      const detailSequence = detailRequestSequence
      itineraryReload = Promise.all([
        loadItinerary(tripId),
        loadItineraryVersionsForTrip(tripId),
      ]).then(async ([itineraryLoaded, versionsLoaded]) => (
        itineraryLoaded
        && versionsLoaded
        && await loadEvaluationForCurrentVersion(tripId, detailSequence, generation)
      ))
    }
  }

  for (let attempt = 0; attempt < 3 && !terminal; attempt += 1) {
    try {
      lastEventId = await withAccessToken((token) => streamPlanningTaskEvents(
        token,
        task.eventStreamUrl,
        handleEvent,
        { lastEventId, signal: controller.signal },
      ))
    } catch (cause) {
      const retriable = cause instanceof TypeError
        || (cause instanceof ApiError && cause.status >= 500 && cause.status < 600)
      if (!retriable || attempt === 2) throw cause
    }
  }
  if (itineraryReload) await itineraryReload
  if (!terminal && isCurrentPlanningRequest(requestSequence, generation, tripId)) {
    planningState.value = 'failed'
    activePlanningTaskId.value = null
    planningError.value = '任务状态连接已中断，请稍后重试'
    clearPlanningOutcome()
  }
}

async function runPlanningTask(
  createTask: (accessToken: string, idempotencyKey: string) => Promise<PlanningTask>,
) {
  if (!selectedTrip.value || planningState.value === 'queued') return
  const tripId = selectedTrip.value.id
  const generation = sessionGeneration
  stopPlanningStream(false)
  const requestSequence = planningRequestSequence
  planningState.value = 'queued'
  planningError.value = null
  activePlanningTaskId.value = null
  planningProgress.value = null
  planningProgressHistory.value = []
  clearPlanningOutcome()

  try {
    const idempotencyKey = crypto.randomUUID()
    const task = await withAccessToken((token) => createTask(token, idempotencyKey))
    if (!isCurrentPlanningRequest(requestSequence, generation, tripId)) return
    activePlanningTaskId.value = task.taskId
    await attachPlanningStream(task, requestSequence, generation, tripId)
  } catch (cause) {
    if (!isCurrentPlanningRequest(requestSequence, generation, tripId)) return
    if (cause instanceof DOMException && cause.name === 'AbortError') return
    planningState.value = 'failed'
    activePlanningTaskId.value = null
    planningError.value = errorMessage(cause)
    clearPlanningOutcome()
  } finally {
    if (requestSequence === planningRequestSequence) planningStreamController = null
  }
}

async function handleStartPlanning() {
  if (!selectedTrip.value) return
  const tripId = selectedTrip.value.id
  await runPlanningTask((token, idempotencyKey) => (
    createPlanningTask(token, tripId, idempotencyKey)
  ))
}

async function handleStartReplanning(input: ItineraryReplanInput) {
  if (!selectedTrip.value || !itinerary.value) return
  const tripId = selectedTrip.value.id
  await runPlanningTask((token, idempotencyKey) => (
    createItineraryReplan(token, tripId, input, idempotencyKey)
  ))
}

async function handleCancelPlanning() {
  const taskId = activePlanningTaskId.value
  if (planningState.value !== 'queued' || !taskId) return
  try {
    await withAccessToken((token) => cancelPlanningTask(token, taskId))
    if (activePlanningTaskId.value !== taskId) return
    stopPlanningStream(false)
    activePlanningTaskId.value = null
    planningState.value = 'cancelled'
    planningError.value = null
    clearPlanningOutcome()
  } catch (cause) {
    if (activePlanningTaskId.value !== taskId) return
    planningError.value = errorMessage(cause)
  }
}

async function logout() {
  error.value = null
  try {
    await logoutSession()
  } catch {
    // Local logout must still complete when the server is unavailable.
  }
  clearLocalSession()
  await router.replace({ name: 'login' })
}

onMounted(() => {
  removeNavigationHook = router.afterEach(() => {
    void handleRouteChange()
  })
  if (phase.value === 'authenticated') {
    void handleRouteChange()
    return
  }
  void restoreSession()
})

onUnmounted(() => {
  stopPlanningStream()
  removeNavigationHook?.()
  removeNavigationHook = null
})
</script>

<template>
  <Transition name="page" mode="out-in">
    <main v-if="phase === 'restoring'" key="restoring" class="min-h-screen flex items-center justify-center gap-1.5 bg-gradient-to-br from-primary-800 to-primary-950" aria-label="正在恢复登录状态">
      <div class="w-10 h-10 grid place-items-center mr-2 rounded-lg bg-primary-500 text-primary-900 font-extrabold text-sm shadow-lg">TP</div>
      <span></span><span></span><span></span>
    </main>
    <TripDashboard
      v-else-if="phase === 'authenticated' && user && route.name === 'trip-list'"
      key="dashboard"
      :user="user"
      :trips="trips"
      :busy="busy"
      :error="error"
      :create-trip="handleCreateTrip"
      :destination-query="destinationSearch"
      :include-archived="includeArchived"
      @logout="logout"
      @open-trip="openTrip"
      @search="handleTripSearch"
      @include-archived="handleIncludeArchived"
      @archive-trip="handleArchiveTrip"
      @restore-trip="handleRestoreTrip"
    />
    <TripDetail
      v-else-if="phase === 'authenticated' && user && route.name === 'trip-detail'"
      :key="route.tripId"
      :user="user"
      :trip="selectedTrip"
      :busy="detailBusy"
      :error="detailError"
      :itinerary="itinerary"
      :itinerary-busy="itineraryBusy"
      :itinerary-error="itineraryError"
      :itinerary-versions="itineraryVersions"
      :evaluation="evaluation"
      :evaluation-busy="evaluationBusy"
      :evaluation-error="evaluationError"
      :reload-evaluation="reloadCurrentEvaluation"
      :itinerary-shares="itineraryShares"
      :version-busy="versionBusy"
      :version-error="versionError"
      :get-itinerary-version-diff="handleGetItineraryVersionDiff"
      :rollback-itinerary="handleRollbackItinerary"
      :create-itinerary-share="handleCreateItineraryShare"
      :revoke-itinerary-share="handleRevokeItineraryShare"
      :download-itinerary-export="handleDownloadItineraryExport"
      :planning-state="planningState"
      :planning-error="planningError"
      :planning-progress="planningProgress"
      :planning-progress-history="planningProgressHistory"
      :feasibility-report="authoritativeFeasibilityReport"
      :candidate-itinerary="candidateItinerary"
      :feasibility-load-state="feasibilityLoadState"
      :guide-imports="guideImports"
      :guide-busy="guideBusy"
      :guide-error="guideError"
      :import-guide="handleImportGuide"
      :set-guide-enabled="handleSetGuideEnabled"
      :preview-itinerary-edit="handlePreviewItineraryEdit"
      :apply-itinerary-edit="handleApplyItineraryEdit"
      :commit-itinerary-edits="handleCommitItineraryEdits"
      :start-replanning="handleStartReplanning"
      :start-planning="handleStartPlanning"
      :cancel-planning="handleCancelPlanning"
      :update-constraints="handleUpdateConstraints"
      :reload-trip="reloadSelectedTrip"
      @back="backToTrips"
      @logout="logout"
    />
    <section v-else-if="phase === 'authenticated' && user" key="404" class="min-h-screen grid place-items-center content-center gap-5 text-surface-900 bg-surface-50">
      <h1 class="m-0 text-2xl font-bold">页面不存在</h1>
      <button type="button" class="min-h-10 px-4 text-white bg-primary-600 border-0 rounded-xl cursor-pointer font-medium hover:bg-primary-700 transition-colors" @click="backToTrips">返回旅行列表</button>
    </section>
    <AuthView v-else key="auth" :busy="busy" :error="error" @submit="authenticate" />
  </Transition>
</template>

<style>
.restoring > span {
  width: 7px;
  height: 7px;
  background: #93c5fd;
  border-radius: 50%;
  animation: restore-pulse 0.8s infinite alternate;
}

.restoring > span:nth-of-type(2) { animation-delay: 0.2s; }
.restoring > span:nth-of-type(3) { animation-delay: 0.4s; }

@keyframes restore-pulse {
  to { opacity: 0.25; }
}
</style>
