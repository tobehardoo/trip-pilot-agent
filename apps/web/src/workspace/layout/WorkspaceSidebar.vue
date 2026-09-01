<script setup lang="ts">
// Workspace Sidebar：工作区导航（Developer Tool 风格）。
// 紧凑小字号、单色图标；激活项 = 浅灰背景 + 左侧 2px 标记，无彩色块。
// F-UI-11 Phase 1：列表渲染真实旅行（listTrips → tripStore），
// 带加载/错误（可重试）/空态；点击切换 → selectTrip + URL 同步。
import { House, LayoutGrid, Plus, RefreshCw, Search, Settings } from 'lucide-vue-next'

import type { Trip } from '../../lib/api'
import { tripSubtitle } from '../lib/present'
import type { TripPhase } from '../lib/phase'

defineProps<{
  trips: Trip[]
  activeTripId: string | null
  activePhase: TripPhase | null
  loading: boolean
  error: string | null
}>()

const emit = defineEmits<{
  selectTrip: [id: string]
  newTrip: []
  retry: []
}>()

/** 旅行状态点：仅激活项显示——规划中（脉动） / 已完成（绿色常亮）；未规划无点 */
function statusDot(phase: TripPhase | null, active: boolean): { visible: boolean; classes: string } {
  if (!active || !phase) return { visible: false, classes: '' }
  if (phase === 'planning') return { visible: true, classes: 'bg-tp-run animate-pulse' }
  if (phase === 'completed') return { visible: true, classes: 'bg-tp-ok' }
  return { visible: false, classes: '' }
}
</script>

<template>
  <nav class="flex h-full min-h-0 w-56 shrink-0 flex-col border-r border-tp-line bg-tp-panel" aria-label="工作区导航">
    <!-- WORKSPACE 功能导航 -->
    <div class="px-2 pb-2 pt-3">
      <h2 class="m-0 mb-1 px-2 text-[10px] font-medium uppercase tracking-[0.08em] text-tp-mute">工作区</h2>
      <a
        href="#"
        class="flex h-7 items-center gap-2 rounded bg-tp-active px-2 text-xs text-tp-ink"
        aria-current="page"
        data-testid="workspace-nav-home"
      >
        <House :size="13" class="text-tp-sub" aria-hidden="true" /> 工作台
      </a>
      <a
        href="#"
        class="flex h-7 items-center gap-2 rounded px-2 text-xs text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
      >
        <LayoutGrid :size="13" aria-hidden="true" /> 我的旅行
      </a>
      <a
        href="#"
        class="flex h-7 items-center gap-2 rounded px-2 text-xs text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
      >
        <Search :size="13" aria-hidden="true" /> 搜索
      </a>
    </div>

    <div class="mx-2 border-t border-tp-div" role="separator" />

    <!-- TRIPS（真实列表） -->
    <div class="flex min-h-0 flex-1 flex-col px-2 py-2">
      <h2 class="m-0 mb-1 px-2 text-[10px] font-medium uppercase tracking-[0.08em] text-tp-mute">
        旅行
        <span class="ml-1 font-mono tracking-normal text-tp-faint">{{ trips.length }}</span>
      </h2>

      <!-- 加载中 -->
      <p
        v-if="loading && trips.length === 0"
        class="m-0 flex items-center gap-1.5 px-2 py-2 text-[11px] leading-4 text-tp-mute"
        data-testid="workspace-trips-loading"
      >
        <span class="inline-block h-1.5 w-1.5 rounded-full bg-tp-dot animate-pulse" aria-hidden="true" />
        正在加载旅行……
      </p>

      <!-- 错误（明确反馈 + 重试；绝不回退假数据） -->
      <div v-else-if="error && trips.length === 0" class="px-2 py-2" data-testid="workspace-trips-error">
        <p class="m-0 text-[11px] leading-4 text-tp-warn">{{ error }}</p>
        <button
          type="button"
          class="mt-1.5 flex h-6 items-center gap-1 rounded px-1.5 text-[11px] text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
          data-testid="workspace-trips-retry"
          @click="emit('retry')"
        >
          <RefreshCw :size="11" aria-hidden="true" /> 重试
        </button>
      </div>

      <!-- 空态 -->
      <p
        v-else-if="trips.length === 0"
        class="m-0 px-2 py-2 text-[11px] leading-4 text-tp-faint"
        data-testid="workspace-trips-empty"
      >
        还没有旅行，从「新建旅行」开始。
      </p>

      <div v-else class="min-h-0 flex-1 space-y-0.5 overflow-y-auto" data-testid="workspace-project-list">
        <button
          v-for="trip in trips"
          :key="trip.id"
          type="button"
          class="flex h-8 w-full items-center gap-2 rounded px-2 text-left transition-colors"
          :class="trip.id === activeTripId
            ? 'bg-tp-active shadow-[inset_2px_0_0_theme(colors.tp.ink)]'
            : 'hover:bg-tp-hover'"
          :aria-current="trip.id === activeTripId ? 'true' : undefined"
          :data-testid="`workspace-project-${trip.id}`"
          @click="emit('selectTrip', trip.id)"
        >
          <span class="min-w-0 flex-1">
            <span
              class="block truncate text-xs leading-4"
              :class="trip.id === activeTripId ? 'font-medium text-tp-ink' : 'text-tp-body'"
            >{{ trip.title }}</span>
            <span class="block truncate text-[11px] leading-4 text-tp-mute">{{ tripSubtitle(trip) }}</span>
          </span>
          <span
            v-if="statusDot(activePhase, trip.id === activeTripId).visible"
            class="h-1.5 w-1.5 shrink-0 rounded-full"
            :class="statusDot(activePhase, trip.id === activeTripId).classes"
            :title="activePhase === 'planning' ? '规划中' : '已完成'"
            aria-hidden="true"
          />
        </button>
      </div>

      <button
        type="button"
        class="flex h-7 items-center gap-2 rounded px-2 text-xs text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
        data-testid="workspace-new-trip"
        @click="emit('newTrip')"
      >
        <Plus :size="13" aria-hidden="true" /> 新建旅行
      </button>
    </div>

    <div class="mx-2 border-t border-tp-div" role="separator" />

    <!-- 底部 -->
    <div class="px-2 py-2">
      <p class="m-0 flex h-7 items-center gap-2 rounded px-2 text-xs text-tp-mute">
        <Settings :size="13" aria-hidden="true" /> 设置
      </p>
    </div>
  </nav>
</template>
