<script setup lang="ts">
import type { ClassValue } from 'clsx'
import { cn } from '../../lib/utils'

const props = withDefaults(defineProps<{
  label?: string
  minHeight?: string
  class?: ClassValue
}>(), {
  label: '加载中',
  minHeight: '300px',
  class: undefined,
})
</script>

<template>
  <div
    role="status"
    :style="{ minHeight: props.minHeight }"
    :class="cn('flex items-center justify-center gap-2', props.class)"
  >
    <span class="h-2 w-2 animate-pulse rounded-full bg-tp-dot" />
    <span class="h-2 w-2 animate-pulse rounded-full bg-tp-dot" style="animation-delay: 0.2s" />
    <span class="h-2 w-2 animate-pulse rounded-full bg-tp-dot" style="animation-delay: 0.4s" />
    <span class="sr-only">{{ props.label }}</span>
  </div>
</template>
