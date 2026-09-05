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
import { Maximize2, Minimize2 } from 'lucide-vue-next'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'

import AuthView, { type AuthSubmission } from '../components/AuthView.vue'
import { useWorkspaceSession } from './session'
import { useAuthStore } from '../app/stores/auth'
import { useAgentWorkspace } from '../components/agent-workspace/useAgentWorkspace'
import WorkspaceHeader from './layout/WorkspaceHeader.vue'
import WorkspaceSidebar from './layout/WorkspaceSidebar.vue'
import WorkspaceContextPanel from './layout/WorkspaceContextPanel.vue'
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
import { createTripFromAgent, createPlanningTask } from '../lib/api'
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
// Agent 通道的请求必须走 withAccessToken（401 → 单飞 refresh → 重试），
// 否则 access token 过期后 run 创建/应答/SSE 重连都会静默 401。
const agent = useAgentWorkspace({
  tripId: () => tripStore.currentTripId ?? '',
  getToken: () => auth.accessToken,
  withAccessToken: session.withAccessToken,
  rotateSession: session.rotateSession,
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

// ── 三栏独立窗口卡片（无抽屉）──────────────────────────────────
// 左栏 / 中栏 / 右栏始终并排（任何屏宽都不覆盖）。每栏顶部标题条带
// 「展开/收起」按钮：点开某栏 → 该栏放大（占 45%），其余两栏按默认权重
// 等比例缩减剩余空间；再点收起恢复默认比例。小屏时按百分比收窄但绝不覆盖。
type PanelKey = 'sidebar' | 'main' | 'context'
const DEFAULT_WEIGHTS: Record<PanelKey, number> = { sidebar: 0.18, main: 0.62, context: 0.2 }
const EXPANDED_WEIGHT = 0.45

const panelWeights = ref<Record<PanelKey, number>>({ ...DEFAULT_WEIGHTS })
const expandedPanel = ref<PanelKey | null>(null)

function togglePanel(key: PanelKey) {
  if (expandedPanel.value === key) {
    panelWeights.value = { ...DEFAULT_WEIGHTS }
    expandedPanel.value = null
    return
  }
  expandedPanel.value = key
  const others = (Object.keys(DEFAULT_WEIGHTS) as PanelKey[]).filter((k) => k !== key)
  const total = others.reduce((sum, k) => sum + DEFAULT_WEIGHTS[k], 0)
  const remaining = 1 - EXPANDED_WEIGHT
  const next = { ...DEFAULT_WEIGHTS }
  next[key] = EXPANDED_WEIGHT
  for (const k of others) next[k] = (DEFAULT_WEIGHTS[k] / total) * remaining
  panelWeights.value = next
}

const panelWidth = (key: PanelKey) => `${(panelWeights.value[key] * 100).toFixed(2)}%`

// ── 双模式 ──────────────────────────────────────────────────────
const creationMode = computed(() => tripStore.currentTripId === null)

/** 中栏窗口卡片标题。 */
const mainPanelTitle = computed(() => (creationMode.value ? '新建旅行' : '行程'))

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

// ── 规划失败态：明确中文错误 + 重新规划入口 ──────────────────────
// 后端首次规划失败会把 trip.status 置为 FAILED（确定性终态），
// 前端据此渲染失败视图，绝不继续显示"正在规划/路线正在生成"的假加载。
const retryingPlanning = ref(false)
const planningRetryError = ref<string | null>(null)

async function handleRetryPlanning(): Promise<void> {
  const tripId = tripStore.currentTripId
  if (!tripId || retryingPlanning.value) return
  retryingPlanning.value = true
  planningRetryError.value = null
  try {
    const key = globalThis.crypto?.randomUUID?.() ?? `replan-${Date.now()}`
    await session.withAccessToken((token) => createPlanningTask(token, tripId, key))
    await tripStore.refreshCurrentTrip()
  } catch (cause) {
    planningRetryError.value = presentableError(cause)
  } finally {
    retryingPlanning.value = false
  }
}

/** 左侧旅行切换：更新数据上下文 + 总是同步 URL */
function handleSelectTrip(id: string) {
  showKnowledge.value = false
  if (tripStore.currentTripId !== id) selectTrip(id)
  router.push(`/workspace/trips/${id}`)
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
      :sidebar-visible="expandedPanel === 'sidebar'"
      :context-visible="expandedPanel === 'context'"
      :phase="tripStore.currentPhase"
      @toggle-sidebar="togglePanel('sidebar')"
      @toggle-context="togglePanel('context')"
    />

    <!-- 三栏独立窗口卡片（始终并排，无抽屉/覆盖） -->
    <div class="flex min-h-0 flex-1 items-stretch">
      <!-- 左栏窗口卡片 -->
      <section
        class="flex h-full min-h-0 flex-col border-r border-tp-line bg-tp-panel"
        :style="{ width: panelWidth('sidebar') }"
        data-testid="panel-sidebar"
      >
        <div class="flex h-8 shrink-0 items-center justify-between border-b border-tp-div px-2">
          <span class="text-[11px] font-medium tracking-[0.08em] text-tp-mute">工作区</span>
          <button
            type="button"
            class="flex h-6 w-6 items-center justify-center rounded text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
            :title="expandedPanel === 'sidebar' ? '收起左栏' : '展开左栏'"
            :aria-label="expandedPanel === 'sidebar' ? '收起左栏' : '展开左栏'"
            data-testid="panel-toggle-sidebar"
            @click="togglePanel('sidebar')"
          >
            <component :is="expandedPanel === 'sidebar' ? Minimize2 : Maximize2" :size="13" aria-hidden="true" />
          </button>
        </div>
        <div class="min-h-0 flex-1 overflow-hidden">
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
      </section>

      <!-- 中栏窗口卡片（主工作区） -->
      <section
        class="flex h-full min-h-0 flex-col"
        :style="{ width: panelWidth('main') }"
        data-testid="panel-main"
      >
        <div class="flex h-8 shrink-0 items-center justify-between border-b border-tp-div bg-tp-panel px-2">
          <span class="text-[11px] font-medium tracking-[0.08em] text-tp-mute">{{ mainPanelTitle }}</span>
          <button
            type="button"
            class="flex h-6 w-6 items-center justify-center rounded text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
            :title="expandedPanel === 'main' ? '收起中栏' : '展开中栏'"
            :aria-label="expandedPanel === 'main' ? '收起中栏' : '展开中栏'"
            data-testid="panel-toggle-main"
            @click="togglePanel('main')"
          >
            <component :is="expandedPanel === 'main' ? Minimize2 : Maximize2" :size="13" aria-hidden="true" />
          </button>
        </div>
        <main class="min-h-0 flex-1 overflow-y-auto bg-tp-bg" data-testid="workspace-main">
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

          <!-- 规划失败：明确中文错误 + 重新规划入口（绝不渲染假"正在规划"） -->
          <div v-else-if="mainView === 'failed' && tripStore.currentTrip" class="mx-auto w-full max-w-3xl px-6 py-5">
            <TripOverview :trip="tripStore.currentTrip" />
            <div
              class="mt-4 rounded-md border border-tp-warn/30 bg-tp-warn/10 px-4 py-3"
              role="alert"
              data-testid="planning-failed"
            >
              <p class="m-0 text-xs leading-5 text-tp-warn">
                行程生成失败，请调整条件后重新规划。若多次失败，请检查服务状态后重试。
              </p>
              <p v-if="planningRetryError" class="m-0 mt-1 text-[11px] leading-4 text-tp-warn" role="alert">
                {{ planningRetryError }}
              </p>
              <button
                type="button"
                :disabled="retryingPlanning"
                class="mt-2 flex h-7 items-center rounded-md border border-tp-line bg-white px-3 text-xs text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink disabled:opacity-50"
                data-testid="planning-retry"
                @click="handleRetryPlanning"
              >
                {{ retryingPlanning ? '正在重新规划……' : '重新规划' }}
              </button>
            </div>
            <div class="mt-4 border-t border-tp-div" role="separator" />
            <!-- 真实 Agent 对话 -->
            <div class="mt-4">
              <AgentDialog :agent="agent" />
            </div>
          </div>

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
        <!-- 底：旅行模式 docked Composer（位于中栏内容流末尾，滚动到底部才显示；
             创建模式由中央悬浮 Composer 接管；知识库 / 行程展示不出现聊天框） -->
        <footer
          v-if="!creationMode && !showKnowledge"
          class="border-t border-tp-line bg-tp-panel px-4 py-2"
        >
          <div class="mx-auto w-full max-w-2xl">
            <WorkspaceComposer
              variant="docked"
              :disabled="agent.inputDisabled.value"
              :context-label="dockContextLabel"
              @send="agent.send"
            />
          </div>
        </footer>
        </main>
      </section>

      <!-- 右栏窗口卡片 -->
      <section
        class="flex h-full min-h-0 flex-col border-l border-tp-line bg-tp-panel"
        :style="{ width: panelWidth('context') }"
        data-testid="panel-context"
      >
        <div class="flex h-8 shrink-0 items-center justify-between border-b border-tp-div px-2">
          <span class="text-[11px] font-medium tracking-[0.08em] text-tp-mute">上下文</span>
          <button
            type="button"
            class="flex h-6 w-6 items-center justify-center rounded text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
            :title="expandedPanel === 'context' ? '收起右栏' : '展开右栏'"
            :aria-label="expandedPanel === 'context' ? '收起右栏' : '展开右栏'"
            data-testid="panel-toggle-context"
            @click="togglePanel('context')"
          >
            <component :is="expandedPanel === 'context' ? Minimize2 : Maximize2" :size="13" aria-hidden="true" />
          </button>
        </div>
        <div class="min-h-0 flex-1 overflow-hidden">
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
      </section>
    </div>
  </div>
</template>
