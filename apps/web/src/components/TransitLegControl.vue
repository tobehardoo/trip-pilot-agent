<script setup lang="ts">
import {
  BusFront,
  CarFront,
  Check,
  ChevronDown,
  Clock3,
  Coins,
  Footprints,
  Sparkles,
} from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'

import type { ItineraryTransitLeg } from '../lib/api'
import {
  commuteModeLabel,
  persistedTransitDisplayCost,
  type CommuteMode,
  type PersistedCommuteMode,
} from '../lib/transit'

const props = withDefaults(defineProps<{
  leg: ItineraryTransitLeg
  fromTitle: string
  toTitle: string
  selectedMode: CommuteMode | PersistedCommuteMode
  availableSeconds?: number
  locked?: boolean
}>(), {
  availableSeconds: undefined,
  locked: false,
})

const emit = defineEmits<{
  select: [mode: CommuteMode]
  lock: [locked: boolean]
}>()

const open = ref(false)
const activeMode = ref<CommuteMode | PersistedCommuteMode>(props.selectedMode)
const selectionPending = computed(() => activeMode.value !== props.leg.mode)
const summaryCost = computed(() => persistedTransitDisplayCost(props.leg))

watch(() => props.selectedMode, (mode) => { activeMode.value = mode })

function selectMode(mode: CommuteMode) {
  if (props.locked || activeMode.value === mode) return
  activeMode.value = mode
  emit('select', mode)
}

function toggleOptions() {
  open.value = !open.value
}

function modeLabel(mode: CommuteMode | PersistedCommuteMode) {
  return commuteModeLabel(mode)
}

function displayModeLabel() {
  if (activeMode.value === 'AUTO') return '自动推荐'
  return modeLabel(activeMode.value)
}

function formatMinutes(seconds: number) {
  return `${Math.max(1, Math.round(seconds / 60))} 分钟`
}

function formatCost(cost: number) {
  return cost === 0 ? '¥0' : `约 ¥${cost.toFixed(cost % 1 === 0 ? 0 : 2)}`
}

</script>

<template>
  <div :data-testid="`transit-leg-${leg.id}`" class="rounded-xl border border-surface-200 bg-surface-50/70 overflow-hidden transition-all duration-200">
    <!-- Summary Button -->
    <button
      class="flex items-center gap-2.5 w-full min-h-[48px] px-3 py-2 text-left bg-transparent border-0 cursor-pointer hover:bg-surface-50 transition-colors"
      type="button"
      :aria-expanded="open"
      :aria-label="`选择 ${fromTitle} 到 ${toTitle} 的通勤方式`"
      :data-testid="`transit-leg-open-${leg.id}`"
      @click="toggleOptions"
    >
      <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white border border-surface-200 text-primary-600">
        <Footprints v-if="activeMode === 'WALKING'" :size="15" aria-hidden="true" />
        <BusFront v-else-if="activeMode === 'TRANSIT'" :size="15" aria-hidden="true" />
        <CarFront v-else :size="15" aria-hidden="true" />
      </span>
      <span class="flex-1 min-w-0 grid gap-0.5">
        <small class="text-[10px] text-surface-400 truncate">{{ fromTitle }} → {{ toTitle }}</small>
        <strong class="text-xs text-surface-700 truncate">
          {{ displayModeLabel() }} · {{ selectionPending ? '保存后计算' : formatMinutes(leg.durationSeconds) }}
        </strong>
      </span>
      <span v-if="!selectionPending && summaryCost !== null" class="text-xs font-semibold text-amber-700 whitespace-nowrap">{{ formatCost(summaryCost) }}</span>
      <ChevronDown :size="15" class="text-surface-400 transition-transform duration-200 shrink-0" :class="{ 'rotate-180': open }" aria-hidden="true" />
    </button>

    <!-- Expanded Options -->
    <div v-if="open" class="border-t border-surface-200 bg-white px-3 py-3 space-y-3">
      <!-- Mode Grid -->
      <div class="grid grid-cols-4 gap-1.5" role="group" aria-label="通勤方式">
        <button
          v-for="mode in (['AUTO', 'WALKING', 'TRANSIT', 'TAXI'] as CommuteMode[])"
          :key="mode"
          class="flex flex-col items-center justify-center gap-1 min-h-[50px] px-1 py-1.5 rounded-lg border text-xs transition-all duration-150 disabled:opacity-40 disabled:cursor-not-allowed"
          :class="activeMode === mode
            ? 'bg-primary-50 border-primary-300 text-primary-700 font-semibold'
            : 'bg-surface-50 border-surface-200 text-surface-500 hover:bg-surface-100 hover:text-surface-700'"
          type="button"
          :aria-pressed="activeMode === mode"
          :disabled="locked && activeMode !== mode"
          data-availability="available"
          :data-testid="`transit-option-${mode}`"
          @click="selectMode(mode)"
        >
          <Sparkles v-if="mode === 'AUTO'" :size="14" aria-hidden="true" />
          <Footprints v-else-if="mode === 'WALKING'" :size="14" aria-hidden="true" />
          <BusFront v-else-if="mode === 'TRANSIT'" :size="14" aria-hidden="true" />
          <CarFront v-else :size="14" aria-hidden="true" />
          <span class="text-[10px]">{{ mode === 'AUTO' ? '自动' : modeLabel(mode) }}</span>
          <Check v-if="activeMode === mode" :size="11" class="text-primary-600" aria-hidden="true" />
        </button>
      </div>

      <!-- Persisted route facts: pending modes are resolved only by the backend. -->
      <div class="flex flex-wrap items-center gap-3 text-xs text-surface-500">
        <span class="inline-flex items-center gap-1"><Clock3 :size="13" aria-hidden="true" />当前 {{ formatMinutes(leg.durationSeconds) }}</span>
        <span v-if="summaryCost !== null" class="inline-flex items-center gap-1"><Coins :size="13" aria-hidden="true" />当前 {{ formatCost(summaryCost) }}</span>
        <span>约 {{ (leg.distanceMeters / 1000).toFixed(1) }} km</span>
      </div>

      <p v-if="selectionPending" :data-testid="`transit-change-${leg.id}`" class="text-xs font-semibold text-primary-700 m-0">
        路线时长、费用与可行性将在保存后由路线服务计算。
      </p>

      <!-- Lock -->
      <label class="flex items-center gap-2 text-xs text-surface-600 cursor-pointer" :data-testid="`transit-lock-${leg.id}`">
        <input type="checkbox" :checked="locked" class="w-4 h-4 rounded accent-primary-600" @change="emit('lock', ($event.target as HTMLInputElement).checked)" />
        锁定此段通勤方式
      </label>

      <!-- Note -->
      <p class="text-[10px] text-surface-400 m-0 leading-relaxed">自动推荐只在保存后由路线服务决定；打车价格为规则估算，不包含动态加价。</p>
    </div>
  </div>
</template>
