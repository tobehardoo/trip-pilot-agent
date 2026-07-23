<script setup lang="ts">
import { BookOpen, ExternalLink, LoaderCircle, Radar, ShieldCheck } from 'lucide-vue-next'
import { ref } from 'vue'

import type { GuideFact, GuideImport } from '../lib/api'

const props = defineProps<{
  guideImports: GuideImport[]
  busy: boolean
  error: string | null
  importGuide: (sourceUrl: string) => Promise<void>
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
  <section class="guide-panel" aria-labelledby="guide-intelligence-title">
    <header class="panel-heading">
      <div>
        <p class="eyebrow">LIVE GUIDE INTELLIGENCE</p>
        <h2 id="guide-intelligence-title"><Radar :size="20" aria-hidden="true" />攻略情报</h2>
        <p>导入公开攻略链接，提取景点、吃饭、交通、费用和预约等可追溯事实。</p>
      </div>
      <span class="scope-badge"><ShieldCheck :size="14" aria-hidden="true" />仅当前行程</span>
    </header>

    <form class="import-form" @submit.prevent="submit">
      <label for="guide-source-url">公开攻略链接</label>
      <div>
        <input
          id="guide-source-url"
          v-model="sourceUrl"
          type="url"
          inputmode="url"
          autocomplete="url"
          maxlength="2048"
          placeholder="https://example.com/travel-guide"
          required
        />
        <button type="submit" :disabled="busy || submitting">
          <LoaderCircle v-if="busy || submitting" class="spinning" :size="16" aria-hidden="true" />
          <BookOpen v-else :size="16" aria-hidden="true" />
          导入攻略
        </button>
      </div>
      <small>仅支持无需登录即可访问的 HTTPS 页面；不会绕过验证码或站点访问限制。</small>
    </form>

    <p v-if="error" class="guide-error" role="alert">{{ error }}</p>
    <p v-if="busy && guideImports.length === 0" class="guide-loading" role="status">正在读取攻略情报…</p>
    <div v-else-if="guideImports.length === 0" class="guide-empty">
      <BookOpen :size="22" aria-hidden="true" />
      <strong>还没有导入攻略</strong>
      <span>粘贴一篇公开攻略，系统会保留原文来源和事实有效期。</span>
    </div>

    <article v-for="guide in guideImports" :key="guide.id" class="guide-card">
      <header>
        <div>
          <h3>{{ guide.title }}</h3>
          <span>{{ guide.sourceHost }} · 采集于 {{ formatDateTime(guide.fetchedAt) }}</span>
        </div>
        <a :href="guide.finalUrl" target="_blank" rel="noopener noreferrer">
          查看原文<ExternalLink :size="13" aria-hidden="true" />
        </a>
      </header>
      <p class="guide-excerpt">{{ guide.excerpt }}</p>
      <ul v-if="guide.facts.length" class="fact-list">
        <li v-for="fact in guide.facts" :key="fact.id">
          <div>
            <span class="fact-category">{{ categoryLabels[fact.category] }}</span>
            <span :class="['fact-freshness', { expired: !isFresh(fact.expiresAt) }]">
              {{ isFresh(fact.expiresAt) ? '有效' : '待复核' }}
            </span>
          </div>
          <p>{{ fact.statement }}</p>
          <small>
            置信度 {{ Math.round(fact.confidence * 100) }}% ·
            有效至 {{ formatDateTime(fact.expiresAt) }}
          </small>
        </li>
      </ul>
      <p v-else class="no-facts">已保存正文，但暂未识别出支持的旅行事实。</p>
    </article>
  </section>
</template>

<style scoped>
.guide-panel {
  padding: 26px;
  background: #fff;
  border: 1px solid #dce5e1;
  border-radius: 8px;
  box-shadow: 0 5px 16px rgb(28 60 50 / 6%);
}

.panel-heading { display: flex; justify-content: space-between; gap: 24px; }
.panel-heading h2 { display: flex; align-items: center; gap: 9px; margin: 2px 0 7px; font-size: 21px; }
.panel-heading p { max-width: 650px; margin: 0; color: #60736b; font-size: 13px; line-height: 1.6; }
.eyebrow { color: #b27d13 !important; font-size: 10px !important; font-weight: 800; letter-spacing: 1.4px; }
.scope-badge { align-self: flex-start; display: flex; align-items: center; gap: 5px; padding: 6px 9px; color: #27604f; background: #e7f2ee; border-radius: 999px; font-size: 11px; font-weight: 750; white-space: nowrap; }

.import-form { margin-top: 20px; padding: 16px; background: #f4f7f6; border-radius: 6px; }
.import-form label { display: block; margin-bottom: 7px; color: #273b35; font-size: 12px; font-weight: 750; }
.import-form > div { display: flex; gap: 8px; }
.import-form input { flex: 1; min-width: 0; height: 42px; padding: 0 12px; color: #17201d; background: #fff; border: 1px solid #cad6d1; border-radius: 5px; }
.import-form button { min-width: 124px; display: inline-flex; align-items: center; justify-content: center; gap: 7px; color: #fff; background: #236552; border: 0; border-radius: 5px; font-weight: 750; cursor: pointer; }
.import-form button:disabled { opacity: .6; cursor: wait; }
.import-form small { display: block; margin-top: 8px; color: #71817b; font-size: 10px; }

.guide-error { margin: 14px 0 0; padding: 10px 12px; color: #8a3434; background: #fbecec; border-radius: 5px; font-size: 12px; }
.guide-loading, .guide-empty { margin: 18px 0 0; color: #667970; }
.guide-empty { display: grid; justify-items: center; gap: 5px; padding: 24px; background: #fafbfb; border: 1px dashed #ccd8d3; border-radius: 6px; text-align: center; }
.guide-empty strong { color: #30473f; font-size: 13px; }
.guide-empty span { font-size: 11px; }

.guide-card { margin-top: 16px; padding: 17px; border: 1px solid #dce5e1; border-left: 3px solid #d8a43b; border-radius: 6px; }
.guide-card > header { display: flex; justify-content: space-between; gap: 16px; }
.guide-card h3 { margin: 0 0 4px; color: #17201d; font-size: 15px; }
.guide-card header span { color: #71817b; font-size: 10px; }
.guide-card a { display: inline-flex; align-items: center; gap: 4px; color: #236552; font-size: 11px; font-weight: 750; text-decoration: none; white-space: nowrap; }
.guide-excerpt { margin: 12px 0; color: #53675f; font-size: 12px; line-height: 1.7; }
.fact-list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.fact-list li { padding: 11px 12px; background: #f6f8f7; border-radius: 5px; }
.fact-list li > div { display: flex; gap: 6px; }
.fact-category, .fact-freshness { padding: 3px 6px; border-radius: 999px; font-size: 9px; font-weight: 800; }
.fact-category { color: #275f78; background: #e4f0f6; }
.fact-freshness { color: #27604f; background: #dff0ea; }
.fact-freshness.expired { color: #8a5f13; background: #f7edcf; }
.fact-list p { margin: 7px 0 4px; color: #263a33; font-size: 12px; line-height: 1.55; }
.fact-list small, .no-facts { color: #71817b; font-size: 10px; }
.no-facts { margin: 10px 0 0; }
.spinning { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 680px) {
  .panel-heading, .guide-card > header { flex-direction: column; }
  .import-form > div { flex-direction: column; }
  .import-form button { min-height: 42px; }
}
</style>
