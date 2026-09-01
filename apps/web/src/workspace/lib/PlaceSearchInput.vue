<script setup lang="ts">
// 地点搜索输入框（F-UI-11：基于 searchPlaces API 索引，禁止自由填写）。
// 输入时从后端搜索 POI 候选，选中后 emits 结构化 PlaceRef。
import { computed, onUnmounted, ref, watch } from 'vue'
import { LoaderCircle, MapPin, Search } from 'lucide-vue-next'

import { useAuthStore } from '../../app/stores/auth'
import {
  PlaceSearcher,
  toPlaceRef,
  type PlaceSearchState,
  IDLE_SEARCH_STATE,
} from '../../lib/place-selection'
import type { PlaceCandidate, PlaceRef } from '../../lib/api'

const props = defineProps<{
  modelValue: string
  placeRef?: PlaceRef | null
  city: string
  placeholder?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:placeRef': [ref: PlaceRef | null]
}>()

const auth = useAuthStore()
const query = ref('')
const open = ref(false)
const selectedIndex = ref(-1)

const searchState = ref<PlaceSearchState>(IDLE_SEARCH_STATE)

const searcher = new PlaceSearcher({
  getToken: () => auth.accessToken,
  getCity: () => props.city,
  onChange: (state) => {
    searchState.value = state
    if (state.candidates.length > 0) open.value = true
  },
})

// 同步外部 modelValue 到 query
watch(
  () => props.modelValue,
  (val) => {
    if (val && !query.value) query.value = val
  },
  { immediate: true },
)

onUnmounted(() => {
  searcher.cancel()
})

function onInput(e: Event) {
  const value = (e.target as HTMLInputElement).value
  query.value = value
  open.value = value.trim().length >= 1
  selectedIndex.value = -1
  emit('update:modelValue', value)
  emit('update:placeRef', null)
  searcher.update(value)
}

function select(candidate: PlaceCandidate) {
  query.value = candidate.name
  open.value = false
  emit('update:modelValue', candidate.name)
  emit('update:placeRef', toPlaceRef(candidate))
  searcher.cancel()
}

function onBlur() {
  setTimeout(() => { open.value = false }, 200)
}

function onKeydown(e: KeyboardEvent) {
  if (!open.value) return
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    selectedIndex.value = Math.min(selectedIndex.value + 1, searchState.value.candidates.length - 1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    selectedIndex.value = Math.max(selectedIndex.value - 1, 0)
  } else if (e.key === 'Enter' && selectedIndex.value >= 0) {
    e.preventDefault()
    select(searchState.value.candidates[selectedIndex.value])
  } else if (e.key === 'Escape') {
    open.value = false
  }
}

const candidates = computed(() => searchState.value.candidates)
const searching = computed(() => searchState.value.searching)
</script>

<template>
  <div class="relative" @keydown="onKeydown">
    <div class="flex h-8 items-center gap-1.5 rounded-md border border-tp-line bg-white px-2.5 transition-colors focus-within:border-tp-faint">
      <Search :size="13" class="shrink-0 text-tp-mute" aria-hidden="true" />
      <input
        :value="query"
        type="text"
        class="h-full min-w-0 flex-1 border-0 bg-transparent text-xs text-tp-ink outline-none placeholder:text-tp-faint"
        :placeholder="placeholder ?? '搜索地点，如：上海博物馆、豫园'"
        autocomplete="off"
        role="combobox"
        aria-autocomplete="list"
        :aria-expanded="open && candidates.length > 0"
        @input="onInput"
        @focus="open = query.trim().length >= 1"
        @blur="onBlur"
      />
      <LoaderCircle
        v-if="searching && query.trim().length >= 2"
        :size="12"
        class="shrink-0 animate-spin text-tp-mute"
        aria-hidden="true"
      />
    </div>

    <!-- 下拉选项 -->
    <ul
      v-if="open && (candidates.length > 0 || searching)"
      class="absolute left-0 right-0 top-full z-50 mt-1 max-h-48 overflow-y-auto rounded-md border border-tp-line bg-white py-1 shadow-sm"
      role="listbox"
    >
      <li
        v-if="searching && candidates.length === 0"
        class="flex items-center gap-2 px-2.5 py-2 text-xs text-tp-mute"
      >
        <LoaderCircle :size="12" class="animate-spin" aria-hidden="true" />
        正在搜索…
      </li>
      <li
        v-for="(candidate, i) in candidates"
        :key="`${candidate.providerPoiId}-${i}`"
        role="option"
        :aria-selected="i === selectedIndex"
        :class="i === selectedIndex ? 'bg-tp-active text-tp-ink' : 'text-tp-body'"
        class="flex cursor-pointer items-center gap-2 px-2.5 py-1.5 text-xs transition-colors hover:bg-tp-hover"
        @mousedown.prevent="select(candidate)"
      >
        <MapPin :size="12" class="shrink-0 text-tp-mute" aria-hidden="true" />
        <div class="min-w-0 flex-1">
          <span class="block truncate">{{ candidate.name }}</span>
          <span class="block truncate text-[10px] text-tp-faint">{{ candidate.address || candidate.district }}</span>
        </div>
        <span v-if="candidate.estimated" class="shrink-0 text-[10px] text-tp-warn">估算</span>
      </li>
    </ul>
  </div>
</template>