<script setup lang="ts">
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  BookOpen,
  CalendarDays,
  CircleGauge,
  Clock3,
  Compass,
  Coins,
  ExternalLink,
  LoaderCircle,
  Lock,
  LockOpen,
  LogOut,
  MapPin,
  Pencil,
  Play,
  RefreshCw,
  Route,
  Trash2,
  Users,
  Wallet,
  X,
} from 'lucide-vue-next'
import { computed, nextTick, reactive, ref, watch } from 'vue'

import {
  ApiError,
  type GuideImport,
  type GuideImportInput,
  type Itinerary,
  type ItineraryActivity,
  type ItineraryEditInput,
  type ItineraryEditPreview,
  type ItineraryTransitLeg,
  type ItineraryReplanInput,
  type ItineraryShareStatus,
  type ItineraryVersionDiff,
  type ItineraryVersionSummary,
  type PlaceSearchFn,
  type PlaceSearchResponse,
  type PlaceSuggestFn,
  type PlanEvaluation,
  type PlanningProgressUpdate,
  type Trip,
  type UpdateConfigurationInput,
  type UpdateTripConstraintsInput,
  type User,
} from '../lib/api'
import { useModalFocus } from '../lib/modal'
import { cn } from '../lib/utils'
import TripConstraintForm, { type TripConfigurationPayload } from './TripConstraintForm.vue'
import {
  estimateCommuteOptions,
  recommendedCommuteMode,
  type CommuteMode,
  type ConcreteCommuteMode,
} from '../lib/transit'
import { useItineraryDraft } from '../composables/useItineraryDraft'
import GuideIntelligencePanel from './GuideIntelligencePanel.vue'
import ItineraryActionsPanel, { type CreatedItineraryShare } from './ItineraryActionsPanel.vue'
import ItineraryVersionPanel from './ItineraryVersionPanel.vue'
import PlanEvaluationPanel from './PlanEvaluationPanel.vue'
import PlanningProgress from './PlanningProgress.vue'
import TripMap from './TripMap.vue'
import TripWeatherTimeline from './TripWeatherTimeline.vue'
import TransitLegControl from './TransitLegControl.vue'
import Badge from './ui/Badge.vue'
import Button from './ui/Button.vue'
import Card from './ui/Card.vue'

const props = withDefaults(defineProps<{
  user: User
  trip: Trip | null
  busy: boolean
  error: string | null
  itinerary: Itinerary | null
  itineraryBusy: boolean
  itineraryError: string | null
  itineraryVersions?: ItineraryVersionSummary[]
  itineraryShares?: ItineraryShareStatus[]
  versionBusy?: boolean
  versionError?: string | null
  getItineraryVersionDiff?: (
    fromVersionId: string,
    toVersionId: string,
  ) => Promise<ItineraryVersionDiff>
  rollbackItinerary?: (
    sourceVersionId: string,
    expectedCurrentVersionId: string,
    idempotencyKey: string,
  ) => Promise<void>
  createItineraryShare?: (versionId: string, expiresAt?: string) => Promise<CreatedItineraryShare>
  revokeItineraryShare?: (shareId: string) => Promise<void>
  downloadItineraryExport?: (versionId: string, format: 'ics' | 'pdf') => Promise<void>
  planningState: 'idle' | 'queued' | 'succeeded' | 'failed' | 'cancelled'
  planningError: string | null
  planningProgress?: PlanningProgressUpdate | null
  planningProgressHistory?: PlanningProgressUpdate[]
  guideImports?: GuideImport[]
  guideBusy?: boolean
  guideError?: string | null
  importGuide?: (input: GuideImportInput) => Promise<void>
  setGuideEnabled?: (guideImportId: string, enabled: boolean) => Promise<void>
  previewItineraryEdit?: (input: ItineraryEditInput) => Promise<ItineraryEditPreview>
  applyItineraryEdit?: (input: ItineraryEditInput) => Promise<void>
  commitItineraryEdits?: (baseVersionId: string, edits: ItineraryEditInput[]) => Promise<void>
  startReplanning?: (input: ItineraryReplanInput) => Promise<void>
  startPlanning: () => Promise<void>
  cancelPlanning: () => Promise<void>
  updateConstraints: (input: UpdateTripConstraintsInput) => Promise<void>
  updateConfiguration?: (tripId: string, input: UpdateConfigurationInput) => Promise<void>
  serverDate?: string
  searchPlaces?: PlaceSearchFn
  suggestPlaces?: PlaceSuggestFn
  reloadTrip: () => Promise<boolean>
  evaluation?: PlanEvaluation | null
  evaluationBusy?: boolean
  evaluationError?: string | null
  reloadEvaluation?: () => Promise<boolean>
}>(), {
  evaluation: undefined,
  evaluationBusy: false,
  evaluationError: null,
  reloadEvaluation: async () => false,
  guideImports: () => [],
  planningProgress: null,
  planningProgressHistory: () => [],
  itineraryVersions: () => [],
  itineraryShares: () => [],
  versionBusy: false,
  versionError: null,
  getItineraryVersionDiff: async () => {
    throw new Error('Itinerary version diff is unavailable')
  },
  rollbackItinerary: async () => {},
  createItineraryShare: async () => {
    throw new Error('Itinerary sharing is unavailable')
  },
  revokeItineraryShare: async () => {},
  downloadItineraryExport: async () => {},
  guideBusy: false,
  guideError: null,
  importGuide: async () => {},
  setGuideEnabled: async () => {},
  previewItineraryEdit: async (input: ItineraryEditInput) => ({
    operation: input.operation,
    canApply: false,
    impactedDates: [],
    impactedActivityIds: [],
    warnings: [],
    blockingReasons: [{ code: 'ITINERARY_EDIT_UNAVAILABLE', message: 'Itinerary editing is unavailable' }],
  }),
  applyItineraryEdit: async () => {},
  commitItineraryEdits: async () => {},
  startReplanning: async () => {},
})

const emit = defineEmits<{
  back: []
  logout: []
}>()

const chinaTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
  timeZone: 'Asia/Shanghai',
})
const chinaDateTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
  timeZone: 'Asia/Shanghai',
})
const editing = ref(false)
const dialogElement = ref<HTMLElement | null>(null)
const submitting = ref(false)
const formError = ref<string | null>(null)
const versionConflict = ref(false)
const selectedActivityId = ref<string | null>(null)
const selectedMapDate = ref<string | null>(null)
const pendingItineraryEdit = ref<ItineraryEditInput | null>(null)
const itineraryEditPreview = ref<ItineraryEditPreview | null>(null)
const selectedTransitModes = reactive<Record<string, CommuteMode>>({})
const lockedTransitLegs = reactive<Record<string, boolean>>({})
const transitEditBusy = ref(false)
const transitEditError = ref<string | null>(null)
const {
  edits: draftItineraryEdits,
  busy: draftItineraryBusy,
  error: draftItineraryError,
  queue: queueItineraryEdit,
  discard: clearItineraryDraft,
  commit: commitItineraryDraft,
} = useItineraryDraft(
  (baseVersionId, edits) => props.commitItineraryEdits(baseVersionId, edits),
  (cause) => cause instanceof ApiError ? cause.message : '保存行程草稿失败，请稍后重试',
)
const STRUCTURAL_KINDS = new Set(['MEAL', 'ACCOMMODATION', 'ARRIVAL', 'DEPARTURE'])

function isStructuralKind(kind?: string | null): boolean {
  return !!kind && STRUCTURAL_KINDS.has(kind)
}

function hasMissingTransitGap(day: Itinerary['days'][number]): boolean {
  if (day.activities.length < 2) return false
  const legPairs = new Set(
    day.transitLegs.map((leg) => `${leg.fromActivityId}:${leg.toActivityId}`),
  )
  for (let index = 0; index < day.activities.length - 1; index++) {
    const from = day.activities[index]
    const to = day.activities[index + 1]
    // Gaps around structural nodes (meal/arrival/departure/accommodation) are
    // intentional and do not require a transit refresh.
    if (isStructuralKind(from.kind) || isStructuralKind(to.kind)) continue
    if (!legPairs.has(`${from.id}:${to.id}`)) return true
  }
  return false
}

const datesNeedingTransitRefresh = computed(() => props.itinerary?.days
  .filter(hasMissingTransitGap)
  .map((day) => day.date) ?? [])

async function startLocalReplanning() {
  if (!props.itinerary || !datesNeedingTransitRefresh.value.length) return
  await props.startReplanning({
    baseVersionId: props.itinerary.versionId,
    dates: datesNeedingTransitRefresh.value,
  })
}
const itineraryEditBusy = ref(false)
const itineraryEditError = ref<string | null>(null)

