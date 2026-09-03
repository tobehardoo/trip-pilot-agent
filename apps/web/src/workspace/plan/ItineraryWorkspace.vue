<script setup lang="ts">
// 旅行方案工作区（重新设计：A+ 精装单列）。
//
// 信息架构（A+ 方案）：
//   ① 摘要卡（TripOverview）
//   ② 完成成功条（替代旧朴素文本提示）
//   ③ 旅行路线：Day chips + 固定高度地图（活动↔地图双向联动）
//   ④ 每日行程：天卡折叠（默认展开第 1 天）+ 活动行点击可在地图聚焦
//   ⑤ 行程管理&更多：版本 / 分享导出 / 攻略情报 统一为手风琴分组
//
// 视觉统一：全部改用 tp-* token；时间戳经 formatChinaTime 化为 HH:mm。
import { computed, nextTick, ref, watch, onMounted } from 'vue'
import {
  Bed, BookOpen, Bus, CalendarDays, Car, Check, ChevronDown, ChevronRight,
  CloudLightning, CloudRain, CloudSnow, CloudSun, Cloudy, Coffee, FerrisWheel, Flame,
  Footprints, History, Home, Landmark, Lock, Map as MapIcon, MapPin, Mountain,
  Pencil, Plane, Route as RouteIcon, Sandwich, Search, Share2, ShoppingBag, Sun, Trees,
  Unlock, Utensils, Wand2, Trash2, X,
} from 'lucide-vue-next'

import TripOverview from './TripOverview.vue'
import TripRouteMap from './TripRouteMap.vue'
import ItineraryVersionPanel from '../../components/ItineraryVersionPanel.vue'
import ItineraryActionsPanel from '../../components/ItineraryActionsPanel.vue'
import GuideIntelligencePanel from '../../components/GuideIntelligencePanel.vue'

import { useTripStore } from '../stores/tripStore'
import { useAuthStore } from '../../app/stores/auth'
import { commuteModeLabel, persistedTransitDisplayCost } from '../../lib/transit'
import {
  searchPlaces,
  type Itinerary,
  type ItineraryActivity,
  type ItineraryTransitLeg,
  type PlaceCandidate,
  type Trip,
  type CreatedItineraryShare,
  type ItineraryVersionDiff,
  type GuideImportInput,
} from '../../lib/api'
import { formatChinaDate, formatChinaTime, formatSlashDate } from '../lib/present'
import {
  readPlanningDecisions,
  decisionReasonLabel,
  decisionSubjectLabel,
} from '../../lib/feasibility'

const props = defineProps<{
  trip: Trip
  itinerary: Itinerary | null
}>()

const tripStore = useTripStore()

const itineraryDays = computed(() => props.itinerary?.days ?? [])

// ③ 决策解释上屏：读取该版本的规划说明（展示安全读取；缺失/空则整区不渲染）。
const planningDecisions = computed(() => {
  if (!props.itinerary) return []
  const read = readPlanningDecisions(props.itinerary.planningDecisions)
  return read.ok ? read.value : []
})

// B1：汇总所有活动的费用来源，供概览预算徽标注记「含估算」。
const allActivities = computed<ItineraryActivity[]>(() =>
  itineraryDays.value.flatMap((day) => day.activities),
)

// ── 地图联动（POI ↔ 活动） ─────────────────────────────────────────
const selectedActivityId = ref<string | null>(null)

