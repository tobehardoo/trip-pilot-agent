<script setup lang="ts">
import { BookOpen, ExternalLink, LoaderCircle, Radar, ShieldCheck } from 'lucide-vue-next'
import { ref } from 'vue'

import type { GuideFact, GuideImport } from '../lib/api'

const props = defineProps<{
  guideImports: GuideImport[]
  busy: boolean
  error: string | null
  importGuide: (sourceUrl: string) => Promise<void>
  setGuideEnabled?: (guideImportId: string, enabled: boolean) => Promise<void>
}>()

const sourceUrl = ref('')
const submitting = ref(false)

const categoryLabels: Record<GuideFact['category'], string> = {
  ATTRACTION: '景点',
  DINING: '吃饭',
  TRANSPORT: '交通',
  TIMING: '时间',
  COST: '费用',
  QUEUE: '排队',
  RESERVATION: '预约',
  TIP: '提示',
}

async function submit() {
  if (!sourceUrl.value || submitting.value) return
  submitting.value = true
  try {
    await props.importGuide(sourceUrl.value.trim())
    sourceUrl.value = ''
  } finally {
    submitting.value = false
  }
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
    <!-- Heading -->
    <div class="flex justify-between gap-6 mb-5">
      <div>
        <p class="text-xs font-bold uppercase tracking-widest text-primary-500 mb-1">Live Guide Intelligence</p>
        <h2 id="guide-intelligence-title" class="flex items-center gap-2.5 mt-0.5 mb-2 text-xl font-bold text-surface-800">
          <Radar :size="19" class="text-primary-500" aria-hidden="true" />攻略情报
        </h2>
        <p class="max-w-[650px] text-sm text-surface-500 m-0 leading-relaxed">导入公开攻略链接，提取景点、吃饭、交通、费用和预约等可追溯事实。</p>
      </div>
      <span class="shrink-0 inline-flex items-center gap-1.5 self-start rounded-full bg-primary-50 px-3 py-1.5 text-xs font-semibold text-primary-700">
        <ShieldCheck :size="13" aria-hidden="true" />仅当前行程
      </span>
    </div>

    <!-- Import Form -->
    <form class="rounded-xl bg-surface-50 border border-surface-200 p-4 mb-5" @submit.prevent="submit">
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
          class="flex-1 min-w-0 h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow placeholder:text-surface-300"
        />
        <button
          type="submit"
          :disabled="busy || submitting"
          class="inline-flex items-center justify-center gap-2 min-w-[110px] px-4 rounded-xl bg-primary-600 text-white text-sm font-semibold hover:bg-primary-700 active:scale-[0.97] transition-all duration-200 disabled:opacity-50 disabled:cursor-wait shadow-sm"
        >
          <LoaderCircle v-if="busy || submitting" class="animate-spin" :size="15" aria-hidden="true" />
          <BookOpen v-else :size="15" aria-hidden="true" />
          导入攻略
        </button>
      </div>
      <small class="block mt-2 text-[10px] text-surface-400">仅支持无需登录即可访问的 HTTPS 页面；不会绕过验证码或站点访问限制。</small>
    </form>

    <!-- Error -->
    <p v-if="error" class="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700 mb-4" role="alert">{{ error }}</p>

    <!-- Loading / Empty -->
    <p v-if="busy && guideImports.length === 0" class="text-sm text-surface-500 mb-4" role="status">正在读取攻略情报…</p>
    <div v-else-if="guideImports.length === 0" class="flex flex-col items-center gap-2 py-8 rounded-xl border-2 border-dashed border-surface-200 text-surface-400 text-center">
      <BookOpen :size="24" aria-hidden="true" />
      <strong class="text-sm text-surface-500">还没有导入攻略</strong>
      <span class="text-xs text-surface-400">粘贴一篇公开攻略，系统会保留原文来源和事实有效期。</span>
    </div>

    <!-- Guide Cards -->
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
            class="rounded-lg bg-amber-50 border border-amber-200 px-2.5 py-1.5 text-[10px] font-semibold text-amber-700 hover:bg-amber-100 transition-colors disabled:opacity-50"
            @click="setGuideEnabled(guide.id, !guide.enabled)"
          >
            {{ guide.enabled ? '停用来源' : '启用来源' }}
          </button>
          <a :href="guide.finalUrl" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-1 text-xs font-semibold text-primary-600 hover:text-primary-700 hover:underline whitespace-nowrap">
            查看原文<ExternalLink :size="12" aria-hidden="true" />
          </a>
        </div>
      </div>
      <p class="my-3 text-sm text-surface-600 leading-relaxed">{{ guide.excerpt }}</p>

      <!-- Facts -->
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
      <p v-else class="text-[10px] text-surface-400 mt-3 m-0">已保存正文，但暂未识别出支持的旅行事实。</p>
    </article>
  </section>
</template>