function transitLegFor(day: Itinerary['days'][number], activityIndex: number): ItineraryTransitLeg | null {
  const fromActivity = day.activities[activityIndex]
  const toActivity = day.activities[activityIndex + 1]
  if (!fromActivity || !toActivity) return null
  // Only return the exact leg matching the activity pair — positional
  // fallback would silently display wrong transit data when activities
  // have been reordered or edited.
  return day.transitLegs.find((leg) => leg.fromActivityId === fromActivity.id && leg.toActivityId === toActivity.id)
    ?? null
}

function transitModeFor(leg: ItineraryTransitLeg): CommuteMode {
  if (selectedTransitModes[leg.id]) return selectedTransitModes[leg.id]
  return leg.mode
}

function transitLockedFor(leg: ItineraryTransitLeg): boolean {
  return lockedTransitLegs[leg.id] ?? leg.locked
}

function transitAvailableSeconds(day: Itinerary['days'][number], activityIndex: number) {
  const fromActivity = day.activities[activityIndex]
  const toActivity = day.activities[activityIndex + 1]
  if (!fromActivity || !toActivity) return undefined
  const available = (Date.parse(toActivity.startTime) - Date.parse(fromActivity.endTime)) / 1000
  return Number.isFinite(available) ? Math.max(0, available) : undefined
}

async function updateTransitLeg(
  leg: ItineraryTransitLeg,
  changes: Pick<ItineraryEditInput, 'transitMode' | 'transitLocked'>,
) {
  if (!props.itinerary || transitEditBusy.value) return
  transitEditBusy.value = true
  transitEditError.value = null
  try {
    queueItineraryEdit({
      baseVersionId: props.itinerary.versionId,
      operation: 'UPDATE_TRANSIT_LEG',
      transitLegId: leg.id,
      ...changes,
    })
    if (changes.transitMode) selectedTransitModes[leg.id] = changes.transitMode
    if (changes.transitLocked !== undefined) lockedTransitLegs[leg.id] = changes.transitLocked
  } finally {
    transitEditBusy.value = false
  }
}

function queueRecommendedLongWalks(nextItinerary: Itinerary) {
  for (const day of nextItinerary.days) {
    for (const leg of day.transitLegs) {
      if (leg.locked || leg.mode !== 'WALKING' || leg.durationSeconds <= 20 * 60) continue
      const recommendedMode = recommendedCommuteMode(estimateCommuteOptions(leg))
      if (recommendedMode === 'WALKING') continue
      selectedTransitModes[leg.id] = recommendedMode
      queueItineraryEdit({
        baseVersionId: nextItinerary.versionId,
        operation: 'UPDATE_TRANSIT_LEG',
        transitLegId: leg.id,
        transitMode: recommendedMode,
      })
    }
  }
}

function discardItineraryDraft() {
  clearItineraryDraft()
  Object.keys(selectedTransitModes).forEach((legId) => { delete selectedTransitModes[legId] })
  Object.keys(lockedTransitLegs).forEach((legId) => { delete lockedTransitLegs[legId] })
  transitEditError.value = null
}

async function saveItineraryDraft() {
  if (!props.itinerary) return
  await commitItineraryDraft(props.itinerary.versionId)
}

async function selectTransitMode(leg: ItineraryTransitLeg, mode: ConcreteCommuteMode) {
  if (transitLockedFor(leg)) return
  const previousMode = selectedTransitModes[leg.id]
  selectedTransitModes[leg.id] = mode
  try {
    await updateTransitLeg(leg, { transitMode: mode })
  } catch (cause) {
    if (previousMode) selectedTransitModes[leg.id] = previousMode
    else delete selectedTransitModes[leg.id]
    transitEditError.value = cause instanceof ApiError ? cause.message : '通勤方式保存失败，请稍后重试'
  }
}

async function setTransitLock(leg: ItineraryTransitLeg, locked: boolean) {
  try {
    await updateTransitLeg(leg, { transitLocked: locked })
  } catch (cause) {
    transitEditError.value = cause instanceof ApiError ? cause.message : '通勤锁定保存失败，请稍后重试'
  }
}

watch(() => props.itinerary?.versionId, () => {
  clearItineraryDraft()
  Object.keys(selectedTransitModes).forEach((legId) => { delete selectedTransitModes[legId] })
  Object.keys(lockedTransitLegs).forEach((legId) => { delete lockedTransitLegs[legId] })
  transitEditError.value = null
})
const configFormRef = ref<InstanceType<typeof TripConstraintForm> | null>(null)

const { handleKeydown: handleDialogKeydown, rememberTrigger } = useModalFocus(
  editing,
  dialogElement,
  () => { editing.value = false },
)

function openEditor(event?: Event) {
  if (!props.trip) return
  rememberTrigger(event?.currentTarget)
  formError.value = null
  versionConflict.value = false
  // 表单挂载时通过 :initial 填充当前 trip；不通过 key 卸载重建。
  editing.value = true
}

async function handleConfigSubmit(payload: TripConfigurationPayload) {
  if (!props.trip) return
  submitting.value = true
  formError.value = null
  versionConflict.value = false
  try {
    if (props.updateConfiguration) {
      // 编辑流程 version 由共享表单携带（来自当前 trip.version）。
      await props.updateConfiguration(props.trip.id, { ...payload, version: payload.version ?? props.trip.version })
    } else {
      const { version, constraints } = payload
      await props.updateConstraints({ version: version ?? props.trip.version, ...constraints })
    }
    editing.value = false
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 409) {
      versionConflict.value = true
      formError.value = '数据已更新，当前修改尚未保存。请重新加载最新数据后再编辑。'
    } else {
      formError.value = cause instanceof ApiError ? cause.message : '保存失败，请稍后重试'
    }
  } finally {
    submitting.value = false
  }
}

async function reloadLatestTrip() {
  submitting.value = true
  try {
    const reloaded = await props.reloadTrip()
    if (reloaded) {
      editing.value = false
      return
    }
    versionConflict.value = true
    formError.value = '重新加载失败，当前修改仍保留，请稍后重试。'
  } catch {
    versionConflict.value = true
    formError.value = '重新加载失败，当前修改仍保留，请稍后重试。'
  } finally {
    submitting.value = false
  }
}

function paceLabel(pace: Trip['constraints']['pace']) {
  return { RELAXED: '舒缓', BALANCED: '均衡', INTENSIVE: '紧凑' }[pace]
}

function travelerTypeLabel(type: Trip['constraints']['travelerType']) {
  return { SOLO: '独自出行', COUPLE: '伴侣同行', FAMILY: '家庭出行', FRIENDS: '朋友同行', BUSINESS: '商务出行' }[type]
}

function statusLabel(status: string) {
  return { DRAFT: '草稿', PLANNING: '规划中', READY: '可使用', FAILED: '规划失败' }[status] ?? status
}

function mobilityLabel(level: string | undefined) {
  return { STANDARD: '标准', REDUCED: '行动较缓', STEP_FREE: '无障碍' }[level ?? 'STANDARD'] ?? '标准'
}

function mealLabel(mealType: 'BREAKFAST' | 'LUNCH' | 'DINNER') {
  return { BREAKFAST: '早餐', LUNCH: '午餐', DINNER: '晚餐' }[mealType]
}

function mealSourceLabel(source?: 'SYSTEM_DEFAULT' | 'USER_SET') {
  return source === 'USER_SET' ? '用户设置' : '系统默认'
}

function formatMealWindow(mealType: 'BREAKFAST' | 'LUNCH' | 'DINNER') {
  const window = props.trip?.constraints.mealWindows?.find((item) => item.mealType === mealType)
  if (!window) return '未设置'
  return `${window.startTime.slice(0, 5)}–${window.endTime.slice(0, 5)}`
}

const isItineraryStale = computed(() => props.itinerary?.stale === true)

const accommodationSummary = computed(() => {
  const acc = props.trip?.constraints.accommodation
  if (acc?.poi) return { text: acc.poi.name, note: '已确认' }
  if (acc?.placeName) return { text: acc.placeName, note: '待重新确认' }
  return { text: '尚未选择', note: null }
})

/** No trusted coordinate anchors at all: transit uses an estimated default start. */
const usesEstimatedAnchors = computed(() => {
  const constraints = props.trip?.constraints
  if (!constraints) return false
  return !constraints.arrival?.poi
    && !constraints.departure?.poi
    && !constraints.accommodation?.poi
})

function formatDate(date: string) {
  return date.replaceAll('-', '.')
}

function formatCollectedAt(value: string) {
  return chinaDateTimeFormatter.format(new Date(value))
}

function freshnessLabel(status: Itinerary['knowledge']['freshness']['status']) {
  return { FRESH: '来源新鲜', STALE: '来源可能过期', UNAVAILABLE: '新鲜度不可用' }[status]
}

