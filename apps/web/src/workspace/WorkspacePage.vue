<script setup lang="ts">
// TripPilot Planning Intelligence — Workspace Shell 顶层装配。
//
// Composer 交互重构（2026-09-02 design §1）：双模式。
//   创建模式（无选中旅行）：中央悬浮 Composer + 创建对话（trip-less Plan C 通道），
//     Required Context（目的地+日期）= 最小必填上下文，其余需求对话式补全；
//     [开始规划] → createTripFromAgent → adoptTrip → 进入旅行模式并自动发起 kickoff run。
//   旅行模式：现有三视图（draft/planning/completed）+ 底部 docked Composer
//     （原 WorkspaceCommandBar 被 docked 形态吸收，同一组件不维护两套聊天框）。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'

import AuthView, { type AuthSubmission } from '../components/AuthView.vue'
import { useWorkspaceSession } from './session'
import { useAuthStore } from '../app/stores/auth'
import { useAgentWorkspace } from '../components/agent-workspace/useAgentWorkspace'
import WorkspaceHeader from './layout/WorkspaceHeader.vue'
import WorkspaceSidebar from './layout/WorkspaceSidebar.vue'
import WorkspaceContextPanel from './layout/WorkspaceContextPanel.vue'
import { usePanelResize } from './layout/usePanelResize'
import ItineraryWorkspace from './plan/ItineraryWorkspace.vue'
import TripLoadingState from './plan/TripLoadingState.vue'
import TripOverview from './plan/TripOverview.vue'
import TripRouteMap from './plan/TripRouteMap.vue'
import KnowledgeBasePage from './knowledge/KnowledgeBasePage.vue'
import SettingsPage from './settings/SettingsPage.vue'
import AgentDialog from './execution/AgentDialog.vue'
import WorkspaceComposer from './composer/WorkspaceComposer.vue'
import CreationTranscript from './composer/CreationTranscript.vue'
import { useCreationSession } from './composer/useCreationSession'

import { useTripStore } from './stores/tripStore'
import { createTripFromAgent } from '../lib/api'
import { presentableError } from './lib/errors'

const tripStore = useTripStore()
// setup store 的 ref 状态必须经 storeToRefs 解构才能保持响应式（直接解构拿到的是初始快照）
const { trips } = storeToRefs(tripStore)
const { itinerary, selectTrip, loadTrips, updateConstraints } = tripStore
const session = useWorkspaceSession()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

// ── Agent Workspace（旅行模式对话，Phase 2 既有通道） ────────────
const agent = useAgentWorkspace({
  tripId: () => tripStore.currentTripId ?? '',
  getToken: () => auth.accessToken,
  tripVersion: () => tripStore.currentTrip?.version ?? 0,
  tripConstraints: () => tripStore.currentTrip?.constraints ?? null,
  applyConstraints: async (input) => {
    await updateConstraints(input)
  },
  refreshTrip: () => tripStore.refreshCurrentTrip(),
  tripStatus: () => tripStore.currentTrip?.status,
})

// F-UI-11 Phase 0：冷启动恢复会话；guest → AuthView。
onMounted(() => {
  void session.restoreSession()
})

// 响应式状态（F-UI-12 三栏并排 + 可拖拽）：<768px 两侧均为抽屉（默认收起、
// 互斥打开）；≥768px Sidebar 常驻并排；≥1024px 右栏也常驻——三栏并排，
// 不再以覆盖式抽屉出现（手机除外）。栏宽为「占容器比例」（CSS clamp 包 px
// 上下限），不同屏幕等比例缩放；拖分隔把手调整，宽度持久化见 usePanelResize。
const mdUp = window.matchMedia('(min-width: 768px)')
const lgUp = window.matchMedia('(min-width: 1024px)')

const drawerMode = ref(!mdUp.matches)
const sidebarOpen = ref(mdUp.matches)
const contextOpen = ref(lgUp.matches)

const { panesEl, sidebarRatio, contextRatio, startResize } = usePanelResize()

/** 栏宽渲染：并排 = clamp(px下限, 比例%, px上限) 等比缩放；抽屉 = 固定 px。 */
const sidebarStyle = computed(() =>
  drawerMode.value
    ? { width: '240px' }
    : { width: `clamp(180px, ${(sidebarRatio.value * 100).toFixed(2)}%, 360px)` },
)
const contextStyle = computed(() =>
  drawerMode.value
    ? { width: '264px' }
    : { width: `clamp(200px, ${(contextRatio.value * 100).toFixed(2)}%, 400px)` },
)

