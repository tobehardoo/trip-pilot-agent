<script setup lang="ts">
/**
 * B13-E: the two journey boundaries as Asia/Shanghai datetimes.
 *
 * datetime-local inputs hold a China wall-clock value; on change the
 * component emits the canonical +08:00 OffsetDateTime strings consumed by
 * the server (which derives startDate/endDate in Asia/Shanghai).
 */
import { computed } from 'vue'

const props = defineProps<{
  arrivalAt: string
  departureAt: string
}>()

const emit = defineEmits<{
  'update:arrivalAt': [value: string]
  'update:departureAt': [value: string]
}>()

const error = computed(() => {
  if (props.arrivalAt && props.departureAt && props.arrivalAt >= props.departureAt) {
    return '抵达时间必须早于离开时间'
  }
  return null
})

function onArrival(event: Event) {
  emit('update:arrivalAt', (event.target as HTMLInputElement).value)
}

function onDeparture(event: Event) {
  emit('update:departureAt', (event.target as HTMLInputElement).value)
}
</script>

<template>
  <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
    <div>
      <label for="arrival-at" class="block text-xs font-semibold text-surface-600 mb-1.5">抵达时间</label>
      <input
        id="arrival-at"
        type="datetime-local"
        :value="arrivalAt"
        required
        class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow"
        @input="onArrival"
      />
    </div>
    <div>
      <label for="departure-at" class="block text-xs font-semibold text-surface-600 mb-1.5">离开时间</label>
      <input
        id="departure-at"
        type="datetime-local"
        :value="departureAt"
        :min="arrivalAt"
        required
        class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow"
        @input="onDeparture"
      />
    </div>
    <p v-if="error" class="sm:col-span-2 m-0 text-xs text-red-600" role="alert">{{ error }}</p>
  </div>
</template>
