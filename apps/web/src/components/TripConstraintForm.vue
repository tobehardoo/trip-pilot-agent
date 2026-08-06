<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { CalendarDays, CircleGauge, Landmark, MapPin, Plane, Utensils, Users, Wallet } from 'lucide-vue-next'

import type {
  PlaceSearchResponse,
  StructuredPoi,
  Trip,
  TripConfiguration,
  TripMealWindow,
} from '../lib/api'
import PlaceSearchField from './PlaceSearchField.vue'
import Button from './ui/Button.vue'

export interface TripConfigurationPayload {
  version?: number
  title: string
  destination: string
  startDate: string
  endDate: string
  constraints: TripConfiguration
}

const props = withDefaults(defineProps<{
  /** The trip being edited, or null for the create flow. */
  initial?: Trip | null
  /** Server Beijing-time today, used as the minimum selectable start date. */
  serverDate?: string
  submitting?: boolean
  error?: string | null
  searchPlaces?: (keyword: string, city: string) => Promise<PlaceSearchResponse>
}>(), {
  initial: null,
  serverDate: '',
  submitting: false,
  error: null,
  searchPlaces: undefined,
})

const emit = defineEmits<{
  submit: [payload: TripConfigurationPayload]
}>()

const DEFAULT_MEAL_WINDOWS: TripMealWindow[] = [
  { mealType: 'BREAKFAST', startTime: '08:00', endTime: '09:00', source: 'SYSTEM_DEFAULT' },
  { mealType: 'LUNCH', startTime: '12:00', endTime: '13:00', source: 'SYSTEM_DEFAULT' },
  { mealType: 'DINNER', startTime: '18:00', endTime: '19:00', source: 'SYSTEM_DEFAULT' },
]

function mealWindow(mealType: TripMealWindow['mealType']): TripMealWindow {
  return props.initial?.constraints.mealWindows?.find((w) => w.mealType === mealType)
    ?? DEFAULT_MEAL_WINDOWS.find((w) => w.mealType === mealType)!
}

const form = reactive({
  title: props.initial?.title ?? '',
  destination: props.initial?.destination ?? '广州',
  startDate: props.initial?.startDate ?? props.serverDate,
  endDate: props.initial?.endDate ?? props.serverDate,
  budgetAmount: props.initial?.constraints.budgetAmount?.toString() ?? '',
  travelers: props.initial?.constraints.travelers ?? 1,
  travelerType: props.initial?.constraints.travelerType ?? 'SOLO',
  pace: props.initial?.constraints.pace ?? 'BALANCED',
  mobilityLevel: props.initial?.constraints.mobilityLevel ?? 'STANDARD',
  preferences: [...(props.initial?.constraints.preferences ?? [])],
  mustVisitText: (props.initial?.constraints.mustVisitPlaces ?? []).join('、'),
  avoidText: (props.initial?.constraints.avoidPlaces ?? []).join('、'),
  arrivalPlace: props.initial?.constraints.arrival?.placeName ?? '',
  arrivalTime: toTimeInput(props.initial?.constraints.arrival?.time),
  arrivalPoi: props.initial?.constraints.arrival?.poi ?? null as StructuredPoi | null,
  departurePlace: props.initial?.constraints.departure?.placeName ?? '',
  departureTime: toTimeInput(props.initial?.constraints.departure?.time),
  departurePoi: props.initial?.constraints.departure?.poi ?? null as StructuredPoi | null,
  accommodationPlace: props.initial?.constraints.accommodation?.placeName ?? '',
  accommodationPoi: props.initial?.constraints.accommodation?.poi ?? null as StructuredPoi | null,
  breakfast: { ...mealWindow('BREAKFAST') },
  lunch: { ...mealWindow('LUNCH') },
  dinner: { ...mealWindow('DINNER') },
})

const formError = ref('')

const preferenceOptions = ['岭南文化', '本地美食', '城市漫步', '自然风景', '亲子体验', '夜间活动']

const allPreferences = computed(() => [
  ...new Set([...preferenceOptions, ...form.preferences]),
])

function togglePreference(preference: string) {
  const index = form.preferences.indexOf(preference)
  if (index >= 0) form.preferences.splice(index, 1)
  else form.preferences.push(preference)
}

