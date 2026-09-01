<script setup lang="ts">
// F-UI-10 Phase 2：工具执行详情 —— 挂载在 Agent Message 下方的可展开详情。
//
// 用户 §7/§8 核心原则：Tool Call 是消息的附加详情，不是独立大 Card。
// 视觉只使用：缩进 / Divider / 小字号 / Monospace，不套任何 Card 边框。
import { ref } from 'vue'
import { ChevronDown, ChevronRight } from 'lucide-vue-next'

import type { ToolExecution } from '../../../lib/agent-timeline'

const props = defineProps<{
  execution: ToolExecution
}>()

const expanded = ref(false)

const detailLabel = () => props.execution.detailLabel ?? props.execution.displayName
</script>

<template>
  <div class="mt-2" data-testid="tool-detail">
    <!-- 折叠开关：⌄ 查看路线优化详情（消息内的轻链接，不是面板头） -->
    <button
      type="button"
      class="flex h-6 items-center gap-1 rounded px-1 text-[11px] leading-4 text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
      :aria-expanded="expanded"
      data-testid="tool-detail-toggle"
      @click="expanded = !expanded"
    >
      <component
        :is="expanded ? ChevronDown : ChevronRight"
        :size="12"
        class="shrink-0"
        aria-hidden="true"
      />
      {{ expanded ? '收起' + detailLabel() + '详情' : '查看' + detailLabel() + '详情' }}
    </button>

    <!-- 展开详情：缩进 + Divider + 小字号 + Monospace（无 Card） -->
    <div
      v-if="expanded"
      class="mt-1.5 space-y-2 border-l border-tp-div pl-3"
      data-testid="tool-detail-panel"
    >
      <div v-if="execution.status === 'running'" class="flex items-center gap-1.5">
        <span class="h-1 w-1 animate-pulse rounded-full bg-tp-run" aria-hidden="true" />
        <span class="text-[11px] leading-4 text-tp-mute">{{ execution.activity }}</span>
      </div>

      <div>
        <p class="m-0 text-[11px] leading-4 text-tp-faint">使用工具</p>
        <p class="m-0 font-mono text-xs leading-5 text-tp-ink">{{ execution.displayName }} · {{ execution.identifier }}</p>
      </div>

      <dl v-if="execution.inputs?.length" class="m-0 space-y-1 border-t border-tp-div pt-2">
        <div
          v-for="metric in execution.inputs"
          :key="metric.label"
          class="flex items-baseline justify-between gap-4"
        >
          <dt class="m-0 text-xs leading-5 text-tp-sub">{{ metric.label }}</dt>
          <dd class="m-0 font-mono text-xs leading-5 text-tp-ink">{{ metric.value }}</dd>
        </div>
      </dl>

      <dl v-if="execution.outputs?.length" class="m-0 space-y-1 border-t border-tp-div pt-2">
        <div
          v-for="metric in execution.outputs"
          :key="metric.label"
          class="flex items-baseline justify-between gap-4"
        >
          <dt class="m-0 text-xs leading-5 text-tp-sub">{{ metric.label }}</dt>
          <dd class="m-0 font-mono text-xs leading-5 text-tp-ink">{{ metric.value }}</dd>
        </div>
      </dl>
    </div>
  </div>
</template>
