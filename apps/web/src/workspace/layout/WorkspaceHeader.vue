<script setup lang="ts">
// Workspace Application Bar：极简工具栏（Developer Tool 风格）。
// 左：工作区开关 + 历史导航；中：任务路径标题；右：规划状态 + 面板开关 + 用户。
// F-UI-8：状态完全由当前旅行推导（tripStore），移除"演示"切换按钮。
import { ArrowLeft, ArrowRight, PanelLeft, PanelRight } from 'lucide-vue-next'

import type { TripPhase } from '../lib/phase'

defineProps<{
  taskTitle: string
  contextVisible: boolean
  sidebarVisible: boolean
  phase: TripPhase | null
}>()

const emit = defineEmits<{
  toggleSidebar: []
  toggleContext: []
}>()

const PHASE_META: Record<TripPhase, { text: string; dot: string }> = {
  planning: { text: '规划中', dot: 'bg-tp-dot animate-pulse' },
  completed: { text: '已完成', dot: 'bg-tp-ok' },
  draft: { text: '未规划', dot: 'bg-tp-dot' },
}
</script>

<template>
  <header class="flex h-10 shrink-0 items-center justify-between gap-3 border-b border-tp-line bg-tp-panel px-3">
    <div class="flex min-w-0 items-center gap-0.5">
      <button
        type="button"
        class="flex h-7 w-7 items-center justify-center rounded text-tp-sub transition-colors hover:bg-tp-active hover:text-tp-ink"
        title="切换工作区导航"
        aria-label="切换工作区导航"
        data-testid="workspace-toggle-sidebar"
        @click="emit('toggleSidebar')"
      >
        <PanelLeft :size="14" aria-hidden="true" />
      </button>
      <button
        type="button"
        class="flex h-7 w-7 items-center justify-center rounded text-tp-faint transition-colors hover:bg-tp-active hover:text-tp-sub"
        title="后退"
        aria-label="后退"
        disabled
      >
        <ArrowLeft :size="13" aria-hidden="true" />
      </button>
      <button
        type="button"
        class="flex h-7 w-7 items-center justify-center rounded text-tp-faint transition-colors hover:bg-tp-active hover:text-tp-sub"
        title="前进"
        aria-label="前进"
        disabled
      >
        <ArrowRight :size="13" aria-hidden="true" />
      </button>
    </div>

    <div class="flex min-w-0 flex-1 items-center justify-center gap-1.5 text-xs">
      <span class="truncate text-tp-mute">TripPilot</span>
      <span class="text-tp-faint" aria-hidden="true">/</span>
      <span class="truncate font-medium text-tp-ink">{{ taskTitle }}</span>
    </div>

    <div class="flex items-center gap-2">
      <span v-if="phase" class="flex items-center gap-1.5 text-[11px] text-tp-sub" data-testid="header-agent-state">
        <span
          class="h-1.5 w-1.5 rounded-full"
          :class="PHASE_META[phase].dot"
          aria-hidden="true"
        />
        {{ PHASE_META[phase].text }}
      </span>
      <button
        type="button"
        class="flex h-7 w-7 items-center justify-center rounded transition-colors hover:bg-tp-active"
        :class="contextVisible ? 'text-tp-ink' : 'text-tp-mute'"
        title="切换上下文面板"
        aria-label="切换上下文面板"
        data-testid="workspace-toggle-context"
        @click="emit('toggleContext')"
      >
        <PanelRight :size="14" aria-hidden="true" />
      </button>
      <span
        class="flex h-6 w-6 items-center justify-center rounded-full border border-tp-line bg-white text-[10px] text-tp-sub"
        title="未登录演示会话"
      >T</span>
    </div>
  </header>
</template>
