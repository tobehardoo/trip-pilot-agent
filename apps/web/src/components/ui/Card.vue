<script setup lang="ts">
// Design Baseline 对齐：4px 圆角、无阴影、悬停只变边框色。
// Baseline 规则 10：Card 仅用于真正需要边界的执行面板类内容，默认优先 Divider。
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
        'rounded border border-tp-line bg-white',
        {
          'hover:border-tp-faint': props.hover,
          'p-0': props.padding === 'none',
          'p-2.5': props.padding === 'sm',
          'p-4': props.padding === 'md',
          'p-5': props.padding === 'lg',
        },
        props.class,
      )
    "
  >
    <slot />
  </div>
</template>
