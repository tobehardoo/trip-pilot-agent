<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ChevronDown } from 'lucide-vue-next'

import type { DestinationDistrict, DestinationRegion } from '../lib/api'
import { PROVINCES, type City, type Province } from '../lib/china-divisions'

const props = withDefaults(defineProps<{
  modelValue: DestinationRegion | null
  disabled?: boolean
}>(), {
  disabled: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: DestinationRegion | null]
}>()

/** 从城市 adcode 推导省份 adcode：直辖市的城市码即省份码，其余取前两位补零。 */
function deriveProvinceCode(cityCode: string): string {
  if (!cityCode || cityCode.length !== 6) return ''
  return cityCode.endsWith('0000') ? cityCode : `${cityCode.slice(0, 2)}0000`
}

const selectedProvinceName = ref('')
const selectedCityName = ref('')
const selectedDistricts = ref<DestinationDistrict[]>([])

const provinces = computed(() => PROVINCES)
const selectedProvince = computed<Province | undefined>(() =>
  provinces.value.find((p) => p.name === selectedProvinceName.value),
)
const cities = computed(() => selectedProvince.value?.cities ?? [])
const selectedCity = computed<City | undefined>(() =>
  cities.value.find((c) => c.name === selectedCityName.value),
)
const districts = computed(() =>
  (selectedCity.value?.districts ?? []).filter((d) => !d.name.startsWith('全市')),
)

function emitRegion() {
  const city = selectedCity.value
  if (!city) {
    emit('update:modelValue', null)
    return
  }
  const cityCode = city.adcode ?? ''
  if (!cityCode) {
    // 该城市暂无结构化编码：仅作为目的地字符串，不提交伪造编码。
    emit('update:modelValue', null)
    return
  }
  emit('update:modelValue', {
    provinceCode: deriveProvinceCode(cityCode),
    provinceName: selectedProvinceName.value,
    cityCode,
    cityName: city.name,
    districts: [...selectedDistricts.value],
  })
}

function onProvinceChange() {
  selectedCityName.value = ''
  selectedDistricts.value = []
  emitRegion()
}

function onCityChange() {
  selectedDistricts.value = []
  emitRegion()
}

function toggleDistrict(district: { name: string; adcode?: string }) {
  if (!district.adcode) return
  const index = selectedDistricts.value.findIndex((d) => d.districtCode === district.adcode)
  if (index >= 0) {
    selectedDistricts.value.splice(index, 1)
  } else {
    selectedDistricts.value.push({ districtCode: district.adcode, districtName: district.name })
  }
  emitRegion()
}

// 回填初始值。
watch(() => props.modelValue, (region) => {
  if (!region) {
    // 省份已选而城市未选时，父组件会把 null 写回（onProvinceChange 的中间态
    // 回声）。此时省份是用户正在重选城市的有效输入，保留省份、只清空城市与
    // 区县；只有省份也为空（真正的外部重置）才清空全部。
    if (selectedProvinceName.value) {
      selectedCityName.value = ''
      selectedDistricts.value = []
      return
    }
    selectedProvinceName.value = ''
    selectedCityName.value = ''
    selectedDistricts.value = []
    return
  }
  selectedProvinceName.value = region.provinceName
  selectedCityName.value = region.cityName
  selectedDistricts.value = [...(region.districts ?? [])]
}, { immediate: true })
</script>

<template>
  <div class="space-y-3">
    <div class="grid grid-cols-2 gap-3">
      <div>
        <label for="region-province" class="block text-xs font-semibold text-surface-600 mb-1.5">省份</label>
        <select
          id="region-province"
          :value="selectedProvinceName"
          :disabled="disabled"
          class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400"
          @change="selectedProvinceName = ($event.target as HTMLSelectElement).value; onProvinceChange()"
        >
          <option value="" disabled>请选择省份</option>
          <option v-for="province in provinces" :key="province.name" :value="province.name">{{ province.name }}</option>
        </select>
      </div>
      <div>
        <label for="region-city" class="block text-xs font-semibold text-surface-600 mb-1.5">城市</label>
        <select
          id="region-city"
          :value="selectedCityName"
          :disabled="disabled || !selectedProvince"
          class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 disabled:opacity-50"
          @change="selectedCityName = ($event.target as HTMLSelectElement).value; onCityChange()"
        >
          <option value="" disabled>请选择城市</option>
          <option v-for="city in cities" :key="city.name" :value="city.name">{{ city.name }}</option>
        </select>
      </div>
    </div>

    <div v-if="selectedCity && districts.length">
      <span class="block text-xs font-semibold text-surface-600 mb-1.5">主要游玩区域（可选，多选）</span>
      <div class="flex flex-wrap gap-2">
        <label
          v-for="district in districts"
          :key="district.adcode"
          class="relative inline-flex cursor-pointer items-center rounded-xl border px-3 py-1.5 text-sm font-medium transition-all"
          :class="selectedDistricts.some((d) => d.districtCode === district.adcode)
            ? 'border-primary-300 bg-primary-50 text-primary-700'
            : 'border-surface-200 bg-white text-surface-600 hover:bg-surface-50'"
        >
          <input
            type="checkbox"
            class="sr-only"
            :checked="selectedDistricts.some((d) => d.districtCode === district.adcode)"
            :disabled="disabled"
            @change="toggleDistrict(district)"
          />
          {{ district.name }}
        </label>
      </div>
      <p class="mt-1 text-xs text-surface-400">不选区域表示全市范围规划</p>
    </div>
    <p v-else-if="selectedCity" class="text-xs text-surface-400">全市范围规划（当前城市暂无细分区域数据）</p>
  </div>
</template>
