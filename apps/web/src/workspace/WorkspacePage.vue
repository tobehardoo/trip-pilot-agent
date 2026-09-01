<script setup lang="ts">
// TripPilot Planning Intelligence — Workspace Shell 顶层装配。
//
// F-UI-11 Phase 2：真实 Agent + Planning + SSE 接入。
// useAgentWorkspace 实例化于页面级别，CommandBar 调用其 send()。
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AuthView, { type AuthSubmission } from '../components/AuthView.vue'
import { useWorkspaceSession } from './session'
import { useAuthStore } from '../app/stores/auth'
import { useAgentWorkspace } from '../components/agent-workspace/useAgentWorkspace'
import WorkspaceHeader from './layout/WorkspaceHeader.vue'
import WorkspaceSidebar from './layout/WorkspaceSidebar.vue'
import WorkspaceContextPanel from './layout/WorkspaceContextPanel.vue'
import WorkspaceCommandBar from './layout/WorkspaceCommandBar.vue'
import ConstraintEditDrawer from './layout/ConstraintEditDrawer.vue'
import ItineraryWorkspace from './plan/ItineraryWorkspace.vue'
import TripDraftView from './plan/TripDraftView.vue'
import TripOverview from './plan/TripOverview.vue'
import TripRouteMap from './plan/TripRouteMap.vue'
import NewTripDrawer from './layout/NewTripDrawer.vue'
import EmptyState from '../components/ui/EmptyState.vue'
import AgentDialog from './execution/AgentDialog.vue'

import { useTripStore } from './stores/tripStore'
import type { CreateTripInput } from '../lib/api'

const tripStore = useTripStore()
const { trips, itinerary, selectTrip, createTrip, loadTrips, updateConstraints } = tripStore
const session = useWorkspaceSession()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

// ── Agent Workspace（Phase 2） ──────────────────────────────────
const agent = useAgentWorkspace({
  tripId: () => tripStore.currentTripId ?? '',
  getToken: () => auth.accessToken,
  tripVersion: () => tripStore.currentTrip?.version ?? 0,
  tripConstraints: () => tripStore.currentTrip?.constraints ?? null,
  applyConstraints: async (input) => {
    await updateConstraints(input)
  },
})

// F-UI-11 Phase 0：冷启动恢复会话；guest → AuthView。
onMounted(() => {
  void session.restoreSession()
})

// 响应式状态：<1024px 两侧均为抽屉（默认收起、互斥打开）；
// 1024~1279 仅 Sidebar 常驻；≥1280 三栏全部常驻。
const lgUp = window.matchMedia('(min-width: 1024px)')
const xlUp = window.matchMedia('(min-width: 1280px)')

const drawerMode = ref(!lgUp.matches)
const sidebarOpen = ref(lgUp.matches)
const contextOpen = ref(xlUp.matches)
const newTripOpen = ref(false)
const editConstraintsOpen = ref(false)

/** 中间区渲染由当前旅行阶段推导（数据驱动，不再有"演示"切换） */
const mainView = computed(() => tripStore.currentPhase ?? 'draft')

// URL → 选中旅行（刷新/直链恢复）
watch(
  () => route.params.tripId,
  (id) => {
    if (typeof id === 'string' && id !== tripStore.currentTripId) selectTrip(id)
  },
  { immediate: true },
)

lgUp.addEventListener('change', (event) => {
  drawerMode.value = !event.matches
  if (event.matches) {
    sidebarOpen.value = true
    contextOpen.value = xlUp.matches
  } else {
    sidebarOpen.value = false
    contextOpen.value = false
  }
})
xlUp.addEventListener('change', (event) => {
  if (!drawerMode.value) contextOpen.value = event.matches
})

function toggleSidebar() {
  if (drawerMode.value && !sidebarOpen.value) contextOpen.value = false
  sidebarOpen.value = !sidebarOpen.value
}

function toggleContext() {
  if (drawerMode.value && !contextOpen.value) sidebarOpen.value = false
  contextOpen.value = !contextOpen.value
}

function closeDrawersOnNavigate() {
  if (drawerMode.value) {
    sidebarOpen.value = false
    contextOpen.value = false
  }
}

/** 左侧旅行切换：更新数据上下文 + 总是同步 URL */
function handleSelectTrip(id: string) {
  if (tripStore.currentTripId !== id) selectTrip(id)
  router.push(`/workspace/trips/${id}`)
  closeDrawersOnNavigate()
}

/** 新建旅行：创建（store 自动追加并选中）+ URL 同步 */
async function handleTripCreated(input: CreateTripInput) {
  const created = await createTrip(input)
  router.push(`/workspace/trips/${created.id}`)
  newTripOpen.value = false
  closeDrawersOnNavigate()
}

/** 编辑约束保存后关闭抽屉 */
function handleConstraintsSaved() {
  editConstraintsOpen.value = false
  closeDrawersOnNavigate()
}

/** 打开编辑约束抽屉 */
function openEditConstraints() {
  if (!tripStore.currentTrip) return
  editConstraintsOpen.value = true
}
</script>

