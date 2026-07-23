<script setup lang="ts">
import {
  ArrowLeft,
  BookOpen,
  CalendarDays,
  CircleGauge,
  Clock3,
  Compass,
  Coins,
  ExternalLink,
  LoaderCircle,
  LogOut,
  MapPin,
  Pencil,
  Play,
  RefreshCw,
  Route,
  Users,
  Wallet,
  X,
} from 'lucide-vue-next'
import { computed, nextTick, reactive, ref, watch } from 'vue'

import {
  ApiError,
  type GuideImport,
  type Itinerary,
  type Trip,
  type UpdateTripConstraintsInput,
  type User,
} from '../lib/api'
import { useModalFocus } from '../lib/modal'
import GuideIntelligencePanel from './GuideIntelligencePanel.vue'
import TripMap from './TripMap.vue'

const props = withDefaults(defineProps<{
  user: User
  trip: Trip | null
  busy: boolean
  error: string | null
  itinerary: Itinerary | null
  itineraryBusy: boolean
  itineraryError: string | null
  planningState: 'idle' | 'queued' | 'succeeded' | 'failed' | 'cancelled'
  planningError: string | null
  guideImports?: GuideImport[]
  guideBusy?: boolean
  guideError?: string | null
  importGuide?: (sourceUrl: string) => Promise<void>
  setGuideEnabled?: (guideImportId: string, enabled: boolean) => Promise<void>
  startPlanning: () => Promise<void>
  cancelPlanning: () => Promise<void>
  updateConstraints: (input: UpdateTripConstraintsInput) => Promise<void>
  reloadTrip: () => Promise<boolean>
}>(), {
  guideImports: () => [],
  guideBusy: false,
  guideError: null,
  importGuide: async () => {},
  setGuideEnabled: async () => {},
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

watch(() => props.itinerary, (nextItinerary) => {
  const firstActivity = nextItinerary?.days.flatMap((day) => day.activities).find((activity) => activity.coordinates)
  if (!firstActivity || !nextItinerary?.days.flatMap((day) => day.activities).some((activity) => activity.id === selectedActivityId.value)) {
    selectedActivityId.value = firstActivity?.id ?? null
  }
}, { immediate: true })
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand-lockup">
        <span class="brand-icon"><Compass :size="20" aria-hidden="true" /></span>
        <div>
          <strong>TripPilot</strong>
          <span>旅行规划工作台</span>
        </div>
      </div>
      <div class="user-actions">
        <div class="user-copy">
          <strong>{{ user.displayName }}</strong>
          <span>{{ user.email }}</span>
        </div>
        <button class="icon-button" type="button" title="退出登录" aria-label="退出登录" @click="emit('logout')">
          <LogOut :size="18" aria-hidden="true" />
        </button>
      </div>
    </header>

    <main class="workspace">
      <button class="back-button" type="button" @click="emit('back')">
        <ArrowLeft :size="17" aria-hidden="true" />
        返回旅行列表
      </button>

      <section v-if="busy" class="loading-state" aria-label="正在加载旅行详情">
        <span></span><span></span><span></span>
      </section>

      <section v-else-if="error" class="error-state">
        <p role="alert">{{ error }}</p>
        <button type="button" @click="emit('back')">返回旅行列表</button>
      </section>

      <template v-else-if="trip">
        <header class="trip-heading">
          <div>
            <p class="eyebrow">TRIP WORKSPACE</p>
            <h1>{{ trip.title }}</h1>
            <div class="trip-meta">
              <span><MapPin :size="16" aria-hidden="true" />{{ trip.destination }}</span>
              <span><CalendarDays :size="16" aria-hidden="true" />{{ formatDate(trip.startDate) }} — {{ formatDate(trip.endDate) }}</span>
            </div>
          </div>
          <div class="state-copy">
            <span class="status-badge">{{ statusLabel(trip.status) }}</span>
            <span>版本 {{ trip.version }}</span>
          </div>
        </header>

        <section class="itinerary-workspace" aria-labelledby="itinerary-title">
          <header class="itinerary-heading">
            <div>
              <p class="eyebrow">ITINERARY</p>
              <h2 id="itinerary-title">行程时间轴</h2>
            </div>
            <div class="planning-actions">
              <button
                class="planning-button"
                type="button"
                :disabled="planningState === 'queued'"
                @click="startPlanning"
              >
                <LoaderCircle v-if="planningState === 'queued'" class="spinning" :size="16" aria-hidden="true" />
                <RefreshCw v-else-if="itinerary" :size="16" aria-hidden="true" />
                <Play v-else :size="16" aria-hidden="true" />
                {{ planningState === 'queued' ? '规划中' : itinerary ? '重新规划' : '开始规划' }}
              </button>
              <button
                v-if="planningState === 'queued'"
                class="cancel-planning-button"
                type="button"
                @click="cancelPlanning"
              >
                <X :size="16" aria-hidden="true" />取消规划
              </button>
            </div>
          </header>

          <p v-if="planningState === 'queued'" class="planning-status" role="status">
            <LoaderCircle class="spinning" :size="16" aria-hidden="true" />
            正在生成行程
          </p>
          <p v-else-if="planningState === 'cancelled'" class="planning-status" role="status">规划已取消</p>
          <p v-else-if="planningError" class="planning-error" role="alert">{{ planningError }}</p>

          <div v-if="itineraryBusy" class="itinerary-loading" aria-label="正在加载当前行程">
            <span></span><span></span><span></span>
          </div>
          <div v-else-if="itineraryError" class="itinerary-error" role="alert">
            <strong>当前行程加载失败</strong>
            <span>{{ itineraryError }}</span>
          </div>
          <div v-else-if="!itinerary" class="itinerary-empty">
            <Route :size="24" aria-hidden="true" />
            <strong>尚未生成行程</strong>
          </div>
          <div v-else class="itinerary-content">
            <header class="itinerary-summary">
              <div>
                <span class="provider-badge">{{ itinerary.provider === 'DEMO' ? 'Demo 数据' : itinerary.provider }}</span>
                <h3>{{ itinerary.title }}</h3>
              </div>
              <dl>
                <div>
                  <dt>版本</dt>
                  <dd>V{{ itinerary.versionNumber }}</dd>
                </div>
                <div>
                  <dt>预计总费用</dt>
                  <dd>{{ formatMoney(itinerary.estimatedTotalCost) }}</dd>
                </div>
              </dl>
            </header>

            <section class="knowledge-evidence" aria-labelledby="knowledge-title">
              <header>
                <div>
                  <BookOpen :size="17" aria-hidden="true" />
                  <h3 id="knowledge-title">推荐依据</h3>
                </div>
                <div class="evidence-badges">
                  <span :class="['evidence-status-badge', `is-${itinerary.knowledge.status.toLowerCase()}`]">
                    {{ evidenceStatusLabel(itinerary.knowledge.status) }}
                  </span>
                  <span :class="['freshness-badge', `is-${itinerary.knowledge.freshness.status.toLowerCase()}`]">
                    {{ freshnessLabel(itinerary.knowledge.freshness.status) }}
                  </span>
                </div>
              </header>
              <p class="knowledge-query">检索问题：{{ itinerary.knowledge.query }}</p>
              <ul v-if="itinerary.knowledge.status === 'REAL' && itinerary.knowledge.citations.length">
                <li v-for="citation in itinerary.knowledge.citations" :key="citation.chunkId">
                  <a :href="citation.sourceUrl" target="_blank" rel="noopener noreferrer">
                    <span>{{ citation.title }}</span>
                    <ExternalLink :size="13" aria-hidden="true" />
                  </a>
                  <small>
                    {{ citation.sourceName }} · 文档 V{{ citation.documentVersion }} ·
                    采集于 {{ formatCollectedAt(citation.collectedAt) }}
                  </small>
                </li>
              </ul>
              <p v-else class="knowledge-message">{{ itinerary.knowledge.message }}</p>
            </section>

            <div class="itinerary-layout">
              <TripMap
                :itinerary="itinerary"
                :selected-activity-id="selectedActivityId"
                @select-activity="selectActivity"
              />
              <div class="itinerary-days">
              <section v-for="(day, dayIndex) in itinerary.days" :key="day.date" class="itinerary-day">
                <header>
                  <span>DAY {{ dayIndex + 1 }}</span>
                  <h3>{{ formatDay(day.date) }}</h3>
                </header>
                <ol>
                  <li v-for="activity in day.activities" :id="`activity-${activity.id}`" :key="activity.id" :class="{ 'is-selected': activity.id === selectedActivityId }">
                    <time>{{ formatTime(activity.startTime) }} — {{ formatTime(activity.endTime) }}</time>
                    <div class="timeline-marker"><span></span></div>
                    <button class="activity-copy" type="button" :aria-label="`选择活动 ${activity.title}`" :aria-pressed="activity.id === selectedActivityId" @click="selectActivity(activity.id)">
                      <strong>{{ activity.title }}</strong>
                      <span class="activity-meta">
                        <Coins :size="14" aria-hidden="true" />
                        {{ formatMoney(activity.estimatedCost) }}
                        <Clock3 :size="14" aria-hidden="true" />
                        {{ activity.source === 'DEMO' ? 'Demo' : activity.source }}
                      </span>
                      <small v-if="activity.address" class="activity-address"><MapPin :size="13" aria-hidden="true" />{{ activity.address }}</small>
                    </button>
                  </li>
                </ol>
              </section>
              </div>
            </div>
          </div>
        </section>

        <GuideIntelligencePanel
          :guide-imports="guideImports"
          :busy="guideBusy"
          :error="guideError"
          :import-guide="importGuide"
          :set-guide-enabled="setGuideEnabled"
        />

        <section class="constraints" aria-labelledby="constraints-title">
          <header class="section-heading">
            <div>
              <p class="eyebrow">CONSTRAINTS</p>
              <h2 id="constraints-title">结构化约束</h2>
            </div>
            <button class="edit-button" type="button" @click="openEditor">
              <Pencil :size="15" aria-hidden="true" />
              编辑约束
            </button>
          </header>

          <dl class="constraint-grid">
            <div>
              <dt><Wallet :size="17" aria-hidden="true" />预算</dt>
              <dd>{{ trip.constraints.budgetAmount === null ? '未设置' : `¥${trip.constraints.budgetAmount}` }}</dd>
            </div>
            <div>
              <dt><Users :size="17" aria-hidden="true" />同行</dt>
              <dd>{{ trip.constraints.travelers }} 人 · {{ travelerTypeLabel(trip.constraints.travelerType) }}</dd>
            </div>
            <div>
              <dt><CircleGauge :size="17" aria-hidden="true" />节奏</dt>
              <dd>{{ paceLabel(trip.constraints.pace) }}</dd>
            </div>
          </dl>

          <div class="constraint-details">
            <section>
              <h3>旅行偏好</h3>
              <div v-if="trip.constraints.preferences.length" class="tags">
                <span v-for="preference in trip.constraints.preferences" :key="preference">{{ preference }}</span>
              </div>
              <p v-else class="muted">暂无偏好</p>
            </section>
            <section>
              <h3>固定安排</h3>
              <p v-if="trip.constraints.fixedSchedules.length === 0" class="muted">暂无固定安排</p>
              <ul v-else class="schedule-list">
                <li v-for="schedule in trip.constraints.fixedSchedules" :key="`${schedule.placeName}-${schedule.startTime}`">
                  <strong>{{ schedule.placeName }}</strong>
                  <span>{{ schedule.startTime }} — {{ schedule.endTime }}</span>
                </li>
              </ul>
            </section>
            <section>
              <h3>到返与住宿</h3>
              <p class="muted">
                到达：{{ trip.constraints.arrival?.placeName ?? '未设置' }}；
                返程：{{ trip.constraints.departure?.placeName ?? '未设置' }}；
                住宿：{{ trip.constraints.accommodation?.placeName ?? '未设置' }}
              </p>
            </section>
            <section>
              <h3>地点与行动能力</h3>
              <p class="muted">
                必去：{{ (trip.constraints.mustVisitPlaces ?? []).join('、') || '未设置' }}；
                排除：{{ (trip.constraints.avoidPlaces ?? []).join('、') || '未设置' }}；
                行动能力：{{ trip.constraints.mobilityLevel ?? 'STANDARD' }}
              </p>
            </section>
          </div>
        </section>
      </template>
    </main>

    <div v-if="editing && trip" class="dialog-backdrop" @click.self="editing = false">
      <section
        ref="dialogElement"
        class="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="edit-constraints-title"
        tabindex="-1"
        @keydown="handleDialogKeydown"
      >
        <header class="dialog-header">
          <div>
            <p class="eyebrow">EDIT CONSTRAINTS</p>
            <h2 id="edit-constraints-title">编辑约束</h2>
          </div>
          <button class="dialog-close" type="button" title="关闭" aria-label="关闭" @click="editing = false">
            <X :size="19" aria-hidden="true" />
          </button>
        </header>

        <form @submit.prevent="saveConstraints">
          <div class="form-grid">
            <div class="field">
              <label for="edit-budget">预算</label>
              <div class="number-input"><span>¥</span><input id="edit-budget" v-model="form.budgetAmount" type="number" min="0" step="0.01" data-modal-initial-focus /></div>
            </div>
            <div class="field">
              <label for="edit-travelers">同行人数</label>
              <input id="edit-travelers" v-model.number="form.travelers" type="number" min="1" max="50" required />
            </div>
            <div class="field field-wide">
              <label for="edit-traveler-type">同行类型</label>
              <select id="edit-traveler-type" v-model="form.travelerType" required>
                <option value="SOLO">独自出行</option>
                <option value="COUPLE">伴侣同行</option>
                <option value="FAMILY">家庭出行</option>
                <option value="FRIENDS">朋友同行</option>
                <option value="BUSINESS">商务出行</option>
              </select>
            </div>
            <div class="field">
              <label for="arrival-place">到达地点</label>
              <input id="arrival-place" v-model.trim="form.arrivalPlace" maxlength="120" />
            </div>
            <div class="field">
              <label for="arrival-time">到达时间（北京时间）</label>
              <input id="arrival-time" v-model="form.arrivalTime" type="datetime-local" />
            </div>
            <div class="field">
              <label for="departure-place">返程地点</label>
              <input id="departure-place" v-model.trim="form.departurePlace" maxlength="120" />
            </div>
            <div class="field">
              <label for="departure-time">返程时间（北京时间）</label>
              <input id="departure-time" v-model="form.departureTime" type="datetime-local" />
            </div>
            <div class="field field-wide">
              <label for="accommodation-place">住宿锚点</label>
              <input id="accommodation-place" v-model.trim="form.accommodationPlace" maxlength="120" />
            </div>
            <div class="field">
              <label for="must-visit">必去地点（用顿号分隔）</label>
              <input id="must-visit" v-model="form.mustVisitText" maxlength="1000" />
            </div>
            <div class="field">
              <label for="avoid-places">排除地点（用顿号分隔）</label>
              <input id="avoid-places" v-model="form.avoidText" maxlength="1000" />
            </div>
            <div class="field field-wide">
              <label for="mobility-level">行动能力</label>
              <select id="mobility-level" v-model="form.mobilityLevel">
                <option value="STANDARD">标准步行</option>
                <option value="REDUCED">减少步行</option>
                <option value="STEP_FREE">尽量无台阶（车行接驳，场地需确认）</option>
              </select>
            </div>
            <div v-for="meal in [
              { key: 'breakfast', label: '早餐' },
              { key: 'lunch', label: '午餐' },
              { key: 'dinner', label: '晚餐' },
            ]" :key="meal.key" class="field field-wide meal-window">
              <label>{{ meal.label }}窗口</label>
              <div>
                <input v-model="form[`${meal.key}Start` as 'breakfastStart' | 'lunchStart' | 'dinnerStart']" type="time" :aria-label="`${meal.label}开始时间`" />
                <span>至</span>
                <input v-model="form[`${meal.key}End` as 'breakfastEnd' | 'lunchEnd' | 'dinnerEnd']" type="time" :aria-label="`${meal.label}结束时间`" />
              </div>
            </div>
          </div>

          <fieldset class="option-group">
            <legend>旅行节奏</legend>
            <div class="segmented-control">
              <label><input v-model="form.pace" type="radio" value="RELAXED" />舒缓</label>
              <label><input v-model="form.pace" type="radio" value="BALANCED" />均衡</label>
              <label><input v-model="form.pace" type="radio" value="INTENSIVE" />紧凑</label>
            </div>
          </fieldset>

          <fieldset class="option-group">
            <legend>偏好</legend>
            <div class="preference-options">
              <label v-for="preference in preferenceOptions" :key="preference">
                <input
                  type="checkbox"
                  :value="preference"
                  :checked="form.preferences.includes(preference)"
                  @change="togglePreference(preference)"
                />
                {{ preference }}
              </label>
            </div>
          </fieldset>

          <p v-if="formError" class="form-error" role="alert">{{ formError }}</p>

          <button
            v-if="versionConflict"
            class="reload-button"
            type="button"
            :disabled="submitting"
            @click="reloadLatestTrip"
          >
            重新加载最新数据
          </button>

          <footer class="dialog-actions">
            <button class="secondary-button" type="button" @click="editing = false">取消</button>
            <button class="primary-button" type="submit" :disabled="submitting">保存约束</button>
          </footer>
        </form>
      </section>
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  min-height: 100vh;
  color: #17201d;
  background: #f2f5f4;
}

