<script setup lang="ts">
import { cn } from '../../lib/utils'

interface Props {
  variant?: 'default' | 'secondary' | 'outline' | 'accent' | 'success' | 'warning' | 'danger'
  size?: 'sm' | 'md'
}

withDefaults(defineProps<Props>(), {
  variant: 'default',
  size: 'sm',
})
</script>

<template>
  <span
    :class="
      cn(
        'inline-flex items-center gap-1 rounded-lg font-medium',
        {
          'px-2 py-0.5 text-xs': size === 'sm',
          'px-3 py-1 text-sm': size === 'md',
        },
        {
          'bg-primary-100 text-primary-700': variant === 'default',
          'bg-surface-200 text-surface-600': variant === 'secondary',
          'border border-surface-300 text-surface-600': variant === 'outline',
          'bg-primary-600 text-white': variant === 'accent',
          'bg-emerald-100 text-emerald-700': variant === 'success',
          'bg-amber-100 text-amber-700': variant === 'warning',
          'bg-red-100 text-red-700': variant === 'danger',
        },
      )
    "
  >
    <slot />
  </span>
</template>
