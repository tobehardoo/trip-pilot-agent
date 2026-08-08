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
  estimateCommuteOptions,
  recommendedCommuteMode,
  type CommuteEstimate,
  type CommuteMode,
  type ConcreteCommuteMode,
} from '../lib/transit'

const props = withDefaults(defineProps<{
  leg: ItineraryTransitLeg
  fromTitle: string
  toTitle: string
  selectedMode: CommuteMode
  availableSeconds?: number
  locked?: boolean
}>(), {
  availableSeconds: undefined,
  locked: false,
})

const emit = defineEmits<{
  select: [mode: ConcreteCommuteMode]
  lock: [locked: boolean]
}>()

const LONG_WALK_REVIEW_SECONDS = 45 * 60
const open = ref(false)
const activeMode = ref<CommuteMode>(props.selectedMode)
const options = computed(() => estimateCommuteOptions(props.leg))
const recommendedMode = computed(() => recommendedCommuteMode(options.value))
const fastestMode = computed(() => [...options.value]
  .sort((left, right) => left.durationSeconds - right.durationSeconds || left.cost - right.cost)[0]?.mode)
const cheapestMode = computed(() => [...options.value]
  .sort((left, right) => left.cost - right.cost || left.durationSeconds - right.durationSeconds)[0]?.mode)
const currentEstimate = computed(() => optionFor(props.leg.mode))
const selectedEstimate = computed(() => optionFor(
  activeMode.value === 'AUTO' ? recommendedMode.value : activeMode.value,
))
const durationDeltaMinutes = computed(() => Math.round(
  (selectedEstimate.value.durationSeconds - currentEstimate.value.durationSeconds) / 60,
))
const costDelta = computed(() => selectedEstimate.value.cost - currentEstimate.value.cost)
const hasConflict = computed(() => props.availableSeconds !== undefined
  && selectedEstimate.value.durationSeconds > props.availableSeconds)

watch(() => props.selectedMode, (mode) => { activeMode.value = mode })

function optionFor(mode: ConcreteCommuteMode): CommuteEstimate {
  return options.value.find((option) => option.mode === mode) ?? options.value[0]
}

function selectMode(mode: CommuteMode) {
  if (props.locked || activeMode.value === mode) return
  activeMode.value = mode
  emit('select', mode === 'AUTO' ? recommendedMode.value : mode)
}

function toggleOptions() {
  open.value = !open.value
  if (
    !open.value
    || props.locked
    || props.leg.mode !== 'WALKING'
    || props.leg.durationSeconds <= LONG_WALK_REVIEW_SECONDS
    || recommendedMode.value === 'WALKING'
  ) return
  selectMode(recommendedMode.value)
}

function modeHasConflict(mode: CommuteMode) {
  if (props.availableSeconds === undefined) return false
  const concreteMode = mode === 'AUTO' ? recommendedMode.value : mode
  return optionFor(concreteMode).durationSeconds > props.availableSeconds
}

function modeAvailability(mode: CommuteMode) {
  return modeHasConflict(mode) ? 'requires-replan' : 'available'
}

function modeLabel(mode: ConcreteCommuteMode) {
  return {
    WALKING: '步行',
    TRANSIT: '公交/地铁',
    DRIVING: '驾车',
    TAXI: '打车',
  }[mode]
}

function displayModeLabel() {
  if (activeMode.value === 'AUTO') return `自动 · ${modeLabel(recommendedMode.value)}`
  return modeLabel(activeMode.value)
}

function formatMinutes(seconds: number) {
  return `${Math.max(1, Math.round(seconds / 60))} 分钟`
}

function formatCost(cost: number) {
  return cost === 0 ? '¥0' : `约 ¥${cost.toFixed(cost % 1 === 0 ? 0 : 2)}`
}

