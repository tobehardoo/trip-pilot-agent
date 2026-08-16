<script setup lang="ts">
import { MEAL_DEFAULT_WINDOWS, type ConstraintEditorModel, type PlaceEntry } from '../lib/constraint-editor'
import type { PlaceRef } from '../lib/api'
import PlaceAutocomplete from './PlaceAutocomplete.vue'
import TravelStyleEditor from './TravelStyleEditor.vue'

const props = withDefaults(defineProps<{
  model: ConstraintEditorModel
  mode: 'create' | 'edit'
  preferenceOptions: string[]
  city?: string
  getToken?: () => string
}>(), {
  city: '',
  getToken: () => '',
})

function fieldId(name: string) {
  return `${props.mode}-${name}`
}

const inputClass = 'w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow'

const mealOptions = [
  { key: 'breakfast', label: '早餐', mealType: 'BREAKFAST' as const },
  { key: 'lunch', label: '午餐', mealType: 'LUNCH' as const },
  { key: 'dinner', label: '晚餐', mealType: 'DINNER' as const },
]

function defaultWindowLabel(mealType: 'BREAKFAST' | 'LUNCH' | 'DINNER') {
  const [start, end] = MEAL_DEFAULT_WINDOWS[mealType]
  return `${start}–${end}`
}

/** B13-D: add a structured candidate (or legacy name) to a place list. */
function addEntry(list: PlaceEntry[], entry: PlaceEntry) {
  const name = entry.name.trim()
  if (!name) return
  if (!list.some((item) => item.name === name)) {
    list.push({ name, placeRef: entry.placeRef })
  }
}

function removeEntry(list: PlaceEntry[], index: number) {
  list.splice(index, 1)
}

/** B13_FIX R5: pick an anchor from candidates; keeps the server-issued
 * selection token so the save can canonicalize the ref. */
function pickAnchor(
  kind: 'arrival' | 'departure' | 'accommodation',
  ref: PlaceRef | null,
) {
  if (kind === 'arrival') {
    props.model.arrivalPlace = ref?.name ?? ''
    props.model.arrivalRef = ref ?? undefined
  } else if (kind === 'departure') {
    props.model.departurePlace = ref?.name ?? ''
    props.model.departureRef = ref ?? undefined
  } else {
    props.model.accommodationPlace = ref?.name ?? ''
    props.model.accommodationRef = ref ?? undefined
  }
}

/** B13_FIX R5: typed (unpicked) anchor text stays a legacy text anchor —
 * it never fabricates a ref; picking a candidate replaces it. */
