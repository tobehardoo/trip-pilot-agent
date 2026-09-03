<script setup lang="ts">
// 旅行概览（重新设计：A+ 摘要卡）。
// Hero 卡片承载「目的地 + 日期 + 关键数据徽章」，替换旧版纯文本 header，
// 统一到 tp-* 视觉语言。徽章行把天数/人数/预算/偏好做成一眼可读的密度块。
import { computed } from 'vue'

import type { ItineraryActivity, Trip } from '../../lib/api'
import { formatChinaDate, formatChinaMoney, daySpanOfRange } from '../lib/present'

const props = defineProps<{
  trip: Trip
  /** B1：供预算徽标注记「含估算」费用来源 */
  activities?: ItineraryActivity[]
}>()

const days = computed(() => daySpanOfRange(props.trip.startDate, props.trip.endDate))

/** 行程中存在任一活动为非 PROVIDER（估算类）费用来源时提示用户。 */
const hasEstimatedCost = computed(() =>
  (props.activities ?? []).some((activity) =>
    (activity.costSource ?? 'UNKNOWN') !== 'PROVIDER',
  ),
)

const metaLine = computed(() =>
  [
    props.trip.destination,
    props.trip.startDate && props.trip.endDate
      ? `${formatChinaDate(props.trip.startDate)} — ${formatChinaDate(props.trip.endDate)}`
      : null,
  ]
    .filter((part) => part && part !== '未设置')
    .join(' · '),
)

// 关键数据徽章：只展示真实可用的字段，缺失自动隐藏。
const stats = computed(() => {
  const constraints = props.trip.constraints
  const items: Array<{ label: string; value: string; hint?: string }> = []
  if (days.value) items.push({ label: '天数', value: `${days.value} 天` })
  items.push({ label: '人数', value: `${constraints.travelers} 人` })
  if (constraints.budgetAmount != null && constraints.budgetAmount !== 0) {
    items.push({
      label: '预算',
      value: formatChinaMoney(constraints.budgetAmount),
      hint: hasEstimatedCost.value ? '含估算' : undefined,
    })
  }
  if (constraints.preferences.length > 0) {
    items.push({ label: '节奏偏好', value: constraints.preferences.join(' · ') })
  }
  return items
})
</script>

<template>
  <header>
    <p class="m-0 text-[11px] font-medium uppercase tracking-[0.14em] text-tp-faint" data-testid="plan-overview-kicker">
      TripPilot · 完整方案
    </p>
    <h1 class="m-0 mt-1 text-xl font-semibold leading-7 tracking-tight text-tp-ink" data-testid="plan-overview-title">
      {{ trip.title }}
    </h1>
    <p class="m-0 mt-1 text-xs leading-5 text-tp-sub" data-testid="plan-header-meta">{{ metaLine }}</p>

    <dl class="m-0 mt-4 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4" data-testid="plan-overview-stats">
      <template v-for="stat in stats" :key="stat.label">
        <div class="rounded-lg border border-tp-line bg-tp-panel px-3 py-2">
          <dt class="m-0 flex items-center gap-1.5 text-[11px] leading-4 text-tp-mute">{{ stat.label }}</dt>
          <dd class="m-0 mt-0.5 flex items-center gap-1.5 truncate text-[13px] font-medium leading-5 text-tp-ink" :title="stat.value">
            {{ stat.value }}
            <span
              v-if="stat.hint"
              class="shrink-0 rounded-full bg-tp-ok/10 px-1.5 py-0.5 text-[10px] font-medium leading-3 text-tp-ok"
              title="行程中存在按规则/品类/城市估算的费用，非真实报价"
              data-testid="plan-overview-budget-estimated"
            >{{ stat.hint }}</span>
          </dd>
        </div>
      </template>
    </dl>
  </header>
</template>