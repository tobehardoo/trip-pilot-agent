<script setup lang="ts">
// Design Baseline 对齐（docs/design/DESIGN-BASELINE.md）：
// 6px 圆角、无阴影、tp 中性色；variant 语义保持不变。
// primary = 墨色主按钮；accent/danger 仅用于真正需要强调的状态。
import { cn } from '../../lib/utils'

interface Props {
  variant?: 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger' | 'accent'
  size?: 'sm' | 'md' | 'lg' | 'icon'
  as?: string
  type?: 'button' | 'submit' | 'reset'
  disabled?: boolean
}

withDefaults(defineProps<Props>(), {
  as: 'button',
  type: 'button',
  variant: 'primary',
  size: 'md',
  disabled: false,
})

const variantClasses: Record<string, string> = {
  primary: 'bg-tp-ink text-white hover:bg-[#3D3D3B]',
  secondary: 'bg-tp-active text-tp-body hover:bg-tp-hover hover:text-tp-ink',
  outline: 'border border-tp-line bg-white text-tp-body hover:bg-tp-hover hover:text-tp-ink',
  ghost: 'text-tp-sub hover:bg-tp-hover hover:text-tp-ink',
  danger: 'bg-tp-warn text-white hover:opacity-90',
  accent: 'bg-tp-active text-tp-ink hover:bg-tp-hover',
}

const sizeClasses: Record<string, string> = {
  sm: 'h-7 px-2.5 text-xs rounded-md',
  md: 'h-8 px-3 text-xs rounded-md',
  // B15.1 R3 可访问性闸口：主操作按钮（lg）必须 ≥44px 触控高度。
  lg: 'h-12 px-4 text-sm rounded-md',
  icon: 'h-7 w-7 rounded-md',
}
</script>

<template>
  <component
    :is="as"
    :type="type"
    :disabled="disabled"
    :class="cn(
      'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-xs font-medium transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-tp-sub focus-visible:outline-offset-2 disabled:pointer-events-none disabled:opacity-40',
      variantClasses[variant],
      sizeClasses[size],
    )"
  >
    <slot />
  </component>
</template>
