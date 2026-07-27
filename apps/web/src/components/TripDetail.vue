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
  type ItineraryVersionDiff,
  type ItineraryVersionSummary,
  type Trip,
  type UpdateTripConstraintsInput,
  type User,
} from '../lib/api'
import { useModalFocus } from '../lib/modal'
import { cn } from '../lib/utils'
import type { CommuteMode } from '../lib/transit'
import GuideIntelligencePanel from './GuideIntelligencePanel.vue'
import ItineraryVersionPanel from './ItineraryVersionPanel.vue'
import PlanningProgress from './PlanningProgress.vue'
import TripMap from './TripMap.vue'
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
  planningState: 'idle' | 'queued' | 'succeeded' | 'failed' | 'cancelled'
  planningError: string | null
  guideImports?: GuideImport[]
  guideBusy?: boolean
  guideError?: string | null
  importGuide?: (input: GuideImportInput) => Promise<void>
  setGuideEnabled?: (guideImportId: string, enabled: boolean) => Promise<void>
  previewItineraryEdit?: (input: ItineraryEditInput) => Promise<ItineraryEditPreview>
  applyItineraryEdit?: (input: ItineraryEditInput) => Promise<void>
  startReplanning?: (input: ItineraryReplanInput) => Promise<void>
  startPlanning: () => Promise<void>
  cancelPlanning: () => Promise<void>
  updateConstraints: (input: UpdateTripConstraintsInput) => Promise<void>
  reloadTrip: () => Promise<boolean>
}>(), {
  guideImports: () => [],
  itineraryVersions: () => [],
  versionBusy: false,
  versionError: null,
  getItineraryVersionDiff: async () => {
    throw new Error('Itinerary version diff is unavailable')
  },
  rollbackItinerary: async () => {},
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
  startReplanning: async () => {},
})

const emit = defineEmits<{
  back: []
  logout: []
}>()

const defaultPreferences = ['岭南文化', '本地美食', '城市漫步', '自然风景', '亲子体验', '夜间活动']
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
const pendingItineraryEdit = ref<ItineraryEditInput | null>(null)
const itineraryEditPreview = ref<ItineraryEditPreview | null>(null)
const selectedTransitModes = reactive<Record<string, CommuteMode>>({})
const lockedTransitLegs = reactive<Record<string, boolean>>({})
const transitEditBusy = ref(false)
const transitEditError = ref<string | null>(null)
const datesNeedingTransitRefresh = computed(() => props.itinerary?.days
  .filter((day) => day.activities.length > 1 && day.transitLegs.length !== day.activities.length - 1)
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
  return day.transitLegs.find((leg) => leg.fromActivityId === fromActivity.id && leg.toActivityId === toActivity.id)
    ?? day.transitLegs[activityIndex]
    ?? null
}