function typeAnchor(kind: 'arrival' | 'departure' | 'accommodation', text: string) {
  if (kind === 'arrival') {
    props.model.arrivalPlace = text
    props.model.arrivalRef = undefined
  } else if (kind === 'departure') {
    props.model.departurePlace = text
    props.model.departureRef = undefined
  } else {
    props.model.accommodationPlace = text
    props.model.accommodationRef = undefined
  }
}
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
        <PlaceAutocomplete
          :label="'到达地点'"
          :city="city"
          :get-token="getToken"
          :model-value="model.arrivalRef ?? null"
          :placeholder="model.arrivalRef ? model.arrivalRef.name : (model.arrivalPlace || '搜索车站、机场等到达地点')"
          @update:model-value="(ref: PlaceRef | null) => pickAnchor('arrival', ref)"
          @update:text="(text: string) => typeAnchor('arrival', text)"
        />
        <p v-if="model.arrivalPlace && !model.arrivalRef" class="mt-1 text-[11px] text-surface-400">
          自由文本地点保持原样，重新搜索选择后才会成为结构化地点
        </p>
      </div>
      <div>
        <label :for="fieldId('arrival-time')" v-if="mode === 'edit'" class="mb-1.5 block text-xs font-semibold text-surface-600">到达时间（北京时间）</label>
        <input
          v-if="mode === 'edit'"
          :id="fieldId('arrival-time')"
          v-model="model.arrivalTime"
          type="datetime-local"
          :class="inputClass"
        />
        <!-- B13_FIX R6 (P1-3): the create page owns exactly two datetime
             inputs (TripBoundaryEditor); the anchor time is derived from
             the authoritative arrivalAt boundary at save time. -->
        <p v-else-if="model.arrivalPlace" class="text-xs text-surface-400">
          到达时间沿用抵达时间（{{ model.arrivalTime || '未填' }}）
        </p>
      </div>
      <div>
        <label :for="fieldId('departure-place')" class="mb-1.5 block text-xs font-semibold text-surface-600">返程地点</label>
        <PlaceAutocomplete
          :label="'返程地点'"
          :city="city"
          :get-token="getToken"
          :model-value="model.departureRef ?? null"
          :placeholder="model.departureRef ? model.departureRef.name : (model.departurePlace || '搜索车站、机场等返程地点')"
          @update:model-value="(ref: PlaceRef | null) => pickAnchor('departure', ref)"
          @update:text="(text: string) => typeAnchor('departure', text)"
        />
        <p v-if="model.departurePlace && !model.departureRef" class="mt-1 text-[11px] text-surface-400">
          自由文本地点保持原样，重新搜索选择后才会成为结构化地点
        </p>
      </div>
      <div>
        <label :for="fieldId('departure-time')" v-if="mode === 'edit'" class="mb-1.5 block text-xs font-semibold text-surface-600">返程时间（北京时间）</label>
        <input
          v-if="mode === 'edit'"
          :id="fieldId('departure-time')"
          v-model="model.departureTime"
          type="datetime-local"
          :class="inputClass"
        />
        <p v-else-if="model.departurePlace" class="text-xs text-surface-400">
          返程时间沿用离开时间（{{ model.departureTime || '未填' }}）
        </p>
      </div>
      <div class="sm:col-span-2">
        <label :for="fieldId('accommodation')" class="mb-1.5 block text-xs font-semibold text-surface-600">住宿锚点</label>
        <PlaceAutocomplete
          :label="'住宿锚点'"
          :city="city"
          :get-token="getToken"
          :model-value="model.accommodationRef ?? null"
          :placeholder="model.accommodationRef ? model.accommodationRef.name : (model.accommodationPlace || '搜索酒店等住宿地点')"
          @update:model-value="(ref: PlaceRef | null) => pickAnchor('accommodation', ref)"
          @update:text="(text: string) => typeAnchor('accommodation', text)"
        />
        <p v-if="model.accommodationPlace && !model.accommodationRef" class="mt-1 text-[11px] text-surface-400">
          自由文本地点保持原样，重新搜索选择后才会成为结构化地点
        </p>
      </div>
      <div class="sm:col-span-2">
        <label :for="fieldId('must-visit')" class="mb-1.5 block text-xs font-semibold text-surface-600">必去地点</label>
        <div class="mb-2 flex flex-wrap gap-2">
          <span v-for="(entry, index) in model.mustVisitEntries" :key="`${entry.name}-${index}`" class="inline-flex items-center gap-1 rounded-xl border border-primary-200 bg-primary-50 px-2.5 py-1 text-xs text-primary-800">
            {{ entry.name }}
            <span v-if="entry.placeRef?.provider === 'DEMO'" class="rounded bg-amber-100 px-1 text-[10px] text-amber-700">演示</span>
            <button type="button" :aria-label="`移除必去地点 ${entry.name}`" class="text-primary-400 hover:text-danger-600" @click="removeEntry(model.mustVisitEntries, index)">×</button>
          </span>
        </div>
        <PlaceAutocomplete
          :label="'必去地点'"
          :city="city"
          :get-token="getToken"
          :model-value="null"
          @update:model-value="(ref: PlaceRef | null) => { if (ref) addEntry(model.mustVisitEntries, { name: ref.name, placeRef: ref }) }"
        />
        <p v-if="model.mustVisitEntries.length > 0 && !model.mustVisitEntries.every((entry) => entry.placeRef)" class="mt-1 text-[11px] text-surface-400">
          自由文本地点保持原样，重新搜索选择后才会成为结构化地点
        </p>
      </div>
      <div class="sm:col-span-2">
        <label :for="fieldId('avoid')" class="mb-1.5 block text-xs font-semibold text-surface-600">排除地点</label>
        <div class="mb-2 flex flex-wrap gap-2">
          <span v-for="(entry, index) in model.avoidEntries" :key="`${entry.name}-${index}`" class="inline-flex items-center gap-1 rounded-xl border border-surface-200 bg-surface-100 px-2.5 py-1 text-xs text-surface-700">
            {{ entry.name }}
            <span v-if="entry.placeRef?.provider === 'DEMO'" class="rounded bg-amber-100 px-1 text-[10px] text-amber-700">演示</span>
            <button type="button" :aria-label="`移除排除地点 ${entry.name}`" class="text-surface-400 hover:text-danger-600" @click="removeEntry(model.avoidEntries, index)">×</button>
          </span>
        </div>
        <PlaceAutocomplete
          :label="'排除地点'"
          :city="city"
          :get-token="getToken"
          :model-value="null"
          @update:model-value="(ref: PlaceRef | null) => { if (ref) addEntry(model.avoidEntries, { name: ref.name, placeRef: ref }) }"
        />
        <p v-if="model.avoidEntries.length > 0 && !model.avoidEntries.every((entry) => entry.placeRef)" class="mt-1 text-[11px] text-surface-400">
          自由文本地点保持原样，重新搜索选择后才会成为结构化地点
        </p>
      </div>
      <div v-for="meal in mealOptions" :key="meal.key" class="sm:col-span-2">
        <span class="mb-1.5 block text-xs font-semibold text-surface-600">{{ meal.label }}安排</span>
        <div class="flex flex-wrap items-center gap-3">
          <select
            v-model="model[`${meal.key}Source` as 'breakfastSource' | 'lunchSource' | 'dinnerSource']"
            :aria-label="`${meal.label}安排方式`"
            :class="inputClass"
            class="w-44"
          >
            <option value="DEFAULT">采用常用时间</option>
            <option value="USER">自定义时间</option>
            <option value="DISABLED">不安排</option>
          </select>
          <template v-if="model[`${meal.key}Source` as 'breakfastSource' | 'lunchSource' | 'dinnerSource'] === 'DEFAULT'">
            <span class="text-sm text-surface-500">{{ defaultWindowLabel(meal.mealType) }}</span>
          </template>
          <template v-else-if="model[`${meal.key}Source` as 'breakfastSource' | 'lunchSource' | 'dinnerSource'] === 'USER'">
            <input v-model="model[`${meal.key}Start` as 'breakfastStart' | 'lunchStart' | 'dinnerStart']" type="time" :aria-label="`${meal.label}开始时间`" :class="inputClass" class="w-32" />
            <span class="text-sm text-surface-400">至</span>
            <input v-model="model[`${meal.key}End` as 'breakfastEnd' | 'lunchEnd' | 'dinnerEnd']" type="time" :aria-label="`${meal.label}结束时间`" :class="inputClass" class="w-32" />
          </template>
          <span v-else class="text-sm text-surface-500">不在行程中安排</span>
        </div>
      </div>
    </div>

    <!-- B13-G: pace / mobility / preferences share one UI region; the
         domain fields stay independent. -->
    <TravelStyleEditor :model="model" :preference-options="preferenceOptions" />
  </div>
</template>
