<script setup lang="ts">
// 未规划 draft 视图（F-UI-11 Phase 3：真实 Trip 数据，不再伪装）。
// 展示旅行标题 + 状态"还没有开始规划" + 约束信息 + "继续完善旅行"入口。
import { computed } from 'vue'

import { constraintRows } from '../lib/present'
import type { Trip } from '../../lib/api'

const props = defineProps<{
  trip: Trip
}>()

const emit = defineEmits<{
  editConstraints: []
}>()

const rows = computed(() => constraintRows(props.trip))
</script>

<template>
  <article class="mx-auto w-full max-w-2xl px-6 py-5" data-testid="trip-draft-view" aria-label="未规划旅行">
    <header class="mb-4">
      <h1 class="m-0 text-lg font-semibold leading-6 tracking-tight text-tp-ink">{{ trip.title }}</h1>
      <p class="m-0 mt-1 flex items-center gap-1.5 text-xs leading-4 text-tp-sub">
        <span class="inline-block h-1.5 w-1.5 rounded-full bg-tp-dot" aria-hidden="true" />
        还没有开始规划
      </p>
    </header>

    <div class="border-t border-tp-div" role="separator" />

    <!-- 约束信息 -->
    <section class="mt-4" aria-label="旅行约束">
      <h2 class="m-0 mb-1.5 text-[13px] font-medium leading-5 text-tp-ink">旅行约束</h2>
      <dl class="m-0 space-y-1">
        <div
          v-for="row in rows"
          :key="row.label"
          class="flex items-baseline justify-between gap-3"
        >
          <dt class="m-0 shrink-0 text-[11px] leading-5 text-tp-mute">{{ row.label }}</dt>
          <dd class="m-0 min-w-0 truncate text-right text-xs leading-5 text-tp-body">{{ row.value }}</dd>
        </div>
      </dl>
    </section>

    <div class="mt-4 border-t border-tp-div" role="separator" />

    <!-- 引导入口 -->
    <div class="mt-4 flex flex-wrap items-center gap-2.5">
      <button
        type="button"
        class="flex h-8 items-center rounded-md bg-tp-ink px-3 text-xs font-medium text-white transition-colors hover:bg-[#3D3D3B]"
        data-testid="trip-draft-edit-constraints"
        @click="emit('editConstraints')"
      >
        继续完善旅行
      </button>
      <span class="text-[11px] leading-4 text-tp-mute">约束完善后即可启动规划（真实 AI 规划通道）</span>
    </div>
  </article>
</template>
