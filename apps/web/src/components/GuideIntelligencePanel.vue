<script setup lang="ts">
import {
  BookOpen,
  ChevronRight,
  ExternalLink,
  LoaderCircle,
  Radar,
  ShieldCheck,
  Upload,
  X,
} from 'lucide-vue-next'
import { computed, ref } from 'vue'

import type { GuideFact, GuideImport, GuideImportInput, Itinerary } from '../lib/api'

const props = defineProps<{
  guideImports: GuideImport[]
  destination: string
  startDate: string
  endDate: string
  itinerary?: Pick<Itinerary, 'days'> | null
  busy: boolean
  error: string | null
  importGuide: (input: GuideImportInput) => Promise<void>
  setGuideEnabled?: (guideImportId: string, enabled: boolean) => Promise<void>
}>()

const importMode = ref<'url' | 'text'>('url')
const sourceUrl = ref('')
const textSourceType = ref<'PASTED_TEXT' | 'TEXT_FILE' | 'XIAOHONGSHU_SHARED_TEXT'>(
  'PASTED_TEXT',
)
const textTitle = ref('')
const textContent = ref('')
const formError = ref<string | null>(null)
const submitting = ref(false)
const cityDetailsOpen = ref(false)

const cityIntelligenceImports = computed(() => props.guideImports.filter(
  (guide) => guide.sourceType === 'CITY_INTELLIGENCE',
).sort((left, right) => Date.parse(right.fetchedAt) - Date.parse(left.fetchedAt)))
const latestCityIntelligenceImport = computed(() => cityIntelligenceImports.value[0] ?? null)
const activeCityIntelligenceImport = computed(() => (
  latestCityIntelligenceImport.value?.enabled ? latestCityIntelligenceImport.value : null
))
const userGuideImports = computed(() => props.guideImports.filter(
  (guide) => guide.sourceType !== 'CITY_INTELLIGENCE',
))
const cityFacts = computed(() => activeCityIntelligenceImport.value?.facts ?? [])
const cityDisplayFacts = computed(() => cityFacts.value.filter((fact) => fact.category !== 'WEATHER'))

interface CityPlaceCard {
  name: string
  updatedAt: string
  address: string | null
  openingHours: string | null
  ticket: string | null
  reservation: string | null
  notices: string[]
  inItinerary: boolean
  itineraryDates: string[]
}

function compactValue(value: string) {
  return value.replace(/\s+/g, ' ').replace(/[；;，,。]+$/g, '').trim()
}

function normalizeAddress(value: string | null) {
  if (!value) return null
  return compactValue(value).replace(
    /([\u4e00-\u9fff]{2,16}?(?:街道|街|社区|大道|路|巷|区|镇|村))(?:\1)+/g,
    '$1',
  )
}

function extractValue(statement: string, pattern: RegExp) {
  return compactValue(statement.match(pattern)?.[1] ?? '') || null
}

function placeName(statement: string) {
  return compactValue(statement.match(/^([^：:；;。]{2,48})[：:]/)?.[1] ?? '') || null
}

function normalizeTicket(value: string | null) {
  if (!value) return null
  if (/免费|免票/.test(value)) return '免费'
  return value.replace(/(\d+)\s*元/g, '$1 元')
}

function normalizeReservation(value: string | null) {
  if (!value) return null
  if (/^(需|须)/.test(value)) return value.replace(/^(需|须)/, '需要')
  return value
}

function cityNotice(statement: string) {
  return compactValue(
    statement
      .replace(/^[^：:；;。]{2,48}[：:]/, '')
      .replace(/(?:地址|地点位置)[：:]?\s*[^；;。]+[；;。]?/g, '')
      .replace(/(?:营业信息|营业时间|开放时间)[：:]?\s*[^；;。]+[；;。]?/g, '')
      .replace(/(?:门票|票价)[：:]?\s*(?:约|为)?\s*[^；;。]+[；;。]?/g, '')
      .replace(/(?:需|需要|须|建议|必须)?(?:提前)?预约[^；;。]*[；;。]?/g, ''),
  )
}

