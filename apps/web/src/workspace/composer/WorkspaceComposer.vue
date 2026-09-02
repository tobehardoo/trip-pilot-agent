<script setup lang="ts">
// 统一 Composer（Composer 交互重构 design §2）：三层结构，两种形态。
//
// Layer 1  Required Context：目的地 chip（CitySearchInput 行政区划索引）+
//          日期 chip（原生 date 双控件，结束 ≥ 开始）。
//          floating（创建模式）可编辑，对话开始后锁定（服务端 TRIP 事实语义）；
//          docked（旅行模式）为只读上下文行（contextLabel，来自 trip 实体）。
// Layer 2  自然语言输入区：Enter 发送 / Shift+Enter 换行，自动增高。
// Layer 3  动作条：[重新开始]（创建中）· TripPilot · [开始规划]（ready 时）· 发送。
//
// 必填规则只约束发送与开始规划（服务端 422 兜底）：缺目的地/日期时禁用发送，
// 不使用 alert，不引入其他业务字段。
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ArrowUp, ChevronDown, LoaderCircle, Users, Wallet } from 'lucide-vue-next'

import CitySearchInput from '../lib/CitySearchInput.vue'

const props = withDefaults(defineProps<{
  variant?: 'floating' | 'docked'
  disabled?: boolean
  sending?: boolean
  placeholder?: string
  /** 创建模式 Required Context（floating 生；docked 用 contextLabel 只读行） */
  destination?: string | null
  startDate?: string | null
  endDate?: string | null
  /** 对话开始后 chips 锁定（服务端 TRIP 事实只读） */
  chipsLocked?: boolean
  /** 服务端 ready 信号 → 显示 [开始规划] */
  ready?: boolean
  /** docked 形态的只读上下文行（如「广州 · 09/10 → 09/13」） */
  contextLabel?: string
  /** 发送键旁的出行设置：人数/预算（创建模式；null=未填） */
  travelers?: number | null
  budget?: number | null
}>(), {
  variant: 'floating',
  disabled: false,
  sending: false,
  placeholder: undefined,
  destination: null,
  startDate: null,
  endDate: null,
  chipsLocked: false,
  ready: false,
  contextLabel: '',
})

const emit = defineEmits<{
  send: [text: string]
  startPlanning: []
  resetCreation: []
  updateDestination: [name: string, region: { provinceCode: string; cityCode: string } | null]
  updateDates: [start: string, end: string]
  updateTravelers: [value: number | null]
  updateBudget: [value: number | null]
}>()

const draft = ref('')
const inputEl = ref<HTMLTextAreaElement | null>(null)
const showDatePop = ref(false)
const showInlineCitySearch = ref(false)
const dateStart = ref('')
const dateEnd = ref('')
const dateError = ref('')

// 出行设置（人数/预算）：发送键旁的芯片选择，选中即同步给上层 → 随 tripContext 提交。
const showTravelersPop = ref(false)
const showBudgetPop = ref(false)
const TRAVELER_OPTIONS = [1, 2, 3, 4, 5, 6, 8]
const BUDGET_OPTIONS: { label: string; value: number }[] = [
  { label: '3000 以内', value: 2500 },
  { label: '3000-8000', value: 5500 },
  { label: '8000-15000', value: 11500 },
  { label: '15000 以上', value: 20000 },
]
function budgetLabel(): string {
  const v = props.budget
  if (!v) return '预算'
  return `¥${v.toLocaleString('zh-CN')}`
}

// CitySearchInput 的城市名与 region 编码在同一次 select 里先后 emit；
// 城市名事件先到、region 后到 → 名字事件里 nextTick 再判定，两个都齐才算选中。
const cityDraft = ref('')
const cityRegion = ref<{ provinceCode: string; cityCode: string } | null>(null)

const datesFilled = computed(() => Boolean(props.startDate && props.endDate))
const requiredOk = computed(() => Boolean(props.destination) && datesFilled.value)
const isFloating = computed(() => props.variant === 'floating')
const canSend = computed(() =>
  !props.disabled
  && !props.sending
  && draft.value.trim().length > 0
  && (props.variant === 'docked' || requiredOk.value),
)

function shortDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const parts = iso.split('-')
  return parts.length === 3 ? `${parts[1]}/${parts[2]}` : iso
}

function submit() {
  const text = draft.value.trim()
  if (!text || !canSend.value) return
  emit('send', text)
  draft.value = ''
  nextTick(autoGrow)
}

function autoGrow() {
  const el = inputEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 120)}px`
}

function toggleCityPop() {
  if (!isFloating.value || props.chipsLocked) return
  showDatePop.value = false
  showInlineCitySearch.value = !showInlineCitySearch.value
  if (showInlineCitySearch.value) {
    cityDraft.value = props.destination ?? ''
  }
}

function toggleDatePop() {
  if (!isFloating.value || props.chipsLocked) return
  showInlineCitySearch.value = false
  if (showDatePop.value) {
    showDatePop.value = false
    return
  }
  dateStart.value = props.startDate ?? ''
  dateEnd.value = props.endDate ?? ''
  dateError.value = ''
  showDatePop.value = true
}

function toggleTravelersPop() {
  showBudgetPop.value = false
  showTravelersPop.value = !showTravelersPop.value
}

function toggleBudgetPop() {
  showTravelersPop.value = false
  showBudgetPop.value = !showBudgetPop.value
}

function pickTravelers(value: number) {
  showTravelersPop.value = false
  emit('updateTravelers', value)
}

function pickBudget(value: number) {
  showBudgetPop.value = false
  emit('updateBudget', value)
}

function onCityName(name: string) {
  cityDraft.value = name
  void nextTick(flushCitySelection)
}

function onCityRegion(region: { provinceCode: string; cityCode: string } | null) {
  cityRegion.value = region
}

// 功能④：用户明确选择「其他」自定义目的地（region=null 也接受）。
let customDestination = false
function onCityCustom() {
  customDestination = true
  void nextTick(flushCitySelection)
}

function flushCitySelection() {
  const name = cityDraft.value.trim()
  if (!name) return
  if (!cityRegion.value && !customDestination) return // 自由输入（未点「其他」）不算选中
  const region = cityRegion.value
  customDestination = false
  showInlineCitySearch.value = false
  emit('updateDestination', name, region)
}

function onDateInput() {
  dateError.value = ''
  if (dateStart.value && dateEnd.value && dateStart.value > dateEnd.value) {
    dateError.value = '结束日期不能早于开始日期'
    return
  }
  if (dateStart.value && dateEnd.value) {
    emit('updateDates', dateStart.value, dateEnd.value)
    showDatePop.value = false
  }
}

function onDocumentClick(event: MouseEvent) {
  const target = event.target as HTMLElement
  if (target.closest('[data-composer-pop], [data-composer-chip], [data-composer-inline]')) return
  showDatePop.value = false
  showInlineCitySearch.value = false
  showTravelersPop.value = false
  showBudgetPop.value = false
}

function onKeydown(event: KeyboardEvent) {
  if (event.target !== inputEl.value) return
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    submit()
  }
}

onMounted(() => document.addEventListener('click', onDocumentClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocumentClick))
</script>

<template>
  <div
    class="rounded-[10px] border border-tp-line bg-white"
    :class="variant === 'floating' ? 'shadow-[0_8px_24px_-4px_rgb(0_0_0/0.08),0_2px_8px_-2px_rgb(0_0_0/0.04)]' : ''"
    data-testid="workspace-composer"
  >
    <!-- Layer 1: Required Context -->
    <div class="relative flex flex-wrap items-center gap-1.5 px-3 pb-0 pt-2.5">
      <template v-if="isFloating">
        <!-- 目的地：inline search -->
        <div v-if="!chipsLocked" data-composer-inline class="relative">
          <div
            v-if="!showInlineCitySearch"
            class="flex items-center"
          >
            <span class="mr-1 text-xs text-tp-mute">目的地：</span>
            <button
              type="button"
              class="flex h-[26px] items-center gap-1 rounded-md border px-2.5 text-xs transition-colors"
              :class="destination
                ? 'border-tp-line bg-white text-tp-ink'
                : 'border-dashed border-tp-line text-tp-mute hover:bg-tp-hover hover:text-tp-ink'"
              data-composer-chip
              data-testid="composer-destination-chip"
              @click="toggleCityPop"
            >
              {{ destination || '未设置' }}
            </button>
          </div>
          <div v-else class="w-56">
            <CitySearchInput
              :model-value="cityDraft"
              @update:model-value="onCityName"
              @update:region="onCityRegion"
              @update:custom="onCityCustom"
            />
          </div>
        </div>

        <!-- 日期 chip -->
        <button
          v-if="!chipsLocked"
          type="button"
          class="flex h-[26px] items-center gap-1.5 rounded-md border px-2.5 text-xs transition-colors"
          :class="datesFilled
            ? 'border-tp-line bg-white text-tp-ink'
            : 'border-dashed border-tp-line text-tp-mute hover:bg-tp-hover hover:text-tp-ink'"
          data-composer-chip
          data-testid="composer-date-chip"
          :aria-label="datesFilled ? `日期：${shortDate(startDate)} → ${shortDate(endDate)}` : '设置日期'"
          @click="toggleDatePop"
        >
          {{ datesFilled ? `${shortDate(startDate)} → ${shortDate(endDate)}` : '日期：未设置' }}
          <span v-if="chipsLocked" class="text-[10px] text-tp-faint">已锁定</span>
        </button>

        <!-- 日期弹层：原生 date 双控件 -->
        <div
          v-if="showDatePop"
          data-composer-pop
          class="absolute left-0 top-full z-40 mt-1.5 w-64 rounded-lg border border-tp-line bg-white p-2.5 shadow-[0_8px_24px_-4px_rgb(0_0_0/0.08)]"
          data-testid="composer-date-popover"
        >
          <div class="flex items-center gap-1.5">
            <input
              v-model="dateStart"
              type="date"
              class="h-7 min-w-0 flex-1 rounded-md border border-tp-line bg-white px-2 text-xs text-tp-ink outline-none transition-colors focus:border-tp-faint"
              data-testid="composer-date-start"
              @input="onDateInput"
            />
            <span class="shrink-0 text-xs text-tp-faint" aria-hidden="true">—</span>
            <input
              v-model="dateEnd"
              type="date"
              class="h-7 min-w-0 flex-1 rounded-md border border-tp-line bg-white px-2 text-xs text-tp-ink outline-none transition-colors focus:border-tp-faint"
              data-testid="composer-date-end"
              @input="onDateInput"
            />
          </div>
          <p v-if="dateError" class="mb-0 mt-1.5 text-[11px] leading-4 text-tp-mute" data-testid="composer-date-error">
            {{ dateError }}
          </p>
        </div>
      </template>

      <!-- docked：只读上下文行 -->
      <span
        v-else-if="contextLabel"
        class="flex h-[26px] items-center rounded-md border border-tp-line bg-tp-panel px-2.5 text-xs text-tp-ink"
        data-testid="composer-context-label"
      >
        {{ contextLabel }}
      </span>
    </div>

    <!-- Layer 2: 自然语言输入区 -->
    <div class="px-3 pb-1 pt-1.5">
      <textarea
        ref="inputEl"
        v-model="draft"
        rows="1"
        class="block min-h-[28px] w-full resize-none border-0 bg-transparent px-1 py-1 text-[13px] leading-5 text-tp-ink outline-none placeholder:text-tp-faint"
        style="max-height: 120px"
        :placeholder="placeholder ?? (variant === 'floating'
          ? '告诉我你想怎么旅行，比如：想轻松一点，多看看历史文化……'
          : '继续告诉 TripPilot 你想如何调整旅行…')"
        :disabled="disabled"
        data-testid="composer-input"
        @keydown="onKeydown"
        @input="autoGrow"
      />
    </div>

    <!-- Layer 3: 动作条 -->
    <div class="flex items-center gap-2 px-3 pb-2 pt-0.5">
      <button
        v-if="isFloating && chipsLocked"
        type="button"
        class="flex h-6 items-center rounded px-1.5 text-[11px] text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
        data-testid="composer-reset"
        @click="emit('resetCreation')"
      >
        ↺ 重新开始
      </button>
      <span class="flex-1" aria-hidden="true" />
      <!-- 出行设置：人数 / 预算（发送键旁，创建模式） -->
      <div v-if="isFloating" class="flex items-center gap-1.5">
        <div class="relative">
          <button
            type="button"
            class="flex h-6 items-center gap-1 rounded-md border px-2 text-[11px] transition-colors"
            :class="travelers
              ? 'border-tp-line bg-white text-tp-sub'
              : 'border-dashed border-tp-line text-tp-faint hover:bg-tp-hover hover:text-tp-sub'"
            data-composer-chip
            data-testid="composer-travelers"
            @click="toggleTravelersPop"
          >
            <Users :size="11" aria-hidden="true" />{{ travelers ? `${travelers}人` : '人数' }}
            <ChevronDown :size="10" class="opacity-60" aria-hidden="true" />
          </button>
          <div
            v-if="showTravelersPop"
            data-composer-pop
            class="absolute bottom-full right-0 z-40 mb-1.5 w-24 rounded-lg border border-tp-line bg-white p-1 shadow-[0_8px_24px_-4px_rgb(0_0_0/0.12)]"
            data-testid="composer-travelers-pop"
          >
            <button
              v-for="n in TRAVELER_OPTIONS"
              :key="n"
              type="button"
              class="flex h-7 w-full items-center rounded px-2 text-xs text-tp-body transition-colors hover:bg-tp-hover hover:text-tp-ink"
              :class="travelers === n ? 'bg-tp-active font-medium text-tp-ink' : ''"
              :data-testid="`composer-travelers-${n}`"
              @click="pickTravelers(n)"
            >{{ n }} 人</button>
          </div>
        </div>
        <div class="relative">
          <button
            type="button"
            class="flex h-6 items-center gap-1 rounded-md border px-2 text-[11px] transition-colors"
            :class="budget
              ? 'border-tp-line bg-white text-tp-sub'
              : 'border-dashed border-tp-line text-tp-faint hover:bg-tp-hover hover:text-tp-sub'"
            data-composer-chip
            data-testid="composer-budget"
            @click="toggleBudgetPop"
          >
            <Wallet :size="11" aria-hidden="true" />{{ budgetLabel() }}
            <ChevronDown :size="10" class="opacity-60" aria-hidden="true" />
          </button>
          <div
            v-if="showBudgetPop"
            data-composer-pop
            class="absolute bottom-full right-0 z-40 mb-1.5 w-32 rounded-lg border border-tp-line bg-white p-1 shadow-[0_8px_24px_-4px_rgb(0_0_0/0.12)]"
            data-testid="composer-budget-pop"
          >
            <button
              v-for="opt in BUDGET_OPTIONS"
              :key="opt.value"
              type="button"
              class="flex h-7 w-full items-center rounded px-2 text-xs text-tp-body transition-colors hover:bg-tp-hover hover:text-tp-ink"
              :class="budget === opt.value ? 'bg-tp-active font-medium text-tp-ink' : ''"
              :data-testid="`composer-budget-${opt.value}`"
              @click="pickBudget(opt.value)"
            >{{ opt.label }}</button>
          </div>
        </div>
      </div>
      <button
        v-if="isFloating && ready"
        type="button"
        class="flex h-7 items-center gap-1 rounded-md bg-tp-ink px-3 text-xs font-medium text-white transition-colors hover:bg-[#3D3D3B]"
        data-testid="composer-start-planning"
        @click="emit('startPlanning')"
      >
        开始规划
      </button>
      <button
        type="button"
        class="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-tp-ink text-white transition-colors hover:bg-[#3D3D3B] disabled:cursor-not-allowed disabled:opacity-30"
        :disabled="!canSend"
        title="发送"
        aria-label="发送"
        data-testid="composer-send"
        @click="submit"
      >
        <component :is="sending ? LoaderCircle : ArrowUp" :size="13" :class="sending ? 'animate-spin' : ''" aria-hidden="true" />
      </button>
    </div>
  </div>
</template>
