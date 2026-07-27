<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'

import AuthView, { type AuthSubmission } from './components/AuthView.vue'
import TripDashboard from './components/TripDashboard.vue'
import TripDetail from './components/TripDetail.vue'
import {
  ApiError,
  applyItineraryEdit,
  cancelPlanningTask,
  createGuideImport,
  createItineraryReplan,
  createPlanningTask,
  createTrip,
  diffItineraryVersions,
  getCurrentItinerary,
  getTrip,
  listTrips,
  listGuideImports,
  listItineraryVersions,
  login,
  logoutSession,
  previewItineraryEdit,
  refreshSession,
  register,
  rollbackItinerary,
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
  type ItineraryVersionDiff,
  type ItineraryVersionSummary,
  type PlanningTask,
  type PlanningTaskEvent,
  type Trip,
  type UpdateTripConstraintsInput,
  type User,
} from './lib/api'
import { parseRoute, tripDetailPath, type AppRoute } from './lib/routes'

type Phase = 'guest' | 'restoring' | 'authenticated'

class SessionChangedError extends Error {}

const phase = ref<Phase>('restoring')
const busy = ref(false)
const error = ref<string | null>(null)
const user = ref<User | null>(null)
const accessToken = ref('')
const trips = ref<Trip[]>([])
const selectedTrip = ref<Trip | null>(null)
const route = ref<AppRoute>(parseRoute(window.location.pathname))
const detailBusy = ref(false)
const detailError = ref<string | null>(null)
const itinerary = ref<Itinerary | null>(null)
const itineraryBusy = ref(false)
const itineraryError = ref<string | null>(null)
const itineraryVersions = ref<ItineraryVersionSummary[]>([])
const versionBusy = ref(false)
const versionError = ref<string | null>(null)
const planningState = ref<'idle' | 'queued' | 'succeeded' | 'failed' | 'cancelled'>('idle')
const planningError = ref<string | null>(null)
const guideImports = ref<GuideImport[]>([])
const guideBusy = ref(false)
const guideError = ref<string | null>(null)
const activePlanningTaskId = ref<string | null>(null)
let sessionGeneration = 0
let detailRequestSequence = 0
let itineraryRequestSequence = 0
let versionRequestSequence = 0
let listRequestSequence = 0
let busyRequestSequence = 0
let planningRequestSequence = 0
let guideRequestSequence = 0
let refreshInFlight: Promise<void> | null = null
let planningStreamController: AbortController | null = null

function errorMessage(cause: unknown) {
  if (cause instanceof ApiError) return cause.message
  return '无法连接业务服务，请稍后重试'
}

function applySession(session: AuthSession) {
  user.value = session.user
  accessToken.value = session.accessToken
  phase.value = 'authenticated'
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
  phase.value = 'guest'
  busy.value = false
  user.value = null
  accessToken.value = ''
  trips.value = []
  selectedTrip.value = null
  detailBusy.value = false
  detailError.value = null
  itinerary.value = null
  itineraryBusy.value = false
  itineraryError.value = null
  itineraryVersions.value = []
  versionBusy.value = false
  versionError.value = null
  guideImports.value = []
  guideBusy.value = false
  guideError.value = null
  guideRequestSequence += 1
}

function stopPlanningStream(resetState = true) {
  planningRequestSequence += 1
  planningStreamController?.abort()
  planningStreamController = null
  if (resetState) {
    planningState.value = 'idle'
    planningError.value = null
    activePlanningTaskId.value = null
  }
}

function syncTripInList(loadedTrip: Trip) {
  listRequestSequence += 1
  trips.value = trips.value.map((trip) => trip.id === loadedTrip.id ? loadedTrip : trip)
}

async function loadTrips() {
  const requestSequence = ++listRequestSequence
  const loadedTrips = await withAccessToken((token) => listTrips(token))
  if (requestSequence === listRequestSequence) trips.value = loadedTrips
}

async function loadTrip(tripId: string, preserveCurrentTrip = false): Promise<boolean> {
  const requestSequence = ++detailRequestSequence
  detailBusy.value = true
  detailError.value = null
  if (!preserveCurrentTrip) {
    selectedTrip.value = null
    itinerary.value = null
    itineraryError.value = null
    itineraryVersions.value = []
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
    ])
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