function setMealTime(meal: { source?: 'SYSTEM_DEFAULT' | 'USER_SET' }, value: string, key: 'startTime' | 'endTime') {
  ;(meal as Record<string, unknown>)[key] = value
  // A real user edit marks the window as USER_SET; untouched defaults stay SYSTEM_DEFAULT.
  meal.source = 'USER_SET'
}

function splitPlaces(value: string): string[] {
  return value.split(/[、,，]/).map((item) => item.trim()).filter(Boolean)
}

function toTimeInput(value?: string): string {
  if (!value) return ''
  return value.slice(0, 5)
}

function buildMealWindows(): TripMealWindow[] {
  return [form.breakfast, form.lunch, form.dinner].map((w) => ({
    mealType: w.mealType,
    startTime: w.startTime,
    endTime: w.endTime,
    source: w.source ?? 'USER_SET',
  }))
}

function accommodationPayload(): TripConfiguration['accommodation'] {
  if (form.accommodationPoi) {
    return { placeName: form.accommodationPoi.name, poi: form.accommodationPoi }
  }
  if (form.accommodationPlace) {
    // Legacy free text preserved for display but never treated as a trusted anchor.
    return { placeName: form.accommodationPlace }
  }
  return null
}

function handleSubmit() {
  formError.value = ''
  if (!form.title.trim()) {
    formError.value = '请填写旅行名称'
    return
  }
  if (!form.destination.trim()) {
    formError.value = '请填写目的地'
    return
  }
  if (!form.startDate || !form.endDate) {
    formError.value = '请选择旅行日期'
    return
  }
  if (form.endDate < form.startDate) {
    formError.value = '结束日期不能早于开始日期'
    return
  }
  const arrivalPlace = form.arrivalPlace || form.arrivalPoi?.name || ''
  const departurePlace = form.departurePlace || form.departurePoi?.name || ''
  if (Boolean(arrivalPlace) !== Boolean(form.arrivalTime)) {
    formError.value = '请同时填写到达地点和到达时间'
    return
  }
  if (Boolean(departurePlace) !== Boolean(form.departureTime)) {
    formError.value = '请同时填写返程地点和返程时间'
    return
  }
  for (const meal of [form.breakfast, form.lunch, form.dinner]) {
    if (!meal.startTime || !meal.endTime) {
      formError.value = `三餐时间不能为空（${meal.mealType}）`
      return
    }
    if (meal.endTime <= meal.startTime) {
      formError.value = '餐窗口时间无效'
      return
    }
  }

  const constraints: TripConfiguration = {
    budgetAmount: form.budgetAmount === '' ? null : Number(form.budgetAmount),
    travelers: form.travelers,
    travelerType: form.travelerType,
    pace: form.pace,
    mobilityLevel: form.mobilityLevel,
    preferences: [...form.preferences],
    fixedSchedules: props.initial?.constraints.fixedSchedules.map((s) => ({ ...s })) ?? [],
    mustVisitPlaces: splitPlaces(form.mustVisitText),
    avoidPlaces: splitPlaces(form.avoidText),
    arrival: arrivalPlace && form.arrivalTime
      ? { placeName: arrivalPlace, time: `${form.arrivalTime}:00+08:00`, poi: form.arrivalPoi }
      : null,
    departure: departurePlace && form.departureTime
      ? { placeName: departurePlace, time: `${form.departureTime}:00+08:00`, poi: form.departurePoi }
      : null,
    accommodation: accommodationPayload(),
    mealWindows: buildMealWindows(),
  }

  emit('submit', {
    ...(props.initial ? { version: props.initial.version } : {}),
    title: form.title.trim(),
    destination: form.destination.trim(),
    startDate: form.startDate,
    endDate: form.endDate,
    constraints,
  })
}

defineExpose({ reset: () => {
  formError.value = ''
} })
</script>

