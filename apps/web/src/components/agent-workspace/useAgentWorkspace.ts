// Agent Workspace 状态机（Agent UX 2.0 §5）：每个 UI 状态都映射到唯一的
// 真实信号（SSE 事件 / HTTP 状态）。没有事件就没有阶段——不做假进度。

import { computed, onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

import {
  answerAgentRun,
  ApiError,
  startAgentRun,
  streamAgentDialogEvents,
  type AgentDialogEventView,
  type AgentSlotViewWire,
  type TripConstraints,
  type UpdateTripConstraintsInput,
} from '../../lib/api'
import {
  AGENT_START_TIMEOUT_COPY,
  AGENT_STREAM_LOST_COPY,
  agentErrorCopy,
  type AgentErrorCopy,
} from '../../lib/agent-error-presentation'
import {
  createTurnReducer,
  deriveStage,
  type AgentTurn,
  type WorkspaceStage,
} from '../../lib/agent-timeline'

const MAX_TEXT_LENGTH = 2000
const STREAM_FAILURE_LIMIT = 3
const STREAM_RETRY_DELAY_MS = 2000
/** STARTING 兜底：覆盖 outbox 轮询 + 有界 run 的最坏路径。 */
const FIRST_EVENT_TIMEOUT_MS = 90_000
/** 重开面板时等待 SSE 重放完成的最大宽限期（之后解锁输入）。 */
const HYDRATION_GRACE_MS = 800

export interface AgentWorkspaceOptions {
  tripId: () => string
  getToken: () => string
  tripVersion: () => number
  tripConstraints: () => TripConstraints | null
  applyConstraints: (input: UpdateTripConstraintsInput) => Promise<void>
}

export function useAgentWorkspace(options: AgentWorkspaceOptions) {
  const reducer = createTurnReducer()
  const turns: Ref<AgentTurn[]> = ref([])
  const runId = ref<string | null>(null)
  const draft = ref('')
  const sending = ref(false)
  const connection = ref<'connecting' | 'live' | 'lost'>('connecting')
  const hydrated = ref(false)
  const awaitingEvent = ref(false)
  const commandError = ref<AgentErrorCopy | null>(null)
  const applied = ref(false)
  const applying = ref(false)
  const lastSentText = ref<string | null>(null)
  const answeredTurnIds = ref(new Set<number>())

  const derived = computed(() => deriveStage(turns.value))
  const stage = computed<WorkspaceStage>(() => derived.value.stage)
  const awaitingAnswer = computed(() => derived.value.awaitingAnswer)
  const pendingQuestion = computed(() => {
    if (!awaitingAnswer.value) return null
    const outcome = turns.value[turns.value.length - 1]?.outcome
    return outcome && outcome.kind === 'question' ? outcome : null
  })
  const completedOutcome = computed(() => {
    const outcome = turns.value[turns.value.length - 1]?.outcome
    return outcome && outcome.kind === 'completed' ? outcome : null
  })
  const failedOutcome = computed(() => {
    const outcome = turns.value[turns.value.length - 1]?.outcome
    return outcome && outcome.kind === 'failed' ? outcome : null
  })
  // 事件在途时锁定输入：既防止 run 未建时误开新 run，也防止 resume 在途时
  // 重复应答（后者会触发 RUN_IN_PROGRESS 拒绝）。
  const inputDisabled = computed(() => sending.value || !hydrated.value || awaitingEvent.value)

  // ── SSE 事件流（重放 + 断线重连） ──────────────────────────────────

  let stopped = false
  let abort: AbortController | null = null
  let lastMessageId = 0
  let failures = 0
  let firstEventTimer: ReturnType<typeof setTimeout> | null = null

  function syncTurns(): void {
    turns.value = [...reducer.turns]
  }

  function onEvent(event: AgentDialogEventView, messageId: number): void {
    lastMessageId = Math.max(lastMessageId, messageId)
    runId.value = event.runId
    awaitingEvent.value = false
    commandError.value = null
    disarmFirstEventTimer()
    hydrated.value = true
    reducer.applyEvent(event)
    syncTurns()
  }

  function disarmFirstEventTimer(): void {
    if (firstEventTimer !== null) {
      clearTimeout(firstEventTimer)
      firstEventTimer = null
    }
  }

  function armFirstEventTimer(): void {
    disarmFirstEventTimer()
    firstEventTimer = setTimeout(() => {
      if (!awaitingEvent.value || stopped) return
      awaitingEvent.value = false
      commandError.value = AGENT_START_TIMEOUT_COPY
      const open = reducer.turns[reducer.turns.length - 1]
      if (open && open.outcome === null) {
        open.outcome = {
          kind: 'failed',
          status: 'STOPPED',
          reasonCode: 'FRONTEND_TIMEOUT',
          message: AGENT_START_TIMEOUT_COPY.detail,
        }
        syncTurns()
      }
    }, FIRST_EVENT_TIMEOUT_MS)
  }

  async function streamLoop(): Promise<void> {
    while (!stopped) {
      try {
        await streamAgentDialogEvents(
          options.getToken(),
          options.tripId(),
          onEvent,
          { lastMessageId, signal: abort?.signal },
        )
        failures = 0
      } catch (cause) {
        if (stopped || abort?.signal.aborted) return
        failures += 1
        if (failures >= STREAM_FAILURE_LIMIT) {
          connection.value = 'lost'
          commandError.value = commandError.value ?? AGENT_STREAM_LOST_COPY
          return
        }
        void cause
      }
      if (stopped) return
      connection.value = 'live'
      await new Promise((resolve) => setTimeout(resolve, STREAM_RETRY_DELAY_MS))
    }
  }

  function reconnect(): void {
    failures = 0
    connection.value = 'connecting'
    commandError.value = commandError.value === AGENT_STREAM_LOST_COPY ? null : commandError.value
    void streamLoop()
  }

  // ── 发送与回答 ─────────────────────────────────────────────────────

  function newIdempotencyKey(): string {
    const cryptoRef = globalThis.crypto as Crypto | undefined
    if (cryptoRef && typeof cryptoRef.randomUUID === 'function') {
      return cryptoRef.randomUUID()
    }
    // jsdom 及旧环境没有 WebCrypto——幂等键只需进程内唯一。
    return `key-${Date.now()}-${Math.round(Math.random() * 1e9)}`
  }

  function isTurnAnswered(turnId: number): boolean {
    return answeredTurnIds.value.has(turnId)
  }

  async function send(text: string): Promise<void> {
    const trimmed = text.trim()
    if (!trimmed || sending.value || trimmed.length > MAX_TEXT_LENGTH) return
    sending.value = true
    commandError.value = null
    lastSentText.value = trimmed
    // 在新增回合改变派生状态之前捕获：pushUserMessage 会让 awaitingAnswer
    // 重新计算为 false，路由必须基于回答时刻的真实状态。
    const wasAwaitingAnswer = awaitingAnswer.value
    if (wasAwaitingAnswer) {
      const open = reducer.turns[reducer.turns.length - 1]
      if (open) answeredTurnIds.value.add(open.id)
    }
    reducer.pushUserMessage(trimmed)
    syncTurns()
    try {
      const key = newIdempotencyKey()
      if (runId.value && wasAwaitingAnswer) {
        awaitingEvent.value = true
        await answerAgentRun(options.getToken(), options.tripId(), runId.value, trimmed, key)
      } else {
        // 上一个 run 已终态（完成/失败/答复）——下一条消息开启新 run。
        runId.value = null
        awaitingEvent.value = true
        await startAgentRun(options.getToken(), options.tripId(), trimmed, key)
      }
      armFirstEventTimer()
    } catch (cause) {
      awaitingEvent.value = false
      commandError.value = agentErrorCopy(cause)
    } finally {
      sending.value = false
    }
  }

  /** 澄清卡片的直接应答（单选/日期/数字），文本 chips 仍走输入框。 */
  async function answerQuestion(text: string): Promise<void> {
    await send(text)
  }

  function retryLast(): void {
    if (!lastSentText.value || sending.value) return
    const open = reducer.turns[reducer.turns.length - 1]
    if (open && open.outcome === null) {
      open.outcome = { kind: 'failed', status: 'STOPPED', reasonCode: 'RETRY', message: '已放弃这次尝试。' }
      syncTurns()
    }
    void send(lastSentText.value)
  }

  function restart(): void {
    if (sending.value || applying.value) return
    reducer.turns.length = 0
    syncTurns()
    runId.value = null
    commandError.value = null
    applied.value = false
    awaitingEvent.value = false
    lastSentText.value = null
    answeredTurnIds.value = new Set<number>()
  }

  // ── 应用约束：完整基线 + 确认槽位 + 乐观锁 version（修复 F-1） ────

  function toArray(value: unknown): string[] {
    if (Array.isArray(value)) return value.map(String)
    const text = String(value ?? '').trim()
    return text ? [text] : []
  }

  function buildConstraintInput(
    slots: Record<string, AgentSlotViewWire>,
  ): UpdateTripConstraintsInput | null {
    const base = options.tripConstraints()
    if (!base) return null
    const input: UpdateTripConstraintsInput = {
      budgetAmount: base.budgetAmount,
      travelers: base.travelers,
      travelerType: base.travelerType,
      pace: base.pace,
      preferences: base.preferences,
      fixedSchedules: base.fixedSchedules,
      arrival: base.arrival,
      departure: base.departure,
      accommodation: base.accommodation,
      mustVisitPlaces: base.mustVisitPlaces,
      avoidPlaces: base.avoidPlaces,
      mustVisitPlaceRefs: base.mustVisitPlaceRefs,
      avoidPlaceRefs: base.avoidPlaceRefs,
      mealWindows: base.mealWindows,
      mobilityLevel: base.mobilityLevel,
      version: options.tripVersion(),
    }
    for (const [name, slot] of Object.entries(slots)) {
      if (slot.state !== 'CONFIRMED' && slot.state !== 'USER_OVERRIDE') continue
      if (name === 'budget') {
        const amount = Number(slot.value)
        if (Number.isFinite(amount)) input.budgetAmount = amount
      } else if (name === 'travelers') {
        const count = Number(slot.value)
        if (Number.isFinite(count) && count >= 1) input.travelers = count
      } else if (name === 'pace') {
        const pace = String(slot.value).toUpperCase()
        if (pace === 'RELAXED' || pace === 'BALANCED' || pace === 'INTENSIVE') input.pace = pace
      } else if (name === 'must_visit') {
        const places = toArray(slot.value)
        if (places.length) input.mustVisitPlaces = places
      } else if (name === 'avoid') {
        const places = toArray(slot.value)
        if (places.length) input.avoidPlaces = places
      } else if (name === 'mobility') {
        const level = String(slot.value).toUpperCase()
        if (level === 'STANDARD' || level === 'REDUCED' || level === 'STEP_FREE') {
          input.mobilityLevel = level
        }
      }
    }
    return input
  }

  async function applyCompleted(slots: Record<string, AgentSlotViewWire>): Promise<void> {
    if (applying.value || applied.value) return
    const input = buildConstraintInput(slots)
    if (input === null) {
      commandError.value = {
        title: '暂时无法应用约束',
        detail: '没有读取到当前行程的约束基线，请刷新页面后重试。',
      }
      return
    }
    applying.value = true
    commandError.value = null
    try {
      await options.applyConstraints(input)
      applied.value = true
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        commandError.value = {
          title: '数据已被更新',
          detail: '行程刚发生了变化，请刷新页面后再应用约束。',
        }
      } else {
        commandError.value = agentErrorCopy(cause)
      }
    } finally {
      applying.value = false
    }
  }

  onMounted(() => {
    abort = new AbortController()
    void streamLoop()
    setTimeout(() => {
      if (!stopped) hydrated.value = true
    }, HYDRATION_GRACE_MS)
  })

  onBeforeUnmount(() => {
    stopped = true
    disarmFirstEventTimer()
    abort?.abort()
  })

  return {
    turns,
    draft,
    sending,
    connection,
    hydrated,
    commandError,
    applied,
    applying,
    stage,
    awaitingAnswer,
    pendingQuestion,
    completedOutcome,
    failedOutcome,
    inputDisabled,
    send,
    answerQuestion,
    isTurnAnswered,
    retryLast,
    buildConstraintInput,
    restart,
    reconnect,
    applyCompleted,
  }
}
