<script setup lang="ts">
// 城市搜索输入框（F-UI-11：基于 china-divisions 索引，禁止自由填写）。
// 输入时从中国行政区划数据中匹配省/市，选中后 emits 城市名 + RegionRef。
import { computed, ref, watch } from 'vue'
import { Search, MapPin } from 'lucide-vue-next'

import { PROVINCES, type Province } from '../../lib/china-divisions'

const props = defineProps<{
  modelValue: string
  region?: { provinceCode: string; cityCode: string } | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:region': [region: { provinceCode: string; cityCode: string } | null]
}>()

const query = ref('')
const open = ref(false)
const selectedIndex = ref(-1)

// 提取所有城市（含省份信息）
interface CityEntry {
  cityName: string
  provinceName: string
  cityCode: string
  provinceCode: string
}

const allCities = computed<CityEntry[]>(() => {
  const entries: CityEntry[] = []
  for (const province of PROVINCES) {
    for (const city of province.cities) {
      if (city.adcode) {
        entries.push({
          cityName: city.name,
          provinceName: province.name,
          cityCode: city.adcode,
          // 省级 adcode = 城市码前两位 + 0000（与 constraint-draft 的 endsWith('0000') 校验一致；
          // 直辖市城市码自身即省级码，前两位推导不变式同样成立）。
          provinceCode: `${city.adcode.slice(0, 2)}0000`,
        })
      }
    }
  }
  return entries
})

const filtered = computed(() => {
  const q = query.value.trim()
  if (q.length < 1) return []
  const lower = q.toLowerCase()
  return allCities.value.filter(
    (entry) =>
      entry.cityName.includes(q) ||
      entry.cityName.toLowerCase().includes(lower) ||
      entry.provinceName.includes(q) ||
      `${entry.cityName}${entry.provinceName}`.includes(q),
  ).slice(0, 15)
})

// 同步外部 modelValue 到 query
watch(
  () => props.modelValue,
  (val) => {
    if (val && !query.value) query.value = val
  },
  { immediate: true },
)

function select(entry: CityEntry) {
  query.value = entry.cityName
  open.value = false
  emit('update:modelValue', entry.cityName)
  emit('update:region', {
    provinceCode: entry.provinceCode,
    cityCode: entry.cityCode,
  })
}

function onInput(e: Event) {
  const value = (e.target as HTMLInputElement).value
  query.value = value
  open.value = value.trim().length >= 1
  selectedIndex.value = -1
  // 用户手动输入时不 emit region
  emit('update:region', null)
  emit('update:modelValue', value)
}

function onBlur() {
  // 延迟关闭让点击选项生效
  setTimeout(() => { open.value = false }, 200)
}

function onKeydown(e: KeyboardEvent) {
  if (!open.value) return
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    selectedIndex.value = Math.min(selectedIndex.value + 1, filtered.value.length - 1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    selectedIndex.value = Math.max(selectedIndex.value - 1, 0)
  } else if (e.key === 'Enter' && selectedIndex.value >= 0) {
    e.preventDefault()
    select(filtered.value[selectedIndex.value])
  } else if (e.key === 'Escape') {
    open.value = false
  }
}
</script>

<template>
  <div class="relative" @keydown="onKeydown">
    <div class="flex h-8 items-center gap-1.5 rounded-md border border-tp-line bg-white px-2.5 transition-colors focus-within:border-tp-faint">
      <Search :size="13" class="shrink-0 text-tp-mute" aria-hidden="true" />
      <input
        :value="query"
        type="text"
        class="h-full min-w-0 flex-1 border-0 bg-transparent text-xs text-tp-ink outline-none placeholder:text-tp-faint"
        placeholder="搜索城市，如：广州、上海、成都"
        autocomplete="off"
        role="combobox"
        aria-autocomplete="list"
        :aria-expanded="open && filtered.length > 0"
        @input="onInput"
        @focus="open = query.trim().length >= 1"
        @blur="onBlur"
      />
      <span v-if="query && !open" class="shrink-0 text-[11px] text-tp-ok">{{ modelValue || '已选' }}</span>
    </div>

    <!-- 下拉选项 -->
    <ul
      v-if="open && filtered.length > 0"
      class="absolute left-0 right-0 top-full z-50 mt-1 max-h-48 overflow-y-auto rounded-md border border-tp-line bg-white py-1 shadow-sm"
      role="listbox"
    >
      <li
        v-for="(entry, i) in filtered"
        :key="entry.cityCode"
        role="option"
        :aria-selected="i === selectedIndex"
        :class="i === selectedIndex ? 'bg-tp-active text-tp-ink' : 'text-tp-body'"
        class="flex cursor-pointer items-center gap-2 px-2.5 py-1.5 text-xs transition-colors hover:bg-tp-hover"
        @mousedown.prevent="select(entry)"
      >
        <MapPin :size="12" class="shrink-0 text-tp-mute" aria-hidden="true" />
        <span class="min-w-0 flex-1 truncate">{{ entry.cityName }}</span>
        <span class="shrink-0 text-[10px] text-tp-faint">{{ entry.provinceName }}</span>
      </li>
    </ul>
  </div>
</template>