function evidenceStatusLabel(status: Itinerary['knowledge']['status']) {
  return { REAL: '真实知识', DEMO: '演示知识', UNAVAILABLE: '知识不可用' }[status]
}

function providerLabel(provider: Itinerary['provider']) {
  return { AMAP: '真实数据', DEMO: '演示数据', MIXED: '混合数据', PLANNER: '规划器数据' }[provider]
}

function formatDay(date: string) {
  const [, month, day] = date.split('-')
  return `${Number(month)}月${Number(day)}日`
}

function formatTime(dateTime: string) {
  const value = new Date(dateTime)
  return Number.isNaN(value.getTime()) ? dateTime : chinaTimeFormatter.format(value)
}

function formatMoney(amount: number) {
  return `¥${amount}`
}

function selectActivity(activityId: string) {
  selectedActivityId.value = activityId
  void nextTick(() => {
    const target = document.getElementById(`activity-${activityId}`)
    target?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
  })
}

function selectWeatherDate(date: string) {
  selectedMapDate.value = date
  const activity = props.itinerary?.days.find((day) => day.date === date)?.activities[0]
  // Date cards filter the map only. Timeline scrolling is reserved for an
  // explicit itinerary activity selection, not for changing map scope.
  selectedActivityId.value = activity?.id ?? null
}

function showAllMapRoutes() {
  selectedMapDate.value = null
}

async function openItineraryEdit(input: ItineraryEditInput, event?: Event) {
  rememberTrigger(event?.currentTarget)
  itineraryEditBusy.value = true
  itineraryEditError.value = null
  pendingItineraryEdit.value = input
  itineraryEditPreview.value = null
  try {
    itineraryEditPreview.value = await props.previewItineraryEdit(input)
  } catch (cause) {
    itineraryEditError.value = cause instanceof ApiError ? cause.message : '无法预览本次修改'
  } finally {
    itineraryEditBusy.value = false
  }
}

function closeItineraryEdit() {
  pendingItineraryEdit.value = null
  itineraryEditPreview.value = null
  itineraryEditError.value = null
}

async function confirmItineraryEdit() {
  if (!pendingItineraryEdit.value || !itineraryEditPreview.value?.canApply) return
  itineraryEditBusy.value = true
  itineraryEditError.value = null
  try {
    queueItineraryEdit(pendingItineraryEdit.value)
    closeItineraryEdit()
  } catch (cause) {
    itineraryEditError.value = cause instanceof ApiError ? cause.message : '行程修改失败，请稍后重试'
  } finally {
    itineraryEditBusy.value = false
  }
}

function basicActivityEdit(
  activity: ItineraryActivity,
  operation: 'DELETE_ACTIVITY' | 'LOCK_ACTIVITY' | 'UNLOCK_ACTIVITY',
): ItineraryEditInput {
  return {
    baseVersionId: props.itinerary!.versionId,
    operation,
    activityId: activity.id,
  }
}

function moveActivityEdit(
  day: Itinerary['days'][number],
  activity: ItineraryActivity,
  direction: 'up' | 'down',
): ItineraryEditInput {
  const activityIndex = day.activities.findIndex((item) => item.id === activity.id)
  const adjacentIndex = direction === 'up' ? activityIndex - 1 : activityIndex + 1
  const anchor = day.activities[adjacentIndex]
  if (activityIndex < 0 || !anchor) {
    throw new Error('Activity cannot move in the requested direction')
  }
  const duration = new Date(activity.endTime).getTime() - new Date(activity.startTime).getTime()
  const targetStart = direction === 'up'
    ? new Date(new Date(anchor.startTime).getTime() - duration)
    : new Date(anchor.endTime)
  const targetEnd = new Date(targetStart.getTime() + duration)
  return {
    baseVersionId: props.itinerary!.versionId,
    operation: 'MOVE_ACTIVITY',
    activityId: activity.id,
    targetDate: day.date,
    targetOrder: adjacentIndex,
    targetStartTime: toChinaOffset(targetStart),
    targetEndTime: toChinaOffset(targetEnd),
  }
}

function toChinaOffset(value: Date) {
  const local = value.toLocaleString('sv-SE', {
    timeZone: 'Asia/Shanghai',
    hour12: false,
  }).replace(' ', 'T')
  return `${local}+08:00`
}

function itineraryEditLabel(operation?: ItineraryEditInput['operation']) {
  return {
    DELETE_ACTIVITY: '删除活动',
    LOCK_ACTIVITY: '锁定活动',
    UNLOCK_ACTIVITY: '解除锁定',
    MOVE_ACTIVITY: '移动活动',
    UPDATE_TRANSIT_LEG: '更新通勤方式',
  }[operation ?? 'DELETE_ACTIVITY']
}

function activityDuration(activity: ItineraryActivity): string {
  const minutes = (new Date(activity.endTime).getTime() - new Date(activity.startTime).getTime()) / 60000
  if (minutes >= 60) return `${Math.round(minutes / 60)}小时`
  return `${Math.round(minutes)}分钟`
}

function transitSummary(leg: ItineraryTransitLeg): string {
  const mins = Math.round(leg.durationSeconds / 60)
  const km = (leg.distanceMeters / 1000).toFixed(1)
  return `${mins} 分钟 · ${km} km`
}

const totalPlaces = computed(() =>
  props.itinerary?.days.reduce(
    (sum, day) => sum + day.activities.filter((activity) => !isStructuralKind(activity.kind)).length,
    0,
  ) ?? 0
)

const activityKindLabels: Record<string, string> = {
  MEAL: '餐饮',
  ACCOMMODATION: '住宿',
  ARRIVAL: '到达',
  DEPARTURE: '离开',
  EXPERIENCE: '体验',
}

function activityKindLabel(kind?: string | null): string {
  if (!kind) return ''
  return activityKindLabels[kind] ?? kind
}
const factImpacts = computed(() => props.itinerary?.factImpacts ?? [])
const latestCityIntelligenceImport = computed(() => props.guideImports
  .filter((guide) => guide.sourceType === 'CITY_INTELLIGENCE')
  .sort((left, right) => Date.parse(right.fetchedAt) - Date.parse(left.fetchedAt))[0] ?? null)
const cityWeatherFacts = computed(() => {
  const cityImport = latestCityIntelligenceImport.value
  if (!cityImport?.enabled) return []
  return cityImport.facts.filter((fact) => fact.category === 'WEATHER')
})
const officialFactCount = computed(() => factImpacts.value.filter(impact =>
  impact.reliabilityLevel.startsWith('OFFICIAL')).length)
const communityFactCount = computed(() => factImpacts.value.length - officialFactCount.value)
const weatherFactCount = computed(() => factImpacts.value.filter(
  impact => impact.category === 'WEATHER',
).length)
const staleFactCount = computed(() => factImpacts.value.filter(impact => impact.stale).length)
const conflictedFactCount = computed(() => factImpacts.value.filter(
  impact => impact.conflicted,
).length)
const refreshFailedCount = computed(() => factImpacts.value.filter(
  impact => impact.refreshFailed,
).length)

function factEffectLabel(effect: string) {
  const labels: Record<string, string> = {
    OUTDOOR_POI_DOWNRANKED: '露天景点降权',
    INDOOR_POI_UPRANKED: '室内景点优先',
    OFFICIAL_CLOSURE_APPLIED: '官方关闭约束已应用',
    RESERVATION_REQUIRED: '需要预约',
    OPENING_HOURS_APPLIED: '已核验开放时间',
    OFFICIAL_TICKET_BUDGET_APPLIED: '官方门票计入预算',
    COMMUNITY_GUIDE_SOFT_SIGNAL: '社区攻略软排序',
    STALE_FACT_WARNING: '过期事实提示',
  }
  return labels[effect] ?? effect
}

const totalWalkDistance = computed(() => {
  if (!props.itinerary) return 0
  return props.itinerary.days.reduce((sum, day) =>
    sum + day.transitLegs
      .filter((leg) => leg.mode === 'WALKING')
      .reduce((legSum, leg) => legSum + leg.distanceMeters, 0), 0)
})

const totalDurationMinutes = computed(() => {
  if (!props.itinerary) return 0
  return props.itinerary.days.reduce((sum, day) =>
    sum + day.activities.reduce((actSum, activity) =>
      actSum + (new Date(activity.endTime).getTime() - new Date(activity.startTime).getTime()) / 60000, 0), 0)
})

const tripDayCount = computed(() => {
  if (!props.trip?.startDate || !props.trip?.endDate) return 1
  const start = new Date(props.trip.startDate)
  const end = new Date(props.trip.endDate)
  return Math.max(1, Math.ceil((end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24)) + 1)
})