<template>
  <form class="space-y-6" @submit.prevent="handleSubmit">
    <!-- 基本信息 -->
    <section aria-label="基本信息">
      <h3 class="mb-3 flex items-center gap-2 text-sm font-semibold text-surface-700">
        <MapPin :size="15" aria-hidden="true" /> 基本信息
      </h3>
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div class="sm:col-span-2">
          <label for="trip-title" class="block text-xs font-semibold text-surface-600 mb-1.5">旅行名称</label>
          <input id="trip-title" v-model.trim="form.title" maxlength="120" required data-modal-initial-focus
            class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
        </div>
        <div class="sm:col-span-2">
          <label for="destination" class="block text-xs font-semibold text-surface-600 mb-1.5">目的地</label>
          <input id="destination" v-model.trim="form.destination" maxlength="120" required
            class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
        </div>
        <div>
          <label for="start-date" class="block text-xs font-semibold text-surface-600 mb-1.5">开始日期</label>
          <input id="start-date" v-model="form.startDate" type="date" :min="serverDate" required
            class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
        </div>
        <div>
          <label for="end-date" class="block text-xs font-semibold text-surface-600 mb-1.5">结束日期</label>
          <input id="end-date" v-model="form.endDate" type="date" :min="form.startDate || serverDate" required
            class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
        </div>
        <div>
          <label for="budget" class="block text-xs font-semibold text-surface-600 mb-1.5">预算</label>
          <div class="flex items-center gap-2 h-10 rounded-xl border border-surface-200 bg-white px-3 focus-within:ring-2 focus-within:ring-primary-400/40 focus-within:border-primary-400 transition-shadow">
            <span class="text-surface-400 text-sm">¥</span>
            <input id="budget" v-model.number="form.budgetAmount" type="number" min="0" step="0.01"
              class="w-full h-full border-0 bg-transparent text-sm text-surface-800 outline-0" />
          </div>
        </div>
        <div>
          <label for="travelers" class="block text-xs font-semibold text-surface-600 mb-1.5">同行人数</label>
          <input id="travelers" v-model.number="form.travelers" type="number" min="1" max="50" required
            class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
        </div>
        <div>
          <label for="traveler-type" class="block text-xs font-semibold text-surface-600 mb-1.5">同行类型</label>
          <select id="traveler-type" v-model="form.travelerType" required
            class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow">
            <option value="SOLO">独自出行</option>
            <option value="COUPLE">伴侣同行</option>
            <option value="FAMILY">家庭出行</option>
            <option value="FRIENDS">朋友同行</option>
            <option value="BUSINESS">商务出行</option>
          </select>
        </div>
        <div>
          <label for="mobility" class="block text-xs font-semibold text-surface-600 mb-1.5">行动能力</label>
          <select id="mobility" v-model="form.mobilityLevel"
            class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow">
            <option value="STANDARD">标准</option>
            <option value="REDUCED">行动较缓</option>
            <option value="STEP_FREE">无障碍</option>
          </select>
        </div>
        <div class="sm:col-span-2">
          <span class="block text-xs font-semibold text-surface-600 mb-1.5">旅行节奏</span>
          <div class="grid grid-cols-3 rounded-xl bg-surface-100 p-1">
            <label v-for="p in [{v:'RELAXED',l:'舒缓'},{v:'BALANCED',l:'均衡'},{v:'INTENSIVE',l:'紧凑'}]" :key="p.v"
              class="relative flex h-9 cursor-pointer items-center justify-center rounded-lg text-sm font-medium transition-all"
              :class="form.pace === p.v ? 'bg-white text-primary-700 shadow-sm' : 'text-surface-500 hover:text-surface-700'"
            >
              <input v-model="form.pace" type="radio" :value="p.v" class="sr-only" />
              {{ p.l }}
            </label>
          </div>
        </div>
      </div>
    </section>

    <!-- 到返信息 -->
    <section aria-label="到返信息">
      <h3 class="mb-3 flex items-center gap-2 text-sm font-semibold text-surface-700">
        <Plane :size="15" aria-hidden="true" /> 到返信息
      </h3>
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label class="block text-xs font-semibold text-surface-600 mb-1.5">到达地点</label>
          <PlaceSearchField
            v-model="form.arrivalPoi"
            :legacy-place-name="form.arrivalPoi ? '' : form.arrivalPlace"
            :city="form.destination"
            :search-places="searchPlaces"
            placeholder="搜索到达站（如：长沙南站）"
          />
        </div>
        <div>
          <label for="arrival-time" class="block text-xs font-semibold text-surface-600 mb-1.5">到达时间</label>
          <input id="arrival-time" v-model="form.arrivalTime" type="time"
            class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
        </div>
        <div>
          <label class="block text-xs font-semibold text-surface-600 mb-1.5">返程地点</label>
          <PlaceSearchField
            v-model="form.departurePoi"
            :legacy-place-name="form.departurePoi ? '' : form.departurePlace"
            :city="form.destination"
            :search-places="searchPlaces"
            placeholder="搜索返程站（如：长沙黄花机场）"
          />
        </div>
        <div>
          <label for="departure-time" class="block text-xs font-semibold text-surface-600 mb-1.5">返程时间</label>
          <input id="departure-time" v-model="form.departureTime" type="time"
            class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
        </div>
      </div>
    </section>

    <!-- 酒店 -->
    <section aria-label="酒店">
      <h3 class="mb-3 flex items-center gap-2 text-sm font-semibold text-surface-700">
        <Landmark :size="15" aria-hidden="true" /> 酒店
      </h3>
      <PlaceSearchField
        v-model="form.accommodationPoi"
        :legacy-place-name="form.accommodationPoi ? '' : form.accommodationPlace"
        :city="form.destination"
        :search-places="searchPlaces"
        placeholder="搜索酒店门店"
      />
      <p v-if="!form.accommodationPoi && !form.accommodationPlace" class="mt-1.5 text-xs text-surface-400">
        暂不设置酒店时，规划将使用虚拟起点估算交通。
      </p>
    </section>

    <!-- 三餐 -->
    <section aria-label="三餐时间">
      <h3 class="mb-3 flex items-center gap-2 text-sm font-semibold text-surface-700">
        <Utensils :size="15" aria-hidden="true" /> 三餐时间
      </h3>
      <div class="space-y-2">
        <div v-for="meal in [form.breakfast, form.lunch, form.dinner]" :key="meal.mealType" class="flex items-center gap-3 rounded-xl border border-surface-200 bg-white px-3 py-2.5">
          <span class="w-12 shrink-0 text-sm font-medium text-surface-600">
            {{ { BREAKFAST: '早餐', LUNCH: '午餐', DINNER: '晚餐' }[meal.mealType] }}
          </span>
          <input :id="`${meal.mealType}-start`" type="time" :value="meal.startTime"
            class="h-9 w-32 rounded-lg border border-surface-200 px-2 text-sm text-surface-800 outline-0 focus:border-primary-400"
            @input="setMealTime(meal, ($event.target as HTMLInputElement).value, 'startTime')" />
          <span class="text-surface-400">—</span>
          <input :id="`${meal.mealType}-end`" type="time" :value="meal.endTime"
            class="h-9 w-32 rounded-lg border border-surface-200 px-2 text-sm text-surface-800 outline-0 focus:border-primary-400"
            @input="setMealTime(meal, ($event.target as HTMLInputElement).value, 'endTime')" />
          <span class="ml-auto text-[11px] text-surface-400">
            {{ meal.source === 'USER_SET' ? '用户设置' : '系统默认' }}
          </span>
        </div>
      </div>
    </section>

    <!-- 偏好与必去 -->
    <section aria-label="偏好与必去">
      <h3 class="mb-3 flex items-center gap-2 text-sm font-semibold text-surface-700">
        <CircleGauge :size="15" aria-hidden="true" /> 偏好与必去
      </h3>
      <div class="flex flex-wrap gap-2 mb-4">
        <label v-for="preference in allPreferences" :key="preference"
          class="relative inline-flex cursor-pointer items-center rounded-xl border px-3 py-2 text-sm font-medium transition-all"
          :class="form.preferences.includes(preference) ? 'border-primary-300 bg-primary-50 text-primary-700' : 'border-surface-200 bg-white text-surface-600 hover:bg-surface-50'"
        >
          <input type="checkbox" :value="preference" :checked="form.preferences.includes(preference)" class="sr-only" @change="togglePreference(preference)" />
          {{ preference }}
        </label>
      </div>
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label for="must-visit" class="block text-xs font-semibold text-surface-600 mb-1.5">必去地点（顿号分隔）</label>
          <input id="must-visit" v-model.trim="form.mustVisitText" maxlength="120" placeholder="如：岳麓山、橘子洲"
            class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
        </div>
        <div>
          <label for="avoid" class="block text-xs font-semibold text-surface-600 mb-1.5">避开地点</label>
          <input id="avoid" v-model.trim="form.avoidText" maxlength="120" placeholder="如：世界之窗"
            class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
        </div>
      </div>
    </section>

    <p v-if="formError || error" class="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700 border-l-4 border-red-400" role="alert">
      {{ formError || error }}
    </p>

    <div class="flex items-center justify-end gap-3 pt-5 border-t border-surface-100">
      <Button variant="primary" size="sm" type="submit" :disabled="submitting">
        {{ submitting ? '保存中…' : '保存并开始规划' }}
      </Button>
    </div>
  </form>
</template>
