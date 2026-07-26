<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { cn } from '../../lib/utils'

const props = withDefaults(defineProps<{
  open: boolean
  class?: string
}>(), {
  class: undefined,
})

const emit = defineEmits<{
  close: []
}>()

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <Transition name="dialog">
      <div
        v-if="open"
        class="fixed inset-0 z-50 flex items-start justify-center pt-[10vh] sm:pt-[15vh]"
      >
        <!-- Backdrop -->
        <div
          class="fixed inset-0 bg-surface-900/30 backdrop-blur-sm transition-opacity duration-300"
          @click="emit('close')"
          aria-hidden="true"
        />

        <!-- Dialog -->
        <div
          :class="
            cn(
              'relative mx-4 w-full max-w-lg animate-scale-in rounded-3xl bg-white shadow-dialog ring-1 ring-black/5 overflow-hidden',
              props.class,
            )
          "
          role="dialog"
          aria-modal="true"
        >
          <slot />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.dialog-enter-active {
  transition: opacity 0.3s ease;
}
.dialog-leave-active {
  transition: opacity 0.2s ease;
}
.dialog-enter-from,
.dialog-leave-to {
  opacity: 0;
}
</style>
