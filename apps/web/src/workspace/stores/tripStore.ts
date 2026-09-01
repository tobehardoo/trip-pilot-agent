// TripPilot Workspace 统一状态源（F-UI-11 Phase 1：真实数据链路）。
//
// 数据流（原则 2）：
//   lib/api.ts → 本 store → Sidebar / Header / 中间区 / 右侧 Context 全部区域
// currentTripId 是整页数据上下文；所有区域围绕当前旅行统一渲染。
//
// 事实边界：
// - 数据只来自真实 API（listTrips/getTrip/createTrip/...），经
//   session.withAccessToken 包装（401 → 单飞 refresh → 自动重试）。
// - 不存在 fixture fallback：API 失败呈现错误状态与重试入口，
//   localStorage 只保留「当前选中旅行 id」这一 UI 偏好，绝不保存业务数据。
// - 约束更新必须携带后端 version（乐观锁）；409 映射为用户可读文案。
import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'

import {
  ApiError,
  createTrip as createTripApi,
  getCurrentItinerary,
  getTrip,
  listTrips,
  updateTripConstraints as updateTripConstraintsApi,
  updateTripMetadata,
  listItineraryVersions,
  diffItineraryVersions as diffItineraryVersionsApi,
  rollbackItinerary as rollbackItineraryApi,
  createItineraryShare as createItineraryShareApi,
  listItineraryShares as listItinerarySharesApi,
  revokeItineraryShare as revokeItineraryShareApi,
  downloadItineraryExport,
  listGuideImports,
  createGuideImport as createGuideImportApi,
  updateGuideImportEnabled as updateGuideImportEnabledApi,
  previewItineraryEdit as previewItineraryEditApi,
  applyItineraryEdit as applyItineraryEditApi,
  type CreateTripInput,
  type CreatedItineraryShare,
  type GuideImport,
  type GuideImportInput,
  type Itinerary,
  type ItineraryEditInput,
  type ItineraryEditPreview,
  type ItineraryShareStatus,
  type ItineraryVersionDiff,
  type ItineraryVersionSummary,
  type Trip,
  type UpdateTripConstraintsInput,
} from '../../lib/api'
import { presentableError, SessionChangedError } from '../lib/errors'
import { useWorkspaceSession } from '../session'
import type { TripPhase } from '../lib/phase'

const LAST_TRIP_KEY = 'tp-workspace-last-trip'

function readLastTripId(): string | null {
  try {
    return localStorage.getItem(LAST_TRIP_KEY)
  } catch {
    return null
  }
}

