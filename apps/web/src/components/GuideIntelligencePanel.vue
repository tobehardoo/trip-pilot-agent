<script setup lang="ts">
import {
  BookOpen,
  ChevronRight,
  ExternalLink,
  ImageIcon,
  LoaderCircle,
  Radar,
  ShieldCheck,
  Trash2,
  Upload,
} from 'lucide-vue-next'
import { computed, ref } from 'vue'

import { ApiError, type GuideFact, type GuideImport, type GuideImportInput, type Itinerary } from '../lib/api'
import Drawer from './ui/Drawer.vue'

type CoverageLevel = 'GOOD' | 'THIN' | 'NONE'

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

const IMAGE_MIME_TYPES = ['image/png', 'image/jpeg', 'image/webp'] as const
const MAX_IMAGE_FILES = 5
const MAX_IMAGE_BYTES = 5_000_000
const MAX_IMAGE_TOTAL_BYTES = 15_000_000

interface PendingImage {
  id: string
  fileName: string
  contentType: string
  size: number
  dataUrl: string
}

const importMode = ref<'url' | 'text' | 'image'>('url')
const sourceUrl = ref('')
const textSourceType = ref<'PASTED_TEXT' | 'TEXT_FILE' | 'XIAOHONGSHU_SHARED_TEXT'>(
  'PASTED_TEXT',
)
const textTitle = ref('')
const textContent = ref('')
const formError = ref<string | null>(null)
const submitting = ref(false)
const cityDetailsOpen = ref(false)
const pendingImages = ref<PendingImage[]>([])
const imageNotice = ref<string | null>(null)
const draggingOver = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

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
const guideCoverage = computed<CoverageLevel>(() => {
  const enabledCount = props.guideImports.filter((g) => g.enabled).length
  if (enabledCount >= 2) return 'GOOD'
  if (enabledCount === 1) return 'THIN'
  return 'NONE'
})
const cityFacts = computed(() => activeCityIntelligenceImport.value?.facts ?? [])
const cityDisplayFacts = computed(() => cityFacts.value.filter((fact) => fact.category !== 'WEATHER'))

interface CityPlaceCard {
  name: string
  updatedAt: string
  address: string | null
  openingHours: string | null
  /** 营业时间是否来自仍有效的（未过期）事实；false = 无来源或来源待复核。 */
  openingHoursFresh: boolean
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
        openingHoursFresh: false,
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
      const opening = extractValue(statement, /(?:营业信息|营业时间|开放时间)[：:]?\s*([^；;。]+)/)
      if (opening && current.openingHours == null) {
        current.openingHours = opening
        // 营业时间来源仍有效 → 视为已核验；过期 → 待复核。
        current.openingHoursFresh = isFresh(fact.expiresAt)
      }
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
        openingHoursFresh: intelligence?.openingHoursFresh ?? false,
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
  let input: GuideImportInput
  if (importMode.value === 'url') {
    input = { sourceType: 'PUBLIC_GUIDE_URL', sourceUrl: sourceUrl.value.trim() }
  } else if (importMode.value === 'image') {
    if (pendingImages.value.length === 0) return
    input = {
      sourceType: 'IMAGE_OCR',
      images: pendingImages.value.map((image) => ({
        dataBase64: image.dataUrl.slice(image.dataUrl.indexOf(',') + 1),
        fileName: image.fileName,
        contentType: image.contentType,
      })),
    }
  } else {
    input = {
      sourceType: textSourceType.value,
      title: textTitle.value.trim(),
      content: textContent.value.trim(),
    }
  }
  if (
    ('sourceUrl' in input && !input.sourceUrl)
    || ('content' in input && (!input.title || !input.content))
    || ('images' in input && input.images.length === 0)
  ) return

  submitting.value = true
  formError.value = null
  try {
    await props.importGuide(input)
    if (importMode.value === 'url') {
      sourceUrl.value = ''
    } else if (importMode.value === 'image') {
      pendingImages.value = []
      imageNotice.value = null
    } else {
      textTitle.value = ''
      textContent.value = ''
      textSourceType.value = 'PASTED_TEXT'
    }
  } catch (cause) {
    formError.value = guideImportErrorText(cause)
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
  } catch (cause) {
    formError.value = guideImportErrorText(cause)
  } finally {
    submitting.value = false
  }
}

