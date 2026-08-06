<script setup lang="ts">
import {
  CalendarDays,
  Archive,
  ArchiveRestore,
  CircleGauge,
  Compass,
  ArrowRight,
  LogOut,
  MapPin,
  Plus,
  Search,
  Users,
  Wallet,
  X,
  Sparkles,
} from 'lucide-vue-next'
import { computed, reactive, ref } from 'vue'

import type { CreateTripInput, Trip, User } from '../lib/api'
import { useModalFocus } from '../lib/modal'
import Button from './ui/Button.vue'
import Card from './ui/Card.vue'
import Badge from './ui/Badge.vue'
import TripTemplates from './TripTemplates.vue'

import ConstraintCard from './ConstraintCard.vue'
import NaturalLanguageInput from './NaturalLanguageInput.vue'
import { createDefaultDraft, destinationToString, toCreateTripInput, type ConstraintDraft } from '../lib/constraint-draft'
import { parseConstraint } from '../lib/constraint-parser'
import type { ParseWarning } from '../lib/constraint-parser'

const props = withDefaults(defineProps<{
  user: User
  trips: Trip[]
  busy: boolean
  error: string | null
  createTrip: (input: CreateTripInput) => Promise<void>
  destinationQuery?: string
  includeArchived?: boolean
}>(), {
  destinationQuery: '',
  includeArchived: false,
})

// ── 自然语言约束输入 ──────────────────────────────────────
const useNaturalLanguage = ref(true)
const draft = ref<ConstraintDraft>(createDefaultDraft())
const parseWarnings = ref<ParseWarning[]>([])
const parseUnrecognized = ref<string[]>([])

function handleParse(text: string) {
  const result = parseConstraint(text)
  parseWarnings.value = result.warnings
  parseUnrecognized.value = result.unrecognized
  applyOperations(result.operations)
}

function applyOperations(ops: ReturnType<typeof parseConstraint>['operations']) {
  for (const op of ops) {
    const field = draft.value[op.field as keyof ConstraintDraft] as { value: unknown; source: string } | undefined
    if (!field) continue
    switch (op.type) {
      case 'set':
        field.value = op.value
        field.source = 'explicit'
        break
      case 'append':
        if (Array.isArray(field.value) && !field.value.includes(op.value)) {
          field.value = [...field.value, op.value]
          field.source = 'explicit'
        }
        break
      case 'remove':
        if (Array.isArray(field.value)) {
          field.value = field.value.filter((v: unknown) => v !== op.value)
        }
        break
      case 'clear':
        if (Array.isArray(field.value)) field.value = []
        else field.value = null
        field.source = 'unset'
        break
    }
  }
  // 同步到表单
  syncDraftToForm()
}

function syncDraftToForm() {
  const destination = destinationToString(draft.value.destination.value)
  form.title = form.title || (destination ? `${destination}之旅` : '')
  form.destination = destination || form.destination
  form.startDate = draft.value.startDate.value || form.startDate
  form.endDate = draft.value.endDate.value || form.endDate
  form.budgetAmount = draft.value.budgetAmount.value ?? form.budgetAmount
  form.travelers = draft.value.travelers.value
  form.preferences = [...draft.value.preferences.value]
}

function handleCardEdit(field: string) {
  // 切换到表单模式编辑
  useNaturalLanguage.value = false
}

function handleCardRemove(field: string, value?: string) {
  if (value) {
    applyOperations([{ type: 'remove', field, value }])
  }
}

function handleCardAppend(field: string) {
  useNaturalLanguage.value = false
}

function handleDestinationChange(sel: { province: string; city: string; districts: string[] }) {
  draft.value.destination.value = { province: sel.province, city: sel.city, districts: sel.districts }
  draft.value.destination.source = 'explicit'
  form.destination = sel.city
}

const emit = defineEmits<{
  logout: []
  openTrip: [tripId: string]
  search: [destination: string]
  includeArchived: [includeArchived: boolean]
  archiveTrip: [tripId: string]
  restoreTrip: [tripId: string]
}>()

