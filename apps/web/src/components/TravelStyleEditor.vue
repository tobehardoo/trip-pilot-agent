<script setup lang="ts">
import type { ConstraintEditorModel } from '../lib/constraint-editor'

const props = withDefaults(defineProps<{
  model: ConstraintEditorModel
  preferenceOptions?: string[]
}>(), {
  preferenceOptions: () => [],
})

function togglePreference(preference: string) {
  const index = props.model.preferences.indexOf(preference)
  if (index >= 0) props.model.preferences.splice(index, 1)
  else props.model.preferences.push(preference)
}

const inputClass = 'w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow'
</script>

<template>
  <!-- B13-G: one merged "旅行方式与偏好" region.  The domain fields stay
       independent — this is a UI-only merge. -->
  <fieldset class="mt-5 border-0 p-0" aria-label="旅行方式与偏好">
    <legend class="mb-3 text-sm font-bold text-surface-800">旅行方式与偏好</legend>
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <div>
        <span class="mb-1.5 block text-xs font-semibold text-surface-600">旅行节奏</span>
        <div class="grid grid-cols-3 rounded-xl bg-surface-100 p-1">
          <label
            v-for="pace in [{v:'RELAXED',l:'舒缓'},{v:'BALANCED',l:'均衡'},{v:'INTENSIVE',l:'紧凑'}]"
            :key="pace.v"
            class="flex h-9 cursor-pointer items-center justify-center rounded-lg text-sm font-medium"
            :class="model.pace === pace.v ? 'bg-white text-primary-700 shadow-sm' : 'text-surface-500'"
          >
            <input v-model="model.pace" type="radio" :value="pace.v" class="sr-only" />{{ pace.l }}
          </label>
        </div>
      </div>
      <div>
        <span class="mb-1.5 block text-xs font-semibold text-surface-600">行动能力</span>
        <select v-model="model.mobilityLevel" :class="inputClass" aria-label="行动能力">
          <option value="STANDARD">标准步行</option>
          <option value="REDUCED">减少步行</option>
          <option value="STEP_FREE">尽量无台阶（车行接驳，场地需确认）</option>
        </select>
      </div>
      <div class="sm:col-span-2">
        <span class="mb-1.5 block text-xs font-semibold text-surface-600">偏好</span>
        <div class="flex flex-wrap gap-2">
          <label
            v-for="preference in preferenceOptions"
            :key="preference"
            class="inline-flex cursor-pointer items-center rounded-xl border px-3 py-2 text-sm font-medium"
            :class="model.preferences.includes(preference)
              ? 'border-primary-300 bg-primary-50 text-primary-700'
              : 'border-surface-200 text-surface-600'"
          >
            <input
              type="checkbox"
              :checked="model.preferences.includes(preference)"
              class="sr-only"
              @change="togglePreference(preference)"
            />{{ preference }}
          </label>
        </div>
      </div>
    </div>
  </fieldset>
</template>
