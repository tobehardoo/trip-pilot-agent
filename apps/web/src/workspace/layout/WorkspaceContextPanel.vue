<script setup lang="ts">
// 上下文检查器（Composer 交互重构 design §3.3）：三态。
// - 创建模式·未开始：极弱化（一行引导，无大面积"未选择"占位）。
// - 创建模式·对话中：旅行需求（chips）+ 已了解（CONFIRMED slots 投影）+ 待确认。
//   纯投影，不是第二个表单；内部枚举不上屏。
// - 旅行模式：目的地/日期/约束摘要 + 生成结果（来自 trip 实体）。
import { computed } from 'vue'

import type { AgentDialogSlotView, Trip } from '../../lib/api'
import { creationSummary } from '../../lib/agent-slots'
import type { TripPhase } from '../lib/phase'
import { formatChinaDate, formatChinaMoney, preferencesLabel, mustVisitLabel } from '../lib/present'

interface CreationContextSummary {
  destination: string | null
  startDate: string | null
  endDate: string | null
  started: boolean
  slots: Record<string, AgentDialogSlotView> | null
}

const props = withDefaults(defineProps<{
  trip: Trip | null
  creation?: CreationContextSummary | null
}>(), {
  trip: null,
  creation: null,
})

const emit = defineEmits<{
  editConstraints: []
}>()

const PHASE_TEXT: Record<TripPhase, string> = {
  planning: '规划中',
  completed: '已完成',
  draft: '未规划',
}

const currentPhase = computed<TripPhase | null>(() => {
  const s = props.trip?.status?.toLowerCase() ?? ''
  if (s === 'draft') return 'draft'
  if (s === 'planning') return 'planning'
  if (s === 'completed') return 'completed'
  return null
})

const agentStateLabel = computed(() =>
  currentPhase.value ? PHASE_TEXT[currentPhase.value] : '未选择旅行',
)

// ── 创建模式摘要 ────────────────────────────────────────────────
const summary = computed(() => creationSummary(props.creation?.slots ?? null))

function shortDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const parts = iso.split('-')
  return parts.length === 3 ? `${parts[1]}/${parts[2]}` : (iso ?? '')
}

const requirementRows = computed(() => {
  const rows: Array<{ done: boolean; text: string }> = []
  rows.push(props.creation?.destination
    ? { done: true, text: props.creation.destination }
    : { done: false, text: '目的地' })
  rows.push(props.creation?.startDate && props.creation.endDate
    ? { done: true, text: `${shortDate(props.creation.startDate)} → ${shortDate(props.creation.endDate)}` }
    : { done: false, text: '日期' })
  return rows
})

// ── 旅行模式 ────────────────────────────────────────────────────
const tripInfoRows = computed(() =>
  props.trip
    ? [
        { label: '目的地', value: props.trip.destination || '待定' },
        { label: '日期', value: props.trip.startDate && props.trip.endDate
          ? `${formatChinaDate(props.trip.startDate)} — ${formatChinaDate(props.trip.endDate)}`
          : '待定' },
        { label: '人数', value: `${props.trip.constraints.travelers} 人` },
        { label: '预算', value: formatChinaMoney(props.trip.constraints.budgetAmount) },
      ]
    : [],
)

const preferenceRows = computed(() =>
  props.trip
    ? [
        { label: '旅行偏好', value: preferencesLabel(props.trip.constraints) },
        { label: '必去地点', value: mustVisitLabel(props.trip.constraints) },
      ]
    : [],
)

interface ArtifactRow {
  icon: 'plan' | 'evaluation' | 'route'
  title: string
  status: 'completed' | 'running' | 'pending'
}

const artifacts = computed<ArtifactRow[]>(() => {
  if (!props.trip || !currentPhase.value || currentPhase.value === 'draft') return []
  if (currentPhase.value === 'completed') {
    return [
      { icon: 'plan', title: '旅行方案', status: 'completed' },
      { icon: 'evaluation', title: '方案评估', status: 'completed' },
      { icon: 'route', title: '路线分析', status: 'completed' },
    ]
  }
  return [
    { icon: 'plan', title: '旅行方案', status: 'pending' },
    { icon: 'evaluation', title: '方案评估', status: 'pending' },
    { icon: 'route', title: '路线分析', status: 'running' },
  ]
})

