<script setup lang="ts">
import type { ClassValue } from 'clsx'
import { cn } from '../../lib/utils'

const props = withDefaults(defineProps<{
  title: string
  description?: string
  class?: ClassValue
}>(), {
  description: undefined,
  class: undefined,
})
</script>

<template>
  <div
    :class="cn(
      'flex min-h-[160px] flex-col items-center justify-center gap-2 rounded border border-dashed border-tp-line px-4 py-6 text-center',
      props.class,
    )"
  >
    <slot name="icon" />
    <h2 class="text-sm font-medium text-tp-sub">{{ title }}</h2>
    <p v-if="description" class="-mt-1 text-xs text-tp-mute">{{ description }}</p>
    <slot />
  </div>
</template>