const cityPlaceCards = computed<CityPlaceCard[]>(() => {
  const places = new Map<string, CityPlaceCard>()
  cityFacts.value
    .filter((fact) => fact.category !== 'WEATHER')
    .forEach((fact) => {
      const statement = displayStatement(fact.statement)
      const name = placeName(statement)
      if (!name) return
      const current = places.get(name) ?? {
        name,
        updatedAt: fact.observedAt,
        address: null,
        openingHours: null,
        ticket: null,
        reservation: null,
        notices: [],
        inItinerary: false,
        itineraryDates: [],
      }
      if (new Date(fact.observedAt).getTime() > new Date(current.updatedAt).getTime()) {
        current.updatedAt = fact.observedAt
      }
      current.address ??= normalizeAddress(
        extractValue(statement, /(?:地址|地点位置)[：:]?\s*([^；;。]+)/),
      )
      current.openingHours ??= extractValue(statement, /(?:营业信息|营业时间|开放时间)[：:]?\s*([^；;。]+)/)
      current.ticket ??= normalizeTicket(extractValue(statement, /(?:门票|票价)[：:]?\s*(?:约|为)?\s*([^；;。]+)/))
      current.reservation ??= normalizeReservation(extractValue(statement, /((?:(?:需|需要|须|建议|必须)?(?:提前)?预约)[^；;。]*)/))
      const notice = cityNotice(statement)
      if (notice && !current.notices.includes(notice)) current.notices.push(notice)
      places.set(name, current)
    })
  return [...places.values()].sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))
})

const displayPlaceCards = computed<CityPlaceCard[]>(() => {
  const intelligenceByName = new Map(cityPlaceCards.value.map((place) => [place.name, place]))
  const itineraryPlaces = new Map<string, CityPlaceCard>()
  for (const day of props.itinerary?.days ?? []) {
    for (const activity of day.activities) {
      const name = activity.title.trim()
      if (!name) continue
      const intelligence = intelligenceByName.get(name)
      const current = itineraryPlaces.get(name) ?? {
        name,
        updatedAt: intelligence?.updatedAt ?? activity.startTime,
        address: intelligence?.address ?? normalizeAddress(activity.address),
        openingHours: intelligence?.openingHours ?? null,
        ticket: intelligence?.ticket ?? null,
        reservation: intelligence?.reservation ?? null,
        notices: intelligence?.notices ?? [],
        inItinerary: true,
        itineraryDates: [],
      }
      if (!current.itineraryDates.includes(day.date)) current.itineraryDates.push(day.date)
      itineraryPlaces.set(name, current)
      intelligenceByName.delete(name)
    }
  }
  return [
    ...itineraryPlaces.values(),
    ...[...intelligenceByName.values()].map((place) => ({ ...place, inItinerary: false, itineraryDates: [] })),
  ]
})

const categoryLabels: Record<GuideFact['category'], string> = {
  ATTRACTION: '景点',
  DINING: '吃饭',
  TRANSPORT: '交通',
  TIMING: '时间',
  COST: '费用',
  QUEUE: '排队',
  RESERVATION: '预约',
  LOCATION: '位置',
  WEATHER: '天气',
  TIP: '提示',
}

async function submit() {
  if (submitting.value) return
  const input: GuideImportInput = importMode.value === 'url'
    ? {
        sourceType: 'PUBLIC_GUIDE_URL',
        sourceUrl: sourceUrl.value.trim(),
      }
    : {
        sourceType: textSourceType.value,
        title: textTitle.value.trim(),
        content: textContent.value.trim(),
      }
  if (
    ('sourceUrl' in input && !input.sourceUrl)
    || ('content' in input && (!input.title || !input.content))
  ) return

  submitting.value = true
  formError.value = null
  try {
    await props.importGuide(input)
    if (importMode.value === 'url') {
      sourceUrl.value = ''
    } else {
      textTitle.value = ''
      textContent.value = ''
      textSourceType.value = 'PASTED_TEXT'
    }
  } finally {
    submitting.value = false
  }
}

async function syncCityIntelligence() {
  if (submitting.value) return
  submitting.value = true
  formError.value = null
  try {
    await props.importGuide({
      sourceType: 'CITY_INTELLIGENCE',
      city: props.destination,
      startDate: props.startDate,
      endDate: props.endDate,
    })
  } finally {
    submitting.value = false
  }
}

async function loadTextFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  formError.value = null
  if (file.size > 100_000) {
    formError.value = 'TXT/Markdown 文件不能超过 100 KB。'
    input.value = ''
    return
  }
  const content = await file.text()
  if (!content.trim()) {
    formError.value = '文件没有可识别的正文。'
    input.value = ''
    return
  }
  textTitle.value = file.name
  textContent.value = content.slice(0, 100_000)
  textSourceType.value = 'TEXT_FILE'
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'Asia/Shanghai',
  }).format(new Date(value))
}