function isCurrentVersionRequest(requestSequence: number, tripId: string) {
  return requestSequence === versionRequestSequence
    && route.value.name === 'trip-detail'
    && route.value.tripId === tripId
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

function navigate(path: string) {
  window.history.pushState({}, '', path)
  route.value = parseRoute(window.location.pathname)
}

async function openTrip(tripId: string) {
  stopPlanningStream()
  navigate(tripDetailPath(tripId))
  await loadTrip(tripId)
}

async function backToTrips() {
  stopPlanningStream()
  navigate('/trips')
  if (trips.value.length > 0) return
  const generation = sessionGeneration
  const busySequence = beginBusy()
  error.value = null
  try {
    await loadTrips()
  } catch (cause) {
    if (!(cause instanceof SessionChangedError) && generation === sessionGeneration) error.value = errorMessage(cause)
  } finally {
    endBusy(busySequence)
  }
}

async function handlePopState() {
  stopPlanningStream()
  route.value = parseRoute(window.location.pathname)
  if (phase.value !== 'authenticated') return
  const loadingList = route.value.name === 'trip-list'
  const generation = sessionGeneration
  let busySequence: number | null = null
  if (loadingList) {
    busySequence = beginBusy()
    error.value = null
  }
  try {
    await loadCurrentRoute()
  } catch (cause) {
    if (!(cause instanceof SessionChangedError) && generation === sessionGeneration) error.value = errorMessage(cause)
  } finally {
    if (busySequence !== null) endBusy(busySequence)
  }
}

async function handleCreateTrip(input: CreateTripInput) {
  error.value = null
  try {
    const created = await withAccessToken((token) => createTrip(token, input))
    listRequestSequence += 1
    trips.value = [created, ...trips.value]
  } catch (cause) {
    if (cause instanceof SessionChangedError) return
    error.value = errorMessage(cause)
    throw cause
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
  const updated = await withAccessToken((token) => applyItineraryEdit(token, tripId, input))
  if (route.value.name === 'trip-detail' && route.value.tripId === tripId) {
    itinerary.value = updated
    itineraryError.value = null
    await loadItineraryVersionsForTrip(tripId)
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
  const rolledBack = await withAccessToken((token) => rollbackItinerary(
    token,
    tripId,
    sourceVersionId,
    expectedCurrentVersionId,
    idempotencyKey,
  ))
  if (route.value.name === 'trip-detail' && route.value.tripId === tripId) {
    itinerary.value = rolledBack
    itineraryError.value = null
    await loadItineraryVersionsForTrip(tripId)
  }
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

function planningFailureMessage(payload: PlanningTaskEvent['payload']): string {
  const parts = [payload.message ?? payload.errorMessage ?? '行程规划失败，请调整条件后重试']
  for (const conflict of payload.conflicts ?? []) {
    if (conflict.message && !parts.includes(conflict.message)) parts.push(conflict.message)
  }
  for (const suggestion of payload.relaxationSuggestions ?? []) {
    if (suggestion.message) parts.push(`建议：${suggestion.message}`)
  }
  return parts.join('；')
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

  try {
    const idempotencyKey = crypto.randomUUID()
    const task = await withAccessToken((token) => createTask(token, idempotencyKey))
    if (!isCurrentPlanningRequest(requestSequence, generation, tripId)) return
    activePlanningTaskId.value = task.taskId
    const controller = new AbortController()
    planningStreamController = controller
    let lastEventId: number | undefined
    let terminal = false
    let itineraryReload: Promise<boolean> | null = null
    const handleEvent = (event: PlanningTaskEvent) => {
      if (!isCurrentPlanningRequest(requestSequence, generation, tripId)) return
      lastEventId = event.eventId
      if (event.eventType === 'PLANNING_COMPLETED') {
        terminal = true
        planningState.value = 'succeeded'
        activePlanningTaskId.value = null
        itineraryReload = Promise.all([
          loadItinerary(tripId),
          loadItineraryVersionsForTrip(tripId),
        ]).then(([loaded]) => loaded)
      } else if (event.eventType === 'PLANNING_FAILED') {
        terminal = true
        planningState.value = 'failed'
        activePlanningTaskId.value = null
        planningError.value = planningFailureMessage(event.payload)
      } else if (event.eventType === 'PLANNING_CANCELLED') {
        terminal = true
        planningState.value = 'cancelled'
        activePlanningTaskId.value = null
        planningError.value = null
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
        if (!(cause instanceof TypeError) || attempt === 2) throw cause
      }
    }
    if (itineraryReload) await itineraryReload
    if (!terminal && isCurrentPlanningRequest(requestSequence, generation, tripId)) {
      planningState.value = 'failed'
      activePlanningTaskId.value = null
      planningError.value = '任务状态连接已中断，请稍后重试'
    }
  } catch (cause) {
    if (!isCurrentPlanningRequest(requestSequence, generation, tripId)) return
    if (cause instanceof DOMException && cause.name === 'AbortError') return
    planningState.value = 'failed'
    activePlanningTaskId.value = null
    planningError.value = errorMessage(cause)
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
  } catch (cause) {
    if (activePlanningTaskId.value !== taskId) return
    planningError.value = errorMessage(cause)
  }
}

async function logout() {
  clearLocalSession()
  error.value = null
  try {
    await logoutSession()
  } catch {
    // Local logout must still complete when the server is unavailable.
  }
}

onMounted(() => {
  window.addEventListener('popstate', handlePopState)
  restoreSession()
})

onUnmounted(() => {
  stopPlanningStream()
  window.removeEventListener('popstate', handlePopState)
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
      @logout="logout"
      @open-trip="openTrip"
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
      :version-busy="versionBusy"
      :version-error="versionError"
      :get-itinerary-version-diff="handleGetItineraryVersionDiff"
      :rollback-itinerary="handleRollbackItinerary"
      :planning-state="planningState"
      :planning-error="planningError"
      :guide-imports="guideImports"
      :guide-busy="guideBusy"
      :guide-error="guideError"
      :import-guide="handleImportGuide"
      :set-guide-enabled="handleSetGuideEnabled"
      :preview-itinerary-edit="handlePreviewItineraryEdit"
      :apply-itinerary-edit="handleApplyItineraryEdit"
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
