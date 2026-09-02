<script setup lang="ts">
// Workspace Sidebar：工作区导航（Developer Tool 风格）。
// 紧凑小字号、单色图标；激活项 = 浅灰背景 + 左侧 2px 标记，无彩色块。
// 导航项均为真实可点击（不再占位）：
//   · 工作台 / 我的旅行 → 定位到旅行列表（我的旅行会清空搜索过滤）
//   · 搜索 → 聚焦侧栏搜索框，实时过滤旅行
//   · 设置 → 展开设置面板（当前账号 + 退出登录）
import { computed, nextTick, ref } from 'vue'
import {
  House, LayoutGrid, LogOut, Plus, RefreshCw, Search, Settings, User as UserIcon,
} from 'lucide-vue-next'

import type { Trip } from '../../lib/api'
import { tripSubtitle } from '../lib/present'
import type { TripPhase } from '../lib/phase'
import { useWorkspaceSession } from '../session'

const props = defineProps<{
  trips: Trip[]
  activeTripId: string | null
  activePhase: TripPhase | null
  loading: boolean
  error: string | null
}>()

const emit = defineEmits<{
  selectTrip: [id: string]
  newTrip: []
  retry: []
}>()

const session = useWorkspaceSession()

// ── 导航态：工作台 / 我的旅行 / 搜索 / 设置 ────────────────────────
type NavKey = 'workbench' | 'mytrips' | 'search' | 'settings'
const activeNav = ref<NavKey>('workbench')
const searchQuery = ref('')
const searchInputEl = ref<HTMLInputElement | null>(null)
const showSettings = ref(false)

const user = computed(() => session.user)

function goTrips() {
  activeNav.value = 'workbench'
  searchQuery.value = ''
  showSettings.value = false
}

function goMyTrips() {
  activeNav.value = 'mytrips'
  searchQuery.value = ''
  showSettings.value = false
}

function goSearch() {
  activeNav.value = 'search'
  showSettings.value = false
  void nextTick(() => searchInputEl.value?.focus())
}

function toggleSettings() {
  activeNav.value = 'settings'
  showSettings.value = !showSettings.value
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
</script>

<template>
  <nav class="flex h-full min-h-0 w-56 shrink-0 flex-col border-r border-tp-line bg-tp-panel" aria-label="工作区导航">
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
        :class="activeNav === 'mytrips' ? 'bg-tp-active text-tp-ink' : 'text-tp-sub hover:bg-tp-hover hover:text-tp-ink'"
        data-testid="workspace-nav-mytrips"
        @click="goMyTrips"
      >
        <LayoutGrid :size="13" aria-hidden="true" /> 我的旅行
      </button>
      <button
        type="button"
        class="flex h-7 w-full items-center justify-between gap-2 rounded px-2 text-xs transition-colors"
        :class="activeNav === 'search' ? 'bg-tp-active text-tp-ink' : 'text-tp-sub hover:bg-tp-hover hover:text-tp-ink'"
        data-testid="workspace-nav-search"
        @click="goSearch"
      >
        <span class="flex items-center gap-2"><Search :size="13" aria-hidden="true" /> 搜索</span>
        <span v-if="searchQuery" class="rounded-full bg-white px-1.5 text-[10px] text-tp-sub">{{ trips.length }}</span>
      </button>
    </div>

    <div class="mx-2 border-t border-tp-div" role="separator" />

    <!-- TRIPS（真实列表，支持搜索过滤） -->
    <div class="flex min-h-0 flex-1 flex-col px-2 py-2">
      <h2 class="m-0 mb-1 px-2 text-[10px] font-medium uppercase tracking-[0.08em] text-tp-mute">
        旅行
        <span class="ml-1 font-mono tracking-normal text-tp-faint">{{ filteredTrips.length }}</span>
      </h2>

      <!-- 搜索框 -->
      <div v-if="activeNav === 'search'" class="mb-1.5 px-1" data-testid="workspace-trips-search">
        <input
          ref="searchInputEl"
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
        <button
          v-for="trip in filteredTrips"
          :key="trip.id"
          type="button"
          class="flex h-8 w-full items-center gap-2 rounded px-2 text-left transition-colors"
          :class="trip.id === activeTripId
            ? 'bg-tp-active shadow-[inset_2px_0_0_theme(colors.tp.ink)]'
            : 'hover:bg-tp-hover'"
          :aria-current="trip.id === activeTripId ? 'true' : undefined"
          :data-testid="`workspace-project-${trip.id}`"
          @click="emit('selectTrip', trip.id)"
        >
          <span class="min-w-0 flex-1">
            <span
              class="block truncate text-xs leading-4"
              :class="trip.id === activeTripId ? 'font-medium text-tp-ink' : 'text-tp-body'"
            >{{ trip.title }}</span>
            <span class="block truncate text-[11px] leading-4 text-tp-mute">{{ tripSubtitle(trip) }}</span>
          </span>
          <span
            v-if="statusDot(activePhase, trip.id === activeTripId).visible"
            class="h-1.5 w-1.5 shrink-0 rounded-full"
            :class="statusDot(activePhase, trip.id === activeTripId).classes"
            :title="activePhase === 'planning' ? '规划中' : '已完成'"
            aria-hidden="true"
          />
        </button>
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

    <!-- 设置（可展开：当前账号 + 退出登录） -->
    <div class="px-2 py-2">
      <button
        type="button"
        class="flex h-7 w-full items-center gap-2 rounded px-2 text-xs transition-colors"
        :class="showSettings ? 'bg-tp-active text-tp-ink' : 'text-tp-sub hover:bg-tp-hover hover:text-tp-ink'"
        data-testid="workspace-nav-settings"
        @click="toggleSettings"
      >
        <Settings :size="13" aria-hidden="true" /> 设置
      </button>

      <div
        v-if="showSettings"
        class="mt-2 rounded-lg border border-tp-line bg-white p-2.5"
        data-testid="workspace-settings-panel"
      >
        <div class="flex items-center gap-2">
          <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-tp-active text-tp-sub" aria-hidden="true">
            <UserIcon :size="12" />
          </span>
          <div class="min-w-0 flex-1">
            <p class="m-0 truncate text-xs font-medium leading-4 text-tp-ink">
              {{ user?.displayName || '未登录' }}
            </p>
            <p class="m-0 truncate text-[11px] leading-4 text-tp-mute">{{ user?.email || '—' }}</p>
          </div>
        </div>
        <button
          type="button"
          class="mt-2 flex h-6 w-full items-center gap-1.5 rounded bg-tp-ink px-2 text-[11px] font-medium text-white transition-colors hover:opacity-90"
          data-testid="workspace-settings-logout"
          @click="session.logout"
        >
          <LogOut :size="11" aria-hidden="true" /> 退出登录
        </button>
      </div>
    </div>
  </nav>
</template>