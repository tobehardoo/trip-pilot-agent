<script setup lang="ts">
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
  primary: 'bg-primary-600 text-white shadow-sm hover:bg-primary-700 hover:shadow-md',
  secondary: 'bg-surface-100 text-surface-700 hover:bg-surface-200 hover:text-surface-900',
  outline: 'border border-surface-300 bg-white text-surface-700 hover:bg-surface-50 hover:border-surface-400 hover:text-surface-900',
  ghost: 'text-surface-600 hover:bg-surface-100 hover:text-surface-900',
  danger: 'bg-red-600 text-white shadow-sm hover:bg-red-700 hover:shadow-md',
  accent: 'bg-primary-50 text-primary-700 hover:bg-primary-100 hover:text-primary-800',
}

const sizeClasses: Record<string, string> = {
  sm: 'h-8 px-3 text-xs rounded-lg',
  md: 'h-10 px-4 text-sm',
  lg: 'h-12 px-6 text-base rounded-2xl',
  icon: 'h-9 w-9 rounded-xl',
}
</script>

<template>
  <component
    :is="as"
    :type="type"
    :disabled="disabled"
    :class="cn(
      'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-medium transition-all duration-200 focus-visible:outline-2 focus-visible:outline-primary-500 focus-visible:outline-offset-2 disabled:pointer-events-none disabled:opacity-40 active:scale-[0.97]',
      variantClasses[variant],
      sizeClasses[size],
    )"
  >
    <slot />
  </component>
</template>
