<script setup lang="ts">
import { GitCompareArrows, History, LoaderCircle, RotateCcw } from 'lucide-vue-next'
import { computed, ref } from 'vue'

import {
  FEASIBILITY_STATUS_LABEL,
  readVersionFeasibilityMetadata,
  type FeasibilityStatus,
} from '../lib/feasibility'
import type { ItineraryVersionDiff, ItineraryVersionSummary } from '../lib/api'

const props = defineProps<{
  versions: ItineraryVersionSummary[]
  currentVersionId: string
  busy: boolean
  error: string | null
  getDiff: (fromVersionId: string, toVersionId: string) => Promise<ItineraryVersionDiff>
  rollback: (
    sourceVersionId: string,
    expectedCurrentVersionId: string,
    idempotencyKey: string,
  ) => Promise<void>
}>()

const selectedDiff = ref<ItineraryVersionDiff | null>(null)
const pendingRollback = ref<ItineraryVersionSummary | null>(null)
const actionBusy = ref(false)
const actionError = ref<string | null>(null)
const expanded = ref(false)
const visibleVersions = computed(() => expanded.value ? props.versions : props.versions.slice(0, 3))

const sourceLabels: Record<ItineraryVersionSummary['versionSource'], string> = {
  PLANNING_TASK: '智能规划',
  USER_EDIT: '手动修改',
  LOCAL_REPLAN: '局部重排',
  ROLLBACK: '历史回滚',
}

type FeasibilityMetaDisplay =
  | { kind: 'status'; status: FeasibilityStatus }
  | { kind: 'none' }
  | { kind: 'unreadable' }

function feasibilityMetaOf(version: ItineraryVersionSummary): FeasibilityMetaDisplay {
  const result = readVersionFeasibilityMetadata(version.feasibility)
  if (result.ok && result.value) return { kind: 'status', status: result.value.status }
  if (result.ok) return { kind: 'none' }
  return { kind: 'unreadable' }
}

function feasibilityBadgeClass(status: FeasibilityStatus) {
  return {
    VERIFIED: 'rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold text-emerald-700',
    NEEDS_REPAIR: 'rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold text-amber-700',
    UNVERIFIED: 'rounded-full bg-surface-100 px-2 py-0.5 text-[10px] font-bold text-surface-500',
  }[status]
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'Asia/Shanghai',
  }).format(new Date(value))
}

function formatBudgetChange(value: number) {
  if (value === 0) return '¥0'
  return `${value > 0 ? '+' : '-'}¥${Math.abs(value)}`
}

async function compare(version: ItineraryVersionSummary) {
  if (actionBusy.value) return
  actionBusy.value = true
  actionError.value = null
  try {
    selectedDiff.value = await props.getDiff(version.versionId, props.currentVersionId)
  } catch {
    actionError.value = '暂时无法读取版本差异，请稍后重试'
  } finally {
    actionBusy.value = false
  }
}

async function confirmRollback() {
  const version = pendingRollback.value
  if (!version || actionBusy.value) return
  actionBusy.value = true
  actionError.value = null
  try {
    await props.rollback(
      version.versionId,
      props.currentVersionId,
      crypto.randomUUID(),
    )
    pendingRollback.value = null
    selectedDiff.value = null
  } catch {
    actionError.value = '回滚失败，当前行程可能已更新，请刷新后重试'
  } finally {
    actionBusy.value = false
  }
}
</script>