export const useTripStore = defineStore('workspace-trips', () => {
  const session = useWorkspaceSession()

  // ── 旅行列表 ──────────────────────────────────────────────────────
  const trips = ref<Trip[]>([])
  const listStatus = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const listError = ref<string | null>(null)
  let listRequestSequence = 0

  async function loadTrips(): Promise<void> {
    const requestSequence = ++listRequestSequence
    listStatus.value = listStatus.value === 'ready' ? 'ready' : 'loading'
    listError.value = null
    try {
      const loaded = await session.withAccessToken((token) => listTrips(token))
      if (requestSequence !== listRequestSequence) return
      trips.value = loaded
      listStatus.value = 'ready'
    } catch (cause) {
      if (requestSequence !== listRequestSequence) return
      if (cause instanceof SessionChangedError) return
      listError.value = presentableError(cause)
      listStatus.value = 'error'
    }
  }

  function syncTripInList(trip: Trip): void {
    const index = trips.value.findIndex((item) => item.id === trip.id)
    if (index >= 0) {
      trips.value[index] = trip
    } else {
      trips.value = [trip, ...trips.value]
    }
  }

  // ── 当前旅行 ──────────────────────────────────────────────────────
  const currentTripId = ref<string | null>(null)
  const currentTrip = ref<Trip | null>(null)
  const detailStatus = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const detailError = ref<string | null>(null)
  let detailRequestSequence = 0

  // 当前旅行的行程与版本（completed 阅读区的数据源；draft 为 null）
  const itinerary = ref<Itinerary | null>(null)
  const itineraryStatus = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const itineraryError = ref<string | null>(null)
  const versions = ref<ItineraryVersionSummary[]>([])
  let itineraryRequestSequence = 0

  function resetCurrentContent(): void {
    itinerary.value = null
    itineraryStatus.value = 'idle'
    itineraryError.value = null
    versions.value = []
  }

  async function loadItinerary(tripId: string): Promise<void> {
    const requestSequence = ++itineraryRequestSequence
    itineraryStatus.value = 'loading'
    itineraryError.value = null
    try {
      const loaded = await session.withAccessToken((token) => getCurrentItinerary(token, tripId))
      if (requestSequence !== itineraryRequestSequence || currentTripId.value !== tripId) return
      itinerary.value = loaded
      itineraryStatus.value = 'ready'
    } catch (cause) {
      if (requestSequence !== itineraryRequestSequence || currentTripId.value !== tripId) return
      // 404 = 该旅行还没有行程（draft），不是错误。
      if (cause instanceof ApiError && cause.status === 404) {
        itinerary.value = null
        itineraryStatus.value = 'ready'
        return
      }
      itineraryError.value = presentableError(cause)
      itineraryStatus.value = 'error'
    }
  }

  /** 选中旅行：装载 Trip 元数据 + 当前行程（阶段推导依赖两者）。 */
  async function selectTrip(id: string): Promise<void> {
    if (session.phase !== 'authenticated') return
    if (currentTripId.value === id && detailStatus.value === 'ready') return
    const requestSequence = ++detailRequestSequence
    currentTripId.value = id
    currentTrip.value = null
    detailStatus.value = 'loading'
    detailError.value = null
    resetCurrentContent()
    try {
      localStorage.setItem(LAST_TRIP_KEY, id)
    } catch {
      /* UI 偏好不可用时静默降级 */
    }
    try {
      const loaded = await session.withAccessToken((token) => getTrip(token, id))
      if (requestSequence !== detailRequestSequence || currentTripId.value !== id) return
      currentTrip.value = loaded
      syncTripInList(loaded)
      detailStatus.value = 'ready'
      void loadItinerary(id)
    } catch (cause) {
      if (requestSequence !== detailRequestSequence || currentTripId.value !== id) return
      if (cause instanceof SessionChangedError) return
      detailError.value = presentableError(cause)
      detailStatus.value = 'error'
    }
  }

  // ── 新建旅行 ──────────────────────────────────────────────────────
  const creating = ref(false)

  async function createTrip(input: CreateTripInput): Promise<Trip> {
    creating.value = true
    try {
      const created = await session.withAccessToken((token) => createTripApi(token, input))
      trips.value = [created, ...trips.value.filter((trip) => trip.id !== created.id)]
      currentTripId.value = created.id
      currentTrip.value = created
      detailStatus.value = 'ready'
      detailError.value = null
      resetCurrentContent()
      try {
        localStorage.setItem(LAST_TRIP_KEY, created.id)
      } catch { /* UI 偏好不可用时静默降级 */ }
      return created
    } finally {
      creating.value = false
    }
  }

  // ── 元数据 / 约束（乐观锁） ────────────────────────────────────────
  async function renameTrip(title: string): Promise<void> {
    const trip = currentTrip.value
    if (!trip) throw new Error('No trip is selected')
    const updated = await session.withAccessToken((token) => updateTripMetadata(token, trip.id, {
      expectedVersion: trip.version,
      title,
    }))
    currentTrip.value = updated
    syncTripInList(updated)
  }

  /**
   * 约束更新：必须携带后端 version（乐观锁）。
   * 409 TRIP_VERSION_CONFLICT → 「旅行信息已被更新，请刷新后再修改。」
   */
  async function updateConstraints(input: Omit<UpdateTripConstraintsInput, 'version'>): Promise<void> {
    const trip = currentTrip.value
    if (!trip) throw new Error('No trip is selected')
    const updated = await session.withAccessToken((token) => updateTripConstraintsApi(token, trip.id, {
      ...input,
      version: trip.version,
    }))
    currentTrip.value = updated
    syncTripInList(updated)
  }

  // ── 版本管理 ──────────────────────────────────────────────────────
  const shares = ref<ItineraryShareStatus[]>([])
  const guideImports = ref<GuideImport[]>([])
  const guideImportBusy = ref(false)
  const guideImportError = ref<string | null>(null)

  async function loadVersions(): Promise<void> {
    const trip = currentTrip.value
    if (!trip) return
    try {
      versions.value = await session.withAccessToken((token) => listItineraryVersions(token, trip.id))
    } catch {
      // 静默失败，版本数据非关键路径
    }
  }

  async function diffVersions(fromVersionId: string, toVersionId: string): Promise<ItineraryVersionDiff> {
    const trip = currentTrip.value
    if (!trip) throw new Error('No trip is selected')
    return session.withAccessToken((token) => diffItineraryVersionsApi(token, trip.id, fromVersionId, toVersionId))
  }

  async function rollbackVersion(sourceVersionId: string, expectedCurrentVersionId: string, idempotencyKey: string): Promise<void> {
    const trip = currentTrip.value
    if (!trip) throw new Error('No trip is selected')
    await session.withAccessToken((token) => rollbackItineraryApi(token, trip.id, sourceVersionId, expectedCurrentVersionId, idempotencyKey))
  }

  // ── 分享 ──────────────────────────────────────────────────────────
  async function loadShares(): Promise<void> {
    const trip = currentTrip.value
    if (!trip) return
    try {
      shares.value = await session.withAccessToken((token) => listItinerarySharesApi(token, trip.id))
    } catch {
      // 静默
    }
  }

  async function createShare(versionId: string, expiresAt?: string): Promise<CreatedItineraryShare> {
    const trip = currentTrip.value
    if (!trip) throw new Error('No trip is selected')
    const created = await session.withAccessToken((token) => createItineraryShareApi(token, trip.id, versionId, expiresAt))
    shares.value = [created, ...shares.value.filter((s) => s.id !== created.id)]
    return created
  }

  async function revokeShare(shareId: string): Promise<void> {
    const trip = currentTrip.value
    if (!trip) throw new Error('No trip is selected')
    await session.withAccessToken((token) => revokeItineraryShareApi(token, trip.id, shareId))
    shares.value = shares.value.map((s) => (s.id === shareId ? { ...s, revokedAt: new Date().toISOString() } : s))
  }

  // ── 导出 ──────────────────────────────────────────────────────────
  async function downloadExport(versionId: string, format: 'ics' | 'pdf'): Promise<void> {
    const trip = currentTrip.value
    if (!trip) throw new Error('No trip is selected')
    await session.withAccessToken((token) => downloadItineraryExport(token, trip.id, versionId, format))
  }

  // ── 攻略 ──────────────────────────────────────────────────────────
  async function loadGuideImports(): Promise<void> {
    const trip = currentTrip.value
    if (!trip) return
    guideImportBusy.value = true
    guideImportError.value = null
    try {
      guideImports.value = await session.withAccessToken((token) => listGuideImports(token, trip.id))
    } catch (cause) {
      guideImportError.value = presentableError(cause)
    } finally {
      guideImportBusy.value = false
    }
  }

  async function importGuide(input: GuideImportInput): Promise<void> {
    const trip = currentTrip.value
    if (!trip) throw new Error('No trip is selected')
    guideImportBusy.value = true
    guideImportError.value = null
    try {
      const created = await session.withAccessToken((token) => createGuideImportApi(token, trip.id, input))
      guideImports.value = [created, ...guideImports.value]
    } catch (cause) {
      guideImportError.value = presentableError(cause)
      throw cause
    } finally {
      guideImportBusy.value = false
    }
  }

  async function setGuideEnabled(guideImportId: string, enabled: boolean): Promise<void> {
    const trip = currentTrip.value
    if (!trip) return
    try {
      const updated = await session.withAccessToken((token) => updateGuideImportEnabledApi(token, trip.id, guideImportId, enabled))
      guideImports.value = guideImports.value.map((g) => (g.id === guideImportId ? updated : g))
    } catch {
      // 静默
    }
  }

  // ── 活动编辑 ──────────────────────────────────────────────────────
  async function previewEdit(input: ItineraryEditInput): Promise<ItineraryEditPreview> {
    const trip = currentTrip.value
    if (!trip) throw new Error('No trip is selected')
    return session.withAccessToken((token) => previewItineraryEditApi(token, trip.id, input))
  }

  async function applyEdit(input: ItineraryEditInput, idempotencyKey: string): Promise<void> {
    const trip = currentTrip.value
    if (!trip) throw new Error('No trip is selected')
    await session.withAccessToken((token) => applyItineraryEditApi(token, trip.id, input, idempotencyKey))
    // 编辑后重新加载行程
    void loadItinerary(trip.id)
  }

  /** 登出/会话失效时清空全部内存态（业务数据绝不落地）。 */
  function resetAll(): void {
    listRequestSequence += 1
    detailRequestSequence += 1
    itineraryRequestSequence += 1
    trips.value = []
    listStatus.value = 'idle'
    listError.value = null
    currentTripId.value = null
    currentTrip.value = null
    detailStatus.value = 'idle'
    detailError.value = null
    resetCurrentContent()
    shares.value = []
    guideImports.value = []
  }

  // 会话失效 → 立即清空业务数据（未登录不能残留任何真实数据）。
  watch(() => session.phase, (phase) => {
    if (phase === 'guest') resetAll()
  })

  const hasTrips = computed(() => trips.value.length > 0)
  /** 从 API Trip.status 推导产品阶段（draft/planning/completed） */
  const currentPhase = computed<TripPhase | null>(() => {
    const s = currentTrip.value?.status?.toLowerCase() ?? ''
    if (s === 'draft') return 'draft'
    if (s === 'planning') return 'planning'
    if (s === 'completed') return 'completed'
    return null
  })

  /** 首次进入已认证态时自动装载旅行列表 */
  let loaded = false
  watch(() => session.phase, (phase) => {
    if (phase === 'authenticated' && !loaded) {
      loaded = true
      void loadTrips()
    }
  })

  return {
    trips,
    hasTrips,
    listStatus,
    listError,
    currentTripId,
    currentTrip,
    currentPhase,
    detailStatus,
    detailError,
    itinerary,
    itineraryStatus,
    itineraryError,
    versions,
    shares,
    guideImports,
    guideImportBusy,
    guideImportError,
    creating,
    loadTrips,
    selectTrip,
    createTrip,
    renameTrip,
    updateConstraints,
    loadItinerary,
    loadVersions,
    diffVersions,
    rollbackVersion,
    loadShares,
    createShare,
    revokeShare,
    downloadExport,
    loadGuideImports,
    importGuide,
    setGuideEnabled,
    previewEdit,
    applyEdit,
    resetAll,
  }
})
