<script setup lang="ts">
// Design Baseline 对齐：状态徽标降级为纯文字/细边框样式。
// Baseline 规则 11：状态色预算制——success/warning/danger 只用低饱和文字色，无彩色底。
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
        'inline-flex items-center gap-1 rounded font-medium',
        {
          'px-1.5 py-0.5 text-[11px]': size === 'sm',
          'px-2 py-0.5 text-xs': size === 'md',
        },
        {
          'bg-tp-active text-tp-body': variant === 'default',
          'bg-tp-hover text-tp-mute': variant === 'secondary',
          'border border-tp-line text-tp-sub': variant === 'outline',
          'bg-tp-ink text-white': variant === 'accent',
          'text-tp-ok': variant === 'success',
          'text-tp-run': variant === 'warning',
          'text-tp-warn': variant === 'danger',
        },
      )
    "
  >
    <slot />
  </span>
</template>
