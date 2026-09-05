<script setup lang="ts">
// Workspace Sidebar：工作区导航（Developer Tool 风格）。
// 紧凑小字号、单色图标；激活项 = 浅灰背景 + 左侧 2px 标记，无彩色块。
// 导航项均为真实可点击（不再占位）：
//   · 工作台 → 定位到旅行列表（清空搜索过滤）
//   · 知识库 → 打开知识库视图
//   · 设置 → icon-only 齿轮 → /workspace/settings（F-UI-11 方案 A / D3：
//     底部账号区与弹卡已移除，账号与退出登录迁移至设置中心「常规」分区）
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  Database, House, Plus, RefreshCw, Settings, Trash2,
} from 'lucide-vue-next'

import type { Trip } from '../../lib/api'
import { tripSubtitle } from '../lib/present'
import type { TripPhase } from '../lib/phase'

const props = defineProps<{
  trips: Trip[]
  activeTripId: string | null
  activePhase: TripPhase | null
  loading: boolean
  error: string | null
  knowledgeActive?: boolean
}>()

const emit = defineEmits<{
  selectTrip: [id: string]
  newTrip: []
  retry: []
  deleteTrips: [ids: string[]]
  openKnowledge: []
  exitKnowledge: []
}>()

const router = useRouter()

// ── 导航态：工作台 / 知识库（设置已迁移至 /workspace/settings，F-UI-11 D3） ──
type NavKey = 'workbench' | 'knowledge'
const activeNav = ref<NavKey>('workbench')
const searchQuery = ref('')

/** 设置入口（D3）：icon-only 齿轮 → 设置中心整页（方案 A 路由）。 */
function openSettings() {
  void router.push('/workspace/settings')
}

function goTrips() {
  activeNav.value = 'workbench'
  searchQuery.value = ''
  emit('exitKnowledge')
}

function goKnowledge() {
  activeNav.value = 'knowledge'
  searchQuery.value = ''
  emit('openKnowledge')
}

const filteredTrips = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return props.trips
  return props.trips.filter((trip) =>
    `${trip.title} ${trip.destination}`.toLowerCase().includes(q))
})

/** 旅行状态点：仅激活项显示——规划中（脉动） / 已完成（绿色常亮）；未规划无点 */
function statusDot(phase: TripPhase | null, active: boolean): { visible: boolean; classes: string } {
  if (!active || !phase) return { visible: false, classes: '' }
  if (phase === 'planning') return { visible: true, classes: 'bg-tp-run animate-pulse' }
  if (phase === 'completed') return { visible: true, classes: 'bg-tp-ok' }
  return { visible: false, classes: '' }
}

// ── 旅行删除：批量选择模式 + 单条删除 ──────────────────────────────
const manageMode = ref(false)
const selectedIds = ref<string[]>([])
const pendingDeleteIds = ref<string[] | null>(null)
const deleting = ref(false)
const deleteError = ref<string | null>(null)

function toggleManage() {
  manageMode.value = !manageMode.value
  selectedIds.value = []
  pendingDeleteIds.value = null
  deleteError.value = null
}

function toggleSelect(tripId: string) {
  selectedIds.value = selectedIds.value.includes(tripId)
    ? selectedIds.value.filter((id) => id !== tripId)
    : [...selectedIds.value, tripId]
}

const allFilteredSelected = computed(() =>
  filteredTrips.value.length > 0
  && filteredTrips.value.every((trip) => selectedIds.value.includes(trip.id)))

function toggleSelectAll() {
  selectedIds.value = allFilteredSelected.value
    ? []
    : filteredTrips.value.map((trip) => trip.id)
}

/** 请求删除确认：单条传入 [tripId]，批量用已勾选。 */
function requestDelete(ids: string[]) {
  pendingDeleteIds.value = [...ids]
  deleteError.value = null
}

