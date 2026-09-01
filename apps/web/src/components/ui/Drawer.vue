<script setup lang="ts">
import { ref, toRef } from 'vue'
import { X } from 'lucide-vue-next'

import { cn } from '../../lib/utils'
import { useModalFocus } from '../../lib/modal'

const props = withDefaults(defineProps<{
  open: boolean
  title: string
  description?: string
  width?: 'md' | 'lg'
}>(), {
  description: undefined,
  width: 'md',
})

const emit = defineEmits<{
  close: []
}>()

const panel = ref<HTMLElement | null>(null)
const { handleKeydown } = useModalFocus(toRef(props, 'open'), panel, () => emit('close'))
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50"
      role="dialog"
      aria-modal="true"
      :aria-label="title"
      @keydown="handleKeydown"
    >
      <div class="fixed inset-0 bg-tp-ink/20" @click="emit('close')" />
      <div
        ref="panel"
        tabindex="-1"
        :class="cn(
          'absolute right-0 top-0 flex h-full w-full flex-col bg-white border-l border-tp-line',
          width === 'lg' ? 'max-w-lg' : 'max-w-md',
        )"
      >
        <header class="flex items-start justify-between gap-3 border-b border-tp-div px-6 py-4">
          <div class="min-w-0">
            <h2 class="m-0 text-sm font-semibold text-tp-ink">{{ title }}</h2>
            <p v-if="description" class="mb-0 mt-0.5 text-xs text-tp-mute">{{ description }}</p>
          </div>
          <button
            type="button"
            class="rounded p-1 text-tp-mute hover:bg-tp-hover hover:text-tp-ink"
            :aria-label="`关闭${title}`"
            data-modal-initial-focus
            @click="emit('close')"
          >
            <X :size="18" aria-hidden="true" />
          </button>
        </header>
        <div class="flex-1 overflow-y-auto px-6 py-5">
          <slot />
        </div>
      </div>
    </div>
  </Teleport>
</template>
