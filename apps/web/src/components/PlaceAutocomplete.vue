<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import type { PlaceCandidate, PlaceRef } from '../lib/api'
import {
  PLACE_SEARCH_MIN_CHARS,
  PlaceSearcher,
  isDemoCandidate,
  toPlaceRef,
  type PlaceSearchState,
} from '../lib/place-selection'

const props = withDefaults(defineProps<{
  label: string
  city: string
  getToken: () => string
  modelValue: PlaceRef | null
  placeholder?: string
}>(), {
  placeholder: '输入至少 2 个字符搜索地点',
})

const emit = defineEmits<{
  'update:modelValue': [value: PlaceRef | null]
  'update:text': [value: string]
}>()

const query = ref('')
const open = ref(false)
const state = ref<PlaceSearchState>({ query: '', searching: false, candidates: [], error: null })

const searcher = new PlaceSearcher({
  getToken: () => props.getToken(),
  getCity: () => props.city,
  onChange: (next) => {
    state.value = next
    if (next.searching || next.candidates.length > 0 || next.error !== null) {
      open.value = true
    }
  },
})

// Editing the text invalidates the current structured selection.
function onInput(event: Event) {
  const value = (event.target as HTMLInputElement).value
  query.value = value
  emit('update:text', value)
  if (props.modelValue !== null && value.trim() !== props.modelValue.name) {
    emit('update:modelValue', null)
  }
  searcher.update(value)
}

function select(candidate: PlaceCandidate) {
  query.value = candidate.name
  open.value = false
  searcher.cancel()
  emit('update:modelValue', toPlaceRef(candidate))
}

function clear() {
  query.value = ''
  open.value = false
  searcher.cancel()
  emit('update:modelValue', null)
}

let closeTimer: ReturnType<typeof setTimeout> | null = null

function scheduleClose() {
  if (closeTimer !== null) clearTimeout(closeTimer)
  closeTimer = setTimeout(() => {
    closeTimer = null
    open.value = false
  }, 120)
}

onBeforeUnmount(() => {
  searcher.cancel()
  if (closeTimer !== null) clearTimeout(closeTimer)
})

watch(() => props.modelValue, (value) => {
  if (value === null && query.value !== '') {
    query.value = ''
  } else if (value !== null) {
    query.value = value.name
  }
})

// B13_FIX R5 (P1-6): a city switch invalidates every in-flight search for
// the old city.  Cancel immediately and reset the dropdown so a stale
// response can never surface old-city candidates.
watch(() => props.city, () => {
  searcher.cancel()
  state.value = { query: '', searching: false, candidates: [], error: null }
  query.value = ''
  open.value = false
})

const showEmpty = computed(() =>
  query.value.trim().length >= PLACE_SEARCH_MIN_CHARS
  && !state.value.searching
  && state.value.candidates.length === 0
  && state.value.error === null)
</script>

<template>
  <div class="relative">
    <div class="flex items-center gap-2">
      <input
        :value="query"
        type="text"
        :aria-label="`${label}搜索`"
        :placeholder="placeholder"
        maxlength="120"
        class="h-10 w-full rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow"
        @input="onInput"
        @focus="open = state.searching || state.candidates.length > 0 || state.error !== null"
        @blur="scheduleClose"
      />
      <button
        v-if="modelValue"
        type="button"
        :aria-label="`清除${label}选择`"
        class="shrink-0 rounded-lg px-2 py-1 text-xs text-surface-500 hover:text-danger-600"
        @mousedown.prevent="clear"
      >
        清除
      </button>
    </div>
    <div v-if="open" class="absolute z-20 mt-1 w-full overflow-hidden rounded-xl border border-surface-200 bg-white shadow-lg">
      <p v-if="state.searching" class="px-3 py-2 text-xs text-surface-500">正在搜索…</p>
      <ul v-else-if="state.candidates.length > 0" class="max-h-56 overflow-y-auto">
        <li v-for="candidate in state.candidates" :key="`${candidate.provider}-${candidate.providerPoiId}`">
          <button
            type="button"
            class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-surface-100"
            @click="select(candidate)"
          >
            <span class="min-w-0 flex-1">
              <span class="block truncate text-surface-800">{{ candidate.name }}</span>
              <span class="block truncate text-xs text-surface-400">
                {{ candidate.address || [candidate.district, candidate.city, candidate.province].filter(Boolean).join(' · ') }}
              </span>
            </span>
            <span v-if="isDemoCandidate(candidate)" class="shrink-0 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-700">演示</span>
          </button>
        </li>
      </ul>
      <p v-else-if="state.error" class="px-3 py-2 text-xs text-danger-600" role="alert">{{ state.error }}</p>
      <p v-else-if="showEmpty" class="px-3 py-2 text-xs text-surface-500">未找到匹配地点</p>
    </div>
  </div>
</template>