<template>
  <section
    class="rounded-2xl border border-surface-200 bg-white p-6 shadow-card sm:p-7"
    aria-labelledby="itinerary-version-title"
  >
    <div class="mb-5 flex items-start justify-between gap-4">
      <div>
        <p class="mb-1 text-xs font-bold uppercase tracking-widest text-primary-500">Version History</p>
        <h2 id="itinerary-version-title" class="m-0 flex items-center gap-2 text-xl font-bold text-surface-800">
          <History :size="19" aria-hidden="true" />行程版本
        </h2>
        <p class="mb-0 mt-2 text-sm leading-relaxed text-surface-500">
          每次规划、修改和回滚都会创建新版本，旧版本不会被覆盖。
        </p>
      </div>
      <LoaderCircle v-if="busy || actionBusy" class="animate-spin text-primary-500" :size="20" aria-label="正在处理版本" />
    </div>

    <p v-if="error || actionError" class="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
      {{ actionError ?? error }}
    </p>
    <p v-if="!busy && versions.length === 0" class="rounded-xl border border-dashed border-surface-200 p-5 text-center text-sm text-surface-400">
      生成行程后，这里会保留可比较、可回滚的历史版本。
    </p>

    <ol v-else class="m-0 grid list-none gap-3 p-0">
      <li
        v-for="version in visibleVersions"
        :key="version.versionId"
        class="rounded-xl border border-surface-200 bg-surface-50 px-4 py-3"
      >
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div class="flex items-center gap-2">
              <strong class="text-sm text-surface-800">版本 {{ version.versionNumber }}</strong>
              <span v-if="version.current" class="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold text-emerald-700">当前</span>
              <span class="rounded-full bg-primary-50 px-2 py-0.5 text-[10px] font-semibold text-primary-700">
                {{ sourceLabels[version.versionSource] }}
              </span>
              <span
                v-for="meta in [feasibilityMetaOf(version)]"
                :key="meta.kind"
              >
                <span v-if="meta.kind === 'status'" :class="feasibilityBadgeClass(meta.status)">
                  {{ FEASIBILITY_STATUS_LABEL[meta.status] }}
                </span>
                <span
                  v-else-if="meta.kind === 'none'"
                  class="rounded-full bg-surface-100 px-2 py-0.5 text-[10px] font-medium text-surface-400"
                >
                  无历史验证
                </span>
                <span v-else class="rounded-full bg-surface-100 px-2 py-0.5 text-[10px] font-medium text-surface-400">
                  验证信息无法读取
                </span>
              </span>
            </div>
            <p class="mb-0 mt-1 text-xs text-surface-500">
              {{ formatDateTime(version.createdAt) }} · 预算 ¥{{ version.estimatedTotalCost }}
            </p>
          </div>
          <div v-if="!version.current" class="flex flex-wrap gap-2">
            <button
              type="button"
              :aria-label="`比较版本 ${version.versionNumber} 与当前版本`"
              :disabled="busy || actionBusy"
              class="inline-flex items-center gap-1.5 rounded-lg border border-surface-200 bg-white px-3 py-2 text-xs font-semibold text-surface-700 disabled:opacity-50"
              @click="compare(version)"
            >
              <GitCompareArrows :size="14" aria-hidden="true" />比较
            </button>
            <button
              type="button"
              :aria-label="`回滚到版本 ${version.versionNumber}`"
              :disabled="busy || actionBusy"
              class="inline-flex items-center gap-1.5 rounded-lg bg-amber-100 px-3 py-2 text-xs font-semibold text-amber-800 disabled:opacity-50"
              @click="pendingRollback = version"
            >
              <RotateCcw :size="14" aria-hidden="true" />回滚
            </button>
          </div>
        </div>
      </li>
    </ol>
    <button
      v-if="versions.length > 3"
      type="button"
      class="mt-3 text-sm font-semibold text-primary-600 hover:text-primary-700"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      {{ expanded ? '收起较早版本' : `查看其余 ${versions.length - 3} 个较早版本` }}
    </button>

    <div v-if="selectedDiff" class="mt-4 rounded-xl border border-primary-100 bg-primary-50 p-4">
      <h3 class="m-0 text-sm font-bold text-primary-900">与当前版本的差异</h3>
      <p class="mb-2 mt-1 text-xs font-semibold text-primary-700">
        预算变化 {{ formatBudgetChange(selectedDiff.budgetChange) }}
      </p>
      <ul class="m-0 space-y-1 pl-5 text-xs leading-relaxed text-surface-700">
        <li v-for="activity in selectedDiff.addedActivities" :key="`added-${activity.key}`">
          新增：{{ activity.title }}
        </li>
        <li v-for="activity in selectedDiff.removedActivities" :key="`removed-${activity.key}`">
          移除：{{ activity.title }}
        </li>
        <li v-for="activity in selectedDiff.changedActivities" :key="`changed-${activity.before.key}`">
          调整：{{ activity.after.title }}（{{ activity.changes.join('、') }}）
        </li>
        <li v-for="leg in selectedDiff.addedTransitLegs" :key="`transit-added-${leg.key}`">
          新增交通：{{ leg.fromTitle }} → {{ leg.toTitle }}（{{ leg.mode }}）
        </li>
        <li v-for="leg in selectedDiff.removedTransitLegs" :key="`transit-removed-${leg.key}`">
          移除交通：{{ leg.fromTitle }} → {{ leg.toTitle }}
        </li>
        <li v-for="leg in selectedDiff.changedTransitLegs" :key="`transit-changed-${leg.before.key}`">
          交通调整：{{ leg.after.fromTitle }} → {{ leg.after.toTitle }}
          （{{ leg.before.mode }} → {{ leg.after.mode }}）
        </li>
        <li v-for="impact in selectedDiff.addedFactImpacts" :key="`fact-added-${impact.factId}-${impact.effect}`">
          新增规划依据：{{ impact.reason }}
        </li>
        <li v-for="impact in selectedDiff.removedFactImpacts" :key="`fact-removed-${impact.factId}-${impact.effect}`">
          移除规划依据：{{ impact.reason }}
        </li>
        <li v-for="impact in selectedDiff.changedFactImpacts" :key="`fact-changed-${impact.before.factId}-${impact.before.effect}`">
          规划依据变化：{{ impact.after.reason }}
        </li>
        <li
          v-if="selectedDiff.addedActivities.length === 0
            && selectedDiff.removedActivities.length === 0
            && selectedDiff.changedActivities.length === 0
            && selectedDiff.addedTransitLegs.length === 0
            && selectedDiff.removedTransitLegs.length === 0
            && selectedDiff.changedTransitLegs.length === 0
            && selectedDiff.addedFactImpacts.length === 0
            && selectedDiff.removedFactImpacts.length === 0
            && selectedDiff.changedFactImpacts.length === 0"
        >
          活动、交通和规划依据没有变化
        </li>
      </ul>
    </div>

    <div v-if="pendingRollback" class="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4" role="alertdialog" aria-label="确认版本回滚">
      <p class="m-0 text-sm font-semibold text-amber-900">
        将基于版本 {{ pendingRollback.versionNumber }} 创建一个新版本；现有历史不会被删除。
      </p>
      <div class="mt-3 flex gap-2">
        <button
          type="button"
          :aria-label="`确认回滚到版本 ${pendingRollback.versionNumber}`"
          :disabled="actionBusy"
          class="rounded-lg bg-amber-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"
          @click="confirmRollback"
        >
          确认回滚
        </button>
        <button
          type="button"
          :disabled="actionBusy"
          class="rounded-lg bg-white px-3 py-2 text-xs font-semibold text-surface-600"
          @click="pendingRollback = null"
        >
          取消
        </button>
      </div>
    </div>
  </section>
</template>
