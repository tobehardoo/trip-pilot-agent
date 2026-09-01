<script setup lang="ts">
// 编辑约束抽屉（F-UI-11：城市/地点索引搜索，禁止自由填写）。
// 允许编辑 目的地/日期/人数/预算/偏好/必去地点；保存 → updateConstraints →
// tripStore.currentTrip 更新 → 中间区（攻略头部副信息）+ 右侧 Inspector 自动同步。
// 409 版本冲突 → 中文提示：「当前旅行信息已发生变化，请刷新后重新修改。」
// 目的地通过 CitySearchInput 从行政区划索引选择，必去地点通过 PlaceSearchInput 从高德 POI 搜索选择。
import { reactive, ref, watch } from 'vue'
import { Check } from 'lucide-vue-next'

import Drawer from '../../components/ui/Drawer.vue'
import CitySearchInput from '../lib/CitySearchInput.vue'
import PlaceSearchInput from '../lib/PlaceSearchInput.vue'
import { useTripStore } from '../stores/tripStore'
import type { PlaceRef, Trip } from '../../../lib/api'

const props = defineProps<{
  open: boolean
  trip: Trip | null
}>()

const emit = defineEmits<{
  close: []
}>()

const { updateConstraints } = useTripStore()

interface MustVisitRow {
  name: string
  ref: PlaceRef | null
}

const form = reactive<{
  destination: string
  startDate: string
  endDate: string
  travelers: number
  budgetAmount: number | null
  preferences: string[]
  mustVisitRows: MustVisitRow[]
}>({
  destination: '',
  startDate: '',
  endDate: '',
  travelers: 2,
  budgetAmount: null,
  preferences: [],
  mustVisitRows: [],
})

const saving = ref(false)
const error = ref('')

const PREF_OPTIONS = ['美食', '历史文化', '自然风光', '城市漫游', '购物', '摄影', '亲子', '轻松休闲']

// 每次打开预填当前约束
watch(
  () => props.open,
  (open) => {
    if (open && props.trip) {
      form.destination = props.trip.destination
      form.startDate = props.trip.startDate
      form.endDate = props.trip.endDate
      form.travelers = props.trip.constraints.travelers
      form.budgetAmount = props.trip.constraints.budgetAmount
      form.preferences = [...props.trip.constraints.preferences]
      // 优先使用 mustVisitPlaceRefs，回退到 mustVisitPlaces
      const refs = props.trip.constraints.mustVisitPlaceRefs ?? []
      const names = props.trip.constraints.mustVisitPlaces ?? []
      if (refs.length > 0) {
        form.mustVisitRows = refs.map((r) => ({ name: r.name, ref: r }))
      } else if (names.length > 0) {
        form.mustVisitRows = names.map((n) => ({ name: n, ref: null }))
      } else {
        form.mustVisitRows = []
      }
      error.value = ''
    }
  },
)

function togglePref(pref: string) {
  const i = form.preferences.indexOf(pref)
  if (i >= 0) form.preferences.splice(i, 1)
  else form.preferences.push(pref)
}

function removeMustVisitRow(index: number) {
  form.mustVisitRows.splice(index, 1)
}

function addMustVisitRow() {
  form.mustVisitRows.push({ name: '', ref: null })
}

