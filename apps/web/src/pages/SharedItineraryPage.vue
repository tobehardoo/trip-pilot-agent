<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { CalendarDays, Clock3, MapPin, ShieldCheck, Wallet } from 'lucide-vue-next'

import { getSharedItinerary, type SharedItinerary } from '../lib/api'
import { dataSourceLabel } from '../lib/source-presentation'
import { commuteModeLabel } from '../lib/transit'

const route = useRoute()
const itinerary = ref<SharedItinerary | null>(null)
const busy = ref(false)
const error = ref<string | null>(null)
const shareToken = computed(() => typeof route.params.shareToken === 'string' ? route.params.shareToken : '')

watch(shareToken, async (token) => {
  itinerary.value = null
  error.value = null
  if (!token) {
    error.value = '分享链接无效或已失效'
    return
  }
  busy.value = true
  try {
    itinerary.value = await getSharedItinerary(token)
  } catch {
    error.value = '分享链接无效、已撤销或已过期'
  } finally {
    busy.value = false
  }
}, { immediate: true })

function dateLabel(date: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'long', day: 'numeric', weekday: 'short',
    timeZone: 'Asia/Shanghai',
  }).format(new Date(`${date}T00:00:00+08:00`))
}

function timeLabel(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit', minute: '2-digit', hour12: false,
    timeZone: 'Asia/Shanghai',
  }).format(new Date(value))
}

function minutes(seconds: number) {
  return Math.round(seconds / 60)
}

function transitCost(leg: SharedItinerary['days'][number]['transitLegs'][number]) {
  if (leg.mode === 'DRIVING') return null
  if (leg.displayCost !== undefined) return leg.displayCost
  return leg.estimatedCost ?? null
}
</script>

<template>
  <main class="min-h-screen bg-surface-50 text-surface-900">
    <header class="border-b border-surface-200 bg-white">
      <div class="mx-auto flex max-w-4xl items-center gap-3 px-4 py-4 sm:px-6">
        <span class="grid h-9 w-9 place-items-center rounded-lg bg-primary-600 text-sm font-bold text-white">TP</span>
        <span class="text-sm font-semibold">TripPilot</span>
        <span class="text-sm text-surface-400">只读行程</span>
      </div>
    </header>

    <section v-if="busy" class="mx-auto max-w-4xl px-4 py-16 sm:px-6" aria-busy="true">
      <div class="h-8 w-2/5 animate-pulse rounded bg-surface-200" />
      <div class="mt-5 h-24 animate-pulse rounded bg-surface-100" />
    </section>

    <section v-else-if="error" class="mx-auto max-w-4xl px-4 py-16 sm:px-6" role="alert">
      <h1 class="m-0 text-xl font-bold">无法打开此行程</h1>
      <p class="mt-2 text-surface-500">{{ error }}</p>
    </section>

    <section v-else-if="itinerary" class="mx-auto max-w-4xl px-4 py-8 sm:px-6">
      <div class="border-b border-surface-200 pb-6">
        <p class="m-0 text-sm text-surface-500">行程版本已固定</p>
        <h1 class="mt-2 text-2xl font-bold sm:text-3xl">{{ itinerary.title }}</h1>
        <dl class="mt-5 grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
          <div class="flex items-center gap-2"><CalendarDays :size="16" /><span>{{ itinerary.days.length }} 天</span></div>
          <div class="flex items-center gap-2"><Wallet :size="16" /><span>¥{{ itinerary.estimatedTotalCost }}</span></div>
          <div v-if="dataSourceLabel(itinerary.provider)" class="flex items-center gap-2"><ShieldCheck :size="16" /><span>{{ dataSourceLabel(itinerary.provider) }}</span></div>
          <div class="flex items-center gap-2"><Clock3 :size="16" /><span>生成于 {{ new Date(itinerary.generatedAt).toLocaleDateString('zh-CN') }}</span></div>
        </dl>
      </div>

      <section v-for="day in itinerary.days" :key="day.date" class="border-b border-surface-200 py-7">
        <h2 class="m-0 text-lg font-semibold">{{ dateLabel(day.date) }}</h2>
        <ol class="mt-5 space-y-4 p-0">
          <li v-for="activity in day.activities" :key="`${day.date}-${activity.startTime}-${activity.title}`" class="grid grid-cols-[4.5rem_1fr] gap-3">
            <time class="pt-0.5 text-sm text-surface-500">{{ timeLabel(activity.startTime) }}</time>
            <div>
              <h3 class="m-0 text-base font-medium">{{ activity.title }}</h3>
              <p v-if="activity.address" class="mt-1 flex items-start gap-1 text-sm text-surface-500"><MapPin :size="15" class="mt-0.5 shrink-0" />{{ activity.address }}</p>
              <p class="mt-1 text-sm text-surface-500">至 {{ timeLabel(activity.endTime) }} · ¥{{ activity.estimatedCost }}<span
                v-if="activity.costSource && activity.costSource !== 'PROVIDER'"
                class="ml-1.5 rounded-full bg-surface-200 px-1.5 py-0.5 text-[10px] font-medium leading-3 text-surface-500"
              >估算</span></p>
            </div>
          </li>
        </ol>
        <ul v-if="day.transitLegs.length" class="mt-4 space-y-2 p-0 text-sm text-surface-500">
          <li v-for="(leg, index) in day.transitLegs" :key="`${day.date}-${index}-${leg.mode}`">
            {{ leg.modeLabel ?? commuteModeLabel(leg.mode) }} · {{ minutes(leg.routeDurationSeconds ?? leg.durationSeconds) }} 分钟<span v-if="leg.waitSeconds"> · 候车 {{ minutes(leg.waitSeconds) }} 分钟</span><span v-if="transitCost(leg) !== null"> · ¥{{ transitCost(leg) }}</span><span v-if="leg.estimated"> · 估算</span><span v-if="leg.stale"> · 待核验</span>
          </li>
        </ul>
      </section>

      <section v-if="itinerary.sources.length" class="py-7">
        <h2 class="m-0 text-lg font-semibold">行程依据</h2>
        <ul class="mt-4 space-y-2 p-0">
          <li v-for="source in itinerary.sources" :key="`${source.sourceName}-${source.title}`" class="text-sm">
            <a :href="source.sourceUrl" target="_blank" rel="noreferrer" class="text-primary-700 underline">{{ source.title }}</a>
            <span class="ml-2 text-surface-500">{{ source.sourceName }}</span>
          </li>
        </ul>
      </section>
    </section>
  </main>
</template>