function isFresh(expiresAt: string) {
  return new Date(expiresAt).getTime() > Date.now()
}

function displayStatement(statement: string) {
  return statement
    .replace(/[；;，,]?\s*坐标\s*[-\d.]+\s*[,，]\s*[-\d.]+/g, '')
    .replace(/\s{2,}/g, ' ')
    .trim()
}
</script>

<template>
  <section class="rounded-2xl border border-surface-200 bg-white shadow-card p-6 sm:p-7" aria-labelledby="guide-intelligence-title">
    <div class="flex justify-between gap-6 mb-5">
      <div>
        <p class="text-xs font-bold uppercase tracking-widest text-primary-500 mb-1">Live Guide Intelligence</p>
        <h2 id="guide-intelligence-title" class="flex items-center gap-2.5 mt-0.5 mb-2 text-xl font-bold text-surface-800">
          <Radar :size="19" class="text-primary-500" aria-hidden="true" />攻略情报
        </h2>
        <p class="max-w-[650px] text-sm text-surface-500 m-0 leading-relaxed">
          导入公开链接、粘贴正文、TXT/Markdown 或小红书分享文本，提取带原句证据的旅行事实。
        </p>
      </div>
      <span class="shrink-0 inline-flex items-center gap-1.5 self-start rounded-full bg-primary-50 px-3 py-1.5 text-xs font-semibold text-primary-700">
        <ShieldCheck :size="13" aria-hidden="true" />仅当前行程
      </span>
    </div>

    <div class="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-sky-200 bg-sky-50 px-4 py-3">
      <p class="m-0 text-xs leading-relaxed text-sky-800">
        同步 {{ destination }} 当前天气、行程日期预报、营业与预约信息；同步结果会进入下一次 Agent 规划快照。
      </p>
      <button
        type="button"
        :disabled="busy || submitting"
        class="shrink-0 rounded-lg bg-sky-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"
        @click="syncCityIntelligence"
      >
        {{ busy || submitting ? '同步中…' : '同步城市情报' }}
      </button>
    </div>

    <section
      v-if="latestCityIntelligenceImport"
      class="mb-5 rounded-xl border border-primary-100 bg-primary-50/50 px-4 py-3"
      aria-labelledby="city-intelligence-summary-title"
    >
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p class="m-0 text-xs font-semibold text-primary-600">出行提醒</p>
          <h3 id="city-intelligence-summary-title" class="mt-1 text-sm font-bold text-surface-800">
            {{ latestCityIntelligenceImport.enabled
              ? `${destination} 已整理 ${displayPlaceCards.length} 个地点的出行资料`
              : `${destination} 城市情报已停用` }}
          </h3>
          <!--
          <h3 v-if="false" aria-hidden="true">
            {{ cityWeather ? displayStatement(cityWeather.statement) : `${destination} 已同步 ${cityDisplayFacts.length} 条实时资料` }}
          </h3>
          -->
          <p v-if="false" class="m-0 text-xs text-surface-500">
            已整理 {{ cityDisplayFacts.length }} 条天气、营业与地点动态，仅在需要时查看详情。
          </p>
        </div>
        <button
          type="button"
          class="inline-flex shrink-0 items-center gap-1 rounded-lg bg-white px-3 py-2 text-xs font-semibold text-primary-700 shadow-sm ring-1 ring-primary-200"
          aria-label="查看实时情报"
          @click="cityDetailsOpen = true"
        >
          查看实时情报 <ChevronRight :size="14" aria-hidden="true" />
        </button>
      </div>
    </section>

    <form class="rounded-xl bg-surface-50 border border-surface-200 p-4 mb-5" @submit.prevent="submit">
      <div class="flex gap-2 mb-4" role="group" aria-label="攻略导入方式">
        <button
          type="button"
          class="rounded-lg px-3 py-1.5 text-xs font-semibold"
          :class="importMode === 'url' ? 'bg-primary-600 text-white' : 'bg-white text-surface-600 border border-surface-200'"
          @click="importMode = 'url'"
        >
          公开链接
        </button>
        <button
          type="button"
          class="rounded-lg px-3 py-1.5 text-xs font-semibold"
          :class="importMode === 'text' ? 'bg-primary-600 text-white' : 'bg-white text-surface-600 border border-surface-200'"
          @click="importMode = 'text'"
        >
          粘贴正文 / TXT
        </button>
      </div>

      <template v-if="importMode === 'url'">
        <label for="guide-source-url" class="block text-xs font-semibold text-surface-700 mb-2">公开攻略链接</label>
        <div class="flex gap-2">
          <input
            id="guide-source-url"
            v-model="sourceUrl"
            type="url"
            inputmode="url"
            autocomplete="url"
            maxlength="2048"
            placeholder="https://example.com/travel-guide"
            required
            class="flex-1 min-w-0 h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400"
          />
          <button
            type="submit"
            :disabled="busy || submitting"
            class="inline-flex items-center justify-center gap-2 min-w-[110px] px-4 rounded-xl bg-primary-600 text-white text-sm font-semibold disabled:opacity-50"
          >
            <LoaderCircle v-if="busy || submitting" class="animate-spin" :size="15" aria-hidden="true" />
            <BookOpen v-else :size="15" aria-hidden="true" />
            导入攻略
          </button>
        </div>
        <small class="block mt-2 text-[10px] text-surface-400">
          仅支持无需登录即可访问的 HTTPS 页面；不会绕过验证码或站点访问限制。
        </small>
      </template>

      <template v-else>
        <div class="grid gap-3 sm:grid-cols-2">
          <div>
            <label for="guide-text-title" class="block text-xs font-semibold text-surface-700 mb-1.5">正文标题</label>
            <input
              id="guide-text-title"
              v-model="textTitle"
              maxlength="300"
              required
              class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm"
              placeholder="例如：广州两日游攻略"
            />
          </div>
          <div>
            <label for="guide-text-source" class="block text-xs font-semibold text-surface-700 mb-1.5">正文来源</label>
            <select
              id="guide-text-source"
              v-model="textSourceType"
              class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm"
            >
              <option value="PASTED_TEXT">普通粘贴文本</option>
              <option value="XIAOHONGSHU_SHARED_TEXT">小红书分享文本</option>
              <option value="TEXT_FILE">TXT / Markdown 文件</option>
            </select>
          </div>
        </div>
        <label for="guide-text-content" class="block text-xs font-semibold text-surface-700 mt-3 mb-1.5">攻略正文</label>
        <textarea
          id="guide-text-content"
          v-model="textContent"
          maxlength="100000"
          rows="6"
          required
          class="w-full rounded-xl border border-surface-200 bg-white px-3 py-2 text-sm leading-relaxed"
          placeholder="粘贴包含景点、地址、门票、开放时间、交通、预约或天气等内容的正文…"
        />
        <div class="mt-3 flex flex-wrap items-center justify-between gap-3">
          <label for="guide-text-file" class="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-surface-200 bg-white px-3 py-2 text-xs font-semibold text-surface-600">
            <Upload :size="14" aria-hidden="true" />导入 TXT 或 Markdown
          </label>
          <input
            id="guide-text-file"
            type="file"
            accept=".txt,.md,text/plain,text/markdown"
            class="sr-only"
            @change="loadTextFile"
          />
          <button
            type="submit"
            :disabled="busy || submitting"
            class="inline-flex min-w-[110px] items-center justify-center gap-2 rounded-xl bg-primary-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
          >
            <LoaderCircle v-if="busy || submitting" class="animate-spin" :size="15" aria-hidden="true" />
            <BookOpen v-else :size="15" aria-hidden="true" />
            识别正文
          </button>
        </div>
        <small class="mt-2 block text-[10px] text-surface-400">
          小红书仅处理你主动提供的分享正文或导出文本，不读取登录 Cookie，也不绕过平台限制。
        </small>
      </template>
      <p v-if="formError" class="mt-3 text-xs text-red-600" role="alert">{{ formError }}</p>
    </form>

    <p v-if="error" class="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700 mb-4" role="alert">{{ error }}</p>

    <p v-if="busy && guideImports.length === 0" class="text-sm text-surface-500 mb-4" role="status">正在读取攻略情报…</p>
    <div v-else-if="guideImports.length === 0" class="flex flex-col items-center gap-2 py-8 rounded-xl border-2 border-dashed border-surface-200 text-surface-400 text-center">
      <BookOpen :size="24" aria-hidden="true" />
      <strong class="text-sm text-surface-500">还没有导入攻略</strong>
      <span class="text-xs text-surface-400">导入链接或正文，系统会保留来源、原句证据和事实有效期。</span>
    </div>

    <article v-for="guide in userGuideImports" :key="guide.id" class="mt-4 rounded-xl border border-surface-200 border-l-[3px] border-l-primary-500 bg-white p-5">
      <div class="flex justify-between gap-4">
        <div>
          <h3 class="text-base font-bold text-surface-800 m-0">{{ guide.title }}</h3>
          <span class="text-[10px] text-surface-400">{{ guide.sourceHost }} · 采集于 {{ formatDateTime(guide.fetchedAt) }}</span>
        </div>
        <div class="flex items-center gap-2.5 shrink-0">
          <button
            v-if="setGuideEnabled"
            type="button"
            :disabled="busy"
            class="rounded-lg bg-amber-50 border border-amber-200 px-2.5 py-1.5 text-[10px] font-semibold text-amber-700 disabled:opacity-50"
            @click="setGuideEnabled(guide.id, !guide.enabled)"
          >
            {{ guide.enabled ? '停用来源' : '启用来源' }}
          </button>
          <a
            v-if="guide.sourceType === 'PUBLIC_GUIDE_URL' || guide.sourceType === 'CITY_INTELLIGENCE'"
            :href="guide.finalUrl"
            target="_blank"
            rel="noopener noreferrer"
            class="inline-flex items-center gap-1 text-xs font-semibold text-primary-600 hover:underline whitespace-nowrap"
          >
            {{ guide.sourceType === 'CITY_INTELLIGENCE' ? '数据说明' : '查看原文' }}<ExternalLink :size="12" aria-hidden="true" />
          </a>
          <span v-else class="rounded-lg bg-surface-100 px-2.5 py-1.5 text-[10px] font-semibold text-surface-500">用户提供正文</span>
        </div>
      </div>
      <p class="my-3 text-sm text-surface-600 leading-relaxed">{{ guide.excerpt }}</p>

      <ul v-if="guide.facts.length" class="space-y-2 m-0 p-0 list-none">
        <li v-for="fact in guide.facts" :key="fact.id" class="rounded-lg bg-surface-50 px-3 py-2.5">
          <div class="flex gap-1.5 mb-1.5">
            <span class="rounded-full bg-sky-100 px-2 py-0.5 text-[9px] font-extrabold text-sky-700">{{ categoryLabels[fact.category] }}</span>
            <span
              class="rounded-full px-2 py-0.5 text-[9px] font-extrabold"
              :class="isFresh(fact.expiresAt) ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'"
            >
              {{ isFresh(fact.expiresAt) ? '有效' : '待复核' }}
            </span>
          </div>
          <p class="text-xs text-surface-700 leading-relaxed m-0 mb-1">{{ displayStatement(fact.statement) }}</p>
          <small class="text-[10px] text-surface-400">
            置信度 {{ Math.round(fact.confidence * 100) }}% · 有效至 {{ formatDateTime(fact.expiresAt) }}
          </small>
        </li>
      </ul>
      <p v-else class="text-[10px] text-amber-700 mt-3 m-0">
        正文已保存，但没有检测到门票、地址、开放时间、交通、预约、天气等明确表达；请粘贴更完整的正文或检查文件编码。
      </p>
    </article>

    <div
      v-if="cityDetailsOpen"
      class="fixed inset-0 z-50 flex justify-end bg-surface-950/25"
      @click.self="cityDetailsOpen = false"
    >
      <aside
        class="h-full w-full max-w-lg overflow-y-auto bg-white p-6 shadow-2xl sm:p-7"
        role="dialog"
        :aria-label="`${destination}实时情报`"
        aria-modal="true"
      >
        <div class="flex items-start justify-between gap-4 border-b border-surface-100 pb-5">
          <div>
            <p class="m-0 text-xs font-semibold text-primary-600">可选查看</p>
            <h2 class="mt-1 text-xl font-bold text-surface-800">{{ destination }}实时情报</h2>
            <p class="m-0 text-sm text-surface-500">仅展示旅行决策相关的信息；坐标仅用于地图定位。</p>
          </div>
          <button
            type="button"
            class="rounded-lg p-2 text-surface-500 hover:bg-surface-100"
            aria-label="关闭实时情报"
            @click="cityDetailsOpen = false"
          ><X :size="18" aria-hidden="true" /></button>
        </div>

        <div v-if="latestCityIntelligenceImport" class="mt-6">
          <div class="flex items-center justify-between gap-3">
            <p class="m-0 text-xs text-surface-400">采集于 {{ formatDateTime(latestCityIntelligenceImport.fetchedAt) }}</p>
            <div class="flex items-center gap-2">
              <button
                v-if="setGuideEnabled"
                type="button"
                :disabled="busy"
                class="rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-xs font-semibold text-amber-700 disabled:opacity-50"
                :aria-label="latestCityIntelligenceImport.enabled ? '停用城市情报' : '启用城市情报'"
                @click="setGuideEnabled(latestCityIntelligenceImport.id, !latestCityIntelligenceImport.enabled)"
              >{{ latestCityIntelligenceImport.enabled ? '停用' : '启用' }}</button>
              <a
                :href="latestCityIntelligenceImport.finalUrl"
                target="_blank"
                rel="noopener noreferrer"
                class="inline-flex items-center gap-1 text-xs font-semibold text-primary-600 hover:underline"
              >数据来源 <ExternalLink :size="12" aria-hidden="true" /></a>
            </div>
          </div>
          <div v-if="displayPlaceCards.length" class="mt-4 space-y-3">
            <article
              v-for="place in displayPlaceCards"
              :key="place.name"
              :aria-label="place.name"
              class="rounded-2xl border border-surface-200 bg-surface-50 p-4"
            >
              <div class="flex items-start justify-between gap-3">
                <div>
                  <h3 class="m-0 text-base font-bold text-surface-800">{{ place.name }}</h3>
                  <p class="mt-1 mb-0 text-[10px] text-surface-400">更新时间：{{ formatDateTime(place.updatedAt) }}</p>
                </div>
                <span
                  class="rounded-full px-2 py-1 text-[10px] font-semibold"
                  :class="place.inItinerary ? 'bg-primary-50 text-primary-700' : 'bg-emerald-50 text-emerald-700'"
                >{{ place.inItinerary ? '行程中' : '已整理' }}</span>
              </div>

              <dl class="mt-4 grid gap-x-4 gap-y-3 text-sm sm:grid-cols-[82px_1fr]">
                <template v-if="place.itineraryDates.length">
                  <dt class="font-semibold text-surface-500">行程日期</dt>
                  <dd class="m-0 text-surface-700">{{ place.itineraryDates.join('、') }}</dd>
                </template>
                <template v-if="place.address">
                  <dt class="font-semibold text-surface-500">地点位置</dt>
                  <dd class="m-0 text-surface-700">{{ place.address }}</dd>
                </template>
                <template v-if="place.openingHours">
                  <dt class="font-semibold text-surface-500">营业时间</dt>
                  <dd class="m-0 text-surface-700">{{ place.openingHours }}</dd>
                </template>
                <template v-if="place.ticket">
                  <dt class="font-semibold text-surface-500">门票</dt>
                  <dd class="m-0 text-surface-700">{{ place.ticket }}</dd>
                </template>
                <template v-if="place.reservation">
                  <dt class="font-semibold text-surface-500">预约</dt>
                  <dd class="m-0 text-surface-700">{{ place.reservation }}</dd>
                </template>
              </dl>

              <div v-if="place.notices.length" class="mt-4 rounded-xl border border-amber-100 bg-amber-50 px-3 py-2.5">
                <p class="m-0 text-xs font-semibold text-amber-800">出行提示</p>
                <p class="mt-1 mb-0 text-xs leading-relaxed text-amber-900">{{ place.notices.join('；') }}</p>
              </div>
            </article>
          </div>
          <p v-else class="mt-4 rounded-xl bg-surface-50 px-4 py-3 text-sm text-surface-500">
            暂无可整理的地点资料；天气已移至地图上方展示。
          </p>

          <ul v-if="false" class="mt-4 space-y-3 p-0 list-none">
            <li v-for="fact in cityDisplayFacts" :key="fact.id" class="rounded-xl border border-surface-100 bg-surface-50 p-4">
              <div class="mb-2 flex items-center gap-2">
                <span class="rounded-full bg-sky-100 px-2 py-0.5 text-[10px] font-bold text-sky-700">{{ categoryLabels[fact.category] }}</span>
                <span class="text-[10px] text-surface-400">更新于 {{ formatDateTime(fact.observedAt) }}</span>
              </div>
              <p class="m-0 text-sm leading-relaxed text-surface-700">{{ displayStatement(fact.statement) }}</p>
            </li>
          </ul>
        </div>
      </aside>
    </div>
  </section>
</template>
