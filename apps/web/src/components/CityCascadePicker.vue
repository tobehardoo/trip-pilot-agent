<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChevronRight, MapPin } from 'lucide-vue-next'
import { cityAdcode, PROVINCES, type City, type District, type Province } from '../lib/china-divisions'

const props = defineProps<{
  province?: string
  city?: string
  districts: string[]
}>()

const emit = defineEmits<{
  change: [selection: {
    province: string
    provinceCode?: string
    city: string
    cityCode?: string
    districts: string[]
    districtCodes: string[]
  }]
}>()

// 当前选中的索引
const selectedProvince = ref(props.province || '')
const selectedCity = ref(props.city || '')
const selectedDistricts = ref<string[]>([...props.districts])

// 派生数据
const provinceList = PROVINCES
const currentProvince = computed(() => PROVINCES.find((p) => p.name === selectedProvince.value))
const cityList = computed(() => currentProvince.value?.cities || [])
const currentCity = computed(() => cityList.value.find((c) => c.name === selectedCity.value))
const districtList = computed(() => currentCity.value?.districts || [])

// 选择省
function selectProvince(name: string) {
  selectedProvince.value = name
  selectedCity.value = ''
  selectedDistricts.value = []
}

// 选择市
function selectCity(name: string) {
  selectedCity.value = name
  const city = cityList.value.find((c) => c.name === name)
  // 默认选"全市"
  const whole = city?.districts.find((d) => d.name.startsWith('全市'))
  if (whole) {
    selectedDistricts.value = [whole.name]
  } else if (city?.districts.length) {
    selectedDistricts.value = [city.districts[0].name]
  } else {
    selectedDistricts.value = []
  }
  emitChange()
}

// 切换区
function toggleDistrict(name: string) {
  const whole = districtList.value.find((d) => d.name.startsWith('全市'))
  // 选了"全市"→取消所有具体区
  if (name === whole?.name) {
    selectedDistricts.value = [name]
  } else {
    // 去掉"全市"
    if (whole) selectedDistricts.value = selectedDistricts.value.filter((d) => d !== whole.name)
    // 切换具体区
    const idx = selectedDistricts.value.indexOf(name)
    if (idx >= 0) {
      selectedDistricts.value = selectedDistricts.value.filter((d) => d !== name)
    } else {
      selectedDistricts.value = [...selectedDistricts.value, name]
    }
    // 如果全部取消了，回退到全市
    if (selectedDistricts.value.length === 0 && whole) {
      selectedDistricts.value = [whole.name]
    }
  }
  emitChange()
}

function isDistrictSelected(name: string) {
  return selectedDistricts.value.includes(name)
}

function emitChange() {
  // 剥离"全市（不限XX内区域）"为简单的"全市"
  const cleanDistricts = selectedDistricts.value.map((d) => {
    const match = /^全市/.exec(d)
    return match ? '全市' : d
  })
  const selectedCityAdcode = currentCity.value ? cityAdcode(currentCity.value) : undefined
  emit('change', {
    province: selectedProvince.value,
    provinceCode: selectedCityAdcode
      ? `${selectedCityAdcode.slice(0, 2)}0000`
      : undefined,
    city: selectedCity.value,
    cityCode: selectedCityAdcode,
    districts: cleanDistricts,
    districtCodes: districtList.value
      .filter((district) => selectedDistricts.value.includes(district.name))
      .flatMap((district) => district.adcode ? [district.adcode] : []),
  })
}

// 外部同步
function syncFromProps() {
  if (props.province && props.province !== selectedProvince.value) {
    selectedProvince.value = props.province
    if (props.city) {
      selectedCity.value = props.city
      selectedDistricts.value = [...props.districts]
    }
  }
}
syncFromProps()
</script>

<template>
  <div class="flex flex-col gap-3">
    <!-- 省 -->
    <div>
      <label for="destination-province" class="mb-1 block text-[11px] font-semibold text-surface-500">省 / 直辖市</label>
      <select
        id="destination-province"
        class="w-full rounded-xl border border-surface-200 bg-surface-50 px-3 py-2.5 text-sm text-surface-800 focus:border-primary-400 focus:outline-none focus:ring-2 focus:ring-primary-100"
        :value="selectedProvince"
        @change="selectProvince(($event.target as HTMLSelectElement).value)"
      >
        <option value="" disabled>选择省份</option>
        <option v-for="p in provinceList" :key="p.name" :value="p.name">{{ p.name }}</option>
      </select>
    </div>

    <!-- 市 -->
    <div v-if="currentProvince">
      <label for="destination-city" class="mb-1 block text-[11px] font-semibold text-surface-500">城市</label>
      <select
        id="destination-city"
        class="w-full rounded-xl border border-surface-200 bg-surface-50 px-3 py-2.5 text-sm text-surface-800 focus:border-primary-400 focus:outline-none focus:ring-2 focus:ring-primary-100"
        :value="selectedCity"
        @change="selectCity(($event.target as HTMLSelectElement).value)"
      >
        <option value="" disabled>选择城市</option>
        <option v-for="c in cityList" :key="c.name" :value="c.name">{{ c.name }}</option>
      </select>
    </div>

    <!-- 区 -->
    <div v-if="currentCity && districtList.length > 1">
      <label class="mb-1 block text-[11px] font-semibold text-surface-500">区域（可多选）</label>
      <div class="flex flex-wrap gap-1.5">
        <button
          v-for="d in districtList"
          :key="d.name"
          type="button"
          class="rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors"
          :class="isDistrictSelected(d.name)
            ? 'border-primary-300 bg-primary-50 text-primary-700'
            : 'border-surface-200 bg-white text-surface-600 hover:border-surface-300'"
          @click="toggleDistrict(d.name)"
        >
          <template v-if="d.name.startsWith('全市')">
            <MapPin :size="11" class="inline mr-0.5" />{{ d.name.replace(/（.*）/, '') }}
          </template>
          <template v-else>
            {{ d.name }}
          </template>
        </button>
      </div>
    </div>

    <!-- 当前选择摘要 -->
    <div v-if="selectedCity" class="rounded-lg bg-primary-50 px-3 py-2 text-xs text-primary-700">
      目的地：{{ selectedProvince }} {{ selectedCity }}{{ selectedDistricts.length ? ' · ' + selectedDistricts.map(d => d.startsWith('全市') ? '全市' : d).join('、') : '' }}
    </div>
  </div>
</template>