function deltaText() {
  const time = durationDeltaMinutes.value === 0
    ? '时间不变'
    : durationDeltaMinutes.value < 0
      ? `节省 ${Math.abs(durationDeltaMinutes.value)} 分钟`
      : `增加 ${durationDeltaMinutes.value} 分钟`
  const money = Math.abs(costDelta.value) < 0.01
    ? '费用不变'
    : costDelta.value < 0
      ? `节省 ¥${Math.abs(costDelta.value).toFixed(2)}`
      : `增加 ¥${costDelta.value.toFixed(2)}`
  return `${time} · ${money}`
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
        <Footprints v-if="selectedEstimate.mode === 'WALKING'" :size="15" aria-hidden="true" />
        <BusFront v-else-if="selectedEstimate.mode === 'TRANSIT'" :size="15" aria-hidden="true" />
        <CarFront v-else :size="15" aria-hidden="true" />
      </span>
      <span class="flex-1 min-w-0 grid gap-0.5">
        <small class="text-[10px] text-surface-400 truncate">{{ fromTitle }} → {{ toTitle }}</small>
        <strong class="text-xs text-surface-700 truncate">{{ displayModeLabel() }} · {{ formatMinutes(selectedEstimate.durationSeconds) }}</strong>
      </span>
      <span class="text-xs font-semibold text-amber-700 whitespace-nowrap">{{ formatCost(selectedEstimate.cost) }}</span>
      <ChevronDown :size="15" class="text-surface-400 transition-transform duration-200 shrink-0" :class="{ 'rotate-180': open }" aria-hidden="true" />
    </button>

    <!-- Expanded Options -->
    <div v-if="open" class="border-t border-surface-200 bg-white px-3 py-3 space-y-3">
      <!-- Highlights -->
      <div class="flex flex-wrap gap-1.5 text-[10px] text-surface-500">
        <span class="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-amber-50 text-amber-700 font-medium">
          <Sparkles :size="11" aria-hidden="true" />推荐 {{ modeLabel(recommendedMode) }}
        </span>
        <span class="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-surface-100">最快 {{ modeLabel(fastestMode!) }}</span>
        <span class="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-surface-100">最省钱 {{ modeLabel(cheapestMode!) }}</span>
      </div>

      <!-- Mode Grid -->
      <div class="grid grid-cols-5 gap-1.5" role="group" aria-label="通勤方式">
        <button
          v-for="mode in (['AUTO', 'WALKING', 'TRANSIT', 'DRIVING', 'TAXI'] as CommuteMode[])"
          :key="mode"
          class="flex flex-col items-center justify-center gap-1 min-h-[50px] px-1 py-1.5 rounded-lg border text-xs transition-all duration-150 disabled:opacity-40 disabled:cursor-not-allowed"
          :class="activeMode === mode
            ? 'bg-primary-50 border-primary-300 text-primary-700 font-semibold'
            : 'bg-surface-50 border-surface-200 text-surface-500 hover:bg-surface-100 hover:text-surface-700'"
          type="button"
          :aria-pressed="activeMode === mode"
          :disabled="locked && activeMode !== mode"
          :data-availability="modeAvailability(mode)"
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

      <!-- Estimate Row -->
      <div class="flex flex-wrap items-center gap-3 text-xs text-surface-500">
        <span class="inline-flex items-center gap-1"><Clock3 :size="13" aria-hidden="true" />{{ formatMinutes(selectedEstimate.durationSeconds) }}</span>
        <span class="inline-flex items-center gap-1"><Coins :size="13" aria-hidden="true" />{{ formatCost(selectedEstimate.cost) }}</span>
        <span>约 {{ (leg.distanceMeters / 1000).toFixed(1) }} km</span>
      </div>

      <!-- Delta -->
      <p :data-testid="`transit-change-${leg.id}`" class="text-xs font-semibold text-primary-700 m-0">{{ deltaText() }}</p>

      <!-- Conflict Warning -->
      <p v-if="hasConflict" class="rounded-lg bg-red-50 border-l-4 border-red-400 px-3 py-2 text-xs text-red-700 m-0" role="alert">
        当前交通方式超出活动间隔，需要调整活动时间后才能提交。
      </p>

      <!-- Lock -->
      <label class="flex items-center gap-2 text-xs text-surface-600 cursor-pointer" :data-testid="`transit-lock-${leg.id}`">
        <input type="checkbox" :checked="locked" class="w-4 h-4 rounded accent-primary-600" @change="emit('lock', ($event.target as HTMLInputElement).checked)" />
        锁定此段通勤方式
      </label>

      <!-- Note -->
      <p class="text-[10px] text-surface-400 m-0 leading-relaxed">公交、驾车和打车为距离估算；打车价格不包含动态加价，驾车费用不包含停车费。</p>
    </div>
  </div>
</template>