.topbar {
  height: 68px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 0 28px;
  color: #f9fbfa;
  background: #173d33;
  border-bottom: 3px solid #e6b44a;
}

.brand-lockup,
.user-actions,
.trip-meta,
.state-copy,
.section-heading,
.constraint-grid dt {
  display: flex;
  align-items: center;
}

.brand-lockup { gap: 10px; }
.brand-lockup div,
.user-copy { display: grid; }
.brand-lockup strong { font-size: 16px; }
.brand-lockup span:not(.brand-icon),
.user-copy span { color: #b9ccc5; font-size: 11px; }

.brand-icon {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  color: #173d33;
  background: #e6b44a;
  border-radius: 5px;
}

.user-actions { min-width: 0; gap: 14px; }
.user-copy { min-width: 0; max-width: 280px; text-align: right; }
.user-copy strong,
.user-copy span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.user-copy strong { font-size: 13px; }

.icon-button {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  padding: 0;
  color: inherit;
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.24);
  border-radius: 5px;
  cursor: pointer;
}

.workspace {
  width: min(1060px, calc(100% - 40px));
  margin: 0 auto;
  padding: 30px 0 72px;
}

.back-button,
.error-state button {
  min-height: 38px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 0;
  color: #315f52;
  background: transparent;
  border: 0;
  font: inherit;
  font-size: 13px;
  font-weight: 750;
  cursor: pointer;
}

