<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'

import AuthView, { type AuthSubmission } from './components/AuthView.vue'
import TripDashboard from './components/TripDashboard.vue'
import TripDetail from './components/TripDetail.vue'
import {
  ApiError,
  cancelPlanningTask,
  createGuideImport,
  createPlanningTask,
  createTrip,
  getCurrentItinerary,
  getTrip,
  listTrips,
  listGuideImports,
  login,
  logoutSession,
  refreshSession,
  register,
  streamPlanningTaskEvents,
  updateGuideImportEnabled,
  updateTripConstraints,
  type AuthSession,
  type CreateTripInput,
  type GuideImport,
  type Itinerary,
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
const planningState = ref<'idle' | 'queued' | 'succeeded' | 'failed' | 'cancelled'>('idle')
const planningError = ref<string | null>(null)
const guideImports = ref<GuideImport[]>([])
const guideBusy = ref(false)
const guideError = ref<string | null>(null)
const activePlanningTaskId = ref<string | null>(null)
let sessionGeneration = 0
let detailRequestSequence = 0
let itineraryRequestSequence = 0
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
    guideImports.value = []
    guideError.value = null
  }
  try {
    const loadedTrip = await withAccessToken((token) => getTrip(token, tripId))
    if (!isCurrentDetailRequest(requestSequence, tripId)) return false
    selectedTrip.value = loadedTrip
    syncTripInList(loadedTrip)
    await Promise.all([loadItinerary(tripId), loadGuideImportsForTrip(tripId)])
    return true
  } catch (cause) {
    if (!isCurrentDetailRequest(requestSequence, tripId)) return false
    if (!preserveCurrentTrip) detailError.value = errorMessage(cause)
    return false
  } finally {
    if (requestSequence === detailRequestSequence) detailBusy.value = false
  }
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

async function handleImportGuide(sourceUrl: string) {
  if (!selectedTrip.value) return
  const tripId = selectedTrip.value.id
  const generation = sessionGeneration
  const requestSequence = ++guideRequestSequence
  guideBusy.value = true
  guideError.value = null
  try {
    const imported = await withAccessToken((token) => (
      createGuideImport(token, tripId, sourceUrl)
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
  guideBusy.value = true
  guideError.value = null
  try {
    const updated = await withAccessToken((token) => (
      updateGuideImportEnabled(token, tripId, guideImportId, enabled)
    ))
    guideImports.value = guideImports.value.map((guide) => (
      guide.id === updated.id ? updated : guide
    ))
  } catch (cause) {
    guideError.value = errorMessage(cause)
    throw cause
  } finally {
    guideBusy.value = false
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

async function handleStartPlanning() {
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
    const task = await withAccessToken((token) => createPlanningTask(token, tripId, idempotencyKey))
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
        itineraryReload = loadItinerary(tripId)
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
  <main v-if="phase === 'restoring'" class="restoring" aria-label="正在恢复登录状态">
    <div class="restore-mark">TP</div>
    <span></span><span></span><span></span>
  </main>
  <TripDashboard
    v-else-if="phase === 'authenticated' && user && route.name === 'trip-list'"
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
    :user="user"
    :trip="selectedTrip"
    :busy="detailBusy"
    :error="detailError"
    :itinerary="itinerary"
    :itinerary-busy="itineraryBusy"
    :itinerary-error="itineraryError"
    :planning-state="planningState"
    :planning-error="planningError"
    :guide-imports="guideImports"
    :guide-busy="guideBusy"
    :guide-error="guideError"
    :import-guide="handleImportGuide"
    :set-guide-enabled="handleSetGuideEnabled"
    :start-planning="handleStartPlanning"
    :cancel-planning="handleCancelPlanning"
    :update-constraints="handleUpdateConstraints"
    :reload-trip="reloadSelectedTrip"
    @back="backToTrips"
    @logout="logout"
  />
  <section v-else-if="phase === 'authenticated' && user" class="not-found">
    <h1>页面不存在</h1>
    <button type="button" @click="backToTrips">返回旅行列表</button>
  </section>
  <AuthView v-else :busy="busy" :error="error" @submit="authenticate" />
</template>

<style>
:root {
  color-scheme: light;
  font-family: Inter, "PingFang SC", "Microsoft YaHei", sans-serif;
  font-synthesis: none;
  text-rendering: optimizeLegibility;
}

* {
  box-sizing: border-box;
}

body {
  min-width: 320px;
  min-height: 100vh;
  margin: 0;
}

button,
input,
select {
  letter-spacing: 0;
}

button:focus-visible,
input:focus-visible,
select:focus-visible {
  outline: 2px solid #26725f;
  outline-offset: 2px;
}

.restoring {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  background: #173d33;
}

.not-found {
  min-height: 100vh;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 18px;
  color: #17201d;
  background: #f2f5f4;
}

.not-found h1 { margin: 0; font-size: 25px; }
.not-found button { min-height: 40px; padding: 0 16px; color: #fff; background: #236552; border: 0; border-radius: 5px; cursor: pointer; }

.restore-mark {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  margin-right: 8px;
  color: #173d33;
  background: #e6b44a;
  border-radius: 6px;
  font-weight: 800;
}

.restoring > span {
  width: 7px;
  height: 7px;
  background: #d5e2de;
  border-radius: 50%;
  animation: restore-pulse 0.8s infinite alternate;
}

.restoring > span:nth-of-type(2) { animation-delay: 0.2s; }
.restoring > span:nth-of-type(3) { animation-delay: 0.4s; }

@keyframes restore-pulse {
  to { opacity: 0.25; }
}
</style>