async function confirmDelete() {
  const ids = pendingDeleteIds.value
  if (!ids || ids.length === 0 || deleting.value) return
  deleting.value = true
  deleteError.value = null
  try {
    await (emit('deleteTrips', ids) as unknown as Promise<unknown>)
    selectedIds.value = selectedIds.value.filter((id) => !ids.includes(id))
    pendingDeleteIds.value = null
    if (manageMode.value && selectedIds.value.length === 0) manageMode.value = false
  } catch {
    deleteError.value = '删除失败，请稍后重试'
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <nav class="flex h-full min-h-0 w-full shrink-0 flex-col bg-tp-panel" aria-label="工作区导航">
    <!-- WORKSPACE 功能导航 -->
    <div class="px-2 pb-2 pt-3">
      <h2 class="m-0 mb-1 px-2 text-[10px] font-medium uppercase tracking-[0.08em] text-tp-mute">工作区</h2>
      <button
        type="button"
        class="flex h-7 w-full items-center gap-2 rounded px-2 text-xs transition-colors"
        :class="activeNav === 'workbench' ? 'bg-tp-active text-tp-ink' : 'text-tp-sub hover:bg-tp-hover hover:text-tp-ink'"
        aria-current="page"
        data-testid="workspace-nav-home"
        @click="goTrips"
      >
        <House :size="13" :class="activeNav === 'workbench' ? 'text-tp-sub' : ''" aria-hidden="true" /> 工作台
      </button>
      <button
        type="button"
        class="flex h-7 w-full items-center gap-2 rounded px-2 text-xs transition-colors"
        :class="props.knowledgeActive || activeNav === 'knowledge' ? 'bg-tp-active text-tp-ink' : 'text-tp-sub hover:bg-tp-hover hover:text-tp-ink'"
        data-testid="workspace-nav-knowledge"
        @click="goKnowledge"
      >
        <Database :size="13" aria-hidden="true" /> 知识库
      </button>
    </div>

    <div class="mx-2 border-t border-tp-div" role="separator" />

    <!-- TRIPS（真实列表，支持搜索过滤） -->
    <div class="flex min-h-0 flex-1 flex-col px-2 py-2">
      <div class="mb-1 flex items-center justify-between px-2">
        <h2 class="m-0 text-[10px] font-medium uppercase tracking-[0.08em] text-tp-mute">
          旅行
          <span class="ml-1 font-mono tracking-normal text-tp-faint">{{ filteredTrips.length }}</span>
        </h2>
        <button
          v-if="filteredTrips.length"
          type="button"
          class="rounded px-1.5 text-[10px] font-medium text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
          data-testid="workspace-manage-toggle"
          @click="toggleManage"
        >{{ manageMode ? '完成' : '选择' }}</button>
      </div>

      <!-- 批量选择工具条 -->
      <div
        v-if="manageMode && filteredTrips.length"
        class="mb-1.5 flex items-center justify-between gap-1 rounded-md border border-tp-line bg-white px-1.5 py-1"
        data-testid="workspace-manage-bar"
      >
        <button
          type="button"
          class="rounded px-1.5 py-0.5 text-[11px] font-medium text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
          data-testid="workspace-manage-select-all"
          @click="toggleSelectAll"
        >{{ allFilteredSelected ? '取消全选' : '全选' }}</button>
        <span class="text-[11px] text-tp-mute">已选 {{ selectedIds.length }}</span>
        <button
          type="button"
          :disabled="selectedIds.length === 0 || deleting"
          class="flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium transition-colors disabled:opacity-40"
          :class="selectedIds.length ? 'text-tp-warn hover:bg-tp-warn/10' : 'text-tp-faint'"
          data-testid="workspace-manage-delete-selected"
          @click="requestDelete(selectedIds)"
        >
          <Trash2 :size="11" aria-hidden="true" />删除
        </button>
      </div>

      <!-- 删除确认（单条与批量共用） -->
      <div
        v-if="pendingDeleteIds"
        class="mb-1.5 rounded-md border border-tp-warn/30 bg-tp-warn/10 px-2 py-2"
        role="alertdialog"
        aria-label="确认删除旅行"
        data-testid="workspace-delete-confirm"
      >
        <p class="m-0 text-[11px] leading-4 text-tp-warn">
          确定删除 {{ pendingDeleteIds.length }} 个旅行？删除后将从列表移除。
        </p>
        <p v-if="deleteError" class="m-0 mt-1 text-[11px] leading-4 text-tp-warn" role="alert">{{ deleteError }}</p>
        <div class="mt-1.5 flex gap-1.5">
          <button
            type="button"
            :disabled="deleting"
            class="rounded bg-tp-warn px-2 py-1 text-[11px] font-medium text-white disabled:opacity-50"
            data-testid="workspace-delete-confirm-ok"
            @click="confirmDelete"
          >{{ deleting ? '删除中…' : '确认删除' }}</button>
          <button
            type="button"
            :disabled="deleting"
            class="rounded bg-white px-2 py-1 text-[11px] text-tp-sub transition-colors hover:bg-tp-hover disabled:opacity-50"
            data-testid="workspace-delete-confirm-cancel"
            @click="pendingDeleteIds = null; deleteError = null"
          >取消</button>
        </div>
      </div>

      <!-- 搜索框（常驻：合并到此，始终可见） -->
      <div class="mb-1.5 px-1" data-testid="workspace-trips-search">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="按标题/目的地过滤"
          class="h-7 w-full rounded-md border border-tp-line bg-white px-2 text-xs text-tp-ink outline-none placeholder:text-tp-faint"
          data-testid="workspace-trips-search-input"
        />
      </div>

      <!-- 加载中 -->
      <p
        v-if="loading && trips.length === 0"
        class="m-0 flex items-center gap-1.5 px-2 py-2 text-[11px] leading-4 text-tp-mute"
        data-testid="workspace-trips-loading"
      >
        <span class="inline-block h-1.5 w-1.5 rounded-full bg-tp-dot animate-pulse" aria-hidden="true" />
        正在加载旅行……
      </p>

      <!-- 错误（明确反馈 + 重试；绝不回退假数据） -->
      <div v-else-if="error && trips.length === 0" class="px-2 py-2" data-testid="workspace-trips-error">
        <p class="m-0 text-[11px] leading-4 text-tp-warn">{{ error }}</p>
        <button
          type="button"
          class="mt-1.5 flex h-6 items-center gap-1 rounded px-1.5 text-[11px] text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
          data-testid="workspace-trips-retry"
          @click="emit('retry')"
        >
          <RefreshCw :size="11" aria-hidden="true" /> 重试
        </button>
      </div>

      <!-- 空态 -->
      <p
        v-else-if="trips.length === 0"
        class="m-0 px-2 py-2 text-[11px] leading-4 text-tp-faint"
        data-testid="workspace-trips-empty"
      >
        还没有旅行，从「新建旅行」开始。
      </p>
      <p v-else-if="filteredTrips.length === 0" class="m-0 px-2 py-2 text-[11px] leading-4 text-tp-faint">
        没有匹配的旅行。
      </p>

      <div v-else class="min-h-0 flex-1 space-y-0.5 overflow-y-auto" data-testid="workspace-project-list">
        <div
          v-for="trip in filteredTrips"
          :key="trip.id"
          class="group flex h-8 w-full items-center gap-1.5 rounded px-2 transition-colors"
          :class="trip.id === activeTripId
            ? 'bg-tp-active shadow-[inset_2px_0_0_theme(colors.tp.ink)]'
            : 'hover:bg-tp-hover'"
          :data-selected="manageMode && selectedIds.includes(trip.id) ? 'true' : undefined"
          :data-testid="`workspace-project-row-${trip.id}`"
        >
          <!-- 批量选择复选框 -->
          <button
            v-if="manageMode"
            type="button"
            class="flex h-5 w-5 shrink-0 items-center justify-center rounded border border-tp-line transition-colors"
            :class="selectedIds.includes(trip.id) ? 'border-tp-ink bg-tp-ink text-white' : 'bg-white text-transparent'"
            :aria-label="`选择旅行 ${trip.title}`"
            :aria-pressed="selectedIds.includes(trip.id)"
            :data-testid="`workspace-manage-check-${trip.id}`"
            @click="toggleSelect(trip.id)"
          >
            <span class="text-[10px] leading-none">✓</span>
          </button>

          <!-- 主体：选中进入该旅行 -->
          <button
            type="button"
            class="min-w-0 flex-1 text-left"
            :disabled="manageMode"
            :aria-current="trip.id === activeTripId ? 'true' : undefined"
            :data-testid="`workspace-project-${trip.id}`"
            @click="emit('selectTrip', trip.id)"
          >
            <span
              class="block truncate text-xs leading-4"
              :class="trip.id === activeTripId ? 'font-medium text-tp-ink' : 'text-tp-body'"
            >{{ trip.title }}</span>
            <span class="block truncate text-[11px] leading-4 text-tp-mute">{{ tripSubtitle(trip) }}</span>
          </button>

          <span
            v-if="statusDot(activePhase, trip.id === activeTripId).visible"
            class="h-1.5 w-1.5 shrink-0 rounded-full"
            :class="statusDot(activePhase, trip.id === activeTripId).classes"
            :title="activePhase === 'planning' ? '规划中' : '已完成'"
            aria-hidden="true"
          />

          <!-- 单条删除（非批量模式，hover 显现） -->
          <button
            v-if="!manageMode"
            type="button"
            class="hidden h-6 w-6 shrink-0 items-center justify-center rounded text-tp-faint transition-colors hover:bg-tp-warn/10 hover:text-tp-warn group-hover:flex"
            title="删除旅行"
            :aria-label="`删除旅行 ${trip.title}`"
            :data-testid="`workspace-delete-${trip.id}`"
            @click="requestDelete([trip.id])"
          >
            <Trash2 :size="12" aria-hidden="true" />
          </button>
        </div>
      </div>

      <button
        type="button"
        class="flex h-7 items-center gap-2 rounded px-2 text-xs text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
        data-testid="workspace-new-trip"
        @click="emit('newTrip')"
      >
        <Plus :size="13" aria-hidden="true" /> 新建旅行
      </button>
    </div>

    <div class="mx-2 border-t border-tp-div" role="separator" />

    <!-- 设置入口（F-UI-11 D3）：icon-only 齿轮 → /workspace/settings -->
    <div class="px-2 py-2">
      <button
        type="button"
        class="flex h-7 w-7 items-center justify-center rounded text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
        title="设置"
        aria-label="设置"
        data-testid="workspace-nav-settings"
        @click="openSettings"
      >
        <Settings :size="14" aria-hidden="true" />
      </button>
    </div>
  </nav>
</template>