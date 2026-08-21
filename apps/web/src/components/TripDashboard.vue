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
} from 'lucide-vue-next'
import { reactive, ref, computed } from 'vue'

import type { CreateTripInput, Trip, User } from '../lib/api'
import { useModalFocus } from '../lib/modal'
import { defaultTripTitle } from '../lib/trip-title'
import Button from './ui/Button.vue'
import Card from './ui/Card.vue'
import Badge from './ui/Badge.vue'

import ConstraintEditor from './ConstraintEditor.vue'
import CityCascadePicker from './CityCascadePicker.vue'
import TripBoundaryEditor from './TripBoundaryEditor.vue'
import {
  createConstraintEditorModel,
  toTripConstraints,
  validateConstraintEditor,
} from '../lib/constraint-editor'
import {
  destinationToRegionRef,
  type StructuredDestination,
} from '../lib/constraint-draft'

const props = withDefaults(defineProps<{
  user: User
  trips: Trip[]
  busy: boolean
  error: string | null
  createTrip: (input: CreateTripInput) => Promise<void>
  destinationQuery?: string
  includeArchived?: boolean
  getToken?: () => string
}>(), {
  destinationQuery: '',
  includeArchived: false,
  getToken: () => '',
})

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
const editorError = ref<string | null>(null)
const destination = ref<StructuredDestination | null>(null)
const form = reactive({
  title: '',
  destination: '',
  arrivalAt: '',
  departureAt: '',
  ...createConstraintEditorModel(),
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

type StatusVariant = 'default' | 'secondary' | 'accent' | 'warning' | 'danger' | 'success' | 'outline'

const STATUS_VARIANTS: Record<string, StatusVariant> = {
  DRAFT: 'secondary',
  PLANNING: 'warning',
  READY: 'success',
  FAILED: 'danger',
}

function statusVariant(status: string): StatusVariant {
  return STATUS_VARIANTS[status] ?? 'secondary'
}

function resetForm() {
  form.title = ''
  form.destination = ''
  form.arrivalAt = ''
  form.departureAt = ''
  destination.value = null
  Object.assign(form, createConstraintEditorModel())
  editorError.value = null
}

/** B13-B: structured province → city → district selection. */
function handleDestinationChange(sel: StructuredDestination) {
  // B13_FIX R5 (P1-6): switching cities invalidates place chips and anchor
  // picks chosen for the previous city — stale old-city selections must
  // never leak into a different destination's trip.
  if (destination.value?.city && sel.city !== destination.value.city) {
    form.mustVisitEntries = []
    form.avoidEntries = []
    form.arrivalRef = undefined
    form.departureRef = undefined
    form.accommodationRef = undefined
  }
  destination.value = sel
  form.destination = sel.city
}

/** B13-C: live preview of the deterministic server fallback title. */
const autoTitlePreview = computed(() => {
  if (form.title.trim()) return null
  if (!destination.value?.city || !form.arrivalAt || !form.departureAt) return null
  return defaultTripTitle(
    destination.value.city,
    form.arrivalAt.slice(0, 10),
    form.departureAt.slice(0, 10),
  )
})

const { handleKeydown: handleDialogKeydown, rememberTrigger } = useModalFocus(
  dialogOpen,
  dialogElement,
  () => { dialogOpen.value = false },
)

/** B13: the single create-trip flow.  Every entry point opens this dialog. */
function openCreateTrip(event?: Event) {
  rememberTrigger(event?.currentTarget)
  resetForm()
  dialogOpen.value = true
}

async function saveTrip() {
  // B13_FIX R6 (P1-3): the create page owns exactly two datetime inputs
  // (TripBoundaryEditor).  Anchor times are derived from the authoritative
  // boundaries so the legacy constraint times never appear as inputs.
  if (form.arrivalPlace && form.arrivalAt && !form.arrivalTime) {
    form.arrivalTime = form.arrivalAt.slice(0, 16)
  }
  if (form.departurePlace && form.departureAt && !form.departureTime) {
    form.departureTime = form.departureAt.slice(0, 16)
  }
  editorError.value = validateConstraintEditor(form, 'create')
  if (editorError.value) return
  const selection = destination.value
  if (!selection?.city) {
    editorError.value = '请先选择目的地（省—市—区）'
    return
  }
  if (!form.arrivalAt || !form.departureAt) {
    editorError.value = '请填写抵达和离开时间'
    return
  }
  if (form.arrivalAt >= form.departureAt) {
    editorError.value = '抵达时间必须早于离开时间'
    return
  }
  submitting.value = true
  try {
    const customTitle = form.title.trim()
    await props.createTrip({
      title: customTitle || undefined,
      destination: selection.city,
      region: destinationToRegionRef(selection),
      arrivalAt: `${form.arrivalAt}:00+08:00`,
      departureAt: `${form.departureAt}:00+08:00`,
      constraints: toTripConstraints(form, []),
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
            <p class="text-xs font-semibold tracking-widest text-surface-400 mb-1">旅行列表</p>
            <h1 class="text-2xl sm:text-3xl font-bold text-surface-900 tracking-tight text-balance">我的旅行</h1>
          </div>
          <Button variant="primary" size="md" @click="openCreateTrip">
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
          <!-- Empty State -->
          <div
            v-if="trips.length === 0 && !busy"
            class="flex min-h-[220px] flex-col items-center justify-center gap-4 rounded-3xl border-2 border-dashed border-surface-200 text-surface-400 bg-white/50"
          >
            <MapPin :size="36" stroke-width="1.5" aria-hidden="true" />
            <h2 class="text-lg font-semibold text-surface-500">还没有旅行</h2>
            <p class="text-sm text-surface-400 -mt-2">点击右上角“创建旅行”开始规划第一段行程</p>
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
              <p class="text-xs font-semibold tracking-widest text-surface-400 mb-1">新建旅行</p>
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

          <form class="px-6 py-5" @submit.prevent="saveTrip">
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div class="sm:col-span-2">
                <label for="trip-title" class="block text-xs font-semibold text-surface-600 mb-1.5">旅行名称</label>
                <input id="trip-title" v-model.trim="form.title" maxlength="120" data-modal-initial-focus
                  class="w-full h-10 rounded-xl border border-surface-200 bg-white px-3 text-sm text-surface-800 outline-0 focus:ring-2 focus:ring-primary-400/40 focus:border-primary-400 transition-shadow" />
                <p class="mt-1 text-xs text-surface-400">
                  可选，留空将自动命名{{ autoTitlePreview ? `，预览：${autoTitlePreview}` : '' }}
                </p>
              </div>
              <div class="sm:col-span-2">
                <CityCascadePicker
                  :province="destination?.province"
                  :city="destination?.city"
                  :districts="destination?.districts ?? []"
                  @change="handleDestinationChange"
                />
              </div>
              <div class="sm:col-span-2">
                <TripBoundaryEditor
                  v-model:arrival-at="form.arrivalAt"
                  v-model:departure-at="form.departureAt"
                />
              </div>
            </div>

            <ConstraintEditor
              class="mt-5"
              :model="form"
              mode="create"
              :preference-options="preferenceOptions"
              :city="form.destination"
              :get-token="props.getToken"
            />

            <p v-if="editorError" class="mt-5 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700 border-l-4 border-red-400" role="alert">{{ editorError }}</p>
            <p v-if="error" class="mt-5 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700 border-l-4 border-red-400" role="alert">{{ error }}</p>

            <div class="flex items-center justify-end gap-3 mt-6 pt-5 border-t border-surface-100">
              <Button variant="outline" size="sm" type="button" @click="dialogOpen = false">取消</Button>
              <Button variant="primary" size="sm" type="submit" :disabled="submitting">保存旅行</Button>
            </div>
          </form>
        </div>
      </div>
    </div>
  </Transition>
</template>