function guideImportErrorText(cause: unknown): string {
  if (!(cause instanceof ApiError)) {
    return '天气或攻略同步失败，请稍后重试'
  }
  switch (cause.code) {
    case 'GUIDE_OCR_NOT_CONFIGURED':
      return '图片识别未配置：服务端尚未启用视觉识别模型，可先使用粘贴正文导入。'
    case 'GUIDE_OCR_TIMEOUT':
      return '图片识别超时：请减少图片数量后重试，或改用粘贴正文。'
    case 'GUIDE_OCR_FAILED':
      return '未能从图片中识别出可用文字：请确认截图清晰并包含攻略正文。'
    case 'GUIDE_IMAGE_INVALID':
      return '图片不符合要求：仅支持 PNG、JPEG、WEBP，单张不超过 5 MB、一次不超过 5 张。'
    case 'GUIDE_SERVICE_UNAVAILABLE':
      return '攻略服务暂时不可用，请稍后重试'
    case 'GUIDE_IMPORT_REJECTED':
      return '攻略导入被拒绝，请检查链接或内容后重试'
    default:
      return '天气或攻略同步失败，请稍后重试'
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

let imageSequence = 0

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(new Error(`failed to read ${file.name}`))
    reader.readAsDataURL(file)
  })
}

function totalImageBytes() {
  return pendingImages.value.reduce((sum, image) => sum + image.size, 0)
}

async function addImages(files: Iterable<File>) {
  imageNotice.value = null
  for (const file of files) {
    if (pendingImages.value.length >= MAX_IMAGE_FILES) {
      imageNotice.value = `一次最多导入 ${MAX_IMAGE_FILES} 张图片。`
      break
    }
    const isSupportedMime = (IMAGE_MIME_TYPES as readonly string[]).includes(file.type)
    if (!isSupportedMime) {
      imageNotice.value = `「${file.name}」不是支持的格式，仅支持 PNG、JPEG 或 WEBP 图片。`
      continue
    }
    if (file.size > MAX_IMAGE_BYTES) {
      imageNotice.value = `「${file.name}」超过 ${MAX_IMAGE_BYTES / 1_000_000} MB 上限，请压缩后重试。`
      continue
    }
    if (
      pendingImages.value.some(
        (image) =>
          image.fileName === file.name
          && image.size === file.size,
      )
    ) {
      continue
    }
    if (totalImageBytes() + file.size > MAX_IMAGE_TOTAL_BYTES) {
      imageNotice.value = `图片总大小不能超过 ${MAX_IMAGE_TOTAL_BYTES / 1_000_000} MB，请减少数量或压缩截图。`
      break
    }
    try {
      const dataUrl = await readAsDataUrl(file)
      imageSequence += 1
      pendingImages.value = [
        ...pendingImages.value,
        {
          id: `image-${imageSequence}`,
          fileName: file.name || `截图 ${imageSequence}`,
          contentType: file.type || 'image/png',
          size: file.size,
          dataUrl,
        },
      ]
    } catch {
      imageNotice.value = `「${file.name}」读取失败，请重新选择。`
    }
  }
}

function onImageFilesSelected(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files?.length) {
    void addImages(Array.from(input.files))
  }
  input.value = ''
}

function removeImage(id: string) {
  pendingImages.value = pendingImages.value.filter((image) => image.id !== id)
  imageNotice.value = null
}

function onDrop(event: DragEvent) {
  draggingOver.value = false
  const files = Array.from(event.dataTransfer?.files ?? [])
  if (files.length) void addImages(files)
}

function onPaste(event: ClipboardEvent) {
  const files = Array.from(event.clipboardData?.files ?? [])
  if (files.length) {
    event.preventDefault()
    void addImages(files)
  }
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'Asia/Shanghai',
  }).format(new Date(value))
}

function qualityBadgeClass(score: number) {
  if (score >= 80) return 'bg-tp-ok/15 text-tp-ok'
  if (score >= 60) return 'bg-tp-warn/10 text-tp-warn'
  return 'bg-tp-panel text-tp-sub'
}