const preferenceOptions = ['岭南文化', '本地美食', '城市漫步', '自然风景', '亲子体验', '夜间活动']
const dialogOpen = ref(false)
const destinationQuery = ref(props.destinationQuery)
const dialogElement = ref<HTMLElement | null>(null)
const submitting = ref(false)
const form = reactive({
  title: '',
  destination: '广州',
  startDate: '',
  endDate: '',
  budgetAmount: 3000,
  travelers: 1,
  travelerType: 'SOLO' as 'SOLO' | 'COUPLE' | 'FAMILY' | 'FRIENDS' | 'BUSINESS',
  pace: 'BALANCED' as 'RELAXED' | 'BALANCED' | 'INTENSIVE',
  preferences: [] as string[],
})

// ── Destination gradient mapping ──
const destinationGradientMap: Record<string, string> = {
  '广州': 'dest-gz',
  '北京': 'dest-bj',
  '杭州': 'dest-hz',
  '长沙': 'dest-cs',
  '成都': 'dest-cd',
  '上海': 'dest-sh',
  '深圳': 'dest-sz',
}

function destGradientClass(destination: string): string {
  return destinationGradientMap[destination] ?? 'bg-gradient-to-br from-primary-600 via-primary-700 to-primary-800'
}

function tripDays(trip: Trip): number {
  if (!trip.startDate || !trip.endDate) return 1
  const start = new Date(trip.startDate)
  const end = new Date(trip.endDate)
  const diff = Math.ceil((end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24)) + 1
  return Math.max(1, diff)
}

function tripThemes(trip: Trip): string[] {
  return trip.constraints.preferences.slice(0, 2)
}

function formatDate(date: string) {
  return date.replaceAll('-', '.')
}

function paceLabel(pace: Trip['constraints']['pace']) {
  return { RELAXED: '舒缓', BALANCED: '均衡', INTENSIVE: '紧凑' }[pace]
}

function travelerTypeLabel(type: Trip['constraints']['travelerType']) {
  return { SOLO: '独自', COUPLE: '伴侣', FAMILY: '家庭', FRIENDS: '朋友', BUSINESS: '商务' }[type]
}

function statusLabel(status: string) {
  return { DRAFT: '草稿', PLANNING: '规划中', READY: '可使用', FAILED: '规划失败' }[status] ?? status
}

function statusVariant(status: string): 'default' | 'secondary' | 'accent' | 'warning' | 'danger' | 'success' | 'outline' {
  return { DRAFT: 'secondary', PLANNING: 'warning', READY: 'success', FAILED: 'danger' }[status] as any ?? 'secondary'
}

function resetForm() {
  form.title = ''
  form.destination = '广州'
  form.startDate = ''
  form.endDate = ''
  form.budgetAmount = 3000
  form.travelers = 1
  form.travelerType = 'SOLO'
  form.pace = 'BALANCED'
  form.preferences = []
}

const { handleKeydown: handleDialogKeydown, rememberTrigger } = useModalFocus(
  dialogOpen,
  dialogElement,
  () => { dialogOpen.value = false },
)

function openDialog(event?: Event, initial?: Pick<typeof form, 'title' | 'destination'>) {
  rememberTrigger(event?.currentTarget)
  resetForm()
  draft.value = createDefaultDraft()
  parseWarnings.value = []
  parseUnrecognized.value = []
  useNaturalLanguage.value = true
  if (initial) {
    form.title = initial.title
    form.destination = initial.destination
    draft.value.destination.value = initial.destination
    draft.value.destination.source = 'explicit'
  }
  dialogOpen.value = true
}

function togglePreference(preference: string) {
  const index = form.preferences.indexOf(preference)
  if (index >= 0) form.preferences.splice(index, 1)
  else form.preferences.push(preference)
}

