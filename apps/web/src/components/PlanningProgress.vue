<script setup lang="ts">
import { Check, ChevronDown, Cpu, LoaderCircle, Minus } from 'lucide-vue-next'
import { computed, ref } from 'vue'

import type { PlanningProgressStage, PlanningProgressUpdate } from '../lib/api'

const props = defineProps<{
  planningState: 'idle' | 'queued' | 'succeeded' | 'failed' | 'cancelled'
  progress?: PlanningProgressUpdate | null
  progressHistory?: PlanningProgressUpdate[]
}>()

const expanded = ref(false)

interface PipelineStep {
  stage: PlanningProgressStage
  label: string
}

const steps: PipelineStep[] = [
  { stage: 'TASK_ACCEPTED', label: 'Task accepted' },
  { stage: 'CONTEXT_VALIDATING', label: 'Context validation' },
  { stage: 'CITY_FACTS_LOADING', label: 'City facts' },
  { stage: 'POI_RECALLING', label: 'POI recall' },
  { stage: 'CANDIDATES_RANKING', label: 'Candidate ranking' },
  { stage: 'ROUTES_CALCULATING', label: 'Route calculation' },
  { stage: 'CONSTRAINTS_SOLVING', label: 'Constraint solving' },
  { stage: 'KNOWLEDGE_RETRIEVING', label: 'Knowledge retrieval' },
  { stage: 'RESULT_EXPLAINING', label: 'Result explanation' },
  { stage: 'RESULT_PUBLISHING', label: 'Publishing result' },
  { stage: 'RESULT_PERSISTING', label: 'Result persistence' },
]

const observedStages = computed(() => new Set((props.progressHistory ?? []).map((event) => event.stage)))
const currentStepIndex = computed(() => {
  if (!props.progress) return -1
  return steps.findIndex((step) => step.stage === props.progress?.stage)
})

const currentMessage = computed(() => {
  if (props.progress) return props.progress.message
  if (props.planningState === 'succeeded') return 'Itinerary planning completed'
  if (props.planningState === 'failed') return 'Itinerary planning did not complete'
  if (props.planningState === 'cancelled') return 'Itinerary planning was cancelled'
  return 'Waiting for the worker to report progress'
})

function stepStatus(index: number): 'done' | 'active' | 'skipped' | 'pending' {
  const stage = steps[index].stage
  if (observedStages.value.has(stage)) {
    return index === currentStepIndex.value && props.planningState === 'queued' ? 'active' : 'done'
  }
  if (index < currentStepIndex.value) return 'skipped'
  return 'pending'
}
</script>

<template>
  <section class="mb-6 overflow-hidden rounded-lg border border-surface-200 bg-white shadow-soft" aria-live="polite">
    <button
      type="button"
      class="flex w-full items-center justify-between px-5 py-4 text-left hover:bg-surface-50"
      :aria-expanded="expanded || planningState === 'queued'"
      @click="expanded = !expanded"
    >
      <span class="flex min-w-0 items-center gap-3">
        <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-50 text-primary-600">
          <Cpu :size="16" aria-hidden="true" />
        </span>
        <span class="min-w-0">
          <span class="block text-sm font-semibold text-surface-800">Planning progress</span>
          <span data-testid="planning-current-stage" class="mt-0.5 block truncate text-xs text-surface-500">
            {{ currentMessage }}
          </span>
          <span v-if="progress" class="mt-1 block text-xs font-medium text-primary-700">{{ progress.progress }}%</span>
        </span>
      </span>
      <ChevronDown
        :size="16"
        class="shrink-0 text-surface-400 transition-transform duration-200"
        :class="{ 'rotate-180': expanded || planningState === 'queued' }"
        aria-hidden="true"
      />
    </button>

    <div v-if="expanded || planningState === 'queued'" class="border-t border-surface-100 bg-surface-50/50 px-5 py-4">
      <div v-if="progress && Object.keys(progress.statistics).length" class="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-surface-500">
        <span v-for="(value, name) in progress.statistics" :key="name">{{ name }}: {{ value }}</span>
      </div>
      <ol class="space-y-0">
        <li
          v-for="(step, index) in steps"
          :key="step.stage"
          :data-testid="`planning-stage-${step.stage}`"
          class="flex items-center gap-3 py-2 text-sm"
          :class="{
            'text-surface-700': stepStatus(index) === 'done' || stepStatus(index) === 'active',
            'text-surface-400': stepStatus(index) === 'skipped' || stepStatus(index) === 'pending',
          }"
        >
          <span class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full" :class="{
            'bg-nature-500 text-white': stepStatus(index) === 'done',
            'bg-primary-100 text-primary-600': stepStatus(index) === 'active',
            'bg-surface-200 text-surface-500': stepStatus(index) === 'skipped',
            'bg-surface-100 text-surface-400': stepStatus(index) === 'pending',
          }">
            <Check v-if="stepStatus(index) === 'done'" :size="11" aria-hidden="true" />
            <LoaderCircle v-else-if="stepStatus(index) === 'active'" :size="12" class="animate-spin" aria-hidden="true" />
            <Minus v-else-if="stepStatus(index) === 'skipped'" :size="11" aria-hidden="true" />
            <span v-else class="text-[10px]">{{ index + 1 }}</span>
          </span>
          <span>{{ step.label }}</span>
          <span class="ml-auto text-xs lowercase">{{ stepStatus(index) === 'skipped' ? 'not used' : stepStatus(index) }}</span>
        </li>
      </ol>
    </div>
  </section>
</template>
