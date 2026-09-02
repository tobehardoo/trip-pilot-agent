<script setup lang="ts">
// 通用"加载 / 出错可重试"状态（P0：completed 但方案未就绪时不得展示假成功）。
// loading 时显示进行中；error 时显示错误 + 重试按钮。
defineProps<{
  loading: boolean
  error: string | null
}>()

const emit = defineEmits<{ retry: [] }>()
</script>

<template>
  <p v-if="loading" class="m-0 flex items-center gap-2 text-xs leading-4 text-tp-sub" data-testid="workspace-itinerary-loading">
    <span class="inline-block h-1.5 w-1.5 rounded-full bg-tp-run animate-pulse" aria-hidden="true" />
    正在加载旅行方案……
  </p>
  <template v-else>
    <p class="m-0 text-xs leading-5 text-tp-mute" data-testid="workspace-itinerary-empty">
      行程已完成，但方案数据当前不可用。
    </p>
    <p v-if="error" class="m-0 mt-1 text-xs leading-4 text-tp-danger" data-testid="workspace-itinerary-error">
      {{ error }}
    </p>
    <button
      type="button"
      class="mt-3 flex h-7 items-center rounded-md border border-tp-line bg-white px-3 text-xs text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
      data-testid="workspace-itinerary-retry"
      @click="emit('retry')"
    >
      重新加载方案
    </button>
  </template>
</template>