<script setup lang="ts">
// 上下文检查器：右侧常驻面板（Developer Tool 风格）。
// F-UI-11 Phase 1：真实 API 数据接入。
import { computed } from 'vue'

import type { Trip } from '../../lib/api'
import type { TripPhase } from '../lib/phase'
import { formatChinaDate, formatChinaMoney, preferencesLabel, mustVisitLabel } from '../lib/present'

const props = withDefaults(defineProps<{
  trip: Trip | null
}>(), {
  trip: null,
})

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

// 旅行信息
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

// 旅行偏好
const preferenceRows = computed(() =>
  props.trip
    ? [
        { label: '旅行偏好', value: preferencesLabel(props.trip.constraints) },
        { label: '必去地点', value: mustVisitLabel(props.trip.constraints) },
      ]
    : [],
)

// 生成结果
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

const emit = defineEmits<{
  editConstraints: []
}>()
</script>

<template>
  <aside class="flex h-full min-h-0 w-64 shrink-0 flex-col border-l border-tp-line bg-tp-panel" aria-label="旅行上下文">
    <div class="min-h-0 flex-1 overflow-y-auto px-3 py-3">
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
          {{ currentPhase === 'planning' ? '正在智能规划……' : '从左侧选择一个旅行查看上下文' }}
        </p>
      </section>

      <div class="border-t border-tp-div" role="separator" />

      <!-- 旅行标题 -->
      <section class="mb-3 mt-3" aria-label="旅行信息">
        <div class="mb-1 flex items-center justify-between">
          <h3 class="m-0 text-[10px] font-medium tracking-[0.08em] text-tp-mute">旅行</h3>
          <button
            v-if="trip"
            type="button"
            class="text-[11px] text-tp-sub transition-colors hover:text-tp-ink"
            data-testid="context-edit-constraints"
            @click="emit('editConstraints')"
          >
            编辑约束
          </button>
        </div>
        <p class="m-0 flex items-baseline justify-between gap-2">
          <span class="min-w-0 truncate text-xs font-medium text-tp-ink">{{ trip?.title ?? '未选择' }}</span>
          <span v-if="trip" class="shrink-0 font-mono text-[11px] text-tp-mute">v{{ trip.version }}</span>
        </p>
        <p class="m-0 text-[11px] leading-4 text-tp-mute">
          {{ trip ? `${trip.destination || '待定'} · ${trip.startDate ? formatChinaDate(trip.startDate) : '待定'}` : '—' }}
        </p>
      </section>

      <div class="border-t border-tp-div" role="separator" />

      <!-- 旅行信息（目的地/日期/人数/预算） -->
      <section class="mb-3 mt-3" aria-label="旅行信息">
        <h3 class="m-0 mb-1 text-[10px] font-medium tracking-[0.08em] text-tp-mute">旅行信息</h3>
        <dl v-if="trip" class="m-0 mt-1.5 space-y-1">
          <div
            v-for="row in tripInfoRows"
            :key="row.label"
            class="flex items-baseline justify-between gap-3"
          >
            <dt class="m-0 shrink-0 text-[11px] leading-5 text-tp-mute">{{ row.label }}</dt>
            <dd class="m-0 min-w-0 truncate text-right text-xs leading-5 text-tp-body">{{ row.value }}</dd>
          </div>
        </dl>
        <p v-else class="m-0 text-[11px] leading-4 text-tp-faint">未选择旅行</p>
      </section>

      <div v-if="trip" class="border-t border-tp-div" role="separator" />

      <!-- 旅行偏好 -->
      <section v-if="trip" class="mb-3 mt-3" aria-label="旅行偏好">
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
    </div>
  </aside>
</template>