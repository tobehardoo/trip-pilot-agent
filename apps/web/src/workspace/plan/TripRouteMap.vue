<script setup lang="ts">
// 旅行路线区块（F-UI-11 Phase 3：真实 Trip 数据）。
// 地图本身是原项目已有的真实组件 components/TripMap.vue（高德 JS SDK）。
// planning 态：路线尚未生成，显示占位而不是伪造路线。
// completed 态：使用真实 Itinerary 数据渲染地图。
import { computed } from 'vue'

import TripMap from '../../components/TripMap.vue'

import type { Trip, Itinerary } from '../../../lib/api'

const props = withDefaults(
  defineProps<{
    trip: Trip
    itinerary?: Itinerary | null
    selectedActivityId?: string | null
    generating?: boolean
  }>(),
  {
    itinerary: null,
    selectedActivityId: null,
    generating: false,
  },
)

const emit = defineEmits<{
  selectActivity: [activityId: string]
}>()

const hasItinerary = computed(() => props.itinerary && props.itinerary.days.length > 0 && !props.generating)
</script>

<template>
  <section class="mt-4" aria-label="旅行路线" data-testid="trip-route-section">
    <div class="mb-2 flex items-baseline justify-between gap-3">
      <h2 class="m-0 text-[13px] font-medium leading-5 text-tp-ink">旅行路线</h2>
    </div>

    <div
      class="route-map h-[320px] w-full overflow-hidden rounded-md border border-tp-line bg-white md:h-[360px] xl:h-[400px]"
      data-testid="trip-route-map"
    >
      <TripMap
        v-if="hasItinerary && itinerary"
        :itinerary="itinerary"
        :selected-activity-id="selectedActivityId"
        :allow-empty-selection="true"
        @select-activity="emit('selectActivity', $event)"
      />

      <div
        v-else
        class="flex h-full flex-col items-center justify-center gap-1.5 bg-tp-panel"
        data-testid="trip-route-placeholder"
      >
        <span class="flex items-center gap-1.5 text-xs leading-5 text-tp-sub">
          <span class="inline-block h-1.5 w-1.5 rounded-full bg-tp-run animate-pulse" aria-hidden="true" />
          {{ generating ? '路线正在生成' : '暂无可定位地点' }}
        </span>
        <span class="text-[11px] leading-4 text-tp-faint">
          {{ generating ? '规划完成后会显示地点与路线' : '行程中的地点生成坐标后会显示在这里' }}
        </span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.route-map :deep([data-testid='trip-map'] > .bg-surface-200) {
  display: none;
}
</style>