// ── 双模式 ──────────────────────────────────────────────────────
const creationMode = computed(() => tripStore.currentTripId === null)

/** 知识库管理视图（侧栏「知识库」打开时接管主区）。 */
const showKnowledge = ref(false)

/** 设置中心（F-UI-11 方案 A）：/workspace/settings 整页替换工作区壳。 */
const isSettingsRoute = computed(() => route.name === 'workspace-settings')

/** 中间区渲染由当前旅行阶段推导（数据驱动，不再有"演示"切换） */
const mainView = computed(() => tripStore.currentPhase ?? 'draft')

// P0「假成功」门控：trip.status=COMPLETED 本身不足以渲染"已完成"视图。
// 必须同时拿到**非空**的 itinerary.days，才呈现真实方案；否则显示加载/重试态，
// 绝不展示"旅行方案已经完成，共 0 天"这种空结果完成的假成功。
const completedItineraryReady = computed(() =>
  tripStore.currentPhase === 'completed'
  && Boolean(tripStore.itinerary)
  && tripStore.itinerary!.days.length > 0,
)
const tripCompletedNoData = computed(() =>
  tripStore.currentPhase === 'completed' && !completedItineraryReady.value,
)

function reloadItinerary(): void {
  const id = tripStore.currentTripId
  if (id) void tripStore.loadItinerary(id)
}

// ── 创建会话（Composer 前置对话）+ Required Context ─────────────
const creation = useCreationSession()

const requiredContext = ref<{
  destination: string | null
  region: { provinceCode: string; cityCode: string } | null
  startDate: string | null
  endDate: string | null
}>({ destination: null, region: null, startDate: null, endDate: null })

// Composer 右下出行设置：人数/预算（随每轮 tripContext 提交；null=未填）
const travelers = ref<number | null>(null)
const budget = ref<number | null>(null)

const creationStarted = computed(() => creation.reply.value !== null)
const chipsLocked = computed(() => creationStarted.value)
const requiredOk = computed(() =>
  Boolean(requiredContext.value.destination)
  && Boolean(requiredContext.value.startDate && requiredContext.value.endDate),
)
const creationReady = computed(() => creation.reply.value?.ready === true && requiredOk.value)
const creatingTrip = ref(false)
const startError = ref<string | null>(null)

const creationHint = computed(() => {
  if (startError.value) return startError.value
  if (creatingTrip.value) return '正在创建旅行……'
  if (!requiredOk.value && !creationStarted.value) return '先填写目的地和日期，就可以开始和 TripPilot 聊。'
  if (requiredOk.value && creationStarted.value && (travelers.value == null || budget.value == null))
    return '还要填一下右下角的出行人数和预算，就可以开始规划。'
  return null
})

const taskTitle = computed(() => {
  if (tripStore.currentTrip) return tripStore.currentTrip.title
  const dest = requiredContext.value.destination
  return dest ? `${dest} · 新旅行` : '新旅行'
})

function shortDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const parts = iso.split('-')
  return parts.length === 3 ? `${parts[1]}/${parts[2]}` : (iso ?? '')
}

const dockContextLabel = computed(() => {
  const trip = tripStore.currentTrip
  if (!trip) return ''
  return `${trip.destination} · ${shortDate(trip.startDate)} → ${shortDate(trip.endDate)}`
})

// URL → 选中旅行（刷新/直链恢复）
watch(
  () => route.params.tripId,
  (id) => {
    if (typeof id === 'string' && id !== tripStore.currentTripId) selectTrip(id)
  },
  { immediate: true },
)

// 深链接/刷新修复：页面挂载时 session 尚在 restoring，route watch 触发的
// selectTrip 会被其「未认证即返回」守卫跳过；认证完成后必须重新按 URL 选中旅行，
// 否则 currentTrip 永远为 null（渲染「未选择旅行」空状态）。
watch(
  () => session.phase,
  (phase) => {
    if (phase !== 'authenticated') return
    const id = route.params.tripId
    if (typeof id === 'string' && id !== tripStore.currentTripId) selectTrip(id)
  },
)

mdUp.addEventListener('change', (event) => {
  drawerMode.value = !event.matches
  if (event.matches) {
    sidebarOpen.value = true
    contextOpen.value = lgUp.matches
  } else {
    sidebarOpen.value = false
    contextOpen.value = false
  }
})
lgUp.addEventListener('change', (event) => {
  if (!drawerMode.value) contextOpen.value = event.matches
})

