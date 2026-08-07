<script setup lang="ts">
import { ChevronLeft, ChevronRight, CloudSun, Sun } from 'lucide-vue-next'
import { computed, ref } from 'vue'

import type { GuideFact } from '../lib/api'

const props = defineProps<{
  weatherFacts: GuideFact[]
  startDate: string
  endDate: string
  selectedDate?: string | null
  referenceDate?: string
}>()

const emit = defineEmits<{
  selectDate: [date: string]
  showAll: []
}>()

const timelineElement = ref<HTMLElement | null>(null)

interface WeatherSummary {
  date: string
  condition: string
  temperature: string
  wind: string | null
}

interface WeatherDay {
  date: string
  summary: WeatherSummary | null
  inTrip: boolean
  availability: 'available' | 'pending' | 'unavailable'
}

/** Provider forecast coverage from the reference (Beijing-today) date. */
const FORECAST_HORIZON_DAYS = 7

function addDays(date: string, amount: number) {
  const value = new Date(`${date}T00:00:00Z`)
  value.setUTCDate(value.getUTCDate() + amount)
  return value.toISOString().slice(0, 10)
}

function dateFromFact(fact: GuideFact) {
  if (fact.effectiveDate && /^20\d{2}-\d{2}-\d{2}$/.test(fact.effectiveDate)) {
    return fact.effectiveDate
  }
  return fact.statement.match(/\b(20\d{2}-\d{2}-\d{2})\b/)?.[1]
    ?? fact.observedAt.slice(0, 10)
}

function weatherSummary(fact: GuideFact): WeatherSummary {
  const statement = fact.statement
  const temperatures = [...statement.matchAll(/(-?\d+(?:\.\d+)?)\s*℃/g)]
    .map((match) => Number(match[1]))
    .filter(Number.isFinite)
  const rawCondition = statement.match(/(?:当前天气|天气预报|历史天气)[：:]\s*(?:白天|夜间)?\s*([^，,；;。\d]+)/)?.[1]?.trim()
  const condition = rawCondition || '天气待更新'
  const temperature = temperatures.length > 1
    ? `${Math.max(...temperatures)}° / ${Math.min(...temperatures)}°`
    : temperatures.length === 1 ? `${temperatures[0]}°` : '—'
  const wind = statement.match(/(?:东北|东南|西北|西南|东|西|南|北)风[^，,；;。]*/)?.[0] ?? null
  return {
    date: dateFromFact(fact),
    condition,
    temperature,
    wind,
  }
}

const summariesByDate = computed(() => {
  const results = new Map<string, WeatherSummary>()
  props.weatherFacts.forEach((fact) => {
    const summary = weatherSummary(fact)
    if (!results.has(summary.date)) results.set(summary.date, summary)
  })
  return results
})

const weatherDays = computed<WeatherDay[]>(() => {
  // 只展示行程日期范围内的天气，旧范围（改期前）的 facts 不再渲染。
  const days: WeatherDay[] = []
  for (let date = props.startDate; date <= props.endDate; date = addDays(date, 1)) {
    const hasFact = summariesByDate.value.has(date)
    // 结合旅行日期、已返回事实覆盖、Provider 预报覆盖范围共同判定：
    // 有事实直接显示；无事实且超出预报范围才算“暂时超出预报”；否则待同步。
    const beyondForecastCoverage = date > addDays(referenceDate.value, FORECAST_HORIZON_DAYS)
    days.push({
      date,
      summary: summariesByDate.value.get(date) ?? null,
      inTrip: true,
      availability: hasFact
        ? 'available'
        : beyondForecastCoverage ? 'unavailable' : 'pending',
    })
  }
  return days
})

const referenceDate = computed(() => props.referenceDate ?? new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Shanghai',
}).format(new Date()))

const showScrollerControls = computed(() => weatherDays.value.length > 7)

function dayLabel(date: string) {
  const [year, month, day] = date.split('-').map(Number)
  return `${month}月${day}日`
}

function weekdayLabel(date: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    weekday: 'short',
    timeZone: 'Asia/Shanghai',
  }).format(new Date(`${date}T00:00:00+08:00`))
}