<template>
  <!-- 会话恢复中 -->
  <main
    v-if="session.phase === 'restoring'"
    class="grid h-screen place-items-center bg-tp-bg"
    aria-label="正在恢复登录状态"
    data-testid="workspace-restoring"
  >
    <p class="m-0 flex items-center gap-2 text-xs leading-4 text-tp-sub">
      <span class="inline-block h-1.5 w-1.5 rounded-full bg-tp-dot animate-pulse" aria-hidden="true" />
      正在恢复登录状态……
    </p>
  </main>

  <!-- 未登录 -->
  <AuthView
    v-else-if="session.phase === 'guest'"
    :busy="session.busy"
    :error="session.error"
    data-testid="workspace-auth"
    @submit="session.authenticate"
  />

  <!-- 已登录：Workspace 四区壳 -->
  <div v-else class="flex h-screen min-h-0 flex-col overflow-hidden bg-tp-bg" data-testid="workspace-shell">
    <WorkspaceHeader
      :task-title="tripStore.currentTrip?.title ?? '未选择旅行'"
      :sidebar-visible="sidebarOpen"
      :context-visible="contextOpen"
      :phase="tripStore.currentPhase"
      @toggle-sidebar="toggleSidebar"
      @toggle-context="toggleContext"
    />

    <div class="relative flex min-h-0 flex-1 items-stretch">
      <!-- 抽屉遮罩 -->
      <div
        v-if="drawerMode && (sidebarOpen || contextOpen)"
        class="absolute inset-0 z-20 bg-tp-ink/20"
        data-testid="workspace-drawer-backdrop"
        @click="closeDrawersOnNavigate"
      />

      <!-- 左：Sidebar -->
      <div
        v-if="sidebarOpen"
        class="absolute inset-y-0 left-0 z-30 border-r border-tp-line lg:static lg:z-auto lg:border-r-0"
      >
        <WorkspaceSidebar
          :trips="trips"
          :active-trip-id="tripStore.currentTripId"
          :active-phase="tripStore.currentPhase"
          :loading="tripStore.listStatus === 'loading'"
          :error="tripStore.listError"
          @select-trip="handleSelectTrip"
          @new-trip="newTripOpen = true"
          @retry="loadTrips"
        />
      </div>

      <!-- 中：工作区 -->
      <main class="min-w-0 flex-1 overflow-y-auto bg-tp-bg" data-testid="workspace-main">
        <!-- 规划中 -->
        <div v-if="mainView === 'planning' && tripStore.currentTrip" class="mx-auto w-full max-w-3xl px-6 py-5">
          <TripOverview :trip="tripStore.currentTrip" />
          <p class="m-0 mt-2 flex items-center gap-1.5 text-xs leading-4 text-tp-sub" data-testid="planning-status-line">
            <span class="inline-block h-1.5 w-1.5 rounded-full bg-tp-run animate-pulse" aria-hidden="true" />
            TripPilot 正在规划你的旅行
          </p>
          <div class="mt-4 border-t border-tp-div" role="separator" />
          <TripRouteMap :trip="tripStore.currentTrip" :generating="true" />
          <div class="mt-4 border-t border-tp-div" role="separator" />
          <!-- 真实 Agent 对话 -->
          <div class="mt-4">
            <AgentDialog :agent="agent" />
          </div>
        </div>

        <!-- 已完成 -->
        <ItineraryWorkspace v-else-if="mainView === 'completed' && tripStore.currentTrip" :trip="tripStore.currentTrip" :itinerary="itinerary" />

        <!-- 未规划 draft -->
        <TripDraftView
          v-else-if="mainView === 'draft' && tripStore.currentTrip"
          :trip="tripStore.currentTrip"
          @edit-constraints="openEditConstraints"
        />

        <!-- 兜底 -->
        <div v-else class="mx-auto w-full max-w-2xl px-6 py-10">
          <EmptyState title="未选择旅行" description="从左侧选择一个旅行，或新建一个旅行开始。" />
        </div>
      </main>

      <!-- 右：Context Inspector -->
      <div
        v-if="contextOpen"
        class="absolute inset-y-0 right-0 z-30 border-l border-tp-line xl:static xl:z-auto xl:border-l-0"
      >
        <WorkspaceContextPanel :trip="tripStore.currentTrip" @edit-constraints="openEditConstraints" />
      </div>
    </div>

    <!-- 底：Agent Command Bar（接入真实 Agent） -->
    <WorkspaceCommandBar :disabled="agent.inputDisabled.value" @submit="agent.send" />

    <!-- 新建旅行抽屉 -->
    <NewTripDrawer :open="newTripOpen" @close="newTripOpen = false" @created="handleTripCreated" />

    <!-- 编辑约束抽屉 -->
    <ConstraintEditDrawer
      :open="editConstraintsOpen"
      :trip="tripStore.currentTrip"
      @close="editConstraintsOpen = false"
    />
  </div>
</template>