// ── 规划阶段轮询 ──────────────────────────────────────────────────
// AGENT_COMPLETED（SSE）与后端 itinerary 落库（RabbitMQ 异步消费）存在时差：
// run 终态事件先到时 trip.status 可能还是 PLANNING，且此后不再有事件触发
// 刷新。planning 阶段轮询重取 trip，确保状态流转后视图切到 completed。
let planningPollTimer: number | null = null

function stopPlanningPoll(): void {
  if (planningPollTimer !== null) {
    clearInterval(planningPollTimer)
    planningPollTimer = null
  }
}

watch(
  () => tripStore.currentPhase,
  (phase) => {
    stopPlanningPoll()
    if (phase === 'planning') {
      planningPollTimer = window.setInterval(() => {
        void tripStore.refreshCurrentTrip()
      }, 4000)
    }
  },
  { immediate: true },
)

onBeforeUnmount(stopPlanningPoll)

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
  showKnowledge.value = false
  if (tripStore.currentTripId !== id) selectTrip(id)
  router.push(`/workspace/trips/${id}`)
  closeDrawersOnNavigate()
}

/** [+ 新建旅行]：切换到创建模式（中央 Composer），不再打开 Drawer。 */
function handleNewTrip() {
  showKnowledge.value = false
  if (tripStore.currentTripId !== null) {
    tripStore.clearCurrentTrip()
    if (route.params.tripId) router.push('/workspace')
  }
}

/** [删除旅行]：批量/单条走 tripStore，返回 Promise 供侧栏确认按钮等待。 */
async function deleteTrips(ids: string[]): Promise<number> {
  const result = await tripStore.removeTrips(ids)
  // 删除了当前旅行 → 已回到创建模式；同步 URL，避免刷新后按残留 tripId 重选到 404。
  if (tripStore.currentTripId === null && route.params.tripId) {
    router.push('/workspace')
  }
  return result
}

function handleUpdateDestination(name: string, region: { provinceCode: string; cityCode: string } | null) {
  requiredContext.value.destination = name
  requiredContext.value.region = region
}

function handleUpdateDates(start: string, end: string) {
  requiredContext.value.startDate = start
  requiredContext.value.endDate = end
}

async function handleCreationSend(text: string) {
  if (!requiredOk.value || creation.sending.value) return
  startError.value = null
  await creation.send(text, {
    destination: requiredContext.value.destination as string,
    startDate: requiredContext.value.startDate,
    endDate: requiredContext.value.endDate,
    travelers: travelers.value,
    budgetAmount: budget.value,
  })
}

function handleUpdateTravelers(value: number | null) {
  travelers.value = value
}
function handleUpdateBudget(value: number | null) {
  budget.value = value
}

/** [重新开始]：新会话；chips 解锁但保留已填内容。 */
function handleResetCreation() {
  creation.reset()
  startError.value = null
}

/** 处理创建对话中的选项点击，拦截「开始规划」直接触发创建流程 */
function handleCreationOption(option: { action: string; label: string; value?: unknown }) {
  if (option.value === 'START_PLANNING') {
    handleStartPlanning()
    return
  }
  creation.choose(option as any)
}

/**
 * [开始规划]：从已确认槽位建旅行，然后直接启动规划，不显示 draft 页面。
 */