.trip-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 28px 0 34px;
}

.eyebrow {
  margin: 0 0 5px;
  color: #8a650f;
  font-size: 11px;
  font-weight: 800;
}

h1, h2, h3, p { letter-spacing: 0; }
h1 { margin: 0; overflow-wrap: anywhere; font-size: 30px; }
h2 { margin: 0; font-size: 21px; }
h3 { margin: 0 0 12px; font-size: 13px; }

.trip-meta {
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 12px;
  color: #5d6e68;
  font-size: 13px;
}

.trip-meta span { display: inline-flex; align-items: center; gap: 5px; }
.state-copy { flex: 0 0 auto; gap: 8px; color: #66756f; font-size: 12px; }
.status-badge {
  padding: 4px 8px;
  color: #6c531a;
  background: #fbf1d5;
  border-radius: 4px;
  font-weight: 750;
}

.constraints {
  background: #fff;
  border: 1px solid #d4ddda;
  border-top: 3px solid #2f705e;
  border-radius: 6px;
}

.itinerary-workspace {
  margin-bottom: 26px;
  background: #fff;
  border: 1px solid #d4ddda;
  border-top: 3px solid #e6b44a;
  border-radius: 6px;
}

.itinerary-heading,
.itinerary-summary,
.itinerary-day > header,
.planning-status {
  display: flex;
  align-items: center;
}

.itinerary-heading {
  justify-content: space-between;
  gap: 20px;
  padding: 22px 24px;
  border-bottom: 1px solid #e2e8e5;
}

.planning-button {
  min-width: 116px;
  min-height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 0 14px;
  color: #fff;
  background: #236552;
  border: 1px solid #236552;
  border-radius: 5px;
  font: inherit;
  font-size: 12px;
  font-weight: 750;
  cursor: pointer;
}

.planning-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cancel-planning-button {
  min-height: 40px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 12px;
  color: #7c2d2d;
  background: #fff;
  border: 1px solid #d9a3a3;
  border-radius: 5px;
  font: inherit;
  font-size: 12px;
  font-weight: 750;
  cursor: pointer;
}

.planning-button:disabled { cursor: wait; opacity: 0.72; }
.spinning { animation: spin 0.9s linear infinite; }

.planning-status,
.planning-error {
  gap: 8px;
  margin: 0;
  padding: 11px 24px;
  font-size: 13px;
}

.planning-status { color: #315f52; background: #edf5f2; }
.planning-error { color: #8a2929; background: #fff0ef; }

.itinerary-loading,
.itinerary-empty,
.itinerary-error {
  min-height: 180px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.itinerary-loading { gap: 6px; }
.itinerary-loading span {
  width: 8px;
  height: 8px;
  background: #2f705e;
  border-radius: 50%;
  animation: pulse 0.9s infinite alternate;
}
.itinerary-loading span:nth-child(2) { animation-delay: 0.2s; }
.itinerary-loading span:nth-child(3) { animation-delay: 0.4s; }

.itinerary-empty,
.itinerary-error {
  flex-direction: column;
  gap: 8px;
  color: #71817b;
  font-size: 13px;
}
.itinerary-empty strong,
.itinerary-error strong { color: #34443f; font-size: 14px; }
.itinerary-error { color: #8a2929; }

.itinerary-content { padding: 0 24px 24px; }
.itinerary-summary {
  justify-content: space-between;
  gap: 24px;
  padding: 22px 0;
  border-bottom: 1px solid #e2e8e5;
}
.itinerary-summary h3 { margin: 7px 0 0; font-size: 18px; }
.provider-badge {
  display: inline-block;
  padding: 4px 7px;
  color: #72550d;
  background: #fbf1d5;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 800;
}
.itinerary-summary dl { display: flex; gap: 30px; margin: 0; text-align: right; }
.itinerary-summary dt { color: #71817b; font-size: 11px; }
.itinerary-summary dd { margin: 4px 0 0; color: #17201d; font-size: 15px; font-weight: 800; }

.knowledge-evidence { padding: 20px 0; border-bottom: 1px solid #e2e8e5; }
.knowledge-evidence > header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.knowledge-evidence > header > div { display: flex; align-items: center; gap: 8px; color: #315f52; }
.knowledge-evidence h3 { margin: 0; color: #17201d; font-size: 15px; }
.evidence-badges { display: flex; align-items: center; justify-content: flex-end; gap: 6px; flex-wrap: wrap; }
.evidence-status-badge { padding: 4px 8px; border-radius: 999px; font-size: 10px; font-weight: 800; }
.evidence-status-badge.is-real { color: #245c75; background: #e5f1f7; }
.evidence-status-badge.is-demo { color: #805d0b; background: #fbf1d5; }
.evidence-status-badge.is-unavailable { color: #7b3b3b; background: #f8e9e9; }
.freshness-badge { padding: 4px 8px; border-radius: 999px; font-size: 10px; font-weight: 800; }
.freshness-badge.is-fresh { color: #236552; background: #e7f3ee; }
.freshness-badge.is-stale { color: #805d0b; background: #fbf1d5; }
.freshness-badge.is-unavailable { color: #6d7773; background: #edf0ef; }
.knowledge-query { margin: 12px 0; color: #60736b; font-size: 12px; }
.knowledge-evidence ul { display: grid; gap: 9px; margin: 0; padding: 0; list-style: none; }
.knowledge-evidence li { padding: 10px 12px; background: #f6f8f7; border-radius: 6px; }
.knowledge-evidence a { display: inline-flex; align-items: center; gap: 6px; color: #236552; font-size: 13px; font-weight: 750; text-decoration: none; }
.knowledge-evidence a:hover { text-decoration: underline; }
.knowledge-evidence small { display: block; margin-top: 5px; color: #71817b; font-size: 10px; }
.knowledge-message { margin: 10px 0 0; color: #71817b; font-size: 12px; }

.itinerary-layout { display: grid; grid-template-columns: minmax(280px, .9fr) minmax(0, 1.1fr); gap: 24px; padding-top: 24px; }
.itinerary-days { display: grid; }
.itinerary-day {
  display: grid;
  grid-template-columns: 118px minmax(0, 1fr);
  padding: 24px 0 4px;
  border-bottom: 1px solid #e2e8e5;
}
.itinerary-day:last-child { border-bottom: 0; }
.itinerary-day > header { align-items: flex-start; flex-direction: column; gap: 5px; }
.itinerary-day > header span { color: #8a650f; font-size: 10px; font-weight: 850; }
.itinerary-day > header h3 { margin: 0; font-size: 15px; }
.itinerary-day ol { margin: 0; padding: 0; list-style: none; }
.itinerary-day li { min-height: 72px; display: grid; grid-template-columns: 104px 22px minmax(0, 1fr); }
.itinerary-day time { padding-top: 3px; color: #52625c; font-size: 12px; font-weight: 750; white-space: nowrap; }
.timeline-marker { position: relative; display: flex; justify-content: center; }
.timeline-marker::after { content: ''; position: absolute; top: 11px; bottom: 0; width: 1px; background: #cbd8d3; }
.itinerary-day li:last-child .timeline-marker::after { display: none; }
.timeline-marker span {
  position: relative;
  z-index: 1;
  width: 9px;
  height: 9px;
  margin-top: 4px;
  background: #e6b44a;
  border: 2px solid #fff;
  border-radius: 50%;
  box-shadow: 0 0 0 1px #bd8e28;
}
.activity-copy { min-width: 0; width: 100%; padding: 0 0 22px 10px; color: inherit; background: transparent; border: 0; text-align: left; cursor: pointer; }
.activity-copy:hover strong, .itinerary-day li.is-selected .activity-copy strong { color: #236552; }
.itinerary-day li.is-selected .timeline-marker span { background: #2f705e; box-shadow: 0 0 0 3px rgba(47, 112, 94, .16); }
.activity-copy > strong { display: block; overflow-wrap: anywhere; font-size: 14px; }
.activity-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 5px; margin-top: 7px; color: #71817b; font-size: 11px; }
.activity-meta svg:nth-of-type(2) { margin-left: 7px; }
.activity-address { display: flex; align-items: flex-start; gap: 4px; margin-top: 7px; color: #60736b; font-size: 11px; line-height: 1.45; }
.activity-address svg { flex: 0 0 auto; margin-top: 1px; }

.section-heading {
  justify-content: space-between;
  gap: 20px;
  padding: 22px 24px;
  border-bottom: 1px solid #e2e8e5;
}

.edit-button,
.primary-button,
.secondary-button {
  min-height: 38px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 0 13px;
  border-radius: 5px;
  font: inherit;
  font-size: 12px;
  font-weight: 750;
  cursor: pointer;
}
.edit-button { color: #236552; background: #fff; border: 1px solid #9db5ad; }
.primary-button { color: #fff; background: #236552; border: 1px solid #236552; }
.secondary-button { color: #34443f; background: #fff; border: 1px solid #cbd5d1; }
.primary-button:disabled { cursor: wait; opacity: 0.65; }
.constraint-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 0;
  padding: 24px;
  border-bottom: 1px solid #e2e8e5;
}

.constraint-grid > div {
  min-width: 0;
  padding: 0 24px;
  border-right: 1px solid #e2e8e5;
}
.constraint-grid > div:first-child { padding-left: 0; }
.constraint-grid > div:last-child { padding-right: 0; border-right: 0; }
.constraint-grid dt { gap: 6px; color: #71817b; font-size: 12px; }
.constraint-grid dd { margin: 8px 0 0; overflow-wrap: anywhere; font-size: 17px; font-weight: 800; }

.constraint-details {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 32px;
  padding: 24px;
}
.tags { display: flex; flex-wrap: wrap; gap: 7px; }
.tags span {
  padding: 5px 8px;
  color: #315f52;
  background: #eaf1ee;
  border-radius: 4px;
  font-size: 12px;
}
.muted { margin: 0; color: #71817b; font-size: 13px; }
.schedule-list { margin: 0; padding: 0; list-style: none; }
.schedule-list li { display: grid; gap: 4px; padding: 8px 0; border-top: 1px solid #e8ecea; }
.schedule-list li:first-child { padding-top: 0; border-top: 0; }
.schedule-list span { color: #71817b; font-size: 12px; }

.dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 20;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(15, 29, 24, 0.62);
}
.dialog {
  width: min(600px, 100%);
  max-height: calc(100vh - 40px);
  overflow-y: auto;
  padding: 24px;
  background: #fff;
  border-radius: 7px;
  box-shadow: 0 22px 70px rgba(10, 28, 22, 0.24);
}
.dialog-header,
.dialog-actions { display: flex; align-items: center; justify-content: space-between; }
.dialog-header { margin-bottom: 22px; }
.dialog-close {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  padding: 0;
  color: #45564f;
  background: transparent;
  border: 1px solid #d4ddda;
  border-radius: 5px;
  cursor: pointer;
}
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.field-wide { grid-column: 1 / -1; }
.field label,
.option-group legend { display: block; margin-bottom: 7px; color: #34443f; font-size: 12px; font-weight: 750; }
.field input,
.field select,
.number-input {
  width: 100%;
  height: 42px;
  padding: 0 11px;
  color: #17201d;
  background: #fff;
  border: 1px solid #cbd5d1;
  border-radius: 5px;
  outline: 0;
  font: inherit;
}
.number-input { display: flex; align-items: center; gap: 6px; }
.number-input span { color: #71817b; }
.number-input input { height: 38px; padding: 0; border: 0; }
.option-group { margin: 20px 0 0; padding: 0; border: 0; }
.segmented-control { display: grid; grid-template-columns: repeat(3, 1fr); padding: 3px; background: #edf1ef; border-radius: 5px; }
.segmented-control label {
  position: relative;
  min-height: 34px;
  display: grid;
  place-items: center;
  color: #5f7069;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.segmented-control label:has(input:checked) { color: #194d3e; background: #fff; box-shadow: 0 1px 4px rgba(23, 61, 51, 0.12); }
.segmented-control label:has(input:focus-visible),
.preference-options label:has(input:focus-visible) { outline: 2px solid #26725f; outline-offset: 2px; }
.segmented-control input,
.preference-options input { position: absolute; opacity: 0; }
.preference-options { display: flex; flex-wrap: wrap; gap: 7px; }
.preference-options label {
  position: relative;
  padding: 7px 10px;
  color: #52625c;
  background: #fff;
  border: 1px solid #cbd5d1;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
}
.preference-options label:has(input:checked) { color: #194d3e; background: #e8f2ee; border-color: #5c9685; }
.form-error { margin: 18px 0 0; padding: 10px 12px; color: #8a2929; background: #fff0ef; border-left: 3px solid #bb4942; font-size: 13px; }
.reload-button {
  min-height: 36px;
  margin-top: 10px;
  padding: 0 12px;
  color: #8a2929;
  background: #fff;
  border: 1px solid #d69b98;
  border-radius: 5px;
  font: inherit;
  font-size: 12px;
  font-weight: 750;
  cursor: pointer;
}
.dialog-actions { justify-content: flex-end; gap: 10px; margin-top: 24px; padding-top: 18px; border-top: 1px solid #e2e8e5; }

.loading-state,
.error-state {
  min-height: 360px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
.loading-state span { width: 8px; height: 8px; background: #2f705e; border-radius: 50%; animation: pulse 0.9s infinite alternate; }
.loading-state span:nth-child(2) { animation-delay: 0.2s; }
.loading-state span:nth-child(3) { animation-delay: 0.4s; }
.error-state { flex-direction: column; color: #8a2929; }
.error-state p { margin: 0; }

@keyframes pulse { to { opacity: 0.25; transform: translateY(-4px); } }
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 620px) {
  .topbar { height: 62px; padding: 0 16px; }
  .brand-lockup span:not(.brand-icon),
  .user-copy span { display: none; }
  .user-copy { max-width: 110px; }
  .workspace { width: min(100% - 28px, 1060px); padding-top: 18px; }
  .trip-heading { display: grid; gap: 16px; padding: 20px 0 26px; }
  h1 { font-size: 25px; }
  .constraint-grid,
  .constraint-details,
  .form-grid { grid-template-columns: 1fr; }
  .itinerary-summary { align-items: flex-start; flex-direction: column; }
  .itinerary-summary dl { width: 100%; justify-content: space-between; text-align: left; }
  .itinerary-layout { grid-template-columns: 1fr; gap: 18px; }
  .itinerary-day { grid-template-columns: 1fr; gap: 16px; }
  .itinerary-day > header { flex-direction: row; align-items: baseline; }
  .itinerary-heading { align-items: flex-start; }
  .itinerary-day li { grid-template-columns: 90px 20px minmax(0, 1fr); }
  .field-wide { grid-column: auto; }
  .dialog { padding: 19px; }
  .constraint-grid { gap: 18px; }
  .constraint-grid > div,
  .constraint-grid > div:first-child,
  .constraint-grid > div:last-child { padding: 0 0 18px; border-right: 0; border-bottom: 1px solid #e2e8e5; }
  .constraint-grid > div:last-child { padding-bottom: 0; border-bottom: 0; }
}
</style>