function qualityTooltip(q: { overall: number; label: string; dimensions: { factDensity: number; categoryCoverage: number; strongFactRatio: number; conflictRate: number; freshnessHealth: number } }) {
  const d = q.dimensions
  return `事实密度 ${d.factDensity} · 类别覆盖 ${d.categoryCoverage} · 强事实 ${d.strongFactRatio} · 冲突率 ${d.conflictRate} · 时效 ${d.freshnessHealth}`
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
  <section class="space-y-4" aria-labelledby="guide-intelligence-title">
    <div class="flex justify-between gap-6 mb-5">
      <div>
        <p class="text-xs font-bold tracking-widest text-tp-mute mb-1">实时攻略信息</p>
        <h2 id="guide-intelligence-title" class="flex items-center gap-2.5 mt-0.5 mb-2 text-xl font-bold text-tp-ink">
          <Radar :size="19" class="text-tp-mute" aria-hidden="true" />攻略情报
        </h2>
        <p class="max-w-[650px] text-sm text-tp-sub m-0 leading-relaxed">
          导入公开链接、粘贴正文、TXT/Markdown、小红书分享文本或攻略截图，提取带原句证据的旅行事实。
        </p>
      </div>
      <span class="shrink-0 inline-flex items-center gap-1.5 self-start rounded-full bg-tp-panel px-3 py-1.5 text-xs font-semibold text-tp-sub">
        <ShieldCheck :size="13" aria-hidden="true" />仅当前行程
      </span>
    </div>

    <div class="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-tp-line bg-tp-active px-4 py-3">
      <p class="m-0 text-xs leading-relaxed text-tp-ink">
        同步 {{ destination }} 当前天气、行程日期预报、营业与预约信息；同步结果会进入下一次 Agent 规划快照。
      </p>
      <button
        type="button"
        :disabled="busy || submitting"
        class="shrink-0 rounded-lg bg-tp-ink px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"
        @click="syncCityIntelligence"
      >
        {{ busy || submitting ? '同步中…' : '同步城市情报' }}
      </button>
    </div>

    <section
      v-if="latestCityIntelligenceImport"
      class="mb-5 rounded-xl border border-tp-line bg-tp-panel px-4 py-3"
      aria-labelledby="city-intelligence-summary-title"
    >
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p class="m-0 text-xs font-semibold text-tp-ink">出行提醒</p>
          <h3 id="city-intelligence-summary-title" class="mt-1 text-sm font-bold text-tp-ink">
            {{ latestCityIntelligenceImport.enabled
              ? `${destination} 已整理 ${displayPlaceCards.length} 个地点的出行资料`
              : `${destination} 城市情报已停用` }}
          </h3>
          <!--
          <h3 v-if="false" aria-hidden="true">
            {{ cityWeather ? displayStatement(cityWeather.statement) : `${destination} 已同步 ${cityDisplayFacts.length} 条实时资料` }}
          </h3>
          -->
          <p v-if="false" class="m-0 text-xs text-tp-sub">
            已整理 {{ cityDisplayFacts.length }} 条天气、营业与地点动态，仅在需要时查看详情。
          </p>
        </div>
        <button
          type="button"
          class="inline-flex shrink-0 items-center gap-1 rounded-lg bg-white px-3 py-2 text-xs font-semibold text-tp-ink shadow-sm ring-1 ring-tp-line"
          aria-label="查看实时情报"
          @click="cityDetailsOpen = true"
        >
          查看实时情报 <ChevronRight :size="14" aria-hidden="true" />
        </button>
      </div>
    </section>

    <form class="rounded-xl bg-tp-panel border border-tp-line p-4 mb-5" @submit.prevent="submit">
      <div class="flex gap-2 mb-4" role="group" aria-label="攻略导入方式">
        <button
          type="button"
          class="rounded-lg px-3 py-1.5 text-xs font-semibold"
          :class="importMode === 'url' ? 'bg-tp-ink text-white' : 'bg-white text-tp-body border border-tp-line'"
          @click="importMode = 'url'"
        >
          公开链接
        </button>
        <button
          type="button"
          class="rounded-lg px-3 py-1.5 text-xs font-semibold"
          :class="importMode === 'text' ? 'bg-tp-ink text-white' : 'bg-white text-tp-body border border-tp-line'"
          @click="importMode = 'text'"
        >
          粘贴正文 / TXT
        </button>
        <button
          type="button"
          class="rounded-lg px-3 py-1.5 text-xs font-semibold"
          :class="importMode === 'image' ? 'bg-tp-ink text-white' : 'bg-white text-tp-body border border-tp-line'"
          @click="importMode = 'image'"
        >
          图片截图
        </button>
      </div>

      <template v-if="importMode === 'url'">
        <label for="guide-source-url" class="block text-xs font-semibold text-tp-body mb-2">公开攻略链接</label>
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
            class="flex-1 min-w-0 h-10 rounded-xl border border-tp-line bg-white px-3 text-sm text-tp-ink outline-0 focus:border-tp-sub"
          />
          <button
            type="submit"
            :disabled="busy || submitting"
            class="inline-flex items-center justify-center gap-2 min-w-[110px] px-4 rounded-xl bg-tp-ink text-white text-sm font-semibold disabled:opacity-50"
          >
            <LoaderCircle v-if="busy || submitting" class="animate-spin" :size="15" aria-hidden="true" />
            <BookOpen v-else :size="15" aria-hidden="true" />
            导入攻略
          </button>
        </div>
        <small class="block mt-2 text-[10px] text-tp-sub">
          仅支持无需登录即可访问的 HTTPS 静态页面；动态渲染、登录墙或反爬限制的页面（如小红书、公众号正文）无法直接抓取，建议复制正文粘贴，或在“图片截图”页上传页面截图。
        </small>
      </template>

      <template v-else-if="importMode === 'image'">
        <div
          class="rounded-xl border-2 border-dashed px-4 py-6 text-center cursor-pointer transition-colors"
          :class="draggingOver
            ? 'border-tp-active bg-tp-panel'
            : 'border-tp-line bg-white hover:border-tp-line'"
          role="button"
          tabindex="0"
          aria-label="添加攻略截图：点击选择、拖拽图片到此处，或聚焦后按 Ctrl+V 粘贴剪贴板截图"
          @click="fileInput?.click()"
          @keydown.enter.prevent="fileInput?.click()"
          @keydown.space.prevent="fileInput?.click()"
          @dragover.prevent="draggingOver = true"
          @dragleave.prevent="draggingOver = false"
          @drop.prevent="onDrop"
          @paste="onPaste"
        >
          <ImageIcon :size="22" class="mx-auto text-tp-mute" aria-hidden="true" />
          <p class="mt-2 mb-0 text-sm font-semibold text-tp-body">
            拖拽攻略截图到这里，点击选择，或粘贴剪贴板截图
          </p>
          <small class="mt-1 block text-[10px] text-tp-sub">
            支持 PNG / JPEG / WEBP；最多 {{ MAX_IMAGE_FILES }} 张，单张不超过
            {{ MAX_IMAGE_BYTES / 1_000_000 }} MB。
          </small>
        </div>
        <input
          ref="fileInput"
          type="file"
          accept="image/png,image/jpeg,image/webp"
          multiple
          class="sr-only"
          :aria-label="'选择攻略截图文件'"
          @change="onImageFilesSelected"
        />

        <ul
          v-if="pendingImages.length"
          class="mt-3 flex flex-wrap gap-3 p-0 m-0 list-none"
          aria-label="待识别的攻略截图"
        >
          <li
            v-for="image in pendingImages"
            :key="image.id"
            class="relative rounded-xl border border-tp-line bg-white overflow-hidden w-[104px]"
          >
            <img
              :src="image.dataUrl"
              :alt="`预览：${image.fileName}`"
              class="h-[72px] w-full object-cover"
            />
            <p class="m-0 px-2 py-1 text-[9px] text-tp-sub truncate">{{ image.fileName }}</p>
            <button
              type="button"
              class="absolute top-1 right-1 rounded-full bg-tp-ink/60 p-1 text-white hover:bg-tp-ink/80"
              :aria-label="`删除图片 ${image.fileName}`"
              @click.stop="removeImage(image.id)"
            >
              <Trash2 :size="12" aria-hidden="true" />
            </button>
          </li>
        </ul>

        <p
          v-if="imageNotice"
          class="mt-3 mb-0 text-xs text-tp-warn"
          role="alert"
        >{{ imageNotice }}</p>

        <div class="mt-3 flex flex-wrap items-center justify-between gap-3">
          <small class="text-[10px] text-tp-sub max-w-[420px] leading-relaxed">
            图片仅用于识别文字，原图不会被保存；识别结果与粘贴正文走同一事实校验链路。服务端未配置视觉模型时会明确提示。
          </small>
          <button
            type="submit"
            :disabled="busy || submitting || pendingImages.length === 0"
            class="inline-flex min-w-[110px] items-center justify-center gap-2 rounded-xl bg-tp-ink px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
          >
            <LoaderCircle v-if="busy || submitting" class="animate-spin" :size="15" aria-hidden="true" />
            <BookOpen v-else :size="15" aria-hidden="true" />
            识别图片文字
          </button>
        </div>
      </template>

      <template v-else>
        <div class="grid gap-3 sm:grid-cols-2">
          <div>
            <label for="guide-text-title" class="block text-xs font-semibold text-tp-body mb-1.5">正文标题</label>
            <input
              id="guide-text-title"
              v-model="textTitle"
              maxlength="300"
              required
              class="w-full h-10 rounded-xl border border-tp-line bg-white px-3 text-sm"
              placeholder="例如：广州两日游攻略"
            />
          </div>
          <div>
            <label for="guide-text-source" class="block text-xs font-semibold text-tp-body mb-1.5">正文来源</label>
            <select
              id="guide-text-source"
              v-model="textSourceType"
              class="w-full h-10 rounded-xl border border-tp-line bg-white px-3 text-sm"
            >
              <option value="PASTED_TEXT">普通粘贴文本</option>
              <option value="XIAOHONGSHU_SHARED_TEXT">小红书分享文本</option>
              <option value="TEXT_FILE">TXT / Markdown 文件</option>
            </select>
          </div>
        </div>
        <label for="guide-text-content" class="block text-xs font-semibold text-tp-body mt-3 mb-1.5">攻略正文</label>
        <textarea
          id="guide-text-content"
          v-model="textContent"
          maxlength="100000"
          rows="6"
          required
          class="w-full rounded-xl border border-tp-line bg-white px-3 py-2 text-sm leading-relaxed"
          placeholder="粘贴包含景点、地址、门票、开放时间、交通、预约或天气等内容的正文…"
        />
        <div class="mt-3 flex flex-wrap items-center justify-between gap-3">
          <label for="guide-text-file" class="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-tp-line bg-white px-3 py-2 text-xs font-semibold text-tp-body">
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
            class="inline-flex min-w-[110px] items-center justify-center gap-2 rounded-xl bg-tp-ink px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
          >
            <LoaderCircle v-if="busy || submitting" class="animate-spin" :size="15" aria-hidden="true" />
            <BookOpen v-else :size="15" aria-hidden="true" />
            识别正文
          </button>
        </div>
        <small class="mt-2 block text-[10px] text-tp-sub">
          小红书仅处理你主动提供的分享正文或导出文本，不读取登录 Cookie，也不绕过平台限制。
        </small>
      </template>
      <p v-if="formError" class="mt-3 text-xs text-tp-warn" role="alert">{{ formError }}</p>
    </form>

    <p v-if="error" class="rounded-xl bg-tp-warn/10 px-4 py-3 text-sm text-tp-warn mb-4" role="alert">{{ error }}</p>

    <p v-if="busy && guideImports.length === 0" class="text-sm text-tp-sub mb-4" role="status">正在读取攻略情报…</p>
    <div v-else-if="guideImports.length === 0" class="flex flex-col items-center gap-2 py-8 rounded-xl border-2 border-dashed border-tp-line text-tp-sub text-center">
      <BookOpen :size="24" aria-hidden="true" />
      <strong class="text-sm text-tp-sub">还没有导入攻略</strong>
      <span class="text-xs text-tp-sub">导入链接或正文，系统会保留来源、原句证据和事实有效期。</span>
      <p class="mt-2 max-w-xs rounded-lg bg-tp-warn/10 px-3 py-2 text-[11px] text-tp-warn">
        当前城市「{{ destination }}」尚无攻略数据，行程推荐完全基于地图 POI 数据。建议导入官方文旅网站链接或旅行攻略文本。
      </p>
    </div>

    <p
      v-if="guideCoverage === 'THIN' && guideImports.length > 0"
      class="mb-4 rounded-lg bg-tp-warn/10 px-4 py-2.5 text-xs text-tp-warn"
      role="status"
    >
      当前城市「{{ destination }}」攻略数据较少（{{ guideImports.filter(g => g.enabled).length }} 个来源），部分推荐基于地图 POI 数据。
    </p>

    <article v-for="guide in userGuideImports" :key="guide.id" class="mt-4 rounded-xl border border-tp-line border-l-[3px] border-l-tp-ink bg-white p-5">
      <div class="flex justify-between gap-4">
        <div>
          <h3 class="text-base font-bold text-tp-ink m-0">{{ guide.title }}</h3>
          <span class="text-[10px] text-tp-sub">
            {{ guide.sourceHost }} · 采集于 {{ formatDateTime(guide.fetchedAt) }}
            <span
              v-if="guide.quality"
              class="ml-1.5 inline-flex items-center gap-1 rounded-full px-1.5 py-px text-[10px] font-semibold"
              :class="qualityBadgeClass(guide.quality.overall)"
              :title="qualityTooltip(guide.quality)"
            >{{ guide.quality.label }} {{ guide.quality.overall }}</span>
          </span>
        </div>
        <div class="flex items-center gap-2.5 shrink-0">
          <button
            v-if="setGuideEnabled"
            type="button"
            :disabled="busy"
            class="rounded-lg bg-tp-warn/10 border border-tp-warn/25 px-2.5 py-1.5 text-[10px] font-semibold text-tp-warn disabled:opacity-50"
            @click="setGuideEnabled(guide.id, !guide.enabled)"
          >
            {{ guide.enabled ? '停用来源' : '启用来源' }}
          </button>
          <a
            v-if="guide.sourceType === 'PUBLIC_GUIDE_URL' || guide.sourceType === 'CITY_INTELLIGENCE'"
            :href="guide.finalUrl"
            target="_blank"
            rel="noopener noreferrer"
            class="inline-flex items-center gap-1 text-xs font-semibold text-tp-ink hover:underline whitespace-nowrap"
          >
            {{ guide.sourceType === 'CITY_INTELLIGENCE' ? '数据说明' : '查看原文' }}<ExternalLink :size="12" aria-hidden="true" />
          </a>
          <span v-else class="rounded-lg bg-tp-panel px-2.5 py-1.5 text-[10px] font-semibold text-tp-sub">用户提供正文</span>
        </div>
      </div>
      <p class="my-3 text-sm text-tp-body leading-relaxed">{{ guide.excerpt }}</p>

      <ul v-if="guide.facts.length" class="space-y-2 m-0 p-0 list-none">
        <li v-for="fact in guide.facts" :key="fact.id" class="rounded-lg bg-tp-panel px-3 py-2.5">
          <div class="flex gap-1.5 mb-1.5">
            <span class="rounded-full bg-tp-active px-2 py-0.5 text-[9px] font-extrabold text-tp-ink">{{ categoryLabels[fact.category] }}</span>
            <span
              class="rounded-full px-2 py-0.5 text-[9px] font-extrabold"
              :class="isFresh(fact.expiresAt) ? 'bg-tp-ok/15 text-tp-ok' : 'bg-tp-warn/10 text-tp-warn'"
            >
              {{ isFresh(fact.expiresAt) ? '有效' : '待复核' }}
            </span>
          </div>
          <p class="text-xs text-tp-body leading-relaxed m-0 mb-1">{{ displayStatement(fact.statement) }}</p>
          <small class="text-[10px] text-tp-sub">
            置信度 {{ Math.round(fact.confidence * 100) }}% · 有效至 {{ formatDateTime(fact.expiresAt) }}
          </small>
        </li>
      </ul>
      <p v-else class="text-[10px] text-tp-warn mt-3 m-0">
        正文已保存，但没有检测到门票、地址、开放时间、交通、预约、天气等明确表达；请粘贴更完整的正文或检查文件编码。
      </p>
    </article>

    <Drawer
      :open="cityDetailsOpen"
      :title="`${destination}实时情报`"
      description="仅展示旅行决策相关的信息；坐标仅用于地图定位。"
      width="lg"
      @close="cityDetailsOpen = false"
    >
      <div v-if="latestCityIntelligenceImport">
        <div class="flex items-center justify-between gap-3">
          <p class="m-0 text-xs text-tp-sub">采集于 {{ formatDateTime(latestCityIntelligenceImport.fetchedAt) }}</p>
          <div class="flex items-center gap-2">
            <button
              v-if="setGuideEnabled"
              type="button"
              :disabled="busy"
              class="rounded-lg border border-tp-warn/25 bg-tp-warn/10 px-2.5 py-1.5 text-xs font-semibold text-tp-warn disabled:opacity-50"
              :aria-label="latestCityIntelligenceImport.enabled ? '停用城市情报' : '启用城市情报'"
              @click="setGuideEnabled(latestCityIntelligenceImport.id, !latestCityIntelligenceImport.enabled)"
            >{{ latestCityIntelligenceImport.enabled ? '停用' : '启用' }}</button>
            <a
              :href="latestCityIntelligenceImport.finalUrl"
              target="_blank"
              rel="noopener noreferrer"
              class="inline-flex items-center gap-1 text-xs font-semibold text-tp-ink hover:underline"
            >数据来源 <ExternalLink :size="12" aria-hidden="true" /></a>
          </div>
        </div>
        <div v-if="displayPlaceCards.length" class="mt-4 space-y-3">
          <article
            v-for="place in displayPlaceCards"
            :key="place.name"
            :aria-label="place.name"
            class="rounded-2xl border border-tp-line bg-tp-panel p-4"
          >
            <div class="flex items-start justify-between gap-3">
              <div>
                <h3 class="m-0 text-base font-bold text-tp-ink">{{ place.name }}</h3>
                <p class="mt-1 mb-0 text-[10px] text-tp-sub">更新时间：{{ formatDateTime(place.updatedAt) }}</p>
              </div>
              <span
                class="rounded-full px-2 py-1 text-[10px] font-semibold"
                :class="place.inItinerary ? 'bg-tp-panel text-tp-ink' : 'bg-tp-ok/15 text-tp-ok'"
              >{{ place.inItinerary ? '行程中' : '已整理' }}</span>
            </div>

            <dl class="mt-4 grid gap-x-4 gap-y-3 text-sm sm:grid-cols-[82px_1fr]">
              <template v-if="place.itineraryDates.length">
                <dt class="font-semibold text-tp-sub">行程日期</dt>
                <dd class="m-0 text-tp-body">{{ place.itineraryDates.join('、') }}</dd>
              </template>
              <template v-if="place.address">
                <dt class="font-semibold text-tp-sub">地点位置</dt>
                <dd class="m-0 text-tp-body">{{ place.address }}</dd>
              </template>
              <template v-if="place.openingHours">
                <dt class="font-semibold text-tp-sub">营业时间</dt>
                <dd class="m-0 text-tp-body">
                  <span>{{ place.openingHours }}</span>
                  <span
                    class="ml-1.5 inline-flex items-center rounded-full px-1.5 py-px text-[9px] font-bold"
                    :class="place.openingHoursFresh
                      ? 'bg-tp-ok/15 text-tp-ok'
                      : 'bg-tp-warn/10 text-tp-warn'"
                    data-testid="opening-hours-status"
                  >{{ place.openingHoursFresh ? '已核验' : '待复核' }}</span>
                </dd>
              </template>
              <template v-else-if="place.inItinerary">
                <dt class="font-semibold text-tp-sub">营业时间</dt>
                <dd class="m-0 text-tp-warn" data-testid="opening-hours-unverified">
                  暂未核验，请出发前通过官方渠道确认
                </dd>
              </template>
              <template v-if="place.ticket">
                <dt class="font-semibold text-tp-sub">门票</dt>
                <dd class="m-0 text-tp-body">{{ place.ticket }}</dd>
              </template>
              <template v-if="place.reservation">
                <dt class="font-semibold text-tp-sub">预约</dt>
                <dd class="m-0 text-tp-body">{{ place.reservation }}</dd>
              </template>
            </dl>

            <div v-if="place.notices.length" class="mt-4 rounded-xl border border-tp-warn/25 bg-tp-warn/10 px-3 py-2.5">
              <p class="m-0 text-xs font-semibold text-tp-warn">出行提示</p>
              <p class="mt-1 mb-0 text-xs leading-relaxed text-tp-warn">{{ place.notices.join('；') }}</p>
            </div>
          </article>
        </div>
        <p v-else class="mt-4 rounded-xl bg-tp-panel px-4 py-3 text-sm text-tp-sub">
          暂无可整理的地点资料；天气已移至地图上方展示。
        </p>
      </div>
    </Drawer>
  </section>
</template>
