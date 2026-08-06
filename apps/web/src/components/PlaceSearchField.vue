<script setup lang="ts">
import { computed, ref } from 'vue'
import { CheckCircle2, RefreshCcw, Search, X } from 'lucide-vue-next'

import type { PlaceSearchResponse, StructuredPoi } from '../lib/api'

const props = withDefaults(defineProps<{
  modelValue: StructuredPoi | null
  /** A legacy free-text name with no trusted POI, shown as "待重新确认". */
  legacyPlaceName?: string
  city: string
  placeholder?: string
  disabled?: boolean
  searchPlaces?: (keyword: string, city: string) => Promise<PlaceSearchResponse>
}>(), {
  legacyPlaceName: '',
  placeholder: '搜索地点（如：长沙希尔顿酒店）',
  disabled: false,
  searchPlaces: undefined,
})

const emit = defineEmits<{
  'update:modelValue': [value: StructuredPoi | null]
}>()

const keyword = ref('')
const results = ref<StructuredPoi[]>([])
const searching = ref(false)
const unavailable = ref(false)
const showResults = ref(false)

const locked = computed(() => props.modelValue !== null)

function select(poi: StructuredPoi) {
  emit('update:modelValue', poi)
  results.value = []
  showResults.value = false
}

function clear() {
  emit('update:modelValue', null)
  results.value = []
  keyword.value = ''
  unavailable.value = false
}

async function runSearch() {
  const query = keyword.value.trim()
  if (!query || !props.city || !props.searchPlaces) {
    unavailable.value = !props.searchPlaces
    return
  }
  searching.value = true
  unavailable.value = false
  try {
    const response = await props.searchPlaces(query, props.city)
    if (response.status === 'UNAVAILABLE') {
      unavailable.value = true
      results.value = []
    } else {
      results.value = response.results
    }
    showResults.value = true
  } finally {
    searching.value = false
  }
}
</script>

<template>
  <div>
    <!-- Locked selection -->
    <div v-if="locked" class="rounded-xl border border-primary-200 bg-primary-50/60 px-3 py-2.5">
      <div class="flex items-start justify-between gap-2">
        <div class="min-w-0">
          <div class="flex items-center gap-1.5 text-sm font-semibold text-primary-700">
            <CheckCircle2 :size="15" aria-hidden="true" />
            <span class="truncate">{{ modelValue?.name }}</span>
          </div>
          <p class="mt-0.5 truncate text-xs text-surface-500">{{ modelValue?.fullAddress }}</p>
        </div>
        <div class="flex shrink-0 items-center gap-1">
          <button
            type="button"
            class="flex h-8 items-center gap-1 rounded-lg border border-primary-200 bg-white px-2 text-xs font-medium text-primary-700 hover:bg-primary-50"
            :disabled="disabled"
            @click="clear"
          >
            <RefreshCcw :size="13" aria-hidden="true" />
            重新选择
          </button>
          <button
            type="button"
            class="flex h-8 w-8 items-center justify-center rounded-lg text-surface-400 hover:bg-white hover:text-surface-600"
            :disabled="disabled"
            title="清除"
            aria-label="清除"
            @click="clear"
          >
            <X :size="14" aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>

    <!-- Legacy free text awaiting re-confirmation -->
    <div v-else-if="legacyPlaceName" class="rounded-xl border border-amber-200 bg-amber-50/60 px-3 py-2.5">
      <div class="flex items-center justify-between gap-2">
        <div class="min-w-0">
          <div class="text-sm font-semibold text-amber-700">{{ legacyPlaceName }}</div>
          <p class="text-xs text-amber-600/80">地点待重新确认，请重新选择高德 POI</p>
        </div>
        <button
          type="button"
          class="flex h-8 shrink-0 items-center gap-1 rounded-lg border border-amber-200 bg-white px-2 text-xs font-medium text-amber-700 hover:bg-amber-50"
          :disabled="disabled"
          @click="keyword = ''; results = []"
        >
          <Search :size="13" aria-hidden="true" />
          重新选择
        </button>
      </div>
    </div>

    <!-- Search input -->
    <div v-else class="relative">
      <div class="flex items-center gap-2 rounded-xl border border-surface-200 bg-white px-3 focus-within:border-primary-400 focus-within:ring-2 focus-within:ring-primary-400/30">
        <Search :size="15" class="shrink-0 text-surface-400" aria-hidden="true" />
        <input
          v-model="keyword"
          type="search"
          maxlength="30"
          :placeholder="placeholder"
          :disabled="disabled"
          class="h-10 w-full min-w-0 border-0 bg-transparent text-sm text-surface-800 outline-0"
          @input="showResults = false"
          @keydown.enter.prevent="runSearch"
        />
        <button
          type="button"
          class="h-8 shrink-0 rounded-lg bg-primary-600 px-3 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
          :disabled="disabled || searching || !keyword.trim()"
          @click="runSearch"
        >
          {{ searching ? '搜索中…' : '搜索' }}
        </button>
      </div>

      <p v-if="unavailable" class="mt-1.5 text-xs text-amber-600" role="alert">
        地点搜索暂时不可用，可暂不设置酒店，稍后重试。
      </p>

      <ul v-if="showResults && results.length" class="absolute z-20 mt-1.5 w-full overflow-hidden rounded-xl border border-surface-200 bg-white shadow-lg">
        <li v-for="poi in results" :key="poi.providerPoiId">
          <button
            type="button"
            class="flex w-full items-start gap-2 px-3 py-2.5 text-left hover:bg-surface-50"
            @click="select(poi)"
          >
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm font-medium text-surface-800">{{ poi.name }}</span>
              <span class="mt-0.5 block truncate text-xs text-surface-400">{{ poi.fullAddress }}</span>
            </span>
            <span class="mt-0.5 shrink-0 rounded bg-surface-100 px-1.5 py-0.5 text-[11px] text-surface-500">
              {{ poi.district || poi.city }}
            </span>
          </button>
        </li>
      </ul>
      <p v-else-if="showResults && !unavailable" class="mt-1.5 text-xs text-surface-400">未找到匹配地点</p>
    </div>
  </div>
</template>
