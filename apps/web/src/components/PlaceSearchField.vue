<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { CheckCircle2, LoaderCircle, MapPin, RefreshCcw, Search } from 'lucide-vue-next'

import type { PlaceSearchFn, StructuredPoi } from '../lib/api'

const props = withDefaults(defineProps<{
  /** Selected structured POI (the only trusted anchor). */
  modelValue: StructuredPoi | null
  /** A legacy free-text name with no trusted POI, shown as "待重新确认". */
  legacyPlaceName?: string
  /** Destination city that results must belong to. Empty disables the field. */
  city: string
  placeholder?: string
  disabled?: boolean
  searchPlaces?: PlaceSearchFn
}>(), {
  legacyPlaceName: '',
  placeholder: '输入关键词搜索（如：广州南站）',
  disabled: false,
  searchPlaces: undefined,
})

const emit = defineEmits<{
  'update:modelValue': [value: StructuredPoi | null]
}>()

// 状态拆分：输入文本与已选 POI 分离，searchStatus 明确搜索阶段。
const inputText = ref('')
const results = ref<StructuredPoi[]>([])
const searchStatus = ref<'idle' | 'loading' | 'available' | 'unavailable' | 'no-results'>('idle')
const requestSequence = ref(0)
let controller: AbortController | null = null
let debounceTimer: number | undefined

const locked = computed(() => props.modelValue !== null)
const cityReady = computed(() => Boolean(props.city.trim()))

function select(poi: StructuredPoi) {
  emit('update:modelValue', poi)
  inputText.value = poi.name
  results.value = []
  searchStatus.value = 'idle'
}

function clear() {
  emit('update:modelValue', null)
  inputText.value = ''
  results.value = []
  searchStatus.value = 'idle'
}

async function runSearch() {
  const query = inputText.value.trim()
  if (!query || !cityReady.value) return
  if (!props.searchPlaces) {
    searchStatus.value = 'unavailable'
    return
  }
  const seq = ++requestSequence.value
  controller?.abort()
  controller = new AbortController()
  searchStatus.value = 'loading'
  try {
    const response = await props.searchPlaces(query, props.city, controller.signal)
    if (seq !== requestSequence.value) return // 旧请求结果不得覆盖新请求
    if (response.status === 'UNAVAILABLE') {
      searchStatus.value = 'unavailable'
      results.value = []
    } else if (response.results.length === 0) {
      searchStatus.value = 'no-results'
      results.value = []
    } else {
      searchStatus.value = 'available'
      results.value = response.results
    }
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') return
    if (seq === requestSequence.value) {
      searchStatus.value = 'unavailable'
      results.value = []
    }
  } finally {
    if (seq === requestSequence.value && searchStatus.value === 'loading') {
      searchStatus.value = 'no-results'
    }
  }
}

// Search-as-you-type：300ms 防抖。
let lastQuery = ''
watch(inputText, (value) => {
  if (locked.value) return
  const query = value.trim()
  if (query === lastQuery) return
  lastQuery = query
  window.clearTimeout(debounceTimer)
  if (!query) {
    requestSequence.value += 1
    controller?.abort()
    results.value = []
    searchStatus.value = 'idle'
    return
  }
  debounceTimer = window.setTimeout(() => {
    void runSearch()
  }, 300)
})

onBeforeUnmount(() => {
  controller?.abort()
  window.clearTimeout(debounceTimer)
})
</script>

<template>
  <div>
    <!-- 锁定卡片：已选 POI 不可随意修改，只能重新选择。 -->
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
        </div>
      </div>
    </div>

    <!-- 旧自由文本待重新确认 -->
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
          @click="clear"
        >
          <Search :size="13" aria-hidden="true" />
          重新选择
        </button>
      </div>
    </div>

    <!-- 搜索输入 -->
    <div v-else class="relative">
      <div
        class="flex items-center gap-2 rounded-xl border border-surface-200 bg-white px-3 focus-within:border-primary-400 focus-within:ring-2 focus-within:ring-primary-400/30"
        :class="{ 'opacity-60': !cityReady }"
      >
        <Search :size="15" class="shrink-0 text-surface-400" aria-hidden="true" />
        <input
          v-model="inputText"
          type="text"
          maxlength="30"
          autocomplete="off"
          :placeholder="cityReady ? placeholder : '请先选择目的城市'"
          :disabled="disabled || !cityReady"
          class="h-10 w-full min-w-0 border-0 bg-transparent text-sm text-surface-800 outline-0"
          data-testid="poi-search-input"
        />
        <LoaderCircle v-if="searchStatus === 'loading'" class="h-4 w-4 shrink-0 animate-spin text-primary-500" aria-hidden="true" />
      </div>

      <p v-if="!cityReady" class="mt-1.5 text-xs text-surface-400">请先选择目的城市</p>
      <p v-else-if="searchStatus === 'unavailable'" class="mt-1.5 text-xs text-amber-600" role="alert">
        地点搜索暂时不可用，请稍后重试；可暂不设置。
      </p>

      <ul v-if="searchStatus === 'available' && results.length" class="absolute z-20 mt-1.5 w-full overflow-hidden rounded-xl border border-surface-200 bg-white shadow-lg" data-testid="poi-results">
        <li v-for="poi in results" :key="poi.providerPoiId">
          <button
            type="button"
            class="flex w-full items-start gap-2 px-3 py-2.5 text-left hover:bg-surface-50"
            @click="select(poi)"
          >
            <span class="mt-0.5 shrink-0 text-surface-300"><MapPin :size="14" aria-hidden="true" /></span>
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
      <p v-else-if="searchStatus === 'no-results'" class="mt-1.5 text-xs text-surface-400">未找到匹配地点，换个关键词试试</p>
    </div>
  </div>
</template>