function transitModeFor(leg: ItineraryTransitLeg): CommuteMode {
  return selectedTransitModes[leg.id] ?? leg.mode
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
    await props.applyItineraryEdit({
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

async function selectTransitMode(leg: ItineraryTransitLeg, mode: CommuteMode) {
  if (transitLockedFor(leg) || (mode !== 'WALKING' && mode !== 'DRIVING')) return
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
  Object.keys(selectedTransitModes).forEach((legId) => { delete selectedTransitModes[legId] })
  Object.keys(lockedTransitLegs).forEach((legId) => { delete lockedTransitLegs[legId] })
  transitEditError.value = null
})
const form = reactive({
  budgetAmount: '',
  travelers: 1,
  travelerType: 'SOLO' as Trip['constraints']['travelerType'],
  pace: 'BALANCED' as Trip['constraints']['pace'],
  preferences: [] as string[],
  arrivalPlace: '',
  arrivalTime: '',
  departurePlace: '',
  departureTime: '',
  accommodationPlace: '',
  mustVisitText: '',
  avoidText: '',
  breakfastStart: '',
  breakfastEnd: '',
  lunchStart: '',
  lunchEnd: '',
  dinnerStart: '',
  dinnerEnd: '',
  mobilityLevel: 'STANDARD' as NonNullable<Trip['constraints']['mobilityLevel']>,
})

const preferenceOptions = computed(() => [
  ...new Set([...defaultPreferences, ...(props.trip?.constraints.preferences ?? [])]),
])

const { handleKeydown: handleDialogKeydown, rememberTrigger } = useModalFocus(
  editing,
  dialogElement,
  () => { editing.value = false },
)

function openEditor(event?: Event) {
  if (!props.trip) return
  rememberTrigger(event?.currentTarget)
  form.budgetAmount = props.trip.constraints.budgetAmount?.toString() ?? ''
  form.travelers = props.trip.constraints.travelers
  form.travelerType = props.trip.constraints.travelerType
  form.pace = props.trip.constraints.pace
  form.preferences = [...props.trip.constraints.preferences]
  form.arrivalPlace = props.trip.constraints.arrival?.placeName ?? ''
  form.arrivalTime = toChinaLocalInput(props.trip.constraints.arrival?.time)
  form.departurePlace = props.trip.constraints.departure?.placeName ?? ''
  form.departureTime = toChinaLocalInput(props.trip.constraints.departure?.time)
  form.accommodationPlace = props.trip.constraints.accommodation?.placeName ?? ''
  form.mustVisitText = (props.trip.constraints.mustVisitPlaces ?? []).join('、')
  form.avoidText = (props.trip.constraints.avoidPlaces ?? []).join('、')
  const windows = props.trip.constraints.mealWindows ?? []
  for (const meal of ['BREAKFAST', 'LUNCH', 'DINNER'] as const) {
    const window = windows.find((item) => item.mealType === meal)
    const prefix = meal === 'BREAKFAST' ? 'breakfast' : meal.toLowerCase()
    form[`${prefix}Start` as 'breakfastStart' | 'lunchStart' | 'dinnerStart'] = window?.startTime.slice(0, 5) ?? ''
    form[`${prefix}End` as 'breakfastEnd' | 'lunchEnd' | 'dinnerEnd'] = window?.endTime.slice(0, 5) ?? ''
  }
  form.mobilityLevel = props.trip.constraints.mobilityLevel ?? 'STANDARD'
  formError.value = null
  versionConflict.value = false
  editing.value = true
}

function togglePreference(preference: string) {
  const index = form.preferences.indexOf(preference)
  if (index >= 0) form.preferences.splice(index, 1)
  else form.preferences.push(preference)
}

async function saveConstraints() {
  if (!props.trip) return
  if (Boolean(form.arrivalPlace) !== Boolean(form.arrivalTime)) {
    formError.value = '请同时填写到达地点和到达时间'
    return
  }
  if (Boolean(form.departurePlace) !== Boolean(form.departureTime)) {
    formError.value = '请同时填写返程地点和返程时间'
    return
  }
  const partialMeal = [
    ['早餐', form.breakfastStart, form.breakfastEnd],
    ['午餐', form.lunchStart, form.lunchEnd],
    ['晚餐', form.dinnerStart, form.dinnerEnd],
  ].find(([, start, end]) => Boolean(start) !== Boolean(end))
  if (partialMeal) {
    formError.value = `请同时填写${partialMeal[0]}窗口的开始和结束时间`
    return
  }
  submitting.value = true
  formError.value = null
  versionConflict.value = false
  try {
    await props.updateConstraints({
      version: props.trip.version,
      budgetAmount: form.budgetAmount === '' ? null : Number(form.budgetAmount),
      travelers: form.travelers,
      travelerType: form.travelerType,
      pace: form.pace,
      preferences: [...form.preferences],
      fixedSchedules: props.trip.constraints.fixedSchedules.map((schedule) => ({ ...schedule })),
      arrival: form.arrivalPlace && form.arrivalTime
        ? { placeName: form.arrivalPlace, time: `${form.arrivalTime}:00+08:00` }
        : null,
      departure: form.departurePlace && form.departureTime
        ? { placeName: form.departurePlace, time: `${form.departureTime}:00+08:00` }
        : null,
      accommodation: form.accommodationPlace
        ? { placeName: form.accommodationPlace }
        : null,
      mustVisitPlaces: splitPlaces(form.mustVisitText),
      avoidPlaces: splitPlaces(form.avoidText),
      mealWindows: buildMealWindows(),
      mobilityLevel: form.mobilityLevel,
    })
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

function toChinaLocalInput(value?: string) {
  if (!value) return ''
  return new Date(value).toLocaleString('sv-SE', {
    timeZone: 'Asia/Shanghai',
    hour12: false,
  }).replace(' ', 'T').slice(0, 16)
}

function splitPlaces(value: string) {
  return [...new Set(value.split(/[,，、\n]/).map((item) => item.trim()).filter(Boolean))]
}

function buildMealWindows(): NonNullable<Trip['constraints']['mealWindows']> {
  const values = [
    ['BREAKFAST', form.breakfastStart, form.breakfastEnd],
    ['LUNCH', form.lunchStart, form.lunchEnd],
    ['DINNER', form.dinnerStart, form.dinnerEnd],
  ] as const
  return values
    .filter(([, start, end]) => start && end)
    .map(([mealType, startTime, endTime]) => ({ mealType, startTime, endTime }))
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
    await props.applyItineraryEdit(pendingItineraryEdit.value)
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
  props.itinerary?.days.reduce((sum, day) => sum + day.activities.length, 0) ?? 0
)
const factImpacts = computed(() => props.itinerary?.factImpacts ?? [])
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
                <span class="text-xs font-semibold uppercase px-2 py-1 rounded-lg bg-white/15 text-white/80">{{ itinerary.provider === 'DEMO' ? 'Demo 数据' : itinerary.provider }}</span>
              </div>
            </div>
          </div>
        </Card>

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
            <div class="h-[380px] sm:h-[480px] w-full">
              <TripMap
                :itinerary="itinerary"
                :selected-activity-id="selectedActivityId"
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

        <!-- Guide Intelligence Panel -->
        <div class="mt-8">
          <GuideIntelligencePanel
            :guide-imports="guideImports"
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

            <!-- Constraint Summary -->
            <div class="grid grid-cols-1 sm:grid-cols-3 gap-6 pb-6 border-b border-surface-100">
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
                  <dt class="text-xs font-semibold text-surface-400 uppercase tracking-wider mb-1">节奏</dt>
                  <dd class="text-base font-bold text-surface-800">{{ paceLabel(trip.constraints.pace) }}</dd>
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
                <p class="text-sm text-surface-500">
                  到达：{{ trip.constraints.arrival?.placeName ?? '未设置' }}<br />
                  返程：{{ trip.constraints.departure?.placeName ?? '未设置' }}<br />
                  住宿：{{ trip.constraints.accommodation?.placeName ?? '未设置' }}
                </p>
              </div>
              <div>
                <h3 class="text-sm font-semibold text-surface-700 mb-3">地点与行动能力</h3>
                <p class="text-sm text-surface-500">
                  必去：{{ (trip.constraints.mustVisitPlaces ?? []).join('、') || '未设置' }}<br />
                  排除：{{ (trip.constraints.avoidPlaces ?? []).join('、') || '未设置' }}<br />
                  行动能力：{{ trip.constraints.mobilityLevel ?? 'STANDARD' }}
                </p>
              </div>
            </div>
          </Card>
        </section>
      </template>
    </main>

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

        <form class="px-6 py-5" @submit.prevent="saveConstraints">
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label for="edit-budget" class="block text-xs font-semibold text-surface-600 mb-1.5">预算</label>
              <div class="flex items-center gap-2 h-10 rounded-xl border border-surface-200 bg-white px-3 focus-within:ring-2 focus-within:ring-primary-400/40 focus-within:border-primary-400 transition-shadow">
                <span class="text-surface-400 text-sm">¥</span>
                <input id="edit-budget" v-model="form.budgetAmount" type="number" min="0" step="0.01" class="w-full h-full border-0 bg-transparent text-sm text-surface-800 outline-0 placeholder:text-surface-300" data-modal-initial-focus />
              </div>
            </div>
            <div>
              <label for="edit-travelers" class="block text-xs font-semibold text-surface-600 mb-1.5">同行人数</label>
              <input id="edit-travelers" v-model.number="form.travelers" type="number" min="1" max="50" required class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
            </div>
            <div class="sm:col-span-2">
              <label for="edit-traveler-type" class="block text-xs font-semibold text-surface-600 mb-1.5">同行类型</label>
              <select id="edit-traveler-type" v-model="form.travelerType" required class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow">
                <option value="SOLO">独自出行</option>
                <option value="COUPLE">伴侣同行</option>
                <option value="FAMILY">家庭出行</option>
                <option value="FRIENDS">朋友同行</option>
                <option value="BUSINESS">商务出行</option>
              </select>
            </div>
            <div>
              <label for="arrival-place" class="block text-xs font-semibold text-surface-600 mb-1.5">到达地点</label>
              <input id="arrival-place" v-model.trim="form.arrivalPlace" maxlength="120" class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
            </div>
            <div>
              <label for="arrival-time" class="block text-xs font-semibold text-surface-600 mb-1.5">到达时间（北京时间）</label>
              <input id="arrival-time" v-model="form.arrivalTime" type="datetime-local" class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
            </div>
            <div>
              <label for="departure-place" class="block text-xs font-semibold text-surface-600 mb-1.5">返程地点</label>
              <input id="departure-place" v-model.trim="form.departurePlace" maxlength="120" class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
            </div>
            <div>
              <label for="departure-time" class="block text-xs font-semibold text-surface-600 mb-1.5">返程时间（北京时间）</label>
              <input id="departure-time" v-model="form.departureTime" type="datetime-local" class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
            </div>
            <div class="sm:col-span-2">
              <label for="accommodation-place" class="block text-xs font-semibold text-surface-600 mb-1.5">住宿锚点</label>
              <input id="accommodation-place" v-model.trim="form.accommodationPlace" maxlength="120" class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
            </div>
            <div>
              <label for="must-visit" class="block text-xs font-semibold text-surface-600 mb-1.5">必去地点（用顿号分隔）</label>
              <input id="must-visit" v-model="form.mustVisitText" maxlength="1000" class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
            </div>
            <div>
              <label for="avoid-places" class="block text-xs font-semibold text-surface-600 mb-1.5">排除地点（用顿号分隔）</label>
              <input id="avoid-places" v-model="form.avoidText" maxlength="1000" class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
            </div>
            <div class="sm:col-span-2">
              <label for="mobility-level" class="block text-xs font-semibold text-surface-600 mb-1.5">行动能力</label>
              <select id="mobility-level" v-model="form.mobilityLevel" class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow">
                <option value="STANDARD">标准步行</option>
                <option value="REDUCED">减少步行</option>
                <option value="STEP_FREE">尽量无台阶（车行接驳，场地需确认）</option>
              </select>
            </div>

            <!-- Meal Windows -->
            <div v-for="meal in [
              { key: 'breakfast', label: '早餐' },
              { key: 'lunch', label: '午餐' },
              { key: 'dinner', label: '晚餐' },
            ]" :key="meal.key" class="sm:col-span-2">
              <label class="block text-xs font-semibold text-surface-600 mb-1.5">{{ meal.label }}窗口</label>
              <div class="flex items-center gap-3">
                <input v-model="form[`${meal.key}Start` as 'breakfastStart' | 'lunchStart' | 'dinnerStart']" type="time" :aria-label="`${meal.label}开始时间`" class="flex-1 h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
                <span class="text-surface-400 text-sm">至</span>
                <input v-model="form[`${meal.key}End` as 'breakfastEnd' | 'lunchEnd' | 'dinnerEnd']" type="time" :aria-label="`${meal.label}结束时间`" class="flex-1 h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
              </div>
            </div>
          </div>

          <!-- Pace -->
          <fieldset class="mt-5 border-0 p-0">
            <legend class="text-xs font-semibold text-surface-600 mb-2">旅行节奏</legend>
            <div class="grid grid-cols-3 rounded-xl bg-surface-100 p-1">
              <label v-for="pace in [{v:'RELAXED',l:'舒缓'},{v:'BALANCED',l:'均衡'},{v:'INTENSIVE',l:'紧凑'}]" :key="pace.v"
                class="relative flex h-9 cursor-pointer items-center justify-center rounded-lg text-sm font-medium transition-all"
                :class="form.pace === pace.v ? 'bg-white text-primary-700 shadow-sm' : 'text-surface-500 hover:text-surface-700'"
              >
                <input v-model="form.pace" type="radio" :value="pace.v" class="sr-only" />
                {{ pace.l }}
              </label>
            </div>
          </fieldset>

          <!-- Preferences -->
          <fieldset class="mt-5 border-0 p-0">
            <legend class="text-xs font-semibold text-surface-600 mb-2">偏好</legend>
            <div class="flex flex-wrap gap-2">
              <label v-for="preference in preferenceOptions" :key="preference"
                class="relative inline-flex cursor-pointer items-center rounded-xl border px-3 py-2 text-sm font-medium transition-all"
                :class="form.preferences.includes(preference) ? 'border-primary-300 bg-primary-50 text-primary-700' : 'border-surface-200 bg-white text-surface-600 hover:bg-surface-50'"
              >
                <input
                  type="checkbox"
                  :value="preference"
                  :checked="form.preferences.includes(preference)"
                  class="sr-only"
                  @change="togglePreference(preference)"
                />
                {{ preference }}
              </label>
            </div>
          </fieldset>

          <!-- Error -->
          <p v-if="formError" class="mt-5 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700 border-l-4 border-red-400" role="alert">{{ formError }}</p>

          <button
            v-if="versionConflict"
            class="mt-4 inline-flex h-10 items-center rounded-xl border border-red-200 bg-white px-4 text-sm font-medium text-red-600 hover:bg-red-50 transition-colors"
            type="button"
            :disabled="submitting"
            @click="reloadLatestTrip"
          >
            重新加载最新数据
          </button>

          <!-- Actions -->
          <div class="flex items-center justify-end gap-3 mt-6 pt-5 border-t border-surface-100">
            <Button variant="outline" size="sm" type="button" @click="editing = false">取消</Button>
            <Button variant="primary" size="sm" type="submit" :disabled="submitting">保存约束</Button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