const destinationGradientClass = computed(() => {
  const map: Record<string, string> = {
    '广州': 'dest-gz', '北京': 'dest-bj', '杭州': 'dest-hz',
    '长沙': 'dest-cs', '成都': 'dest-cd', '上海': 'dest-sh', '深圳': 'dest-sz',
  }
  return map[props.trip?.destination ?? ''] ?? 'bg-gradient-to-br from-primary-600 via-primary-700 to-primary-800'
})

const tripThemeLabel = computed(() => {
  if (!props.trip) return ''
  const prefs = props.trip.constraints.preferences.slice(0, 2)
  if (prefs.length === 0) return `${tripDayCount.value}天行程`
  return prefs.join(' · ')
})

watch(() => props.itinerary, (nextItinerary) => {
  const firstActivity = nextItinerary?.days.flatMap((day) => day.activities).find((activity) => activity.coordinates)
  if (!firstActivity || !nextItinerary?.days.flatMap((day) => day.activities).some((activity) => activity.id === selectedActivityId.value)) {
    selectedActivityId.value = firstActivity?.id ?? null
  }
  if (selectedMapDate.value && !nextItinerary?.days.some((day) => day.date === selectedMapDate.value)) {
    selectedMapDate.value = null
  }
  if (nextItinerary) queueRecommendedLongWalks(nextItinerary)
}, { immediate: true })
</script>