async function submit() {
  if (!props.trip) return
  if (!form.destination.trim()) {
    error.value = '目的地不能为空'
    return
  }
  saving.value = true
  error.value = ''
  try {
    const mustVisitPlaceRefs = form.mustVisitRows
      .map((row) => row.ref)
      .filter((ref): ref is PlaceRef => ref !== null)
    await updateConstraints({
      budgetAmount: form.budgetAmount,
      travelerType: form.travelers <= 1 ? 'SOLO' : form.travelers === 2 ? 'COUPLE' : form.travelers <= 4 ? 'FAMILY' : 'FRIENDS',
      travelers: form.travelers,
      preferences: form.preferences,
      mustVisitPlaces: mustVisitPlaceRefs.map((r) => r.name),
      mustVisitPlaceRefs,
      transitModes: [],
      accommodationPreference: null,
      pace: 'MODERATE',
      mealBudget: null,
    })
    emit('close')
  } catch (cause: any) {
    if (cause?.status === 409 || cause?.message?.includes('409')) {
      error.value = '当前旅行信息已发生变化，请刷新后重新修改。'
    } else {
      error.value = cause?.message || '保存失败，请重试。'
    }
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Drawer
    :open="open"
    title="编辑旅行约束"
    description="保存后中间工作区与右侧上下文将同步更新。"
    width="md"
    @close="emit('close')"
  >
    <form v-if="trip" class="space-y-4" data-testid="constraint-edit-form" @submit.prevent="submit">
      <!-- 目的地：CitySearchInput 从行政区划索引选择 -->
      <div>
        <label for="ce-destination" class="mb-1 block text-[11px] font-medium leading-4 text-tp-mute">目的地</label>
        <CitySearchInput
          id="ce-destination"
          v-model="form.destination"
        />
      </div>

      <!-- 日期：开始 — 结束 -->
      <div>
        <span class="mb-1 block text-[11px] font-medium leading-4 text-tp-mute">日期</span>
        <div class="flex items-center gap-2">
          <input
            v-model="form.startDate"
            type="date"
            class="h-8 min-w-0 flex-1 rounded-md border border-tp-line bg-white px-2.5 text-xs text-tp-ink outline-none transition-colors focus:border-tp-faint"
            data-testid="ce-start-date"
          />
          <span class="shrink-0 text-xs leading-4 text-tp-faint" aria-hidden="true">—</span>
          <input
            v-model="form.endDate"
            type="date"
            class="h-8 min-w-0 flex-1 rounded-md border border-tp-line bg-white px-2.5 text-xs text-tp-ink outline-none transition-colors focus:border-tp-faint"
            data-testid="ce-end-date"
          />
        </div>
      </div>

      <!-- 人数 + 预算 -->
      <div class="grid grid-cols-2 gap-3">
        <div>
          <span class="mb-1 block text-[11px] font-medium leading-4 text-tp-mute">人数</span>
          <div class="flex h-8 items-stretch overflow-hidden rounded-md border border-tp-line bg-white">
            <button
              type="button"
              class="w-8 shrink-0 text-sm leading-4 text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink disabled:cursor-not-allowed disabled:opacity-40"
              :disabled="form.travelers <= 1"
              aria-label="减少人数"
              @click="form.travelers -= 1"
            >−</button>
            <div class="flex min-w-0 flex-1 items-center justify-center border-x border-tp-line text-xs leading-4 text-tp-ink">
              {{ form.travelers }} 人
            </div>
            <button
              type="button"
              class="w-8 shrink-0 text-sm leading-4 text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink disabled:cursor-not-allowed disabled:opacity-40"
              :disabled="form.travelers >= 20"
              aria-label="增加人数"
              @click="form.travelers += 1"
            >＋</button>
          </div>
        </div>
        <div>
          <label for="ce-budget" class="mb-1 block text-[11px] font-medium leading-4 text-tp-mute">预算</label>
          <div class="flex h-8 items-center overflow-hidden rounded-md border border-tp-line bg-white transition-colors focus-within:border-tp-faint">
            <span class="pl-2.5 text-xs leading-4 text-tp-mute" aria-hidden="true">¥</span>
            <input
              id="ce-budget"
              v-model.number="form.budgetAmount"
              type="number"
              min="0"
              inputmode="numeric"
              class="h-full w-full min-w-0 bg-transparent px-1.5 text-xs text-tp-ink outline-none placeholder:text-tp-faint"
              placeholder="3000"
              data-testid="ce-budget"
            />
          </div>
        </div>
      </div>

      <!-- 旅行偏好 -->
      <div>
        <span class="mb-1 block text-[11px] font-medium leading-4 text-tp-mute">旅行偏好</span>
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="pref in PREF_OPTIONS"
            :key="pref"
            type="button"
            class="rounded px-2 py-1 text-xs leading-4 transition-colors"
            :class="form.preferences.includes(pref)
              ? 'bg-tp-ink text-white'
              : 'text-tp-sub hover:bg-tp-hover hover:text-tp-ink'"
            @click="togglePref(pref)"
          >{{ pref }}</button>
        </div>
      </div>

      <!-- 必去地点：PlaceSearchInput 从高德 POI 索引选择 -->
      <div>
        <span class="mb-1 block text-[11px] font-medium leading-4 text-tp-mute">必去地点</span>
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
              @click="removeMustVisitRow(i)"
            >×</button>
          </div>
        </div>
        <button
          type="button"
          class="mt-1.5 flex h-7 items-center gap-1 rounded px-1.5 text-[11px] leading-4 text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
          @click="addMustVisitRow"
        >添加地点</button>
      </div>

      <p v-if="error" class="m-0 text-[11px] leading-4 text-tp-warn" data-testid="constraint-edit-error">{{ error }}</p>

      <div class="flex items-center justify-end gap-2 border-t border-tp-div pt-4">
        <button
          type="button"
          class="flex h-8 items-center rounded-md px-3 text-xs text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
          data-testid="constraint-edit-cancel"
          @click="emit('close')"
        >取消</button>
        <button
          type="submit"
          class="flex h-8 items-center gap-1.5 rounded-md bg-tp-ink px-3 text-xs font-medium text-white transition-colors hover:bg-[#3D3D3B] disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="saving"
          data-testid="constraint-edit-save"
        >保存 <Check :size="13" aria-hidden="true" /></button>
      </div>
    </form>
  </Drawer>
</template>