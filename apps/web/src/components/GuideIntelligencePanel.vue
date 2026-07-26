<script setup lang="ts">
import {
  BookOpen,
  ExternalLink,
  LoaderCircle,
  Radar,
  ShieldCheck,
  Upload,
} from 'lucide-vue-next'
import { ref } from 'vue'

import type { GuideFact, GuideImport, GuideImportInput } from '../lib/api'

const props = defineProps<{
  guideImports: GuideImport[]
  destination: string
  startDate: string
  endDate: string
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
        同步 {{ destination }} 当前天气、行程日期预报，以及景点地址、坐标、参考消费和营业信息；同步结果会进入下一次 Agent 规划快照。
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

    <article v-for="guide in guideImports" :key="guide.id" class="mt-4 rounded-xl border border-surface-200 border-l-[3px] border-l-primary-500 bg-white p-5">
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
          <p class="text-xs text-surface-700 leading-relaxed m-0 mb-1">{{ fact.statement }}</p>
          <small class="text-[10px] text-surface-400">
            置信度 {{ Math.round(fact.confidence * 100) }}% · 有效至 {{ formatDateTime(fact.expiresAt) }}
          </small>
        </li>
      </ul>
      <p v-else class="text-[10px] text-amber-700 mt-3 m-0">
        正文已保存，但没有检测到门票、地址、开放时间、交通、预约、天气等明确表达；请粘贴更完整的正文或检查文件编码。
      </p>
    </article>
  </section>
</template>
