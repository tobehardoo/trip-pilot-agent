<script setup lang="ts">
// 新建旅行抽屉（F-UI-11：城市/地点索引搜索，禁止自由填写）。
//
// 设计意图：不是"填写一张完整业务表单"，而是"告诉它这次旅行的基本信息，然后开始规划"。
// - 目的地通过 CitySearchInput 从中国行政区划索引选择（带 region 编码）
// - 想去的地方通过 PlaceSearchInput 从高德 POI 搜索选择（带 PlaceRef 坐标）
// - 旅行名称不收集：创建后由 store 按「目的地 + 日期跨度」自动生成（上海三日旅行）。
// - 字段顺序 = 用户决策顺序：目的地 → 日期 → 人数+预算 → 偏好 → 特别想去的地方。
// - 必填仅目的地 + 日期：不给每个字段加"必填"噪音，只在创建按钮不可用时给一句提示。
// - 提交走 createTrip 闭环（写入 store + localStorage 持久化 + 选中 + 跳转新旅行 URL）。
import { computed, reactive, ref, watch } from 'vue'
import { ArrowRight, Plus } from 'lucide-vue-next'

import Drawer from '../../components/ui/Drawer.vue'
import CitySearchInput from '../lib/CitySearchInput.vue'
import PlaceSearchInput from '../lib/PlaceSearchInput.vue'
import type { CreateTripInput, PlaceRef, RegionRef } from '../../../lib/api'

const props = defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  close: []
  created: [input: CreateTripInput]
}>()

/** 旅行偏好可选标签（轻量多选，Codex 中性色 + 极少量强调） */
const PREF_OPTIONS = ['美食', '历史文化', '自然风光', '城市漫游', '购物', '摄影', '亲子', '轻松休闲']

const form = reactive({
  destination: '',
  /** YYYY-MM-DD（原生 date 控件） */
  startDate: '',
  endDate: '',
  people: 2,
  budget: '',
  selectedPrefs: [] as string[],
  mustVisitRows: [] as { name: string; ref: PlaceRef | null }[],
})

// 目的地 region 编码（来自 CitySearchInput）
const destinationRegion = ref<{ provinceCode: string; cityCode: string } | null>(null)

const missingRequired = computed(
  () => !form.destination.trim() || !form.startDate || !form.endDate,
)
const invalidRange = computed(
  () => Boolean(form.startDate && form.endDate && form.startDate > form.endDate),
)
const canSubmit = computed(() => !missingRequired.value && !invalidRange.value)
const hint = computed(() =>
  invalidRange.value ? '结束日期不能早于开始日期' : '请填写目的地和日期',
)

// 每次打开重置表单
watch(
  () => props.open,
  (open) => {
    if (!open) return
    form.destination = ''
    form.startDate = ''
    form.endDate = ''
    form.people = 2
    form.budget = ''
    form.selectedPrefs = []
    form.mustVisitRows = []
    destinationRegion.value = null
  },
)

function togglePref(pref: string) {
  const i = form.selectedPrefs.indexOf(pref)
  if (i >= 0) form.selectedPrefs.splice(i, 1)
  else form.selectedPrefs.push(pref)
}

function removeMustVisitRow(index: number) {
  form.mustVisitRows.splice(index, 1)
}

function addMustVisitRow() {
  form.mustVisitRows.push({ name: '', ref: null })
}

function submit() {
  if (!canSubmit.value) return

  const mustVisitPlaceRefs = form.mustVisitRows
    .map((row) => row.ref)
    .filter((ref): ref is PlaceRef => ref !== null)

  // 构建 region
  const region: RegionRef | undefined = destinationRegion.value
    ? {
        provinceCode: destinationRegion.value.provinceCode,
        cityCode: destinationRegion.value.cityCode,
        districtCodes: [],
        provinceName: '',
        cityName: form.destination,
        districtNames: [],
        datasetVersion: '1',
      }
    : undefined

  emit('created', {
    title: '', // 后端会自动生成
    destination: form.destination.trim(),
    region,
    arrivalAt: form.startDate,
    departureAt: form.endDate,
    constraints: {
      travelers: form.people,
      budgetAmount: form.budget ? Number(form.budget) : null,
      travelerType: form.people <= 1 ? 'SOLO' : form.people === 2 ? 'COUPLE' : form.people <= 4 ? 'FAMILY' : 'FRIENDS',
      preferences: [...form.selectedPrefs],
      mustVisitPlaces: mustVisitPlaceRefs.map((r) => r.name),
      mustVisitPlaceRefs,
      transitModes: [],
      accommodationPreference: null,
      pace: 'MODERATE',
      mealBudget: null,
    },
  })
}
</script>