function scrollTimeline(direction: -1 | 1) {
  timelineElement.value?.scrollBy({ left: direction * 360, behavior: 'smooth' })
}
</script>

<template>
  <section
    class="border-b border-surface-100 bg-white px-3 py-3 sm:px-4"
    role="region"
    aria-label="行程天气"
  >
    <div class="mb-2 flex items-center justify-between gap-3">
      <div class="flex items-center gap-2">
        <span class="grid h-7 w-7 place-items-center rounded-lg bg-sky-50 text-sky-600">
          <CloudSun :size="16" aria-hidden="true" />
        </span>
        <div>
          <h3 class="m-0 text-sm font-bold text-surface-800">行程天气</h3>
          <p class="m-0 text-[10px] text-surface-400">仅显示行程日期；点击日期定位当天路线</p>
        </div>
      </div>
      <div class="flex items-center gap-1">
        <button
          v-if="selectedDate"
          type="button"
          class="rounded-lg border border-primary-200 bg-primary-50 px-2.5 py-1.5 text-xs font-semibold text-primary-700 hover:bg-primary-100"
          @click="emit('showAll')"
        >查看全部行程</button>
        <button
          v-if="showScrollerControls"
          type="button"
          class="grid h-7 w-7 place-items-center rounded-lg border border-surface-200 text-surface-500 hover:bg-surface-50"
          aria-label="向左滚动天气"
          @click="scrollTimeline(-1)"
        ><ChevronLeft :size="15" aria-hidden="true" /></button>
        <button
          v-if="showScrollerControls"
          type="button"
          class="grid h-7 w-7 place-items-center rounded-lg border border-surface-200 text-surface-500 hover:bg-surface-50"
          aria-label="向右滚动天气"
          @click="scrollTimeline(1)"
        ><ChevronRight :size="15" aria-hidden="true" /></button>
      </div>
    </div>

    <div ref="timelineElement" class="flex gap-2 overflow-x-auto scroll-smooth pb-1" tabindex="0">
      <button
        v-for="weatherDay in weatherDays"
        :key="weatherDay.date"
        type="button"
        class="min-w-[98px] shrink-0 rounded-xl border px-3 py-2 text-left transition-colors"
        :class="weatherDay.inTrip
          ? weatherDay.date === selectedDate
            ? 'border-primary-500 bg-primary-100 ring-1 ring-primary-300'
            : 'border-primary-200 bg-primary-50 hover:bg-primary-100'
          : 'border-surface-100 bg-surface-50 hover:bg-surface-100'"
        :aria-label="`选择 ${weatherDay.date} 天气`"
        :aria-pressed="weatherDay.date === selectedDate"
        :disabled="!weatherDay.inTrip"
        @click="emit('selectDate', weatherDay.date)"
      >
        <span class="flex items-center justify-between gap-2 text-[10px] text-surface-500">
          <span>{{ dayLabel(weatherDay.date) }}</span>
          <span>{{ weekdayLabel(weatherDay.date) }}</span>
        </span>
        <strong v-if="weatherDay.summary" class="mt-1 flex items-center gap-1 text-xs text-surface-800">
          <Sun :size="13" class="text-amber-500" aria-hidden="true" />{{ weatherDay.summary.condition }}
        </strong>
        <strong v-else class="mt-1 block text-xs text-surface-400">
          {{ weatherDay.availability === 'unavailable'
            ? '暂时超出天气预报范围'
            : '待同步' }}
        </strong>
        <span v-if="weatherDay.summary" class="mt-0.5 block text-xs font-semibold text-surface-700">
          {{ weatherDay.summary.temperature }}
        </span>
        <span v-if="weatherDay.summary?.wind" class="mt-0.5 block truncate text-[10px] text-surface-400">
          {{ weatherDay.summary.wind }}
        </span>
        <span v-else-if="weatherDay.availability === 'unavailable'" class="mt-0.5 block text-[10px] text-surface-400">
          该日期暂时超出天气预报范围，请临近出发时查看
        </span>
        <span v-else-if="weatherDay.availability === 'pending'" class="mt-0.5 block text-[10px] text-surface-400">
          出行临近时同步天气
        </span>
      </button>
    </div>
  </section>
</template>