// 点击活动行 → 地图高亮该 POI
function selectActivity(activity: ItineraryActivity) {
  selectedActivityId.value = activity.id
}
// 点击地图点 → 列表滚动到对应活动
function onMapSelectActivity(activityId: string) {
  selectedActivityId.value = activityId
  const el = document.querySelector(`[data-activity-ref="${activityId}"]`)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

// ── 天卡折叠（默认只展开第 1 天，第 2~N 天收起以缩短滚动） ──────────
const collapsedDays = ref<number[]>([])
const isDayCollapsed = (dayIndex: number) => collapsedDays.value.includes(dayIndex)

function toggleDay(dayIndex: number) {
  collapsedDays.value = collapsedDays.value.includes(dayIndex)
    ? collapsedDays.value.filter((i) => i !== dayIndex)
    : [...collapsedDays.value, dayIndex]
}

// itinerary 就绪后，把除第 1 天外的天默认设为折叠（首次初始化）。
watch(() => itineraryDays.value.length, (len) => {
  if (len > 1 && collapsedDays.value.length === 0) {
    collapsedDays.value = Array.from({ length: len - 1 }, (_, i) => i + 1)
  }
})

// Day chips：快速定位某一天（展开 + 滚动到该天卡）
async function focusDay(dayIndex: number) {
  collapsedDays.value = collapsedDays.value.filter((i) => i !== dayIndex)
  await nextTick()
  const el = document.querySelector(`[data-day-ref="${dayIndex}"]`)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

// ── 活动攻略折叠 ──────────────────────────────────────────────────
const expandedKeys = ref<string[]>([])
const activityKey = (dayIndex: number, activity: ItineraryActivity) =>
  `${dayIndex}-${activity.startTime}-${activity.title}`
const isExpanded = (dayIndex: number, activity: ItineraryActivity) =>
  expandedKeys.value.includes(activityKey(dayIndex, activity))
const hasGuide = (activity: ItineraryActivity) =>
  Boolean(activity.reason || activity.tips || activity.transportNote || activity.precaution || activity.description)
function toggleGuide(dayIndex: number, activity: ItineraryActivity) {
  const key = activityKey(dayIndex, activity)
  expandedKeys.value = expandedKeys.value.includes(key)
    ? expandedKeys.value.filter((k) => k !== key)
    : [...expandedKeys.value, key]
}

// ── 底部「行程管理 & 更多」手风琴 ───────────────────────────────────
const openSections = ref<string[]>([])
function isSectionOpen(key: string) {
  return openSections.value.includes(key)
}
function toggleSection(key: string) {
  openSections.value = openSections.value.includes(key)
    ? openSections.value.filter((k) => k !== key)
    : [...openSections.value, key]
}

// 加载版本、分享、攻略数据
onMounted(() => {
  if (props.itinerary) {
    void tripStore.loadVersions()
    void tripStore.loadShares()
    void tripStore.loadGuideImports()
  }
})

// 切换旅行时清空地图高亮
watch(() => props.trip.id, () => {
  selectedActivityId.value = null
  collapsedDays.value = []
  expandedKeys.value = []
  openSections.value = []
  if (props.itinerary) {
    void tripStore.loadVersions()
    void tripStore.loadShares()
    void tripStore.loadGuideImports()
  }
})

const currentVersionId = computed(() => props.itinerary?.versionId ?? '')

// ── 活动编辑（Phase 4） ────────────────────────────────────────────
const editingBusy = ref(false)
const confirmDelete = ref<string | null>(null)
const editError = ref<string | null>(null)

function presentEditError(cause: unknown): void {
  editError.value = cause instanceof Error ? cause.message : '行程编辑失败，请稍后重试'
}

async function toggleLock(activity: ItineraryActivity) {
  if (editingBusy.value || !props.itinerary) return
  editingBusy.value = true
  editError.value = null
  try {
    await tripStore.applyEdit({
      baseVersionId: props.itinerary.versionId,
      operation: activity.locked ? 'UNLOCK_ACTIVITY' : 'LOCK_ACTIVITY',
      activityId: activity.id,
    }, crypto.randomUUID())
  } catch (cause) {
    presentEditError(cause)
  } finally {
    editingBusy.value = false
  }
}

async function deleteActivity(activityId: string) {
  if (editingBusy.value || !props.itinerary) return
  editingBusy.value = true
  editError.value = null
  confirmDelete.value = null
  try {
    await tripStore.applyEdit({
      baseVersionId: props.itinerary.versionId,
      operation: 'DELETE_ACTIVITY',
      activityId,
    }, crypto.randomUUID())
  } catch (cause) {
    presentEditError(cause)
  } finally {
    editingBusy.value = false
  }
}

// ── 功能①：行内编辑（改时间 + 改真实地点） ────────────────────────
const auth = useAuthStore()
const editingActivityId = ref<string | null>(null)
// 时间草稿：仅「HH:mm」（日期已固定在当天，无需再选日期）
const editStartTime = ref('')
const editEndTime = ref('')
const editKeyword = ref('')
const placeResults = ref<PlaceCandidate[]>([])
const placeSearching = ref(false)
const pickedPlace = ref<PlaceCandidate | null>(null)

function hhmmOf(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// 时/分下拉（5 分钟步进）
const HOURS = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0'))
const MINUTES = Array.from({ length: 12 }, (_, i) => String(i * 5).padStart(2, '0'))
function setStartTime(h: string, m: string) { editStartTime.value = `${h}:${m}` }
function setEndTime(h: string, m: string) { editEndTime.value = `${h}:${m}` }

const editingActivity = computed<ItineraryActivity | null>(() => {
  if (!editingActivityId.value || !props.itinerary) return null
  for (const day of props.itinerary.days) {
    const found = day.activities.find((a) => a.id === editingActivityId.value)
    if (found) return found
  }
  return null
})

function startEdit(activity: ItineraryActivity) {
  editingActivityId.value = activity.id
  editStartTime.value = hhmmOf(activity.startTime)
  editEndTime.value = hhmmOf(activity.endTime)
  editKeyword.value = ''
  placeResults.value = []
  pickedPlace.value = null
}

function cancelEdit() {
  editingActivityId.value = null
  placeResults.value = []
  pickedPlace.value = null
}

/** 真实地点搜索（复用创建时同款 searchPlaces API）。 */
let placeSearchSeq = 0
async function searchPlace() {
  const keyword = editKeyword.value.trim()
  if (!keyword || !props.trip.destination) return
  const seq = ++placeSearchSeq
  placeSearching.value = true
  try {
    const result = await searchPlaces(auth.accessToken, {
      city: props.trip.destination,
      keyword,
      limit: 6,
    })
    if (seq !== placeSearchSeq) return
    placeResults.value = result.candidates ?? []
  } catch {
    if (seq !== placeSearchSeq) return
    placeResults.value = []
  } finally {
    if (seq === placeSearchSeq) placeSearching.value = false
  }
}

function pickPlace(candidate: PlaceCandidate) {
  pickedPlace.value = candidate
  editKeyword.value = candidate.name
  placeResults.value = []
}

/** 编辑时间草稿为 ISO（日期固定为活动所在天，仅 HH:mm 由用户改）。 */
function timeIso(date: string, hhmm: string): string {
  return new Date(`${date}T${hhmm}:00+08:00`).toISOString()
}

/** 功能①：确定即提交（用户决策：B · 确定即提交）。 */
async function commitEdit() {
  const activity = editingActivity.value
  if (!activity || !props.itinerary || editingBusy.value) return
  editingBusy.value = true
  editError.value = null
  try {
    const day = props.itinerary.days.find((d) =>
      d.activities.some((a) => a.id === activity.id))
    const dayIndex = day ? props.itinerary.days.indexOf(day) : -1
    const order = day ? day.activities.findIndex((a) => a.id === activity.id) : -1
    if (!day) throw new Error('活动不在当前行程中')
    const startIso = timeIso(day.date, editStartTime.value)
    const endIso = timeIso(day.date, editEndTime.value)
    const timeChanged = startIso !== activity.startTime || endIso !== activity.endTime
    const placeChanged = pickedPlace.value !== null

    // 1) 时间变化 → MOVE_ACTIVITY（同天同序，仅改起止时间）
    if (timeChanged) {
      await tripStore.applyEdit({
        baseVersionId: props.itinerary.versionId,
        operation: 'MOVE_ACTIVITY',
        activityId: activity.id,
        targetDate: day.date,
        targetOrder: order >= 0 ? order : 0,
        targetStartTime: startIso,
        targetEndTime: endIso,
      }, crypto.randomUUID())
    }
    // 2) 地点变化 → REPLACE_ACTIVITY（真实 POI，保留时间）
    if (placeChanged && pickedPlace.value) {
      const place = pickedPlace.value
      await tripStore.applyEdit({
        baseVersionId: props.itinerary.versionId,
        operation: 'REPLACE_ACTIVITY',
        activityId: activity.id,
        newTitle: place.name,
        newPoiId: place.providerPoiId,
        newLongitude: place.longitude,
        newLatitude: place.latitude,
        newAddress: place.address,
        newKind: null,
      }, crypto.randomUUID())
    }
    if (!timeChanged && !placeChanged) {
      editError.value = '没有修改：请调整时间或选择新地点'
      return
    }
    editingActivityId.value = null
    placeResults.value = []
    pickedPlace.value = null
  } catch (cause) {
    presentEditError(cause)
  } finally {
    editingBusy.value = false
  }
}

// 版本管理回调
const getDiff = (from: string, to: string): Promise<ItineraryVersionDiff> => tripStore.diffVersions(from, to)
const rollback = (source: string, expected: string, key: string): Promise<void> => tripStore.rollbackVersion(source, expected, key)

// 分享回调
const createShare = (versionId: string, expiresAt?: string): Promise<CreatedItineraryShare> => tripStore.createShare(versionId, expiresAt)
const revokeShare = (shareId: string): Promise<void> => tripStore.revokeShare(shareId)
const downloadExport = (versionId: string, format: 'ics' | 'pdf'): Promise<void> => tripStore.downloadExport(versionId, format)

// 攻略回调
const importGuide = (input: GuideImportInput): Promise<void> => tripStore.importGuide(input)
const setGuideEnabled = (id: string, enabled: boolean): Promise<void> => tripStore.setGuideEnabled(id, enabled)

// ── 功能③：按天聚焦（默认全览，点选某天聚焦，再点取消） ──────────
const selectedDayDate = ref<string | null>(null)

const visibleDays = computed(() => {
  if (!selectedDayDate.value) return itineraryDays.value
  return itineraryDays.value.filter((day) => day.date === selectedDayDate.value)
})

function toggleDayFocus(date: string) {
  selectedDayDate.value = selectedDayDate.value === date ? null : date
}

// ── 功能②：天气条（只取城市情报 CITY_INTELLIGENCE 来源的 WEATHER facts，按日期） ──
const weatherByDate = computed<Map<string, string>>(() => {
  const map = new Map<string, string>()
  for (const guide of tripStore.guideImports) {
    if (guide.sourceType !== 'CITY_INTELLIGENCE') continue
    for (const fact of guide.facts) {
      if (fact.category === 'WEATHER' && fact.effectiveDate) {
        map.set(fact.effectiveDate.slice(0, 10), fact.statement)
      }
    }
  }
  return map
})

const weatherBanner = computed(() => {
  if (selectedDayDate.value) {
    const text = weatherByDate.value.get(selectedDayDate.value)
    return text ? [{ date: selectedDayDate.value, text }] : []
  }
  return itineraryDays.value
    .map((day) => ({ date: day.date, text: weatherByDate.value.get(day.date) ?? '' }))
    .filter((item) => item.text)
})

// ── 图标映射（功能②：天气/交通/活动类型图标化） ────────────────────
function weatherIcon(text: string) {
  if (/晴/.test(text)) return Sun
  if (/雪/.test(text)) return CloudSnow
  if (/雷/.test(text)) return CloudLightning
  if (/雨/.test(text)) return CloudRain
  if (/多云|阴/.test(text)) return CloudSun
  return Cloudy
}

function transitIcon(mode: string) {
  if (mode === 'WALKING') return Footprints
  if (mode === 'TRANSIT') return Bus
  if (mode === 'TAXI' || mode === 'DRIVING') return Car
  if (mode === 'AUTO') return Wand2
  return RouteIcon
}

/** 景点 5 类 + 吃饭 4 类 + 住宿/到达/离开（按 kind 与名称/类别关键词）。 */
function activityIcon(activity: ItineraryActivity) {
  if (activity.kind === 'ACCOMMODATION') return Bed
  if (activity.kind === 'ARRIVAL') return Plane
  if (activity.kind === 'DEPARTURE') return Home
  const text = `${activity.title}${activity.typeName ?? ''}`
  const isMeal = activity.kind === 'MEAL'
    || /餐|菜|食|饭|面|粉|火锅|烧烤|烤|咖啡|茶|甜品|自助|小吃|汉堡/.test(text)
  if (isMeal) {
    if (/快餐|汉堡|面|粉|小吃/.test(text)) return Sandwich
    if (/火锅|烧烤|烤|串|烤肉/.test(text)) return Flame
    if (/咖啡|茶|饮品|甜品/.test(text)) return Coffee
    return Utensils
  }
  if (/山|峰|峡|谷|森林|草原|自然/.test(text)) return Mountain
  if (/公园|广场|园林|湖|海|江|河|水街|滩|泉/.test(text)) return Trees
  if (/博物馆|祠|寺|宫|庙|古迹|遗址|展览|塔/.test(text)) return Landmark
  if (/乐园|游乐|主题/.test(text)) return FerrisWheel
  if (/商场|购物|步行街|街区|市场/.test(text)) return ShoppingBag
  return MapPin
}

// ── B1 费用来源徽标：真实价格 vs 估算 ─────────────────────────────
/** 估算类来源：RULE_ESTIMATE / CATEGORY_ESTIMATE / CITY_ESTIMATE / DEMO / UNKNOWN。 */
function isEstimatedCost(activity: ItineraryActivity) {
  const source = activity.costSource ?? 'UNKNOWN'
  return source !== 'PROVIDER'
}

/** 真实价格（PROVIDER）——展示「已核验」徽标。 */
function isVerifiedCost(activity: ItineraryActivity) {
  return (activity.costSource ?? 'UNKNOWN') === 'PROVIDER'
}

function costSourceLabel(source: ItineraryActivity['costSource']) {
  switch (source) {
    case 'PROVIDER':
      return '费用来自真实提供商报价'
    case 'RULE_ESTIMATE':
      return '费用按规则估算'
    case 'CATEGORY_ESTIMATE':
      return '费用按品类估算'
    case 'CITY_ESTIMATE':
      return '费用按城市整体估算'
    case 'DEMO':
      return '演示数据，费用为演示估算'
    default:
      return '费用来源未知'
  }
}

// ── 功能①：交通行（相邻活动之间的 transit leg） ───────────────────
const editingLegId = ref<string | null>(null)
const legModeDraft = ref<'WALKING' | 'TRANSIT' | 'DRIVING' | 'TAXI' | null>(null)

/** 每个活动“到达它”的 transit leg（from 上一个活动 → to 当前活动）。 */
function arrivingLeg(day: { transitLegs: ItineraryTransitLeg[] }, activityId: string): ItineraryTransitLeg | null {
  return day.transitLegs.find((leg) => leg.toActivityId === activityId) ?? null
}

function formatDuration(seconds: number): string {
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} 分钟`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m > 0 ? `${h} 小时 ${m} 分` : `${h} 小时`
}

function openLegPicker(legId: string) {
  editingLegId.value = editingLegId.value === legId ? null : legId
}

async function changeLegMode(legId: string, mode: 'AUTO' | 'WALKING' | 'TRANSIT' | 'TAXI') {
  if (editingBusy.value || !props.itinerary) return
  editingBusy.value = true
  editError.value = null
  try {
    await tripStore.applyEdit({
      baseVersionId: props.itinerary.versionId,
      operation: 'UPDATE_TRANSIT_LEG',
      transitLegId: legId,
      transitMode: mode,
    }, crypto.randomUUID())
    editingLegId.value = null
    legModeDraft.value = null
  } catch (cause) {
    presentEditError(cause)
  } finally {
    editingBusy.value = false
  }
}
</script>

<template>
  <article class="mx-auto flex w-full max-w-3xl flex-col px-6 py-5" aria-label="旅行方案">
    <!-- ① 摘要卡 -->
    <TripOverview :trip="trip" :activities="allActivities" />

    <div class="mt-5 border-t border-tp-div" role="separator" />

    <!-- ② 完成成功条 -->
    <div
      class="mt-4 flex items-center gap-2.5 rounded-lg border border-tp-ok/25 bg-tp-ok/10 px-3.5 py-2.5"
      role="status"
      data-testid="agent-message-done"
    >
      <span class="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-tp-ok text-[11px] font-semibold text-white" aria-hidden="true">
        <Check :size="10" />
      </span>
      <p class="m-0 text-[13px] leading-5 text-tp-body">
        <span class="font-medium text-tp-ink">旅行方案已经完成</span>
        ，共 {{ itineraryDays.length }} 天的行程，可直接按天查看或在下方继续调整。
      </p>
    </div>

    <!-- ③ TripPilot 的规划说明（决策解释只读区，来自规划引擎 evaluation.decisions） -->
    <section
      v-if="planningDecisions.length"
      class="mt-4 rounded-lg border border-tp-line bg-tp-panel px-3.5 py-2.5"
      aria-label="TripPilot 的规划说明"
      data-testid="plan-decision-explanation"
    >
      <h3 class="m-0 flex items-center gap-1.5 text-[13px] font-medium leading-5 text-tp-ink">
        <Wand2 :size="13" class="text-tp-mute" aria-hidden="true" />TripPilot 的规划说明
      </h3>
      <ul class="m-0 mt-1.5 space-y-2.5">
        <li
          v-for="(decision, index) in planningDecisions"
          :key="`${decision.subjectType}-${decision.subjectId ?? ''}-${decision.summary}-${index}`"
          class="rounded-md bg-white px-2.5 py-2"
          :data-testid="`plan-decision-${index}`"
        >
          <p class="m-0 flex flex-wrap items-start gap-1.5 text-xs leading-5 text-tp-body">
            <span class="mt-0.5 shrink-0 rounded-full bg-tp-panel px-1.5 py-0.5 text-[10px] leading-3 text-tp-mute">
              {{ decisionSubjectLabel(decision.subjectType, decision.dayIndex) }}
            </span>
            <span class="min-w-0 flex-1">{{ decision.summary }}</span>
          </p>
          <div v-if="decision.reasonCodes.length" class="mt-1 flex flex-wrap items-center gap-1">
            <span
              v-for="code in decision.reasonCodes"
              :key="code"
              class="rounded-full border border-tp-line px-1.5 py-0.5 text-[10px] leading-3 text-tp-sub"
              :title="`决策理由：${code}`"
              :data-testid="`plan-decision-reason-${code}`"
            >{{ decisionReasonLabel(code) }}</span>
          </div>
          <ul v-if="decision.reasons.length" class="m-0 mt-1 list-disc pl-4">
            <li
              v-for="(reason, reasonIndex) in decision.reasons"
              :key="reasonIndex"
              class="text-xs leading-5 text-tp-mute"
            >{{ reason }}</li>
          </ul>
          <div v-if="decision.evidence && decision.evidence.length" class="mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
            <span
              v-for="ev in decision.evidence"
              :key="ev.key"
              class="text-[11px] leading-4 text-tp-faint"
              :title="`${ev.label}：${ev.value}`"
            >{{ ev.value }}</span>
          </div>
        </li>
      </ul>
    </section>

    <!-- 编辑/删除失败提示（不再静默吞错） -->
    <div
      v-if="editError"
      class="mt-3 flex items-center gap-2 rounded-lg border border-tp-warn/30 bg-tp-warn/10 px-3.5 py-2.5"
      role="alert"
      data-testid="itinerary-edit-error"
    >
      <p class="m-0 text-xs leading-5 text-tp-warn">{{ editError }}</p>
    </div>

    <!-- ② 天气条（功能②：来自城市情报 WEATHER，地图上方） -->
    <div
      v-if="weatherBanner.length"
      class="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-tp-line bg-tp-panel px-3.5 py-2"
      data-testid="weather-banner"
    >
      <span v-if="selectedDayDate" class="flex items-center gap-1.5 text-[11px] leading-4 text-tp-mute">
        <CloudSun :size="13" class="text-tp-faint" aria-hidden="true" />{{ formatSlashDate(selectedDayDate) }}
      </span>
      <template v-else>
        <span class="flex items-center gap-1.5 text-[11px] leading-4 text-tp-mute">
          <CloudSun :size="13" class="text-tp-faint" aria-hidden="true" />行程天气
        </span>
      </template>
      <span
        v-for="item in weatherBanner"
        :key="item.date"
        class="flex items-center gap-1.5 text-xs leading-5 text-tp-body"
      >
        <span v-if="!selectedDayDate" class="flex items-center gap-1 text-[11px] leading-4 text-tp-sub">
          {{ formatSlashDate(item.date) }}
          <component :is="weatherIcon(item.text)" :size="13" class="text-tp-mute" aria-hidden="true" />
        </span>
        <span v-else class="text-tp-sub">
          <component :is="weatherIcon(item.text)" :size="13" class="mr-1 align-[-2px] text-tp-mute" aria-hidden="true" />
        </span>
        <span class="rounded-full bg-white px-2 py-0.5 text-[11px] leading-4 text-tp-body" :title="item.text">
          {{ item.text }}
        </span>
      </span>
      <span v-if="!weatherByDate.size" class="text-[11px] leading-4 text-tp-faint">
        暂无天气数据，可在「攻略情报」同步城市情报
      </span>
    </div>

    <!-- ③ 旅行路线：Day chips（具体日期，含年份）+ 地图 -->
    <section class="mt-5" aria-label="旅行路线" data-testid="trip-route-section">
      <div class="mb-2 flex items-center justify-between gap-3">
        <h2 class="m-0 flex items-center gap-1.5 text-[13px] font-medium leading-5 text-tp-ink">
          <MapIcon :size="13" class="text-tp-mute" aria-hidden="true" />旅行路线
        </h2>
        <span class="text-[11px] leading-4 text-tp-mute">点选某天聚焦，再点取消</span>
      </div>

      <!-- Day chips：具体日期（功能④含年份），选中高亮（功能③） -->
      <div class="mb-2 flex flex-wrap items-center gap-1.5" role="group" aria-label="按天定位">
        <button
          v-for="day in itineraryDays"
          :key="day.date"
          type="button"
          class="flex h-7 items-center gap-1 rounded-full border px-3 text-xs transition-colors"
          :class="selectedDayDate === day.date
            ? 'border-tp-ink bg-tp-ink text-white'
            : 'border-tp-line bg-white text-tp-sub hover:bg-tp-hover hover:text-tp-ink'"
          :aria-label="`聚焦 ${formatSlashDate(day.date)}`"
          :aria-pressed="selectedDayDate === day.date"
          :data-testid="`plan-day-chip-${day.date}`"
          @click="toggleDayFocus(day.date)"
        >
          <CalendarDays :size="12" class="opacity-60" aria-hidden="true" />
          {{ formatSlashDate(day.date) }}
        </button>
      </div>

      <TripRouteMap
        :trip="trip"
        :itinerary="itinerary"
        :selected-activity-id="selectedActivityId"
        :selected-date="selectedDayDate"
        @select-activity="onMapSelectActivity"
      />
    </section>

    <template v-if="itineraryDays.length > 0">
      <div class="mt-5 border-t border-tp-div" role="separator" />

      <!-- ④ 每日行程：天卡 -->
      <section class="mt-4" aria-label="行程">
        <h2 class="m-0 text-[13px] font-medium leading-5 text-tp-ink">每日行程</h2>

        <div
          v-for="(day, dayIndex) in visibleDays"
          :key="day.date"
          :data-day-ref="dayIndex"
          class="mt-3 rounded-xl border border-tp-line bg-white"
          :data-testid="`plan-day-${day.date}`"
        >
          <!-- 天卡头部：可折叠 -->
          <button
            type="button"
            class="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
            :aria-expanded="!isDayCollapsed(dayIndex)"
            :data-testid="`plan-day-toggle-${day.date}`"
            @click="toggleDay(dayIndex)"
          >
            <span class="flex items-center gap-2.5">
              <span class="flex h-6 w-6 items-center justify-center rounded-md bg-tp-active text-xs font-semibold text-tp-ink">
                {{ dayIndex + 1 }}
              </span>
              <span class="text-[13px] font-medium leading-5 text-tp-ink">第 {{ dayIndex + 1 }} 天</span>
              <span class="rounded-full bg-tp-panel px-2 py-0.5 text-[11px] leading-4 text-tp-mute">
                {{ formatSlashDate(day.date) }}
              </span>
              <span class="hidden text-[11px] leading-4 text-tp-faint sm:inline">{{ day.activities.length }} 个安排</span>
            </span>
            <span class="flex items-center gap-1 text-tp-mute">
              <MapPin :size="12" class="hidden sm:block" aria-hidden="true" />
              <component :is="isDayCollapsed(dayIndex) ? ChevronRight : ChevronDown" :size="14" aria-hidden="true" />
            </span>
          </button>

          <!-- 天卡内容：活动时间线 -->
          <div v-if="!isDayCollapsed(dayIndex)" class="border-t border-tp-div px-4 pb-3 pt-1">
            <div class="divide-y divide-tp-div" data-testid="plan-day-activities">
              <!-- 功能①：相邻活动之间的交通行 -->
              <template
                v-for="(activity, order) in day.activities"
                :key="activityKey(dayIndex, activity)"
              >
                <div
                  :data-activity-ref="activity.id"
                  class="flex gap-3 py-3"
                  :data-testid="`plan-activity-${activity.title}`"
                  @click="selectActivity(activity)"
                >
                <!-- 时间列：HH:mm（修复旧版原始 ISO 直出） -->
                <span class="w-12 shrink-0 pt-px font-mono text-xs leading-5 text-tp-mute">
                  {{ formatChinaTime(activity.startTime) }}
                </span>

                <!-- 内容列 -->
                <div class="min-w-0 flex-1">
                  <div class="flex items-start justify-between gap-2">
                    <div class="min-w-0 flex-1">
                      <p class="m-0 flex items-center gap-1.5 text-[13px] font-medium leading-5 text-tp-ink">
                        <component
                          :is="activityIcon(activity)"
                          :size="13"
                          class="shrink-0 text-tp-mute"
                          aria-hidden="true"
                          :data-testid="`activity-icon-${activity.title}`"
                        />
                        <span class="min-w-0 truncate">{{ activity.title }}</span>
                        <span v-if="activity.typeName" class="ml-1 text-[11px] font-normal text-tp-mute">
                          {{ activity.typeName }}
                        </span>
                        <span
                          v-if="isEstimatedCost(activity)"
                          class="ml-1.5 inline-flex items-center rounded-full bg-tp-ok/10 px-1.5 py-0.5 text-[10px] font-medium leading-3 text-tp-ok"
                          :title="costSourceLabel(activity.costSource)"
                          data-testid="activity-estimate-badge"
                        >估算</span>
                        <span
                          v-else-if="isVerifiedCost(activity)"
                          class="ml-1.5 inline-flex items-center rounded-full bg-tp-panel px-1.5 py-0.5 text-[10px] font-medium leading-3 text-tp-mute"
                          :title="costSourceLabel(activity.costSource)"
                          data-testid="activity-verified-badge"
                        >已核验</span>
                        <span v-if="activity.locked" class="ml-1.5 inline-flex items-center text-tp-mute" title="已锁定">
                          <Lock :size="10" aria-hidden="true" />
                        </span>
                      </p>
                    </div>
                    <!-- 编辑按钮 -->
                    <div class="flex shrink-0 items-center gap-1">
                      <button
                        type="button"
                        :disabled="editingBusy"
                        class="flex h-6 w-6 items-center justify-center rounded text-tp-faint transition-colors hover:bg-tp-hover hover:text-tp-ink disabled:opacity-30"
                        :title="'编辑活动（时间 / 地点）'"
                        :data-testid="`activity-edit-${activity.title}`"
                        @click.stop="startEdit(activity)"
                      >
                        <Pencil :size="12" aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        :disabled="editingBusy"
                        class="flex h-6 w-6 items-center justify-center rounded text-tp-faint transition-colors hover:bg-tp-hover hover:text-tp-ink disabled:opacity-30"
                        :title="activity.locked ? '解锁' : '锁定'"
                        :data-testid="`activity-${activity.locked ? 'unlock' : 'lock'}-${activity.title}`"
                        @click.stop="toggleLock(activity)"
                      >
                        <component :is="activity.locked ? Unlock : Lock" :size="12" aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        :disabled="editingBusy"
                        class="flex h-6 w-6 items-center justify-center rounded text-tp-faint transition-colors hover:bg-tp-warn/10 hover:text-tp-warn disabled:opacity-30"
                        :title="'删除活动'"
                        :data-testid="`activity-delete-${activity.title}`"
                        @click.stop="confirmDelete = activity.id"
                      >
                        <Trash2 :size="12" aria-hidden="true" />
                      </button>
                    </div>
                  </div>

                  <!-- 功能①：行内编辑（时间 + 真实地点搜索） -->
                  <div
                    v-if="editingActivityId === activity.id"
                    class="mt-2 rounded-lg border border-tp-line bg-tp-panel px-3 py-2.5"
                    data-testid="activity-inline-edit"
                    @click.stop
                  >
                    <div class="flex flex-wrap items-end gap-3">
                      <!-- 开始/结束：仅时/分下拉（日期固定在当天） -->
                      <label class="flex flex-col gap-1 text-[11px] leading-4 text-tp-mute">
                        开始时间
                        <span class="flex items-center gap-1">
                          <select
                            :value="editStartTime.slice(0, 2)"
                            class="h-7 rounded-md border border-tp-line bg-white px-1 text-xs text-tp-ink"
                            data-testid="activity-edit-start-h"
                            @change="setStartTime(($event.target as HTMLSelectElement).value, editStartTime.slice(3, 5))"
                          >
                            <option v-for="h in HOURS" :key="h" :value="h">{{ h }}</option>
                          </select>
                          <span class="text-tp-faint">:</span>
                          <select
                            :value="editStartTime.slice(3, 5)"
                            class="h-7 rounded-md border border-tp-line bg-white px-1 text-xs text-tp-ink"
                            data-testid="activity-edit-start-m"
                            @change="setStartTime(editStartTime.slice(0, 2), ($event.target as HTMLSelectElement).value)"
                          >
                            <option v-for="m in MINUTES" :key="m" :value="m">{{ m }}</option>
                          </select>
                        </span>
                      </label>
                      <label class="flex flex-col gap-1 text-[11px] leading-4 text-tp-mute">
                        结束时间
                        <span class="flex items-center gap-1">
                          <select
                            :value="editEndTime.slice(0, 2)"
                            class="h-7 rounded-md border border-tp-line bg-white px-1 text-xs text-tp-ink"
                            data-testid="activity-edit-end-h"
                            @change="setEndTime(($event.target as HTMLSelectElement).value, editEndTime.slice(3, 5))"
                          >
                            <option v-for="h in HOURS" :key="h" :value="h">{{ h }}</option>
                          </select>
                          <span class="text-tp-faint">:</span>
                          <select
                            :value="editEndTime.slice(3, 5)"
                            class="h-7 rounded-md border border-tp-line bg-white px-1 text-xs text-tp-ink"
                            data-testid="activity-edit-end-m"
                            @change="setEndTime(editEndTime.slice(0, 2), ($event.target as HTMLSelectElement).value)"
                          >
                            <option v-for="m in MINUTES" :key="m" :value="m">{{ m }}</option>
                          </select>
                        </span>
                      </label>
                      <div class="flex min-w-[220px] flex-1 flex-col gap-1">
                        <label class="text-[11px] leading-4 text-tp-mute">
                          新地点（搜索真实地点）
                        </label>
                        <div class="flex gap-1">
                          <div class="relative min-w-0 flex-1">
                            <input
                              v-model="editKeyword"
                              type="text"
                              placeholder="输入地点名称搜索"
                              class="h-7 w-full rounded-md border border-tp-line bg-white px-2 pr-7 text-xs text-tp-ink"
                              data-testid="activity-edit-place"
                              @keydown.enter.prevent="searchPlace"
                              @input="pickedPlace = null; if (editKeyword && !placeSearching) searchPlace()"
                            />
                            <span v-if="placeSearching" class="absolute right-2 top-1/2 -translate-y-1/2 text-tp-mute" aria-hidden="true">
                              <span class="inline-block h-3 w-3 animate-spin rounded-full border border-tp-line border-t-tp-ink" />
                            </span>
                          </div>
                          <button
                            type="button"
                            :disabled="!editKeyword.trim() || placeSearching"
                            class="flex h-7 items-center gap-1 rounded-md border border-tp-line bg-white px-2 text-[11px] text-tp-sub hover:bg-tp-hover disabled:opacity-40"
                            data-testid="activity-edit-search"
                            @click="searchPlace"
                          >
                            <Search :size="12" aria-hidden="true" />搜索
                          </button>
                        </div>
                        <ul v-if="placeResults.length" class="mt-1 space-y-0.5" data-testid="activity-edit-results">
                          <li
                            v-for="candidate in placeResults"
                            :key="candidate.providerPoiId + candidate.name"
                          >
                            <button
                              type="button"
                              class="flex w-full items-start justify-between gap-2 rounded-md px-2 py-1 text-left text-xs text-tp-body hover:bg-tp-hover"
                              :data-testid="`activity-edit-pick-${candidate.name}`"
                              @click="pickPlace(candidate)"
                            >
                              <span class="min-w-0 truncate">{{ candidate.name }}</span>
                              <span class="shrink-0 text-[11px] text-tp-mute">{{ candidate.address }}</span>
                            </button>
                          </li>
                        </ul>
                        <p v-if="pickedPlace" class="m-0 flex items-center gap-1 text-[11px] leading-4 text-tp-ok" data-testid="activity-edit-picked">
                          已选：{{ pickedPlace.name }}
                        </p>
                      </div>
                    </div>
                    <div class="mt-2 flex items-center gap-2">
                      <button
                        type="button"
                        :disabled="editingBusy"
                        class="flex h-7 items-center rounded-md bg-tp-ink px-3 text-xs font-medium text-white hover:opacity-90 disabled:opacity-40"
                        data-testid="activity-edit-commit"
                        @click="commitEdit"
                      >确定</button>
                      <button
                        type="button"
                        :disabled="editingBusy"
                        class="flex h-7 items-center gap-1 rounded-md border border-tp-line bg-white px-2 text-xs text-tp-sub hover:bg-tp-hover disabled:opacity-40"
                        data-testid="activity-edit-cancel"
                        @click="cancelEdit"
                      >
                        <X :size="12" aria-hidden="true" />取消
                      </button>
                    </div>
                  </div>

                  <p v-if="activity.description" class="m-0 mt-0.5 text-xs leading-5 text-tp-body">
                    {{ activity.description }}
                  </p>

                  <!-- 攻略折叠 -->
                  <button
                    v-if="hasGuide(activity)"
                    type="button"
                    class="mt-1.5 flex h-6 items-center gap-1 rounded px-1 text-[11px] text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
                    :aria-expanded="isExpanded(dayIndex, activity)"
                    :data-testid="`activity-guide-toggle-${activity.title}`"
                    @click.stop="toggleGuide(dayIndex, activity)"
                  >
                    <component
                      :is="isExpanded(dayIndex, activity) ? ChevronDown : ChevronRight"
                      :size="12"
                      aria-hidden="true"
                    />
                    {{ isExpanded(dayIndex, activity) ? '收起攻略' : '查看攻略' }}
                  </button>

                  <dl v-if="isExpanded(dayIndex, activity)" class="m-0 mt-1 space-y-0.5">
                    <div v-if="activity.reason" class="flex gap-2">
                      <dt class="m-0 shrink-0 text-xs leading-5 text-tp-faint">推荐理由</dt>
                      <dd class="m-0 text-xs leading-5 text-tp-body">{{ activity.reason }}</dd>
                    </div>
                    <div v-if="activity.tips" class="flex gap-2">
                      <dt class="m-0 shrink-0 text-xs leading-5 text-tp-faint">游览建议</dt>
                      <dd class="m-0 text-xs leading-5 text-tp-body">{{ activity.tips }}</dd>
                    </div>
                    <div v-if="activity.transportNote" class="flex gap-2">
                      <dt class="m-0 shrink-0 text-xs leading-5 text-tp-faint">交通</dt>
                      <dd class="m-0 text-xs leading-5 text-tp-body">{{ activity.transportNote }}</dd>
                    </div>
                    <div v-if="activity.precaution" class="flex gap-2">
                      <dt class="m-0 shrink-0 text-xs leading-5 text-tp-faint">注意事项</dt>
                      <dd class="m-0 text-xs leading-5 text-tp-warn">{{ activity.precaution }}</dd>
                    </div>
                  </dl>
                </div>
                <!-- 删除确认 -->
                <div v-if="confirmDelete === activity.id" class="flex items-center gap-2 pt-1">
                  <span class="text-[11px] leading-4 text-tp-warn">确定删除此活动？</span>
                  <button
                    type="button"
                    :disabled="editingBusy"
                    class="flex h-6 items-center rounded bg-tp-warn px-2 text-[11px] font-medium text-white disabled:opacity-50"
                    @click.stop="deleteActivity(activity.id)"
                  >删除</button>
                  <button
                    type="button"
                    :disabled="editingBusy"
                    class="flex h-6 items-center rounded bg-tp-hover px-2 text-[11px] text-tp-sub disabled:opacity-50"
                    @click.stop="confirmDelete = null"
                  >取消</button>
                </div>
              </div>

              <!-- 功能①：到达该活动的交通行（含模式/时长/费用 + 手选） -->
              <template v-if="!isDayCollapsed(dayIndex)">
                <div
                  v-if="arrivingLeg(day, activity.id)"
                  class="flex items-center gap-2 px-1 py-1.5"
                  :data-testid="`plan-transit-${activity.title}`"
                >
                  <component
                    :is="transitIcon(arrivingLeg(day, activity.id)!.mode)"
                    :size="13"
                    class="shrink-0 text-tp-mute"
                    aria-hidden="true"
                  />
                  <button
                    type="button"
                    class="flex min-w-0 items-center gap-1.5 rounded-md px-1.5 py-0.5 text-[11px] leading-4 text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
                    :title="'切换交通方式'"
                    :data-testid="`plan-transit-toggle-${activity.title}`"
                    @click="openLegPicker(arrivingLeg(day, activity.id)!.id)"
                  >
                    <span class="font-medium text-tp-ink">{{ commuteModeLabel(arrivingLeg(day, activity.id)!.mode) }}</span>
                    <span class="text-tp-mute">· {{ formatDuration(arrivingLeg(day, activity.id)!.durationSeconds) }}</span>
                    <span v-if="persistedTransitDisplayCost(arrivingLeg(day, activity.id)!) != null" class="text-tp-mute">
                      · ¥{{ persistedTransitDisplayCost(arrivingLeg(day, activity.id)!) }}
                    </span>
                    <ChevronDown :size="11" class="text-tp-faint" aria-hidden="true" />
                  </button>
                </div>

                <!-- 交通切换弹层（手选，成功后时间/金钱由后端返回自动刷新） -->
                <div
                  v-if="editingLegId === arrivingLeg(day, activity.id)?.id && arrivingLeg(day, activity.id)"
                  class="mb-2 ml-6 flex flex-wrap items-center gap-1.5 rounded-lg border border-tp-line bg-tp-panel px-2.5 py-2"
                  data-testid="plan-transit-picker"
                >
                  <span class="text-[11px] leading-4 text-tp-mute">切换方式：</span>
                  <button
                    v-for="mode in (['AUTO', 'WALKING', 'TRANSIT', 'TAXI'] as const)"
                    :key="mode"
                    type="button"
                    :disabled="editingBusy"
                    class="flex h-6 items-center rounded-full border px-2.5 text-[11px] transition-colors disabled:opacity-40"
                    :class="arrivingLeg(day, activity.id)!.mode === mode
                      ? 'border-tp-ink bg-tp-ink text-white'
                      : 'border-tp-line bg-white text-tp-sub hover:bg-tp-hover'"
                    :data-testid="`plan-transit-mode-${mode}`"
                    @click="changeLegMode(arrivingLeg(day, activity.id)!.id, mode)"
                  >{{ commuteModeLabel(mode) }}</button>
                </div>
              </template>
              </template>
            </div>
          </div>
        </div>
      </section>
    </template>

    <!-- ⑤ 行程管理 & 更多：手风琴分组 -->
    <template v-if="itinerary">
      <div class="mt-5 border-t border-tp-div" role="separator" />

      <section class="mt-4" aria-label="行程管理与更多">
        <h2 class="m-0 text-[13px] font-medium leading-5 text-tp-ink">行程管理与更多</h2>

        <!-- 版本 -->
        <div class="mt-3 rounded-xl border border-tp-line bg-white">
          <button
            type="button"
            class="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
            :aria-expanded="isSectionOpen('version')"
            data-testid="more-toggle-version"
            @click="toggleSection('version')"
          >
            <span class="flex items-center gap-2 text-[13px] font-medium leading-5 text-tp-ink">
              <History :size="14" class="text-tp-mute" aria-hidden="true" />行程版本
            </span>
            <component :is="isSectionOpen('version') ? ChevronDown : ChevronRight" :size="14" class="text-tp-mute" aria-hidden="true" />
          </button>
          <div v-if="isSectionOpen('version')" class="border-t border-tp-div px-4 py-4">
            <ItineraryVersionPanel
              :versions="tripStore.versions"
              :current-version-id="currentVersionId"
              :busy="false"
              :error="null"
              :get-diff="getDiff"
              :rollback="rollback"
            />
          </div>
        </div>

        <!-- 分享与导出 -->
        <div class="mt-3 rounded-xl border border-tp-line bg-white">
          <button
            type="button"
            class="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
            :aria-expanded="isSectionOpen('share')"
            data-testid="more-toggle-share"
            @click="toggleSection('share')"
          >
            <span class="flex items-center gap-2 text-[13px] font-medium leading-5 text-tp-ink">
              <Share2 :size="14" class="text-tp-mute" aria-hidden="true" />分享与导出
            </span>
            <component :is="isSectionOpen('share') ? ChevronDown : ChevronRight" :size="14" class="text-tp-mute" aria-hidden="true" />
          </button>
          <div v-if="isSectionOpen('share')" class="border-t border-tp-div px-4 py-4">
            <ItineraryActionsPanel
              :version-id="currentVersionId"
              :shares="tripStore.shares"
              :create-share="createShare"
              :revoke-share="revokeShare"
              :download="downloadExport"
            />
          </div>
        </div>

        <!-- 攻略情报 -->
        <div class="mt-3 rounded-xl border border-tp-line bg-white">
          <button
            type="button"
            class="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
            :aria-expanded="isSectionOpen('guide')"
            data-testid="more-toggle-guide"
            @click="toggleSection('guide')"
          >
            <span class="flex items-center gap-2 text-[13px] font-medium leading-5 text-tp-ink">
              <BookOpen :size="14" class="text-tp-mute" aria-hidden="true" />攻略情报
            </span>
            <component :is="isSectionOpen('guide') ? ChevronDown : ChevronRight" :size="14" class="text-tp-mute" aria-hidden="true" />
          </button>
          <div v-if="isSectionOpen('guide')" class="border-t border-tp-div px-4 py-4">
            <GuideIntelligencePanel
              :guide-imports="tripStore.guideImports"
              :destination="trip.destination"
              :start-date="trip.startDate"
              :end-date="trip.endDate"
              :itinerary="itinerary"
              :busy="tripStore.guideImportBusy"
              :error="tripStore.guideImportError"
              :import-guide="importGuide"
              :set-guide-enabled="setGuideEnabled"
            />
          </div>
        </div>
      </section>
    </template>
  </article>
</template>