<template>
  <Drawer
    :open="open"
    title="新建旅行"
    description="先记录这次旅行的基本信息，规划会在创建后开始。"
    width="md"
    @close="emit('close')"
  >
    <form class="space-y-5" data-testid="new-trip-form" @submit.prevent="submit">
      <!-- 目的地：CitySearchInput 从行政区划索引选择 -->
      <div>
        <label for="nt-destination" class="mb-1.5 block text-[11px] font-medium leading-4 text-tp-mute">目的地</label>
        <CitySearchInput
          id="nt-destination"
          v-model="form.destination"
          :region="destinationRegion"
          @update:region="destinationRegion = $event"
        />
      </div>

      <!-- 日期：开始 — 结束（紧凑双控件，复用原生 date 输入） -->
      <div>
        <span class="mb-1.5 block text-[11px] font-medium leading-4 text-tp-mute">日期</span>
        <div class="flex items-center gap-2">
          <input
            v-model="form.startDate"
            type="date"
            class="h-8 min-w-0 flex-1 rounded-md border border-tp-line bg-white px-2.5 text-xs text-tp-ink outline-none transition-colors focus:border-tp-faint"
            data-testid="new-trip-start-date"
          />
          <span class="shrink-0 text-xs leading-4 text-tp-faint" aria-hidden="true">—</span>
          <input
            v-model="form.endDate"
            type="date"
            class="h-8 min-w-0 flex-1 rounded-md border border-tp-line bg-white px-2.5 text-xs text-tp-ink outline-none transition-colors focus:border-tp-faint"
            data-testid="new-trip-end-date"
          />
        </div>
      </div>

      <!-- 人数 + 预算：并排，一次定下规模 -->
      <div class="grid grid-cols-2 gap-3">
        <div>
          <span class="mb-1.5 block text-[11px] font-medium leading-4 text-tp-mute">人数</span>
          <div class="flex h-8 items-stretch overflow-hidden rounded-md border border-tp-line bg-white">
            <button
              type="button"
              class="w-8 shrink-0 text-sm leading-4 text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink disabled:cursor-not-allowed disabled:opacity-40"
              :disabled="form.people <= 1"
              aria-label="减少人数"
              data-testid="new-trip-people-dec"
              @click="form.people -= 1"
            >
              −
            </button>
            <div
              class="flex min-w-0 flex-1 items-center justify-center border-x border-tp-line text-xs leading-4 text-tp-ink"
              data-testid="new-trip-people"
            >
              {{ form.people }} 人
            </div>
            <button
              type="button"
              class="w-8 shrink-0 text-sm leading-4 text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink disabled:cursor-not-allowed disabled:opacity-40"
              :disabled="form.people >= 20"
              aria-label="增加人数"
              data-testid="new-trip-people-inc"
              @click="form.people += 1"
            >
              ＋
            </button>
          </div>
        </div>
        <div>
          <label for="nt-budget" class="mb-1.5 block text-[11px] font-medium leading-4 text-tp-mute">预算</label>
          <div class="flex h-8 items-center overflow-hidden rounded-md border border-tp-line bg-white transition-colors focus-within:border-tp-faint">
            <span class="pl-2.5 text-xs leading-4 text-tp-mute" aria-hidden="true">¥</span>
            <input
              id="nt-budget"
              v-model.number="form.budget"
              type="number"
              min="0"
              inputmode="numeric"
              class="h-full w-full min-w-0 bg-transparent px-1.5 text-xs text-tp-ink outline-none placeholder:text-tp-faint"
              placeholder="3000"
              data-testid="new-trip-budget"
            />
          </div>
        </div>
      </div>

      <!-- 旅行偏好：轻量多选标签（可留空） -->
      <div>
        <span class="mb-1.5 block text-[11px] font-medium leading-4 text-tp-mute">旅行偏好</span>
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="pref in PREF_OPTIONS"
            :key="pref"
            type="button"
            class="rounded px-2 py-1 text-xs leading-4 transition-colors"
            :class="form.selectedPrefs.includes(pref)
              ? 'bg-tp-ink text-white'
              : 'text-tp-sub hover:bg-tp-hover hover:text-tp-ink'"
            :data-testid="`new-trip-preference-${pref}`"
            @click="togglePref(pref)"
          >
            {{ pref }}
          </button>
        </div>
      </div>

      <!-- 特别想去的地方：PlaceSearchInput 从高德 POI 索引选择 -->
      <div>
        <span class="mb-1.5 block text-[11px] font-medium leading-4 text-tp-mute">特别想去的地方</span>
        <div class="space-y-1.5">
          <div v-for="(row, i) in form.mustVisitRows" :key="i" class="flex items-center gap-1.5">
            <PlaceSearchInput
              v-model="row.name"
              :place-ref="row.ref"
              :city="form.destination || '广州'"
              :placeholder="i === 0 ? '搜索地点，如：上海博物馆' : '另一个想去的地方'"
              @update:place-ref="row.ref = $event"
            />
            <button
              v-if="form.mustVisitRows.length > 1"
              type="button"
              class="shrink-0 rounded p-1 text-tp-mute transition-colors hover:bg-tp-hover hover:text-tp-ink"
              :aria-label="`移除第 ${i + 1} 个地点`"
              :data-testid="`new-trip-must-visit-remove-${i}`"
              @click="removeMustVisitRow(i)"
            >
              ×
            </button>
          </div>
        </div>
        <button
          type="button"
          class="mt-1.5 flex h-7 items-center gap-1 rounded px-1.5 text-[11px] leading-4 text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
          data-testid="new-trip-must-visit-add"
          @click="addMustVisitRow"
        >
          <Plus :size="12" aria-hidden="true" /> 添加地点
        </button>
      </div>

      <!-- 底部：取消 | 开始规划；仅必填缺失时给一句提示 -->
      <div class="flex items-center justify-between gap-2 border-t border-tp-div pt-4">
        <p v-if="!canSubmit" class="m-0 text-[11px] leading-4 text-tp-mute" data-testid="new-trip-error">
          {{ hint }}
        </p>
        <span v-else />
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="flex h-8 items-center rounded-md px-3 text-xs text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
            data-testid="new-trip-cancel"
            @click="emit('close')"
          >
            取消
          </button>
          <button
            type="submit"
            class="flex h-8 items-center gap-1.5 rounded-md bg-tp-ink px-3 text-xs font-medium text-white transition-colors hover:bg-[#3D3D3B] disabled:cursor-not-allowed disabled:opacity-40"
            :disabled="!canSubmit"
            data-testid="new-trip-submit"
          >
            开始规划 <ArrowRight :size="13" aria-hidden="true" />
          </button>
        </div>
      </div>
    </form>
  </Drawer>
</template>
