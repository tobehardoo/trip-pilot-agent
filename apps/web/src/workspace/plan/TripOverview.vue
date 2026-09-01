<script setup lang="ts">
// 旅行概览（F-UI-11 Phase 3：真实 Trip 数据）。
// 不是大 Hero Card：大标题 + 小号辅助信息 + 几个紧凑数据项，然后 Divider。
import { computed } from 'vue'

import type { Trip } from '../../lib/api'
import { formatChinaDate, formatChinaMoney, daySpanOfRange } from '../lib/present'

const props = defineProps<{
  trip: Trip
}>()

const days = computed(() => daySpanOfRange(props.trip.startDate, props.trip.endDate))

const metaLine = computed(() =>
  [
    props.trip.destination,
    props.trip.startDate && props.trip.endDate
      ? `${formatChinaDate(props.trip.startDate)} — ${formatChinaDate(props.trip.endDate)}`
      : null,
    days.value ? `${days.value} 天` : null,
    `${props.trip.constraints.travelers} 人`,
    formatChinaMoney(props.trip.constraints.budgetAmount),
  ]
    .filter((part) => part && part !== '未设置')
    .join(' · '),
)

const preferences = computed(() => {
  const prefs = props.trip.constraints.preferences
  return prefs.length > 0 ? prefs.join(' · ') : null
})
</script>

<template>
  <header>
    <h1 class="m-0 text-lg font-semibold leading-6 tracking-tight text-tp-ink">{{ trip.title }}</h1>
    <p class="m-0 mt-1 text-xs leading-4 text-tp-sub" data-testid="plan-header-meta">{{ metaLine }}</p>
    <p
      v-if="preferences"
      class="m-0 mt-0.5 text-[11px] leading-4 text-tp-mute"
      data-testid="plan-header-preferences"
    >
      {{ preferences }}
    </p>
  </header>
</template>