<template>
  <div class="min-h-screen bg-surface-50">
    <!-- Top Bar -->
    <header class="sticky top-0 z-30 glass-surface border-b border-surface-200/60">
      <div class="mx-auto flex h-16 max-w-6xl items-center justify-between gap-6 px-6">
        <div class="flex items-center gap-3 min-w-0">
          <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-primary-600 text-white shadow-sm">
            <Compass :size="20" aria-hidden="true" />
          </span>
          <div class="min-w-0">
            <strong class="text-base text-surface-900">TripPilot</strong>
            <span class="hidden sm:inline text-xs text-surface-400 ml-2">旅行规划工作台</span>
          </div>
        </div>
        <div class="flex items-center gap-4 min-w-0">
          <div class="hidden sm:grid min-w-0 max-w-[220px] text-right">
            <strong class="truncate text-sm text-surface-700">{{ user.displayName }}</strong>
            <span class="truncate text-xs text-surface-400">{{ user.email }}</span>
          </div>
          <button
            class="flex h-9 w-9 items-center justify-center rounded-xl border border-surface-200 bg-white text-surface-500 transition-colors hover:bg-surface-100 hover:text-surface-700"
            type="button"
            title="退出登录"
            aria-label="退出登录"
            @click="emit('logout')"
          >
            <LogOut :size="17" aria-hidden="true" />
          </button>
        </div>
      </div>
    </header>

    <!-- Main Content -->
    <main class="mx-auto max-w-6xl px-4 sm:px-6 py-6 sm:py-10 pb-24">
      <!-- Back -->
      <button
        class="mb-6 inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-medium text-surface-500 transition-colors hover:bg-surface-100 hover:text-surface-700"
        type="button"
        @click="emit('back')"
      >
        <ArrowLeft :size="16" aria-hidden="true" />
        返回旅行列表
      </button>

      <!-- Loading -->
      <section v-if="busy" class="flex min-h-[360px] items-center justify-center gap-2">
        <span class="h-2 w-2 animate-pulse rounded-full bg-primary-400" />
        <span class="h-2 w-2 animate-pulse rounded-full bg-primary-400" style="animation-delay: 0.2s" />
        <span class="h-2 w-2 animate-pulse rounded-full bg-primary-400" style="animation-delay: 0.4s" />
      </section>

      <!-- Error -->
      <section v-else-if="error" class="flex min-h-[360px] flex-col items-center justify-center gap-4 text-surface-500">
        <p role="alert" class="text-red-600">{{ error }}</p>
        <Button variant="outline" @click="emit('back')">返回旅行列表</Button>
      </section>

      <template v-else-if="trip">
        <!-- Trip Hero Card -->
        <Card class="mb-8 overflow-hidden" padding="none">
          <div :class="destinationGradientClass" class="relative min-h-[200px] sm:min-h-[260px] px-6 sm:px-8 py-6 sm:py-8 text-white flex flex-col justify-between">
            <!-- Decorative pattern -->
            <div class="absolute inset-0 opacity-10 hero-pattern" />
            <!-- Subtle radial glow -->
            <div class="absolute top-0 right-0 w-64 h-64 bg-white/5 rounded-full blur-3xl" />

            <div class="relative z-10 flex items-start justify-between gap-4">
              <div class="min-w-0">
                <p class="text-xs font-semibold uppercase tracking-widest text-white/60 mb-2">Trip</p>
                <h1 class="text-2xl sm:text-4xl font-bold tracking-tight text-balance">{{ trip.title }}</h1>
                <p class="text-sm text-white/70 mt-2">{{ tripThemeLabel }}</p>
                <div class="flex flex-wrap items-center gap-2 text-sm text-white/60 mt-3">
                  <span class="inline-flex items-center gap-1.5">
                    <MapPin :size="14" aria-hidden="true" />
                    {{ trip.destination }}
                  </span>
                  <span class="text-white/30">·</span>
                  <span class="inline-flex items-center gap-1.5">
                    <CalendarDays :size="14" aria-hidden="true" />
                    {{ formatDate(trip.startDate) }} — {{ formatDate(trip.endDate) }}
                  </span>
                  <span class="text-white/30">·</span>
                  <span>{{ tripDayCount }}天{{ tripDayCount - 1 }}夜</span>
                </div>
              </div>
              <div class="flex flex-col items-end gap-2 shrink-0">
                <Badge variant="accent">{{ statusLabel(trip.status) }}</Badge>
                <span class="text-xs text-white/40">版本 {{ itinerary ? itinerary.versionNumber : trip.version }}</span>
              </div>
            </div>

            <!-- Travel Stats Bar -->
            <div v-if="itinerary" class="relative z-10 mt-6 flex flex-wrap items-center gap-5 sm:gap-8 text-sm">
              <div class="flex items-center gap-2">
                <span class="flex h-8 w-8 items-center justify-center rounded-xl bg-white/15 text-white"><MapPin :size="15" aria-hidden="true" /></span>
                <div>
                  <div class="font-bold tabular-nums">{{ totalPlaces }}</div>
                  <div class="text-xs text-white/50">个地点</div>
                </div>
              </div>
              <div v-if="totalWalkDistance > 0" class="flex items-center gap-2">
                <span class="flex h-8 w-8 items-center justify-center rounded-xl bg-white/15 text-white"><Route :size="15" aria-hidden="true" /></span>
                <div>
                  <div class="font-bold tabular-nums">{{ (totalWalkDistance / 1000).toFixed(1) }}km</div>
                  <div class="text-xs text-white/50">步行距离</div>
                </div>
              </div>
              <div class="flex items-center gap-2">
                <span class="flex h-8 w-8 items-center justify-center rounded-xl bg-white/15 text-white"><Clock3 :size="15" aria-hidden="true" /></span>
                <div>
                  <div class="font-bold tabular-nums">{{ Math.round(totalDurationMinutes / 60) }}h</div>
                  <div class="text-xs text-white/50">游玩时间</div>
                </div>
              </div>
              <div class="flex items-center gap-2">
                <span class="flex h-8 w-8 items-center justify-center rounded-xl bg-white/15 text-white"><Coins :size="15" aria-hidden="true" /></span>
                <div>
                  <div class="font-bold tabular-nums">{{ formatMoney(itinerary.estimatedTotalCost) }}</div>
                  <div class="text-xs text-white/50">预计花费</div>
                </div>
              </div>
              <div class="flex items-center gap-1.5 ml-auto">
                <span class="text-xs font-semibold uppercase px-2 py-1 rounded-lg bg-white/15 text-white/80">{{ providerLabel(itinerary.provider) }}</span>
              </div>
            </div>
          </div>
        </Card>

        <!-- Plan Evaluation -->
        <PlanEvaluationPanel
          v-if="itinerary && evaluation !== undefined"
          :evaluation="evaluation"
          :show-legacy="evaluation === null"
        />
        <div
          v-else-if="itinerary && evaluationBusy"
          class="mb-6 rounded-2xl border border-surface-200 bg-white px-5 py-4 text-sm text-surface-500"
          role="status"
        >
          正在加载行程质量评估…
        </div>
        <div
          v-else-if="itinerary && evaluationError"
          class="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900"
          role="alert"
        >
          <span>{{ evaluationError }}</span>
          <Button variant="outline" size="sm" @click="reloadEvaluation">重试质量评估</Button>
        </div>

        <!-- Planning Actions -->
        <div class="mb-6 flex flex-wrap items-center gap-3">
          <div class="flex items-center gap-2 flex-1 min-w-0">
            <span class="text-sm font-semibold text-surface-500 uppercase tracking-wider">Itinerary</span>
            <h3 v-if="itinerary" class="text-xs text-surface-400 font-normal m-0">{{ itinerary.title }}</h3>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <Button
              v-if="itinerary && datesNeedingTransitRefresh.length"
              variant="outline"
              size="sm"
              :disabled="planningState === 'queued'"
              class="secondary-planning-button"
              @click="startLocalReplanning"
            >
              <Route :size="15" aria-hidden="true" />
              刷新交通
            </Button>
            <Button
              :variant="itinerary ? 'outline' : 'primary'"
              size="sm"
              data-testid="start-planning"
              :disabled="planningState === 'queued'"
              @click="startPlanning"
            >
              <LoaderCircle v-if="planningState === 'queued'" class="animate-spin" :size="15" aria-hidden="true" />
              <RefreshCw v-else-if="itinerary" :size="15" aria-hidden="true" />
              <Play v-else :size="15" aria-hidden="true" />
              {{ planningState === 'queued' ? '规划中' : itinerary ? '重新规划' : '开始规划' }}
            </Button>
            <Button
              v-if="planningState === 'queued'"
              variant="danger"
              size="sm"
              @click="cancelPlanning"
            >
              <X :size="15" aria-hidden="true" />取消规划
            </Button>
          </div>
        </div>

        <!-- Planning Status -->
        <div v-if="planningState === 'queued'" class="mb-6 flex items-center gap-3 rounded-2xl bg-primary-50 px-5 py-3 text-sm text-primary-700 border border-primary-100" role="status">
          <LoaderCircle class="animate-spin" :size="16" aria-hidden="true" />
          正在生成行程
        </div>
        <div v-else-if="planningState === 'cancelled'" class="mb-6 rounded-2xl bg-surface-100 px-5 py-3 text-sm text-surface-500" role="status">规划已取消</div>
        <div v-else-if="planningError" class="mb-6 rounded-2xl bg-red-50 px-5 py-3 text-sm text-red-700 border border-red-100" role="alert">{{ planningError }}</div>
        <div v-if="transitEditError" class="mb-6 rounded-2xl bg-red-50 px-5 py-3 text-sm text-red-700 border border-red-100" role="alert">{{ transitEditError }}</div>

        <!-- Agent Planning Pipeline -->
        <PlanningProgress
          v-if="planningState !== 'idle'"
          :planning-state="planningState"
          :progress="planningProgress"
          :progress-history="planningProgressHistory"
        />

        <!-- Itinerary Loading/Error/Empty -->
        <div v-if="itineraryBusy" class="flex min-h-[180px] items-center justify-center gap-2">
          <span class="h-2 w-2 animate-pulse rounded-full bg-primary-400" />
          <span class="h-2 w-2 animate-pulse rounded-full bg-primary-400" style="animation-delay: 0.2s" />
          <span class="h-2 w-2 animate-pulse rounded-full bg-primary-400" style="animation-delay: 0.4s" />
        </div>
        <div v-else-if="itineraryError" class="flex min-h-[180px] flex-col items-center justify-center gap-2 rounded-3xl bg-red-50 text-red-700" role="alert">
          <strong>当前行程加载失败</strong>
          <span class="text-sm">{{ itineraryError }}</span>
        </div>
        <div v-else-if="!itinerary" class="flex min-h-[180px] flex-col items-center justify-center gap-3 rounded-3xl bg-surface-100 text-surface-400">
          <Route :size="28" aria-hidden="true" />
          <strong class="text-surface-500">尚未生成行程</strong>
          <span class="text-sm">点击上方「开始规划」生成行程</span>
        </div>

        <!-- Itinerary Content -->
        <template v-else>
          <!-- Hidden itinerary heading for accessibility / test compatibility -->
          <h2 id="itinerary-title" class="sr-only">行程时间轴</h2>
            <!-- Map Card -->
            <Card class="mb-6 overflow-hidden" padding="none">
              <TripWeatherTimeline
                :weather-facts="cityWeatherFacts"
                :start-date="trip.startDate"
                :end-date="trip.endDate"
                :selected-date="selectedMapDate"
                @select-date="selectWeatherDate"
                @show-all="showAllMapRoutes"
              />
              <div class="h-[380px] sm:h-[480px] w-full">
                <TripMap
                :itinerary="itinerary"
                :selected-activity-id="selectedActivityId"
                :selected-date="selectedMapDate"
                @select-activity="selectActivity"
              />
            </div>
          </Card>

          <!-- Travel Stats Bar -->
          <div class="mb-8 flex flex-wrap items-center justify-center gap-6 sm:gap-10 px-4 py-4 rounded-2xl bg-white border border-surface-200/60 shadow-soft text-sm text-surface-600">
            <div class="flex items-center gap-2">
              <MapPin :size="16" class="text-primary-500" aria-hidden="true" />
              <span class="font-semibold text-surface-800">{{ totalPlaces }}</span> 个地点
            </div>
            <div v-if="totalWalkDistance > 0" class="flex items-center gap-2">
              <Route :size="16" class="text-primary-500" aria-hidden="true" />
              <span class="font-semibold text-surface-800">{{ (totalWalkDistance / 1000).toFixed(1) }}km</span> 步行
            </div>
            <div class="flex items-center gap-2">
              <Clock3 :size="16" class="text-primary-500" aria-hidden="true" />
              <span class="font-semibold text-surface-800">{{ Math.round(totalDurationMinutes / 60) }}h</span> 游玩
            </div>
          </div>

          <!-- Day Timeline -->
          <div class="space-y-10">
            <section v-for="(day, dayIndex) in itinerary.days" :key="day.date">
              <!-- Day Header -->
              <div class="mb-5">
                <div class="flex items-center gap-3">
                  <span class="text-xs font-bold uppercase tracking-widest text-primary-500 bg-primary-50 px-2.5 py-1 rounded-lg">
                    Day {{ dayIndex + 1 }}
                  </span>
                  <h2 class="text-lg font-bold text-surface-800">{{ formatDay(day.date) }}</h2>
                </div>
                <div class="mt-3 h-px bg-gradient-to-r from-surface-200 via-surface-200 to-transparent" />
              </div>

              <!-- Timeline -->
              <div class="relative ml-2">
                <!-- Timeline bar -->
                <div class="absolute left-[4.5rem] sm:left-[5.5rem] top-0 bottom-0 w-px bg-surface-200" aria-hidden="true" />

                <ol class="space-y-0">
                  <template v-for="(activity, activityIndex) in day.activities" :key="activity.id">
                    <!-- Activity Item -->
                    <li
                      :id="`activity-${activity.id}`"
                      class="relative pb-5 group"
                      :class="{ 'z-10': activity.id === selectedActivityId }"
                    >
                      <div class="flex gap-4 sm:gap-6">
                        <!-- Time -->
                        <div class="flex-none w-14 sm:w-16 pt-0.5">
                          <time class="block text-xs font-semibold text-surface-500 tabular-nums">
                            {{ formatTime(activity.startTime) }}
                          </time>
                        </div>

                        <!-- Dot -->
                        <div class="relative flex-none flex items-start pt-1.5">
                          <span
                            class="relative z-10 block h-3 w-3 rounded-full border-2 border-white ring-1 transition-all duration-200"
                            :class="activity.id === selectedActivityId
                              ? 'bg-primary-600 ring-primary-400 scale-125'
                              : activity.locked
                                ? 'bg-amber-400 ring-amber-300'
                                : 'bg-surface-300 ring-surface-300'"
                          />
                        </div>

                        <!-- Activity Card -->
                        <Card
                          :class="cn(
                            'flex-1 min-w-0 transition-all duration-300 shadow-travel-card hover:shadow-travel-card-hover',
                            activity.id === selectedActivityId && 'ring-2 ring-primary-400/40 shadow-travel-card-hover',
                          )"
                          padding="md"
                          @click="selectActivity(activity.id)"
                        >
                          <div class="flex items-start justify-between gap-4">
                            <button
                              type="button"
                              class="min-w-0 flex-1 cursor-pointer bg-transparent border-0 p-0 text-left text-inherit"
                              :aria-label="`选择活动 ${activity.title}`"
                              :aria-pressed="activity.id === selectedActivityId"
                              @click="selectActivity(activity.id)"
                            >
                              <!-- Title row with lock -->
                              <div class="flex items-center gap-2 mb-2">
                                <span class="flex items-center justify-center w-8 h-8 rounded-xl bg-primary-50 text-primary-600 text-xs font-bold shrink-0">
                                  {{ activityIndex + 1 }}
                                </span>
                                <span
                                  v-if="activity.kind && activity.kind !== 'ATTRACTION'"
                                  class="inline-flex items-center rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700 shrink-0"
                                >
                                  {{ activityKindLabel(activity.kind) }}
                                </span>
                                <h3 class="text-base font-semibold text-surface-900 truncate">{{ activity.title }}</h3>
                                <Lock v-if="activity.locked" :size="12" class="text-amber-500 shrink-0" />
                              </div>

                              <!-- Tags row -->
                              <div class="flex flex-wrap items-center gap-1.5 mb-2">
                                <span class="inline-flex items-center gap-1 rounded-full bg-surface-100 px-2.5 py-1 text-xs font-medium text-surface-600">
                                  <Clock3 :size="11" aria-hidden="true" />
                                  {{ formatTime(activity.startTime) }} — {{ formatTime(activity.endTime) }}
                                </span>
                                <span class="inline-flex items-center gap-1 rounded-full bg-surface-100 px-2.5 py-1 text-xs font-medium text-surface-600">
                                  预计{{ activityDuration(activity) }}
                                </span>
                                <span v-if="activity.address" class="inline-flex items-center gap-1 rounded-full bg-surface-100 px-2.5 py-1 text-xs font-medium text-surface-500 truncate max-w-[180px]">
                                  <MapPin :size="10" aria-hidden="true" />
                                  {{ activity.address }}
                                </span>
                              </div>

                              <!-- Meta row -->
                              <div class="flex flex-wrap items-center gap-3 text-xs text-surface-400">
                                <span v-if="activity.estimatedCost > 0" class="inline-flex items-center gap-1 font-semibold text-warm-600">
                                  <Coins :size="12" aria-hidden="true" />
                                  {{ formatMoney(activity.estimatedCost) }}
                                </span>
                                <span class="inline-flex items-center gap-1">
                                  <span class="inline-block w-1.5 h-1.5 rounded-full" :class="activity.source === 'DEMO' ? 'bg-amber-400' : 'bg-emerald-400'" />
                                  {{ activity.source === 'DEMO' ? 'Demo 数据' : activity.source }}
                                </span>
                              </div>
                            </button>

                            <!-- Action Buttons -->
                            <div class="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
                              <button
                                v-if="activityIndex > 0"
                                type="button"
                                :disabled="activity.locked || itineraryEditBusy"
                                class="flex h-7 w-7 items-center justify-center rounded-lg text-surface-400 hover:bg-surface-100 hover:text-surface-600 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                                :title="`前移 ${activity.title}`"
                                :aria-label="`前移活动 ${activity.title}`"
                                @click.stop="openItineraryEdit(moveActivityEdit(day, activity, 'up'), $event)"
                              ><ArrowUp :size="14" aria-hidden="true" /></button>
                              <button
                                v-if="activityIndex < day.activities.length - 1"
                                type="button"
                                :disabled="activity.locked || itineraryEditBusy"
                                class="flex h-7 w-7 items-center justify-center rounded-lg text-surface-400 hover:bg-surface-100 hover:text-surface-600 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                                :title="`后移 ${activity.title}`"
                                :aria-label="`后移活动 ${activity.title}`"
                                @click.stop="openItineraryEdit(moveActivityEdit(day, activity, 'down'), $event)"
                              ><ArrowDown :size="14" aria-hidden="true" /></button>
                              <button
                                type="button"
                                :disabled="itineraryEditBusy"
                                class="flex h-7 w-7 items-center justify-center rounded-lg text-surface-400 hover:bg-surface-100 hover:text-amber-600 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                                :title="activity.locked ? `解除锁定 ${activity.title}` : `锁定 ${activity.title}`"
                                :aria-label="activity.locked ? `解除锁定活动 ${activity.title}` : `锁定活动 ${activity.title}`"
                                @click.stop="openItineraryEdit(basicActivityEdit(activity, activity.locked ? 'UNLOCK_ACTIVITY' : 'LOCK_ACTIVITY'), $event)"
                              >
                                <LockOpen v-if="activity.locked" :size="14" aria-hidden="true" />
                                <Lock v-else :size="14" aria-hidden="true" />
                              </button>
                              <button
                                type="button"
                                :disabled="activity.locked || itineraryEditBusy"
                                class="flex h-7 w-7 items-center justify-center rounded-lg text-surface-400 hover:bg-red-50 hover:text-red-500 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                                :title="`删除 ${activity.title}`"
                                :aria-label="`删除活动 ${activity.title}`"
                                @click.stop="openItineraryEdit(basicActivityEdit(activity, 'DELETE_ACTIVITY'), $event)"
                              ><Trash2 :size="14" aria-hidden="true" /></button>
                            </div>
                          </div>
                        </Card>
                      </div>
                    </li>

                    <!-- Transit Leg Between Activities -->
                    <li
                      v-if="activityIndex < day.activities.length - 1 && transitLegFor(day, activityIndex)"
                      class="relative pb-5"
                    >
                      <div class="flex gap-4 sm:gap-6">
                        <div class="flex-none w-14 sm:w-16" />
                        <div class="relative flex-none flex items-start pt-1.5">
                          <span class="relative z-10 block h-2 w-2 rounded-full bg-surface-300 ring-2 ring-white" />
                        </div>
                        <div class="flex-1 min-w-0">
                          <TransitLegControl
                            :leg="transitLegFor(day, activityIndex)!"
                            :from-title="activity.title"
                            :to-title="day.activities[activityIndex + 1]!.title"
                            :selected-mode="transitModeFor(transitLegFor(day, activityIndex)!)"
                            :available-seconds="transitAvailableSeconds(day, activityIndex)"
                            :locked="transitLockedFor(transitLegFor(day, activityIndex)!)"
                            @select="selectTransitMode(transitLegFor(day, activityIndex)!, $event)"
                            @lock="setTransitLock(transitLegFor(day, activityIndex)!, $event)"
                          />
                        </div>
                      </div>
                    </li>
                  </template>
                </ol>
              </div>
            </section>
          </div>

          <section class="mt-10" aria-labelledby="planning-evidence-title">
            <Card>
              <div class="flex flex-wrap items-center justify-between gap-3">
                <h3 id="planning-evidence-title" class="text-base font-semibold text-surface-800">本次规划依据</h3>
                <div class="flex flex-wrap gap-2 text-xs">
                  <Badge variant="secondary">{{ factImpacts.length }} 条实际影响</Badge>
                  <Badge variant="success">{{ officialFactCount }} 条官方事实</Badge>
                  <Badge variant="secondary">{{ communityFactCount }} 条社区 / Provider 事实</Badge>
                  <Badge v-if="weatherFactCount" variant="secondary">{{ weatherFactCount }} 条天气影响</Badge>
                  <Badge v-if="staleFactCount" variant="warning">{{ staleFactCount }} 条已过期</Badge>
                  <Badge v-if="conflictedFactCount" variant="warning">{{ conflictedFactCount }} 条有冲突</Badge>
                  <Badge v-if="refreshFailedCount" variant="warning">{{ refreshFailedCount }} 条刷新失败降级</Badge>
                </div>
              </div>
              <p v-if="!factImpacts.length" class="mt-3 text-sm text-surface-400">
                本次结果没有记录到改变排序或约束的城市事实。
              </p>
              <ul v-else class="mt-4 space-y-3">
                <li
                  v-for="impact in factImpacts"
                  :key="`${impact.factId}-${impact.effect}-${impact.date}`"
                  class="rounded-xl bg-surface-50 px-4 py-3"
                >
                  <div class="flex flex-wrap items-center gap-2">
                    <strong class="text-sm text-surface-800">{{ factEffectLabel(impact.effect) }}</strong>
                    <Badge :variant="impact.reliabilityLevel.startsWith('OFFICIAL') ? 'success' : 'secondary'">
                      {{ impact.reliabilityLevel.startsWith('OFFICIAL') ? '官方' : '社区 / Provider' }}
                    </Badge>
                    <Badge v-if="impact.stale" variant="warning">已过期，仅提示</Badge>
                    <Badge v-if="impact.conflicted" variant="warning">存在来源冲突</Badge>
                    <Badge v-if="impact.refreshFailed" variant="warning">刷新失败，沿用快照</Badge>
                  </div>
                  <p class="mt-2 text-sm text-surface-600">{{ impact.reason }}</p>
                  <details class="mt-2 text-xs text-surface-500">
                    <summary class="cursor-pointer select-none">查看来源与核验信息</summary>
                    <div class="mt-2 grid gap-1 sm:grid-cols-2">
                      <p>来源：{{ impact.sourceName }}</p>
                      <p>来源类型：{{ impact.sourceType }}</p>
                      <p>核验：{{ formatCollectedAt(impact.checkedAt) }}</p>
                      <p v-if="impact.date">适用日期：{{ impact.date }}</p>
                      <p v-if="impact.targetName">影响对象：{{ impact.targetName }}</p>
                      <p class="sm:col-span-2">原句证据：{{ impact.evidence }}</p>
                      <p v-if="impact.sourceUrl" class="sm:col-span-2">
                        <a
                          :href="impact.sourceUrl"
                          target="_blank"
                          rel="noopener noreferrer"
                          class="font-semibold text-primary-600 hover:underline"
                        >
                          查看安全来源
                        </a>
                      </p>
                    </div>
                  </details>
                </li>
              </ul>
            </Card>
          </section>

          <!-- Knowledge Evidence Section -->
          <section class="mt-6" aria-labelledby="knowledge-title">
            <Card>
              <div class="flex items-center justify-between gap-4 mb-4">
                <div class="flex items-center gap-2">
                  <BookOpen :size="17" class="text-primary-600" aria-hidden="true" />
                  <h3 id="knowledge-title" class="text-base font-semibold text-surface-800">推荐依据</h3>
                </div>
                <div class="flex items-center gap-2">
                  <Badge :variant="itinerary.knowledge.status === 'REAL' ? 'success' : itinerary.knowledge.status === 'DEMO' ? 'warning' : 'secondary'">
                    {{ evidenceStatusLabel(itinerary.knowledge.status) }}
                  </Badge>
                  <Badge :variant="itinerary.knowledge.freshness.status === 'FRESH' ? 'success' : itinerary.knowledge.freshness.status === 'STALE' ? 'warning' : 'secondary'">
                    {{ freshnessLabel(itinerary.knowledge.freshness.status) }}
                  </Badge>
                </div>
              </div>
              <p class="text-sm text-surface-500 mb-4">检索问题：{{ itinerary.knowledge.query }}</p>
              <ul v-if="itinerary.knowledge.status === 'REAL' && itinerary.knowledge.citations.length" class="space-y-2">
                <li v-for="citation in itinerary.knowledge.citations" :key="citation.chunkId" class="rounded-xl bg-surface-50 px-4 py-3">
                  <a :href="citation.sourceUrl" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-1.5 text-sm font-semibold text-primary-600 hover:text-primary-700 hover:underline">
                    <span>{{ citation.title }}</span>
                    <ExternalLink :size="12" aria-hidden="true" />
                  </a>
                  <small class="block mt-1 text-xs text-surface-400">
                    {{ citation.sourceName }} · 文档 V{{ citation.documentVersion }} ·
                    采集于 {{ formatCollectedAt(citation.collectedAt) }}
                  </small>
                </li>
              </ul>
              <p v-else class="text-sm text-surface-400">{{ itinerary.knowledge.message }}</p>
            </Card>
          </section>
        </template>

        <div v-if="itinerary" class="mt-8">
          <ItineraryVersionPanel
            :versions="itineraryVersions"
            :current-version-id="itinerary.versionId"
            :busy="versionBusy"
            :error="versionError"
            :get-diff="getItineraryVersionDiff"
            :rollback="rollbackItinerary"
          />
        </div>

        <div v-if="itinerary" class="mt-8">
          <ItineraryActionsPanel
            :version-id="itinerary.versionId"
            :shares="itineraryShares"
            :create-share="createItineraryShare"
            :revoke-share="revokeItineraryShare"
            :download="downloadItineraryExport"
          />
        </div>

        <!-- Guide Intelligence Panel -->
        <div class="mt-8">
          <GuideIntelligencePanel
            :guide-imports="guideImports"
            :itinerary="itinerary"
            :destination="trip.destination"
            :start-date="trip.startDate"
            :end-date="trip.endDate"
            :busy="guideBusy"
            :error="guideError"
            :import-guide="importGuide"
            :set-guide-enabled="setGuideEnabled"
          />
        </div>

        <!-- Constraints Section -->
        <section class="mt-8" aria-labelledby="constraints-title">
          <Card>
            <div class="flex items-center justify-between gap-4 mb-6">
              <div>
                <p class="text-xs font-semibold uppercase tracking-widest text-surface-400 mb-1">Constraints</p>
                <h2 id="constraints-title" class="text-lg font-bold text-surface-800">结构化约束</h2>
              </div>
              <Button variant="outline" size="sm" @click="openEditor">
                <Pencil :size="14" aria-hidden="true" />
                编辑约束
              </Button>
            </div>

            <!-- Stale warning: live constraints changed since the itinerary was planned -->
            <div
              v-if="isItineraryStale"
              class="mb-6 flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
              role="status"
            >
              <RefreshCw :size="16" class="mt-0.5 shrink-0" aria-hidden="true" />
              <div>
                <strong>约束已更新，当前行程仍基于上一版约束。</strong>
                <span class="block text-xs text-amber-700 mt-0.5">保存配置后需重新规划，新约束才会反映到行程中。</span>
              </div>
            </div>

            <!-- Constraint Summary -->
            <div class="grid grid-cols-1 sm:grid-cols-3 gap-6 pb-6 border-b border-surface-100">
              <div class="flex items-start gap-3 sm:col-span-2">
                <MapPin :size="18" class="text-surface-400 mt-0.5 shrink-0" aria-hidden="true" />
                <div>
                  <dt class="text-xs font-semibold text-surface-400 uppercase tracking-wider mb-1">目的地与日期</dt>
                  <dd class="text-base font-bold text-surface-800">{{ trip.destination }}</dd>
                  <dd class="text-sm text-surface-500">{{ formatDate(trip.startDate) }} — {{ formatDate(trip.endDate) }}</dd>
                </div>
              </div>
              <div class="flex items-start gap-3">
                <Wallet :size="18" class="text-surface-400 mt-0.5 shrink-0" aria-hidden="true" />
                <div>
                  <dt class="text-xs font-semibold text-surface-400 uppercase tracking-wider mb-1">预算</dt>
                  <dd class="text-base font-bold text-surface-800">{{ trip.constraints.budgetAmount === null ? '未设置' : `¥${trip.constraints.budgetAmount}` }}</dd>
                </div>
              </div>
              <div class="flex items-start gap-3">
                <Users :size="18" class="text-surface-400 mt-0.5 shrink-0" aria-hidden="true" />
                <div>
                  <dt class="text-xs font-semibold text-surface-400 uppercase tracking-wider mb-1">同行</dt>
                  <dd class="text-base font-bold text-surface-800">{{ trip.constraints.travelers }} 人 · {{ travelerTypeLabel(trip.constraints.travelerType) }}</dd>
                </div>
              </div>
              <div class="flex items-start gap-3">
                <CircleGauge :size="18" class="text-surface-400 mt-0.5 shrink-0" aria-hidden="true" />
                <div>
                  <dt class="text-xs font-semibold text-surface-400 uppercase tracking-wider mb-1">节奏 · 行动能力</dt>
                  <dd class="text-base font-bold text-surface-800">{{ paceLabel(trip.constraints.pace) }} · {{ mobilityLabel(trip.constraints.mobilityLevel) }}</dd>
                </div>
              </div>
            </div>

            <!-- Detail Sections -->
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-6 mt-6">
              <div>
                <h3 class="text-sm font-semibold text-surface-700 mb-3">旅行偏好</h3>
                <div v-if="trip.constraints.preferences.length" class="flex flex-wrap gap-2">
                  <span v-for="preference in trip.constraints.preferences" :key="preference" class="inline-flex rounded-xl bg-primary-50 px-3 py-1.5 text-xs font-medium text-primary-700">
                    {{ preference }}
                  </span>
                </div>
                <p v-else class="text-sm text-surface-400">暂无偏好</p>
              </div>
              <div>
                <h3 class="text-sm font-semibold text-surface-700 mb-3">固定安排</h3>
                <p v-if="trip.constraints.fixedSchedules.length === 0" class="text-sm text-surface-400">暂无固定安排</p>
                <ul v-else class="space-y-2">
                  <li v-for="schedule in trip.constraints.fixedSchedules" :key="`${schedule.placeName}-${schedule.startTime}`" class="rounded-xl bg-surface-50 px-3 py-2">
                    <strong class="text-sm text-surface-700">{{ schedule.placeName }}</strong>
                    <span class="block text-xs text-surface-400">{{ schedule.startTime }} — {{ schedule.endTime }}</span>
                  </li>
                </ul>
              </div>
              <div>
                <h3 class="text-sm font-semibold text-surface-700 mb-3">到返与住宿</h3>
                <ul class="space-y-2 text-sm">
                  <li class="flex items-center gap-2">
                    <span class="text-surface-400">到达</span>
                    <span class="text-surface-700">{{ trip.constraints.arrival?.placeName ?? '尚未设置' }}</span>
                  </li>
                  <li class="flex items-center gap-2">
                    <span class="text-surface-400">返程</span>
                    <span class="text-surface-700">{{ trip.constraints.departure?.placeName ?? '尚未设置' }}</span>
                  </li>
                  <li class="flex items-center gap-2">
                    <span class="text-surface-400">酒店</span>
                    <span class="text-surface-700">{{ accommodationSummary.text }}</span>
                    <span v-if="accommodationSummary.note" class="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-medium text-amber-700">
                      {{ accommodationSummary.note }}
                    </span>
                  </li>
                  <li v-if="usesEstimatedAnchors" class="text-xs text-surface-400">
                    首末段交通 按默认起点估算
                  </li>
                </ul>
              </div>
              <div>
                <h3 class="text-sm font-semibold text-surface-700 mb-3">三餐时间</h3>
                <ul class="space-y-2 text-sm">
                  <li v-for="mealType in ['BREAKFAST', 'LUNCH', 'DINNER'] as const" :key="mealType" class="flex items-center gap-2">
                    <span class="w-8 text-surface-400">{{ mealLabel(mealType) }}</span>
                    <span class="text-surface-700">{{ formatMealWindow(mealType) }}</span>
                    <span class="text-xs text-surface-400">
                      · {{ mealSourceLabel(props.trip?.constraints.mealWindows?.find((w) => w.mealType === mealType)?.source) }}
                    </span>
                  </li>
                </ul>
              </div>
              <div>
                <h3 class="text-sm font-semibold text-surface-700 mb-3">必去与避开</h3>
                <p class="text-sm text-surface-500">
                  必去：{{ (trip.constraints.mustVisitPlaces ?? []).join('、') || '未设置' }}<br />
                  排除：{{ (trip.constraints.avoidPlaces ?? []).join('、') || '未设置' }}
                </p>
              </div>
            </div>
          </Card>
        </section>
      </template>
    </main>

      <section
        v-if="draftItineraryEdits.length"
        class="fixed bottom-5 left-1/2 z-40 flex w-[min(94vw,42rem)] -translate-x-1/2 flex-wrap items-center justify-between gap-3 rounded-2xl border border-primary-200 bg-white px-4 py-3 shadow-dialog"
        aria-label="行程修改草稿"
      >
        <p class="m-0 text-sm font-semibold text-surface-700">已暂存 {{ draftItineraryEdits.length }} 处修改，尚未保存为版本。</p>
              <p v-if="draftItineraryError" class="m-0 w-full text-sm text-red-700" role="alert">{{ draftItineraryError }}</p>
              <div class="flex gap-2">
                <Button variant="outline" size="sm" :disabled="draftItineraryBusy" @click="discardItineraryDraft">放弃草稿</Button>
                <Button size="sm" :disabled="draftItineraryBusy" data-testid="save-itinerary-draft" @click="saveItineraryDraft">
                  <LoaderCircle v-if="draftItineraryBusy" class="animate-spin" :size="14" aria-hidden="true" />确认保存版本
          </Button>
        </div>
      </section>

      <!-- Itinerary Edit Dialog -->
    <div v-if="pendingItineraryEdit && (itineraryEditPreview || itineraryEditError)" class="fixed inset-0 z-50 flex items-start justify-center pt-[10vh] sm:pt-[15vh]" @click.self="closeItineraryEdit">
      <div class="fixed inset-0 bg-surface-900/30 backdrop-blur-sm" aria-hidden="true" />
      <div class="relative mx-4 w-full max-w-md animate-scale-in rounded-3xl bg-white shadow-dialog ring-1 ring-black/5 overflow-hidden" role="dialog" aria-modal="true" aria-labelledby="itinerary-edit-title">
        <div class="flex items-center justify-between gap-4 px-6 py-5 border-b border-surface-100">
          <div>
            <p class="text-xs font-semibold uppercase tracking-widest text-surface-400 mb-1">Itinerary Change</p>
            <h2 id="itinerary-edit-title" class="text-base font-bold text-surface-800">确认行程修改</h2>
          </div>
          <button class="flex h-9 w-9 items-center justify-center rounded-xl border border-surface-200 text-surface-400 hover:bg-surface-50 transition-colors" type="button" title="关闭" aria-label="关闭" @click="closeItineraryEdit">
            <X :size="17" aria-hidden="true" />
          </button>
        </div>
        <div class="px-6 py-5">
          <p class="text-sm font-semibold text-surface-700 mb-4">{{ itineraryEditLabel(pendingItineraryEdit.operation) }}</p>
          <template v-if="itineraryEditPreview">
            <div class="grid grid-cols-2 gap-3 mb-4">
              <div class="rounded-xl bg-surface-50 px-4 py-3">
                <dt class="text-xs text-surface-400 mb-1">影响日期</dt>
                <dd class="text-sm font-semibold text-surface-700"><span v-for="date in itineraryEditPreview.impactedDates" :key="date" class="block">{{ date }}</span></dd>
              </div>
              <div class="rounded-xl bg-surface-50 px-4 py-3">
                <dt class="text-xs text-surface-400 mb-1">影响活动</dt>
                <dd class="text-sm font-semibold text-surface-700">{{ itineraryEditPreview.impactedActivityIds.length }} 项</dd>
              </div>
            </div>
            <ul v-if="itineraryEditPreview.warnings.length" class="mb-4 rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-700 space-y-1">
              <li v-for="warning in itineraryEditPreview.warnings" :key="warning">{{ warning }}</li>
            </ul>
            <ul v-if="itineraryEditPreview.blockingReasons.length" class="mb-4 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700 space-y-1">
              <li v-for="reason in itineraryEditPreview.blockingReasons" :key="reason.code">{{ reason.message }}</li>
            </ul>
          </template>
          <p v-if="itineraryEditError" class="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{{ itineraryEditError }}</p>
        </div>
        <div class="flex items-center justify-end gap-3 px-6 py-4 border-t border-surface-100 bg-surface-50/50">
          <Button variant="outline" size="sm" @click="closeItineraryEdit">取消</Button>
          <Button
            v-if="itineraryEditPreview"
            variant="primary"
            size="sm"
            :disabled="itineraryEditBusy || !itineraryEditPreview.canApply"
            aria-label="应用修改"
            @click="confirmItineraryEdit"
          >
            <LoaderCircle v-if="itineraryEditBusy" class="animate-spin" :size="14" aria-hidden="true" />
            应用修改
          </Button>
        </div>
      </div>
    </div>

    <!-- Constraints Edit Dialog -->
    <div v-if="editing && trip" class="fixed inset-0 z-50 flex items-start justify-center pt-[5vh] sm:pt-[8vh]" @click.self="editing = false">
      <div class="fixed inset-0 bg-surface-900/30 backdrop-blur-sm" aria-hidden="true" />
      <div
        ref="dialogElement"
        class="relative mx-4 w-full max-w-xl max-h-[90vh] overflow-y-auto animate-scale-in rounded-3xl bg-white shadow-dialog ring-1 ring-black/5"
        role="dialog"
        aria-modal="true"
        aria-labelledby="edit-constraints-title"
        tabindex="-1"
        @keydown="handleDialogKeydown"
      >
        <div class="flex items-center justify-between gap-4 px-6 py-5 border-b border-surface-100">
          <div>
            <p class="text-xs font-semibold uppercase tracking-widest text-surface-400 mb-1">Edit Constraints</p>
            <h2 id="edit-constraints-title" class="text-base font-bold text-surface-800">编辑约束</h2>
          </div>
          <button class="flex h-9 w-9 items-center justify-center rounded-xl border border-surface-200 text-surface-400 hover:bg-surface-50 transition-colors" type="button" title="关闭" aria-label="关闭" @click="editing = false">
            <X :size="17" aria-hidden="true" />
          </button>
        </div>

        <div class="px-6 py-5">
          <TripConstraintForm
            ref="configFormRef"
            :initial="trip"
            :server-date="serverDate"
            :search-places="searchPlaces"
            :suggest-places="suggestPlaces"
            :submitting="submitting"
            :error="formError"
            @submit="handleConfigSubmit"
          />
          <button
            v-if="versionConflict"
            class="mt-4 inline-flex h-10 items-center rounded-xl border border-red-200 bg-white px-4 text-sm font-medium text-red-600 hover:bg-red-50 transition-colors"
            type="button"
            :disabled="submitting"
            @click="reloadLatestTrip"
          >
            重新加载最新数据
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
