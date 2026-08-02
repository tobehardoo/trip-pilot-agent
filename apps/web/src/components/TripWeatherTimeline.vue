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
  availability: 'available' | 'historical' | 'pending' | 'unavailable'
}

function addDays(date: string, amount: number) {
  const value = new Date(`${date}T00:00:00Z`)
  value.setUTCDate(value.getUTCDate() + amount)
  return value.toISOString().slice(0, 10)
}

function dateFromStatement(statement: string, observedAt: string) {
  return statement.match(/\b(20\d{2}-\d{2}-\d{2})\b/)?.[1]
    ?? observedAt.slice(0, 10)
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
    date: dateFromStatement(statement, fact.observedAt),
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
  const firstDate = addDays(props.startDate, -2)
  const lastDate = addDays(props.endDate, 2)
  const days: WeatherDay[] = []
  for (let date = firstDate; date <= lastDate; date = addDays(date, 1)) {
    days.push({
      date,
      summary: summariesByDate.value.get(date) ?? null,
      inTrip: date >= props.startDate && date <= props.endDate,
      availability: summariesByDate.value.has(date)
        ? 'available'
        : date < referenceDate.value ? 'historical'
        : date > addDays(referenceDate.value, 4) ? 'unavailable' : 'pending',
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
          <p class="m-0 text-[10px] text-surface-400">行程前后各两天；点击日期定位当天路线</p>
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
          {{ weatherDay.availability === 'historical'
            ? '历史天气尚未同步'
            : weatherDay.availability === 'unavailable' ? '预报未开放' : '待同步' }}
        </strong>
        <span v-if="weatherDay.summary" class="mt-0.5 block text-xs font-semibold text-surface-700">
          {{ weatherDay.summary.temperature }}
        </span>
        <span v-if="weatherDay.summary?.wind" class="mt-0.5 block truncate text-[10px] text-surface-400">
          {{ weatherDay.summary.wind }}
        </span>
        <span v-else-if="weatherDay.availability === 'unavailable'" class="mt-0.5 block text-[10px] text-surface-400">
          出行前约 4 天可查看
        </span>
        <span v-else-if="weatherDay.availability === 'historical'" class="mt-0.5 block text-[10px] text-surface-400">
          请重新同步城市情报
        </span>
      </button>
    </div>
  </section>
</template>
