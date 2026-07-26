<script setup lang="ts">
import type { ClassValue } from 'clsx'
import { cn } from '../../lib/utils'

const props = withDefaults(defineProps<{
  class?: ClassValue
  hover?: boolean
  padding?: 'none' | 'sm' | 'md' | 'lg'
}>(), {
  class: undefined,
  hover: false,
  padding: 'md',
})
</script>

<template>
  <div
    :class="
      cn(
        'rounded-2xl border border-surface-200/60 bg-white shadow-card transition-all duration-300',
        {
          'hover:shadow-card-hover hover:border-surface-300/80': props.hover,
          'p-0': props.padding === 'none',
          'p-3': props.padding === 'sm',
          'p-5': props.padding === 'md',
          'p-7': props.padding === 'lg',
        },
        props.class,
      )
    "
  >
    <slot />
  </div>
</template>