const ARTIFACT_STATUS_TEXT: Record<ArtifactRow['status'], { text: string; classes: string }> = {
  completed: { text: '已生成', classes: 'text-tp-ok' },
  running: { text: '进行中', classes: 'text-tp-run' },
  pending: { text: '待生成', classes: 'text-tp-faint' },
}
</script>

<template>
  <aside class="flex h-full min-h-0 w-64 shrink-0 flex-col border-l border-tp-line bg-tp-panel" aria-label="旅行上下文">
    <div class="min-h-0 flex-1 overflow-y-auto px-3 py-3">
      <!-- ── 创建模式（未开始）：极弱化 ─────────────────────────── -->
      <template v-if="!trip && creation && !creation.started">
        <section class="mb-3" aria-label="旅行需求">
          <h3 class="m-0 mb-1 text-[10px] font-medium tracking-[0.08em] text-tp-mute">旅行需求</h3>
          <p class="m-0 text-[11px] leading-5 text-tp-faint" data-testid="context-creation-empty">
            描述你的旅行想法开始。<br />已了解的需求会汇总在这里。
          </p>
        </section>
      </template>

      <!-- ── 创建模式（对话中）：需求摘要投影 ───────────────────── -->
      <template v-else-if="!trip && creation">
        <section class="mb-3" aria-label="旅行需求">
          <h3 class="m-0 mb-1 text-[10px] font-medium tracking-[0.08em] text-tp-mute">旅行需求</h3>
          <p
            v-for="row in requirementRows"
            :key="row.text"
            class="m-0 flex items-center gap-1.5 py-0.5 text-xs leading-5"
            :class="row.done ? 'text-tp-body' : 'text-tp-mute'"
          >
            <span class="text-[11px]" :class="row.done ? 'text-tp-ok' : 'text-tp-faint'">{{ row.done ? '✓' : '○' }}</span>
            {{ row.text }}
          </p>
        </section>

        <div class="border-t border-tp-div" role="separator" />

        <section class="mb-3 mt-3" aria-label="已了解的需求">
          <h3 class="m-0 mb-1 text-[10px] font-medium tracking-[0.08em] text-tp-mute">已了解</h3>
          <dl v-if="summary.known.length" class="m-0 mt-1 space-y-1" data-testid="context-creation-known">
            <div v-for="row in summary.known" :key="row.name" class="flex items-baseline justify-between gap-3">
              <dt class="m-0 shrink-0 text-[11px] leading-5 text-tp-mute">{{ row.label }}</dt>
              <dd class="m-0 min-w-0 truncate text-right text-xs leading-5 text-tp-body">{{ row.display }}</dd>
            </div>
          </dl>
          <p v-else class="m-0 text-[11px] leading-4 text-tp-faint">还没有，继续聊就行。</p>
        </section>

        <div v-if="summary.pending.length" class="border-t border-tp-div" role="separator" />

        <section v-if="summary.pending.length" class="mb-3 mt-3" aria-label="待确认的需求">
          <h3 class="m-0 mb-1 text-[10px] font-medium tracking-[0.08em] text-tp-mute">待确认</h3>
          <p
            v-for="label in summary.pending"
            :key="label"
            class="m-0 flex items-center gap-1.5 py-0.5 text-xs leading-5 text-tp-mute"
            data-testid="context-creation-pending"
          >
            <span class="inline-block h-2 w-2 rounded-full border border-tp-faint" aria-hidden="true" />
            {{ label }}
          </p>
        </section>
      </template>

      <!-- ── 旅行模式 ───────────────────────────────────────────── -->
      <template v-else-if="trip">
        <!-- 智能体 -->
        <section class="mb-3" aria-label="智能体状态">
          <h3 class="m-0 mb-1 text-[10px] font-medium tracking-[0.08em] text-tp-mute">智能体</h3>
          <p class="m-0 flex items-center gap-1.5 text-xs leading-5 text-tp-ink">
            <span
              class="inline-block h-1.5 w-1.5 rounded-full"
              :class="currentPhase === 'completed'
                ? 'bg-tp-ok'
                : currentPhase === 'planning'
                  ? 'bg-tp-dot animate-pulse'
                  : 'bg-tp-dot'"
              aria-hidden="true"
            />
            {{ agentStateLabel }}
          </p>
          <p class="m-0 text-[11px] leading-4 text-tp-mute">
            {{ currentPhase === 'planning' ? '正在智能规划……' : '' }}
          </p>
        </section>

        <div class="border-t border-tp-div" role="separator" />

        <!-- 旅行标题 -->
        <section class="mb-3 mt-3" aria-label="旅行信息">
          <div class="mb-1 flex items-center justify-between">
            <h3 class="m-0 text-[10px] font-medium tracking-[0.08em] text-tp-mute">旅行</h3>
            <button
              type="button"
              class="text-[11px] text-tp-sub transition-colors hover:text-tp-ink"
              data-testid="context-edit-constraints"
              @click="emit('editConstraints')"
            >
              编辑约束
            </button>
          </div>
          <p class="m-0 flex items-baseline justify-between gap-2">
            <span class="min-w-0 truncate text-xs font-medium text-tp-ink">{{ trip.title }}</span>
            <span class="shrink-0 font-mono text-[11px] text-tp-mute">v{{ trip.version }}</span>
          </p>
          <p class="m-0 text-[11px] leading-4 text-tp-mute">
            {{ `${trip.destination || '待定'} · ${trip.startDate ? formatChinaDate(trip.startDate) : '待定'}` }}
          </p>
        </section>

        <div class="border-t border-tp-div" role="separator" />

        <!-- 需求摘要（目的地/日期/人数/预算） -->
        <section class="mb-3 mt-3" aria-label="需求摘要">
          <h3 class="m-0 mb-1 text-[10px] font-medium tracking-[0.08em] text-tp-mute">需求摘要</h3>
          <dl class="m-0 mt-1.5 space-y-1">
            <div
              v-for="row in tripInfoRows"
              :key="row.label"
              class="flex items-baseline justify-between gap-3"
            >
              <dt class="m-0 shrink-0 text-[11px] leading-5 text-tp-mute">{{ row.label }}</dt>
              <dd class="m-0 min-w-0 truncate text-right text-xs leading-5 text-tp-body">{{ row.value }}</dd>
            </div>
          </dl>
        </section>

        <div class="border-t border-tp-div" role="separator" />

        <!-- 偏好 -->
        <section class="mb-3 mt-3" aria-label="旅行偏好">
          <h3 class="m-0 mb-1 text-[10px] font-medium tracking-[0.08em] text-tp-mute">旅行偏好</h3>
          <dl class="m-0 space-y-1">
            <div
              v-for="row in preferenceRows"
              :key="row.label"
              class="flex items-baseline justify-between gap-3"
            >
              <dt class="m-0 shrink-0 text-[11px] leading-5 text-tp-mute">{{ row.label }}</dt>
              <dd class="m-0 min-w-0 truncate text-right text-xs leading-5 text-tp-body">{{ row.value }}</dd>
            </div>
          </dl>
        </section>

        <div v-if="artifacts.length" class="border-t border-tp-div" role="separator" />

        <!-- 生成结果 -->
        <section v-if="artifacts.length" class="mt-3" aria-label="生成结果">
          <h3 class="m-0 mb-1 text-[10px] font-medium tracking-[0.08em] text-tp-mute">生成结果</h3>
          <ul class="m-0 list-none space-y-0.5 p-0">
            <li v-for="artifact in artifacts" :key="artifact.icon">
              <button
                type="button"
                class="flex h-6 w-full items-center justify-between gap-2 rounded px-1.5 text-left transition-colors hover:bg-tp-hover"
                :data-testid="`artifact-${artifact.icon}`"
              >
                <span
                  class="min-w-0 truncate text-xs"
                  :class="artifact.status === 'pending' ? 'text-tp-faint' : 'text-tp-body'"
                >{{ artifact.title }}</span>
                <span class="shrink-0 text-[10px]" :class="ARTIFACT_STATUS_TEXT[artifact.status].classes">
                  {{ ARTIFACT_STATUS_TEXT[artifact.status].text }}
                </span>
              </button>
            </li>
          </ul>
        </section>
      </template>
    </div>
  </aside>
</template>