async function handleStartPlanning() {
  if (!creationReady.value || creatingTrip.value || !creation.sessionId.value) return
  creatingTrip.value = true
  startError.value = null
  try {
    const sessionId = creation.sessionId.value
    const created = await session.withAccessToken((token) => createTripFromAgent(token, sessionId))
    creation.reset()
    tripStore.adoptTrip(created)
    // 立即启动规划，让视图直接进入 planning 状态
    await agent.send('开始规划这次旅行')
  } catch (cause) {
    startError.value = presentableError(cause)
  } finally {
    creatingTrip.value = false
  }
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

  <!-- 设置中心（F-UI-11 方案 A）：整页替换工作区壳（含侧栏与 Header） -->
  <SettingsPage v-else-if="isSettingsRoute" />

  <!-- 已登录：Workspace 四区壳 -->
  <div v-else class="flex h-screen min-h-0 flex-col overflow-hidden bg-tp-bg" data-testid="workspace-shell">
    <WorkspaceHeader
      :task-title="taskTitle"
      :sidebar-visible="sidebarOpen"
      :context-visible="contextOpen"
      :phase="tripStore.currentPhase"
      @toggle-sidebar="toggleSidebar"
      @toggle-context="toggleContext"
    />

    <div ref="panesEl" class="relative flex min-h-0 flex-1 items-stretch">
      <!-- 抽屉遮罩 -->
      <div
        v-if="drawerMode && (sidebarOpen || contextOpen)"
        class="absolute inset-0 z-20 bg-tp-ink/20"
        data-testid="workspace-drawer-backdrop"
        @click="closeDrawersOnNavigate"
      />

      <!-- 左：Sidebar（≥768px 并排常驻；宽度=比例 clamp，等比缩放可拖拽） -->
      <div
        v-if="sidebarOpen"
        class="absolute inset-y-0 left-0 z-30 border-r border-tp-line md:static md:z-auto md:border-r-0"
        :style="sidebarStyle"
      >
        <WorkspaceSidebar
          :trips="trips"
          :active-trip-id="tripStore.currentTripId"
          :active-phase="tripStore.currentPhase"
          :loading="tripStore.listStatus === 'loading'"
          :error="tripStore.listError"
          @select-trip="handleSelectTrip"
          @new-trip="handleNewTrip"
          @retry="loadTrips"
          @delete-trips="deleteTrips"
          :knowledge-active="showKnowledge"
          @open-knowledge="showKnowledge = true"
          @exit-knowledge="showKnowledge = false"
        />
      </div>

      <!-- 左分隔把手：拖拽调整 Sidebar 宽度（并排模式才有） -->
      <div
        v-if="sidebarOpen && !drawerMode"
        class="hidden w-1.5 shrink-0 cursor-col-resize bg-transparent transition-colors hover:bg-tp-hover md:block"
        data-testid="workspace-sidebar-resizer"
        role="separator"
        aria-orientation="vertical"
        aria-label="拖拽调整导航栏宽度"
        @pointerdown="startResize($event, 'sidebar')"
      />

      <!-- 中：工作区 -->
      <main class="min-w-0 flex-1 overflow-y-auto bg-tp-bg" data-testid="workspace-main">
        <!-- ── 知识库管理视图（侧栏「知识库」打开）────────────────── -->
        <KnowledgeBasePage v-if="showKnowledge" />

        <!-- ── 创建模式：中央悬浮 Composer + 创建对话 ─────────────── -->
        <div v-else-if="creationMode" class="flex min-h-full flex-col" data-testid="workspace-creation">
          <div class="min-h-0 flex-1">
            <!-- 空会话：视觉核心 = 引导 + Composer 大量留白 -->
            <div v-if="!creationStarted" class="mx-auto w-full max-w-2xl px-6 pb-2 pt-[16vh] text-center">
              <p class="m-0 mb-2 flex items-center justify-center gap-2 text-[11px] uppercase tracking-[0.12em] text-tp-faint">
                <span class="inline-block h-px w-5 bg-tp-line" aria-hidden="true" />
                TripPilot
                <span class="inline-block h-px w-5 bg-tp-line" aria-hidden="true" />
              </p>
              <h1 class="m-0 text-xl font-semibold tracking-tight text-tp-ink">开始规划一次旅行</h1>
              <p class="m-0 mt-2 text-xs leading-4 text-tp-mute">先告诉我目的地和日期，其余想法直接说出来就好。</p>
            </div>
            <!-- 创建对话流 -->
            <div v-else class="mx-auto w-full max-w-2xl px-6 pb-3 pt-5">
              <CreationTranscript
                :messages="creation.reply.value?.messages ?? []"
                :sending="creation.sending.value"
                @option="handleCreationOption"
              />
            </div>
          </div>
          <!-- 悬浮 Composer（sticky：内容增长时锚定底部） -->
          <div class="sticky bottom-0 bg-tp-bg">
            <div class="mx-auto w-full max-w-2xl px-6 pb-5 pt-2">
              <WorkspaceComposer
                variant="floating"
                :destination="requiredContext.destination"
                :start-date="requiredContext.startDate"
                :end-date="requiredContext.endDate"
                :chips-locked="chipsLocked"
                :ready="creationReady"
                :sending="creation.sending.value || creatingTrip"
                :travelers="travelers"
                :budget="budget"
                @send="handleCreationSend"
                @start-planning="handleStartPlanning"
                @reset-creation="handleResetCreation"
                @update-destination="handleUpdateDestination"
                @update-dates="handleUpdateDates"
                @update-travelers="handleUpdateTravelers"
                @update-budget="handleUpdateBudget"
              />
              <p
                v-if="creationHint"
                class="m-0 mt-2 text-[11px] leading-4 text-tp-mute"
                data-testid="composer-hint"
              >
                {{ creationHint }}
              </p>
            </div>
          </div>
        </div>

        <!-- ── 旅行模式视图 ─────────────── -->
        <template v-else>
          <!-- 规划中 / 刚创建（draft 也走规划视图，不显示单独的 draft 页面） -->
          <div v-if="(mainView === 'planning' || mainView === 'draft') && tripStore.currentTrip" class="mx-auto w-full max-w-3xl px-6 py-5">
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

          <!-- 已完成（仅当方案数据真实就绪的非空行程；否则见下方加载/重试态） -->
          <ItineraryWorkspace
            v-else-if="completedItineraryReady && tripStore.currentTrip"
            :trip="tripStore.currentTrip"
            :itinerary="tripStore.itinerary"
          />

          <!-- COMPLETED 但方案未就绪：不展示"已完成共0天"假成功，改为加载/重试 -->
          <div v-else-if="tripCompletedNoData && tripStore.currentTrip" class="mx-auto w-full max-w-2xl px-6 py-10">
            <TripLoadingState
              :loading="tripStore.itineraryStatus === 'loading'"
              :error="tripStore.itineraryError"
              @retry="reloadItinerary"
            />
          </div>

          <!-- 旅行加载中 / 出错（原兜底空态细分） -->
          <div v-else-if="tripStore.detailStatus === 'loading'" class="mx-auto w-full max-w-2xl px-6 py-10">
            <p class="m-0 flex items-center gap-2 text-xs leading-4 text-tp-sub" data-testid="workspace-trip-loading">
              <span class="inline-block h-1.5 w-1.5 rounded-full bg-tp-dot animate-pulse" aria-hidden="true" />
              正在加载旅行……
            </p>
          </div>
          <div v-else-if="tripStore.detailError" class="mx-auto w-full max-w-2xl px-6 py-10">
            <p class="m-0 text-xs leading-4 text-tp-mute" data-testid="workspace-trip-error">{{ tripStore.detailError }}</p>
            <button
              type="button"
              class="mt-2 flex h-7 items-center rounded-md border border-tp-line bg-white px-3 text-xs text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
              data-testid="workspace-trip-retry"
              @click="selectTrip(tripStore.currentTripId as string)"
            >
              重试
            </button>
          </div>
        </template>
      </main>

      <!-- 右分隔把手：拖拽调整 Context 面板宽度（并排模式才有） -->
      <div
        v-if="contextOpen && !drawerMode"
        class="hidden w-1.5 shrink-0 cursor-col-resize bg-transparent transition-colors hover:bg-tp-hover lg:block"
        data-testid="workspace-context-resizer"
        role="separator"
        aria-orientation="vertical"
        aria-label="拖拽调整上下文面板宽度"
        @pointerdown="startResize($event, 'context')"
      />

      <!-- 右：Context Inspector（≥1024px 并排常驻；宽度=比例 clamp，等比缩放可拖拽） -->
      <div
        v-if="contextOpen"
        class="absolute inset-y-0 right-0 z-30 border-l border-tp-line lg:static lg:z-auto lg:border-l-0"
        :style="contextStyle"
      >
        <WorkspaceContextPanel
          :trip="tripStore.currentTrip"
          :creation="creationMode ? {
            destination: requiredContext.destination,
            startDate: requiredContext.startDate,
            endDate: requiredContext.endDate,
            started: creationStarted,
            slots: creation.reply.value?.slots ?? null,
          } : null"
        />
      </div>
    </div>

    <!-- 底：旅行模式 docked Composer（创建模式由中央悬浮 Composer 接管） -->
    <footer v-if="!creationMode" class="shrink-0 border-t border-tp-line bg-tp-panel px-4 py-2 shadow-[0_-6px_16px_-10px_rgb(0_0_0/0.12)]">
      <div class="mx-auto w-full max-w-2xl">
        <WorkspaceComposer
          variant="docked"
          :disabled="agent.inputDisabled.value"
          :context-label="dockContextLabel"
          @send="agent.send"
        />
      </div>
    </footer>
  </div>
</template>
