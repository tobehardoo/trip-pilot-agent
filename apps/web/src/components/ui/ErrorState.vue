<script setup lang="ts">
import type { ClassValue } from 'clsx'
import { cn } from '../../lib/utils'

const props = withDefaults(defineProps<{
  message: string
  class?: ClassValue
}>(), {
  class: undefined,
})
</script>

<template>
  <p
    role="alert"
    :class="cn(
      'rounded border border-tp-line bg-white px-3 py-2 text-xs text-tp-warn',
      props.class,
    )"
  >{{ message }}</p>
</template>
