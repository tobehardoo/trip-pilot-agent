<script setup lang="ts">
import { Check, ChevronDown, Cpu, LoaderCircle } from 'lucide-vue-next'
import { computed, ref } from 'vue'

const props = defineProps<{
  planningState: 'idle' | 'queued' | 'succeeded' | 'failed' | 'cancelled'
}>()

const expanded = ref(false)

interface PipelineStep {
  phase: string
  label: string
  detail: string
  icon: string
}

const steps: PipelineStep[] = [
  { phase: 'PARSE',    label: '解析旅行约束',     detail: '提取日期、预算、偏好、固定安排', icon: '📋' },
  { phase: 'RETRIEVE', label: '检索目的地 POI',   detail: '从高德地图和知识库检索候选地点',  icon: '🔍' },
  { phase: 'FILTER',   label: '过滤重复和低质量地点', detail: '去重、排除地址不匹配、过滤评分过低', icon: '🔬' },
  { phase: 'SCORE',    label: '偏好评分排序',     detail: '根据用户偏好和文化匹配度排序',    icon: '⭐' },
  { phase: 'OPTIMIZE', label: 'OR-Tools 时间窗口优化', detail: '约束求解：时间、交通、预算、必去地点', icon: '⚙️' },
  { phase: 'GENERATE', label: '生成最终行程方案', detail: '组装活动卡片、交通段和知识引用',  icon: '✨' },
]

const activeStepIndex = computed(() => {
  if (props.planningState === 'idle') return -1
  if (props.planningState === 'succeeded') return steps.length
  if (props.planningState === 'failed') return Math.max(0, steps.length - 2)
  if (props.planningState === 'cancelled') return Math.max(0, steps.length - 3)
  // queued — animate through steps
  // Since we don't get real-time step progress from SSE, simulate slow reveal
  return Math.min(steps.length, 3) // Show first 3 steps during "queued" state
})

function stepStatus(index: number): 'done' | 'active' | 'pending' {
  if (index < activeStepIndex.value) return 'done'
  if (index === activeStepIndex.value && props.planningState === 'queued') return 'active'
  return 'pending'
}
</script>

<template>
  <div class="mb-6 rounded-2xl border border-surface-200/60 bg-white shadow-soft overflow-hidden">
    <!-- Header -->
    <button
      type="button"
      class="flex items-center justify-between w-full px-5 py-4 text-left hover:bg-surface-50 transition-colors"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      <div class="flex items-center gap-3">
        <span class="flex h-8 w-8 items-center justify-center rounded-xl bg-primary-50 text-primary-600">
          <Cpu :size="16" aria-hidden="true" />
        </span>
        <div>
          <p class="text-sm font-semibold text-surface-800">
            <template v-if="planningState === 'succeeded'">规划 Pipeline 已完成</template>
            <template v-else-if="planningState === 'failed'">规划未完成</template>
            <template v-else-if="planningState === 'cancelled'">规划流程已中断</template>
            <template v-else>Agent 规划引擎运行中</template>
          </p>
          <p class="text-xs text-surface-400 mt-0.5">
            {{ planningState === 'queued' ? '正在优化行程方案...' : '查看规划过程' }}
          </p>
        </div>
      </div>
      <ChevronDown
        :size="16"
        class="text-surface-400 transition-transform duration-200 shrink-0"
        :class="{ 'rotate-180': expanded }"
        aria-hidden="true"
      />
    </button>

    <!-- Pipeline Steps -->
    <Transition name="pipeline">
      <div v-if="expanded" class="border-t border-surface-100 px-5 py-4 bg-surface-50/50">
        <p class="text-xs text-surface-400 mb-3 font-medium uppercase tracking-wider">Planning Pipeline</p>
        <div class="space-y-0">
          <div
            v-for="(step, index) in steps"
            :key="step.phase"
            class="flex items-start gap-3 py-2.5 transition-all duration-300"
            :class="{
              'opacity-100': stepStatus(index) !== 'pending',
              'opacity-30': stepStatus(index) === 'pending',
            }"
          >
            <!-- Status indicator -->
            <div class="flex-none mt-0.5">
              <span
                v-if="stepStatus(index) === 'done'"
                class="flex h-5 w-5 items-center justify-center rounded-full bg-nature-500 text-white"
              >
                <Check :size="11" aria-hidden="true" />
              </span>
              <span
                v-else-if="stepStatus(index) === 'active'"
                class="flex h-5 w-5 items-center justify-center rounded-full bg-primary-100 text-primary-600"
              >
                <LoaderCircle :size="12" class="animate-spin" aria-hidden="true" />
              </span>
              <span
                v-else
                class="flex h-5 w-5 items-center justify-center rounded-full bg-surface-200 text-surface-400"
              >
                <span class="text-[10px]">{{ index + 1 }}</span>
              </span>
            </div>

            <!-- Content -->
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <span class="text-xs">{{ step.icon }}</span>
                <p class="text-sm font-medium text-surface-700 m-0">{{ step.label }}</p>
              </div>
              <p
                v-if="stepStatus(index) !== 'pending'"
                class="text-xs text-surface-400 mt-0.5 m-0"
              >
                {{ step.detail }}
              </p>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>
