<script setup lang="ts">
import type { ConstraintEditorModel } from '../lib/constraint-editor'

const props = defineProps<{
  model: ConstraintEditorModel
  mode: 'create' | 'edit'
  preferenceOptions: string[]
}>()

function fieldId(name: string) {
  return `${props.mode}-${name}`
}

function togglePreference(preference: string) {
  const index = props.model.preferences.indexOf(preference)
  if (index >= 0) props.model.preferences.splice(index, 1)
  else props.model.preferences.push(preference)
}

const inputClass = 'w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow'
</script>

<template>
  <div data-testid="constraint-editor" :data-mode="mode">
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <div>
        <label :for="fieldId('budget')" class="mb-1.5 block text-xs font-semibold text-surface-600">预算</label>
        <div class="flex h-10 items-center gap-2 rounded-xl border border-surface-200 bg-white px-3 focus-within:border-primary-400 focus-within:ring-2 focus-within:ring-primary-400/40">
          <span class="text-sm text-surface-400">¥</span>
          <input
            :id="fieldId('budget')"
            v-model="model.budgetAmount"
            type="number"
            min="0"
            step="0.01"
            class="h-full w-full border-0 bg-transparent text-sm outline-0"
            :data-modal-initial-focus="mode === 'edit' || undefined"
          />
        </div>
      </div>
      <div>
        <label :for="fieldId('travelers')" class="mb-1.5 block text-xs font-semibold text-surface-600">同行人数</label>
        <input :id="fieldId('travelers')" v-model.number="model.travelers" type="number" min="1" max="50" required :class="inputClass" />
      </div>
      <div class="sm:col-span-2">
        <label :for="fieldId('traveler-type')" class="mb-1.5 block text-xs font-semibold text-surface-600">同行类型</label>
        <select :id="fieldId('traveler-type')" v-model="model.travelerType" required :class="inputClass">
          <option value="SOLO">独自出行</option><option value="COUPLE">伴侣同行</option>
          <option value="FAMILY">家庭出行</option><option value="FRIENDS">朋友同行</option>
          <option value="BUSINESS">商务出行</option>
        </select>
      </div>
      <div>
        <label :for="fieldId('arrival-place')" class="mb-1.5 block text-xs font-semibold text-surface-600">到达地点</label>
        <input :id="fieldId('arrival-place')" v-model.trim="model.arrivalPlace" maxlength="120" :class="inputClass" />
      </div>
      <div>
        <label :for="fieldId('arrival-time')" class="mb-1.5 block text-xs font-semibold text-surface-600">到达时间（北京时间）</label>
        <input :id="fieldId('arrival-time')" v-model="model.arrivalTime" type="datetime-local" :class="inputClass" />
      </div>
      <div>
        <label :for="fieldId('departure-place')" class="mb-1.5 block text-xs font-semibold text-surface-600">返程地点</label>
        <input :id="fieldId('departure-place')" v-model.trim="model.departurePlace" maxlength="120" :class="inputClass" />
      </div>
      <div>
        <label :for="fieldId('departure-time')" class="mb-1.5 block text-xs font-semibold text-surface-600">返程时间（北京时间）</label>
        <input :id="fieldId('departure-time')" v-model="model.departureTime" type="datetime-local" :class="inputClass" />
      </div>
      <div class="sm:col-span-2">
        <label :for="fieldId('accommodation')" class="mb-1.5 block text-xs font-semibold text-surface-600">住宿锚点</label>
        <input :id="fieldId('accommodation')" v-model.trim="model.accommodationPlace" maxlength="120" :class="inputClass" />
      </div>
      <div>
        <label :for="fieldId('must-visit')" class="mb-1.5 block text-xs font-semibold text-surface-600">必去地点（用顿号分隔）</label>
        <input :id="fieldId('must-visit')" v-model="model.mustVisitText" maxlength="1000" :class="inputClass" />
      </div>
      <div>
        <label :for="fieldId('avoid')" class="mb-1.5 block text-xs font-semibold text-surface-600">排除地点（用顿号分隔）</label>
        <input :id="fieldId('avoid')" v-model="model.avoidText" maxlength="1000" :class="inputClass" />
      </div>
      <div class="sm:col-span-2">
        <label :for="fieldId('mobility')" class="mb-1.5 block text-xs font-semibold text-surface-600">行动能力</label>
        <select :id="fieldId('mobility')" v-model="model.mobilityLevel" :class="inputClass">
          <option value="STANDARD">标准步行</option><option value="REDUCED">减少步行</option>
          <option value="STEP_FREE">尽量无台阶（车行接驳，场地需确认）</option>
        </select>
      </div>
      <div v-for="meal in [{ key: 'breakfast', label: '早餐' }, { key: 'lunch', label: '午餐' }, { key: 'dinner', label: '晚餐' }]" :key="meal.key" class="sm:col-span-2">
        <span class="mb-1.5 block text-xs font-semibold text-surface-600">{{ meal.label }}窗口</span>
        <div class="flex items-center gap-3">
          <input v-model="model[`${meal.key}Start` as 'breakfastStart' | 'lunchStart' | 'dinnerStart']" type="time" :aria-label="`${meal.label}开始时间`" :class="inputClass" />
          <span class="text-sm text-surface-400">至</span>
          <input v-model="model[`${meal.key}End` as 'breakfastEnd' | 'lunchEnd' | 'dinnerEnd']" type="time" :aria-label="`${meal.label}结束时间`" :class="inputClass" />
        </div>
      </div>
    </div>

    <fieldset class="mt-5 border-0 p-0">
      <legend class="mb-2 text-xs font-semibold text-surface-600">旅行节奏</legend>
      <div class="grid grid-cols-3 rounded-xl bg-surface-100 p-1">
        <label v-for="pace in [{v:'RELAXED',l:'舒缓'},{v:'BALANCED',l:'均衡'},{v:'INTENSIVE',l:'紧凑'}]" :key="pace.v" class="flex h-9 cursor-pointer items-center justify-center rounded-lg text-sm font-medium" :class="model.pace === pace.v ? 'bg-white text-primary-700 shadow-sm' : 'text-surface-500'">
          <input v-model="model.pace" type="radio" :value="pace.v" class="sr-only" />{{ pace.l }}
        </label>
      </div>
    </fieldset>
    <fieldset class="mt-5 border-0 p-0">
      <legend class="mb-2 text-xs font-semibold text-surface-600">偏好</legend>
      <div class="flex flex-wrap gap-2">
        <label v-for="preference in preferenceOptions" :key="preference" class="inline-flex cursor-pointer items-center rounded-xl border px-3 py-2 text-sm font-medium" :class="model.preferences.includes(preference) ? 'border-primary-300 bg-primary-50 text-primary-700' : 'border-surface-200 text-surface-600'">
          <input type="checkbox" :checked="model.preferences.includes(preference)" class="sr-only" @change="togglePreference(preference)" />{{ preference }}
        </label>
      </div>
    </fieldset>
  </div>
</template>