async function saveTrip() {
  submitting.value = true
  try {
    const title = form.title || `${form.destination || draft.value.destination.value}之旅`
    await props.createTrip({
      title,
      destination: form.destination,
      startDate: form.startDate,
      endDate: form.endDate,
      constraints: {
        budgetAmount: form.budgetAmount,
        travelers: form.travelers,
        travelerType: form.travelerType,
        pace: form.pace,
        preferences: [...form.preferences],
        fixedSchedules: [],
        arrival: null,
        departure: null,
        accommodation: null,
        mustVisitPlaces: [],
        avoidPlaces: [],
        mealWindows: [],
        mobilityLevel: 'STANDARD',
      },
    })
    dialogOpen.value = false
  } catch {
    // The parent renders the API error while the dialog remains open.
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <Transition name="page" appear>
    <div class="min-h-screen bg-surface-50">
      <!-- Top Bar -->
      <header class="sticky top-0 z-30 glass-surface">
        <div class="mx-auto flex h-16 max-w-6xl items-center justify-between gap-6 px-6">
          <div class="flex items-center gap-3 min-w-0">
            <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-primary-600 text-white shadow-sm">
              <Compass :size="20" aria-hidden="true" />
            </span>
            <div class="min-w-0">
              <strong class="text-base text-surface-900">TripPilot</strong>
              <span class="hidden sm:inline text-xs text-surface-400 ml-2">旅行规划工作台</span>
            </div>
          </div>
          <div class="flex items-center gap-4 min-w-0">
            <div class="hidden sm:grid min-w-0 max-w-[220px] text-right">
              <strong class="truncate text-sm text-surface-700">{{ user.displayName }}</strong>
              <span class="truncate text-xs text-surface-400">{{ user.email }}</span>
            </div>
            <button
              class="flex h-9 w-9 items-center justify-center rounded-xl border border-surface-200 bg-white text-surface-500 transition-colors hover:bg-surface-100 hover:text-surface-700"
              type="button" title="退出登录" aria-label="退出登录"
              @click="emit('logout')"
            >
              <LogOut :size="17" aria-hidden="true" />
            </button>
          </div>
        </div>
      </header>

      <!-- Dashboard -->
      <main class="mx-auto max-w-6xl px-4 sm:px-6 py-8 sm:py-12">
        <!-- Page Heading -->
        <div class="flex items-end justify-between gap-5 mb-4">
          <div>
            <p class="text-xs font-semibold uppercase tracking-widest text-surface-400 mb-1">Trips</p>
            <h1 class="text-2xl sm:text-3xl font-bold text-surface-900 tracking-tight text-balance">我的旅行</h1>
          </div>
          <Button variant="primary" size="md" @click="openDialog">
            <Plus :size="17" aria-hidden="true" />
            创建旅行
          </Button>
        </div>

        <div class="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <form class="flex max-w-md flex-1 items-center gap-2" data-testid="trip-search-form" @submit.prevent="emit('search', destinationQuery)">
            <input
              v-model.trim="destinationQuery"
              class="h-10 min-w-0 flex-1 rounded-lg border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:border-primary-400 focus:ring-2 focus:ring-primary-400/30"
              type="search"
              placeholder="目的地搜索"
              aria-label="目的地搜索"
              data-testid="trip-destination-search"
            />
            <button
              class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-surface-200 bg-white text-surface-600 hover:bg-surface-100"
              type="submit"
              title="搜索旅行"
              aria-label="搜索旅行"
            >
              <Search :size="17" aria-hidden="true" />
            </button>
          </form>
          <label class="inline-flex h-10 items-center gap-2 self-start rounded-lg border border-surface-200 bg-white px-3 text-sm text-surface-600">
            <input
              :checked="includeArchived"
              class="h-4 w-4 accent-primary-600"
              type="checkbox"
              data-testid="include-archived"
              @change="emit('includeArchived', ($event.target as HTMLInputElement).checked)"
            />
            包含已归档
          </label>
        </div>

        <!-- Error -->
        <p v-if="error" class="mb-6 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700 border-l-4 border-red-400" role="alert">{{ error }}</p>

        <!-- Loading -->
        <div v-if="busy" class="flex min-h-[300px] items-center justify-center gap-2">
          <span class="h-2 w-2 animate-pulse rounded-full bg-primary-400" />
          <span class="h-2 w-2 animate-pulse rounded-full bg-primary-400" style="animation-delay: 0.2s" />
          <span class="h-2 w-2 animate-pulse rounded-full bg-primary-400" style="animation-delay: 0.4s" />
        </div>

        <!-- Content when loaded -->
        <template v-else>
          <!-- Trip Templates (always show when not busy) -->
          <TripTemplates
            v-if="trips.length <= 2"
            @select="(tmpl) => {
              openDialog(undefined, tmpl)
            }"
          />

          <!-- Empty State -->
          <div
            v-if="trips.length === 0 && !busy"
            class="flex min-h-[220px] flex-col items-center justify-center gap-4 rounded-3xl border-2 border-dashed border-surface-200 text-surface-400 bg-white/50"
          >
            <MapPin :size="36" stroke-width="1.5" aria-hidden="true" />
            <h2 class="text-lg font-semibold text-surface-500">还没有旅行</h2>
            <p class="text-sm text-surface-400 -mt-2">选择上方模板快速开始，或点击创建旅行</p>
            <Button variant="outline" @click="openDialog">
              <Plus :size="16" /> 创建第一条旅行
            </Button>
          </div>

          <!-- Trip Grid -->
          <div v-else class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5" aria-label="旅行列表">
            <Card
              v-for="trip in trips"
              :key="trip.id"
              padding="none"
              class="overflow-hidden group shadow-travel-card hover:shadow-travel-card-hover transition-all duration-300 hover:-translate-y-1"
              role="button"
              :aria-label="`打开 ${trip.title}`"
              :title="`打开 ${trip.title}`"
              tabindex="0"
              @click="emit('openTrip', trip.id)"
              @keydown.enter="emit('openTrip', trip.id)"
              @keydown.space.prevent="emit('openTrip', trip.id)"
            >
              <!-- Card Header — City-specific gradient -->
              <div
                :class="destGradientClass(trip.destination)"
                class="relative h-32 px-5 pt-4 pb-3 flex flex-col justify-between overflow-hidden"
              >
                <!-- Decorative pattern -->
                <div class="absolute inset-0 opacity-10 hero-pattern" />
                <!-- Status & Destination -->
                <div class="relative z-10 flex items-start justify-between gap-2">
                  <div class="flex min-w-0 items-center gap-2">
                    <Badge :variant="statusVariant(trip.status)" size="sm">{{ statusLabel(trip.status) }}</Badge>
                    <span class="inline-flex min-w-0 items-center gap-1 truncate text-xs font-medium text-white/80">
                      <MapPin :size="12" aria-hidden="true" />
                      {{ trip.destination }}
                    </span>
                  </div>
                  <button
                    v-if="trip.archivedAt"
                    class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/15 text-white hover:bg-white/25"
                    type="button"
                    :title="'恢复 ' + trip.title"
                    :aria-label="'恢复 ' + trip.title"
                    :data-testid="`restore-trip-${trip.id}`"
                    @click.stop="emit('restoreTrip', trip.id)"
                    @keydown.enter.stop
                    @keydown.space.stop
                  >
                    <ArchiveRestore :size="15" aria-hidden="true" />
                  </button>
                  <button
                    v-else
                    class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/15 text-white hover:bg-white/25"
                    type="button"
                    :title="'归档 ' + trip.title"
                    :aria-label="'归档 ' + trip.title"
                    :data-testid="`archive-trip-${trip.id}`"
                    @click.stop="emit('archiveTrip', trip.id)"
                    @keydown.enter.stop
                    @keydown.space.stop
                  >
                    <Archive :size="15" aria-hidden="true" />
                  </button>
                </div>
                <!-- Trip info overlay -->
                <div class="relative z-10">
                  <h2 class="text-white text-lg font-bold truncate tracking-tight">{{ trip.title }}</h2>
                  <p class="text-white/70 text-xs mt-1">
                    {{ tripDays(trip) }}天{{ tripDays(trip) - 1 }}夜 · {{ trip.constraints.travelers }}人同行
                  </p>
                </div>
              </div>

              <!-- Card Body -->
              <div class="px-5 py-4">
                <div class="flex items-center gap-2 text-sm text-surface-500 mb-3">
                  <CalendarDays :size="15" class="shrink-0" aria-hidden="true" />
                  <span>{{ formatDate(trip.startDate) }} — {{ formatDate(trip.endDate) }}</span>
                </div>

                <!-- Constraints Row -->
                <div class="grid grid-cols-3 gap-3 py-4 border-y border-surface-100">
                  <div class="min-w-0">
                    <div class="flex items-center gap-1 text-xs text-surface-400 mb-1"><Wallet :size="12" aria-hidden="true" />预算</div>
                    <div class="text-sm font-semibold text-surface-700 truncate">¥{{ trip.constraints.budgetAmount ?? '未设' }}</div>
                  </div>
                  <div class="min-w-0">
                    <div class="flex items-center gap-1 text-xs text-surface-400 mb-1"><Users :size="12" aria-hidden="true" />同行</div>
                    <div class="text-sm font-semibold text-surface-700 truncate">{{ trip.constraints.travelers }}人 · {{ travelerTypeLabel(trip.constraints.travelerType) }}</div>
                  </div>
                  <div class="min-w-0">
                    <div class="flex items-center gap-1 text-xs text-surface-400 mb-1"><CircleGauge :size="12" aria-hidden="true" />节奏</div>
                    <div class="text-sm font-semibold text-surface-700 truncate">{{ paceLabel(trip.constraints.pace) }}</div>
                  </div>
                </div>

                <!-- Footer: Themes + Arrow -->
                <div class="flex items-center justify-between gap-3 mt-4">
                  <div class="flex gap-1.5 overflow-hidden min-w-0">
                    <span
                      v-for="theme in tripThemes(trip)"
                      :key="theme"
                      class="shrink-0 rounded-full bg-primary-50 px-2.5 py-1 text-xs font-medium text-primary-600"
                    >{{ theme }}</span>
                    <span v-if="trip.constraints.preferences.length === 0" class="text-xs text-surface-300">未设置偏好</span>
                  </div>
                  <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-surface-100 text-surface-400 transition-all duration-300 group-hover:bg-primary-600 group-hover:text-white group-hover:shadow-map-marker">
                    <ArrowRight :size="16" aria-hidden="true" />
                  </span>
                </div>
              </div>
            </Card>
          </div>
        </template>
      </main>

      <!-- Create Trip Dialog -->
      <div v-if="dialogOpen" class="fixed inset-0 z-50 flex items-start justify-center pt-[5vh] sm:pt-[8vh]" @click.self="dialogOpen = false">
        <div class="fixed inset-0 bg-surface-900/30 backdrop-blur-sm" aria-hidden="true" />
        <div
          ref="dialogElement"
          class="relative mx-4 w-full max-w-xl max-h-[90vh] overflow-y-auto animate-scale-in rounded-3xl bg-white shadow-dialog ring-1 ring-black/5"
          role="dialog" aria-modal="true" aria-labelledby="create-trip-title"
          tabindex="-1"
          @keydown="handleDialogKeydown"
        >
          <div class="flex items-center justify-between gap-4 px-6 py-5 border-b border-surface-100">
            <div>
              <p class="text-xs font-semibold uppercase tracking-widest text-surface-400 mb-1">New Trip</p>
              <h2 id="create-trip-title" class="text-lg font-bold text-surface-800">创建旅行</h2>
            </div>
            <button
              class="flex h-9 w-9 items-center justify-center rounded-xl border border-surface-200 text-surface-400 hover:bg-surface-50 transition-colors"
              type="button" title="关闭" aria-label="关闭"
              @click="dialogOpen = false"
            >
              <X :size="17" aria-hidden="true" />
            </button>
          </div>

          <!-- 自然语言输入 -->
          <div class="px-6 pt-5">
            <NaturalLanguageInput
              :warnings="parseWarnings"
              :unrecognized="parseUnrecognized"
              @parse="handleParse"
            />
          </div>

          <!-- 约束卡片 -->
          <div class="px-6 pt-4" v-if="draft.destination.source !== 'unset'">
            <ConstraintCard
              :draft="draft"
              @edit="handleCardEdit"
              @remove="handleCardRemove"
              @append="handleCardAppend"
              @destination-change="handleDestinationChange"
            />
          </div>

          <!-- 传统表单（折叠） -->
          <details class="px-6 pt-4" open>
            <summary class="cursor-pointer text-xs font-semibold text-surface-500 hover:text-surface-700">
              {{ useNaturalLanguage ? '展开完整表单编辑' : '收起完整表单' }}
            </summary>

          <form class="py-5" @submit.prevent="saveTrip">
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div class="sm:col-span-2">
                <label for="trip-title" class="block text-xs font-semibold text-surface-600 mb-1.5">旅行名称</label>
                <input id="trip-title" v-model.trim="form.title" maxlength="120" required data-modal-initial-focus
                  class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
              </div>
              <div class="sm:col-span-2">
                <label for="destination" class="block text-xs font-semibold text-surface-600 mb-1.5">目的地</label>
                <input id="destination" v-model.trim="form.destination" maxlength="120" required
                  class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
              </div>
              <div>
                <label for="start-date" class="block text-xs font-semibold text-surface-600 mb-1.5">开始日期</label>
                <input id="start-date" v-model="form.startDate" type="date" required
                  class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
              </div>
              <div>
                <label for="end-date" class="block text-xs font-semibold text-surface-600 mb-1.5">结束日期</label>
                <input id="end-date" v-model="form.endDate" type="date" :min="form.startDate" required
                  class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
              </div>
              <div>
                <label for="budget" class="block text-xs font-semibold text-surface-600 mb-1.5">预算</label>
                <div class="flex items-center gap-2 h-10 rounded-xl border border-surface-200 bg-white px-3 focus-within:ring-2 focus-within:ring-primary-400/40 focus-within:border-primary-400 transition-shadow">
                  <span class="text-surface-400 text-sm">¥</span>
                  <input id="budget" v-model.number="form.budgetAmount" type="number" min="0" step="0.01" required
                    class="w-full h-full border-0 bg-transparent text-sm text-surface-800 outline-0" />
                </div>
              </div>
              <div>
                <label for="travelers" class="block text-xs font-semibold text-surface-600 mb-1.5">同行人数</label>
                <input id="travelers" v-model.number="form.travelers" type="number" min="1" max="50" required
                  class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
              </div>
              <div class="sm:col-span-2">
                <label for="traveler-type" class="block text-xs font-semibold text-surface-600 mb-1.5">同行类型</label>
                <select id="traveler-type" v-model="form.travelerType" required
                  class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow">
                  <option value="SOLO">独自出行</option>
                  <option value="COUPLE">伴侣同行</option>
                  <option value="FAMILY">家庭出行</option>
                  <option value="FRIENDS">朋友同行</option>
                  <option value="BUSINESS">商务出行</option>
                </select>
              </div>
            </div>

            <fieldset class="mt-5 border-0 p-0">
              <legend class="text-xs font-semibold text-surface-600 mb-2">旅行节奏</legend>
              <div class="grid grid-cols-3 rounded-xl bg-surface-100 p-1">
                <label v-for="p in [{v:'RELAXED',l:'舒缓'},{v:'BALANCED',l:'均衡'},{v:'INTENSIVE',l:'紧凑'}]" :key="p.v"
                  class="relative flex h-9 cursor-pointer items-center justify-center rounded-lg text-sm font-medium transition-all"
                  :class="form.pace === p.v ? 'bg-white text-primary-700 shadow-sm' : 'text-surface-500 hover:text-surface-700'"
                >
                  <input v-model="form.pace" type="radio" :value="p.v" class="sr-only" />
                  {{ p.l }}
                </label>
              </div>
            </fieldset>

            <fieldset class="mt-5 border-0 p-0">
              <legend class="text-xs font-semibold text-surface-600 mb-2">偏好</legend>
              <div class="flex flex-wrap gap-2">
                <label v-for="preference in preferenceOptions" :key="preference"
                  class="relative inline-flex cursor-pointer items-center rounded-xl border px-3 py-2 text-sm font-medium transition-all"
                  :class="form.preferences.includes(preference) ? 'border-primary-300 bg-primary-50 text-primary-700' : 'border-surface-200 bg-white text-surface-600 hover:bg-surface-50'"
                >
                  <input type="checkbox" :value="preference" :checked="form.preferences.includes(preference)" class="sr-only" @change="togglePreference(preference)" />
                  {{ preference }}
                </label>
              </div>
            </fieldset>

            <p v-if="error" class="mt-5 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700 border-l-4 border-red-400" role="alert">{{ error }}</p>

            <div class="flex items-center justify-end gap-3 mt-6 pt-5 border-t border-surface-100">
              <Button variant="outline" size="sm" type="button" @click="dialogOpen = false">取消</Button>
              <Button variant="primary" size="sm" type="submit" :disabled="submitting">保存旅行</Button>
            </div>
          </form>
          </details>
        </div>
      </div>
    </div>
  </Transition>
</template>
