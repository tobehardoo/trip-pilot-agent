<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChevronDown, Info, ShieldCheck, X } from 'lucide-vue-next'

import type { ItineraryFactImpact } from '../lib/api'
import { aggregateFactImpacts, summarizeFactStatus } from '../lib/fact-status-presentation'
import Badge from './ui/Badge.vue'
import Button from './ui/Button.vue'
import Card from './ui/Card.vue'

const props = defineProps<{
  facts: ItineraryFactImpact[]
}>()

const open = ref(false)
const showDiagnostics = ref(false)

const summary = computed(() => summarizeFactStatus(props.facts))
const groups = computed(() => aggregateFactImpacts(props.facts))

const CATEGORY_LABELS: Record<string, string> = {
  OPENING_HOURS: '营业时间',
  WEATHER: '天气',
  ROUTE: '路线',
}

const categoryLabel = (category: string) => CATEGORY_LABELS[category] ?? category

/** 用户层状态行：每组一个摘要，标注是否有待确认项。 */
const statusRows = computed(() =>
  groups.value.map((group) => {
    const hasIssue = group.items.some((f) => f.stale || f.conflicted || f.refreshFailed)
    return {
      category: group.category,
      label: categoryLabel(group.category),
      count: group.count,
      healthy: !hasIssue,
    }
  }),
)

function formatCheckedAt(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function issueFlags(f: ItineraryFactImpact): string[] {
  const flags: string[] = []
  if (f.stale) flags.push('已过期')
  if (f.conflicted) flags.push('来源冲突')
  if (f.refreshFailed) flags.push('刷新失败降级')
  return flags
}
</script>

<template>
  <Card class="data-status-card" aria-label="数据状态">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0 flex-1">
        <h3 class="text-base font-semibold text-surface-800">数据状态</h3>
        <template v-if="!facts.length">
          <p class="mt-1 text-sm text-surface-400">暂无规划数据</p>
        </template>
        <template v-else>
          <p class="mt-1 flex items-center gap-1.5 text-sm font-semibold" :class="summary.allHealthy ? 'text-emerald-700' : 'text-amber-700'">
            <ShieldCheck v-if="summary.allHealthy" :size="15" aria-hidden="true" />
            <Info v-else :size="15" aria-hidden="true" />
            {{ summary.allHealthy ? '真实数据 ✓' : `数据基本完整，${summary.issueCount} 项待确认` }}
          </p>
          <p class="mt-0.5 text-sm text-surface-500">
            {{ summary.allHealthy ? '核心路线、地点和规划数据已获取。' : '大部分核心数据已获取，部分辅助信息待确认。' }}
          </p>
          <!-- A 类：真正影响用户的异常 -> 主动提醒 + 行动建议（用户语言，无内部字段） -->
          <ul v-if="summary.issues.length" class="mt-2 space-y-1.5">
            <li v-for="(issue, i) in summary.issues" :key="i" class="flex items-start gap-2 text-sm">
              <span class="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" aria-hidden="true" />
              <span>
                <span class="font-medium text-amber-800">{{ issue.message }}</span>
                <span class="block text-surface-500">{{ issue.action }}</span>
              </span>
            </li>
          </ul>
        </template>
      </div>
      <Button v-if="facts.length" variant="outline" size="sm" data-testid="open-data-explainer" @click="open = true">
        查看数据说明
      </Button>
    </div>

    <!-- 数据说明 Drawer -->
    <Teleport to="body">
      <div v-if="open" class="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="数据说明">
        <div class="fixed inset-0 bg-surface-900/30 backdrop-blur-sm" @click="open = false" />
        <div class="absolute right-0 top-0 flex h-full w-full max-w-md flex-col bg-white shadow-dialog">
          <header class="flex items-center justify-between gap-3 border-b border-surface-100 px-6 py-4">
            <h2 class="m-0 text-lg font-bold text-surface-800">数据说明</h2>
            <button type="button" class="rounded-lg p-1.5 text-surface-400 hover:bg-surface-100 hover:text-surface-700" aria-label="关闭数据说明" @click="open = false">
              <X :size="18" aria-hidden="true" />
            </button>
          </header>

          <div class="flex-1 overflow-y-auto px-6 py-5">
            <!-- 用户层：按类别摘要 -->
            <section aria-label="数据状态摘要">
              <h3 class="mb-2 text-sm font-semibold text-surface-600">数据状态摘要</h3>
              <ul class="space-y-2">
                <li v-for="row in statusRows" :key="row.category" class="flex items-center justify-between gap-3 rounded-xl bg-surface-50 px-4 py-2.5 text-sm">
                  <span class="font-medium text-surface-700">{{ row.label }}</span>
                  <span :class="row.healthy ? 'text-emerald-700' : 'text-amber-700'">
                    {{ row.healthy ? '✓ 已获取' : '⚠ 待确认' }}
                    <span v-if="row.count > 1" class="text-xs text-surface-400">（{{ row.count }} 项）</span>
                  </span>
                </li>
              </ul>
            </section>

            <!-- 高级诊断（默认折叠；保留 Provider/source/fallback/UNKNOWN/evidence 全部事实） -->
            <section class="mt-6">
              <button
                type="button"
                class="flex w-full items-center justify-between rounded-xl border border-surface-200 px-4 py-2.5 text-sm font-medium text-surface-600 hover:bg-surface-50"
                :aria-expanded="showDiagnostics"
                data-testid="toggle-diagnostics"
                @click="showDiagnostics = !showDiagnostics"
              >
                高级诊断
                <ChevronDown :size="15" aria-hidden="true" :class="showDiagnostics ? 'rotate-180' : ''" />
              </button>
              <div v-if="showDiagnostics" class="mt-3 space-y-3" data-testid="diagnostics-content">
                <p class="text-xs text-surface-400">以下为系统级数据来源与状态明细，供调试与核验使用。</p>
                <div v-for="group in groups" :key="`${group.category}::${group.sourceName}`" class="rounded-xl bg-surface-50 px-4 py-3">
                  <div class="flex flex-wrap items-center gap-2 text-sm">
                    <span class="font-semibold text-surface-700">{{ categoryLabel(group.category) }}</span>
                    <Badge variant="secondary">{{ group.sourceName }}</Badge>
                    <Badge variant="secondary">× {{ group.count }}</Badge>
                  </div>
                  <ul class="mt-2 space-y-2 border-t border-surface-200/60 pt-2">
                    <li v-for="item in group.items" :key="item.factId" class="text-xs text-surface-500">
                      <div class="flex flex-wrap items-center gap-1.5">
                        <span>{{ item.reason }}</span>
                        <span v-for="flag in issueFlags(item)" :key="flag" class="rounded bg-amber-100 px-1 py-0.5 text-amber-800">{{ flag }}</span>
                      </div>
                      <p v-if="item.date" class="mt-0.5">适用日期：{{ item.date }}</p>
                      <p v-if="item.targetName" class="mt-0.5">影响对象：{{ item.targetName }}</p>
                      <p class="mt-0.5">来源：{{ item.sourceName }}（{{ item.sourceType }}）· 核验 {{ formatCheckedAt(item.checkedAt) }}</p>
                      <p v-if="item.evidence" class="mt-0.5">原句证据：{{ item.evidence }}</p>
                      <p v-if="item.sourceUrl" class="mt-0.5">
                        <a :href="item.sourceUrl" target="_blank" rel="noopener noreferrer" class="font-semibold text-primary-600 hover:underline">查看安全来源</a>
                      </p>
                    </li>
                  </ul>
                </div>
              </div>
            </section>
          </div>
        </div>
      </div>
    </Teleport>
  </Card>
</template>
