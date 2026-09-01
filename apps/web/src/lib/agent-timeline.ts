// Agent Execution Timeline 的前端投影（Agent UX 2.0 §7）。
// 全部状态由真实 SSE 事件推导：没有对应的 AGENT_STEP 事件就绝不显示对应阶段。

import type { AgentDialogEventView, AgentSlotViewWire } from './api'

export type AgentPhase = 'UNDERSTANDING' | 'RESEARCH' | 'PLANNING' | 'VALIDATION'

export interface AgentExecutionStep {
  eventId: number
  seq: number
  tool: string
  ok: boolean
  summary: string
  errorCode: string | null
  phase: AgentPhase
  title: string
}

export type TurnOutcome =
  | { kind: 'question'; question: string; options: string[]; expectedType: string | null }
  | { kind: 'completed'; summary: string; itinerary: Record<string, unknown>; slots: Record<string, AgentSlotViewWire> }
  | { kind: 'answered'; message: string }
  | { kind: 'failed'; status: string; reasonCode: string; message: string }

export interface AgentTurn {
  id: number
  userText: string | null
  steps: AgentExecutionStep[]
  outcome: TurnOutcome | null
}

export type WorkspaceStage =
  | 'idle'
  | 'starting'
  | 'collecting'
  | 'clarifying'
  | 'researching'
  | 'planning'
  | 'validating'
  | 'completed'
  | 'failed'

// 工具名 → 用户语言（Agent UX 2.0 §7.2）。内部枚举与函数名禁止上屏。
const TOOL_PRESENTATION: Record<string, { title: string; phase: AgentPhase }> = {
  update_constraints: { title: '理解旅行需求', phase: 'UNDERSTANDING' },
  update_preferences: { title: '更新旅行偏好', phase: 'UNDERSTANDING' },
  retrieve_guide_knowledge: { title: '查阅目的地攻略', phase: 'RESEARCH' },
  search_place: { title: '查询地点信息', phase: 'RESEARCH' },
  check_opening_hours: { title: '确认开放时间', phase: 'RESEARCH' },
  get_route: { title: '计算交通路线', phase: 'RESEARCH' },
  build_itinerary: { title: '生成行程方案', phase: 'PLANNING' },
  validate_itinerary: { title: '验证行程方案', phase: 'VALIDATION' },
}

const FALLBACK_TOOL_PRESENTATION = { title: '处理旅行事务', phase: 'UNDERSTANDING' as AgentPhase }

export function toolPresentation(tool: string): { title: string; phase: AgentPhase } {
  return TOOL_PRESENTATION[tool] ?? FALLBACK_TOOL_PRESENTATION
}

export const STAGE_PIPELINE = [
  { key: 'understanding', label: '理解需求' },
  { key: 'researching', label: '查询信息' },
  { key: 'planning', label: '生成方案' },
  { key: 'validating', label: '验证方案' },
  { key: 'completed', label: '完成' },
] as const

export function stageLabel(stage: WorkspaceStage): string {
  const labels: Record<WorkspaceStage, string> = {
    idle: '待开始',
    starting: '正在启动…',
    collecting: '理解你的旅行需求',
    clarifying: '等待你的回答',
    researching: '正在查询旅行信息',
    planning: '正在生成旅行方案',
    validating: '正在验证旅行方案',
    completed: '行程方案已生成',
    failed: '本次任务未能完成',
  }
  return labels[stage]
}

/** 阶段条上哪个 pipeline 节点处于激活态（failed/idle/clarifying 特殊处理）。 */
export function activePipelineKey(stage: WorkspaceStage): string | null {
  switch (stage) {
    case 'collecting':
    case 'clarifying':
      return 'understanding'
    case 'researching':
      return 'researching'
    case 'planning':
      return 'planning'
    case 'validating':
      return 'validating'
    case 'completed':
      return 'completed'
    default:
      return null
  }
}

/** 将事件流折叠成回合：一个回合 = 用户一次输入 → 下一个终态（追问/完成/失败/答复）。 */
export function createTurnReducer() {
  let turnId = 0
  const turns: AgentTurn[] = []

  function openTurn(): AgentTurn {
    const existing = turns[turns.length - 1]
    if (existing && existing.outcome === null) return existing
    const turn: AgentTurn = { id: ++turnId, userText: null, steps: [], outcome: null }
    turns.push(turn)
    return turn
  }

  return {
    turns,

    pushUserMessage(text: string): void {
      openTurn().userText = text
    },

    applyEvent(event: AgentDialogEventView): void {
      if (event.eventType === 'AGENT_STEP') {
        const presentation = toolPresentation(event.payload.tool)
        openTurn().steps.push({
          eventId: event.eventId,
          seq: event.payload.seq,
          tool: event.payload.tool,
          ok: event.payload.ok,
          summary: event.payload.summary,
          errorCode: event.payload.errorCode ?? null,
          phase: presentation.phase,
          title: presentation.title,
        })
        return
      }
      const turn = openTurn()
      if (event.eventType === 'AGENT_ASK_USER') {
        turn.outcome = {
          kind: 'question',
          question: event.payload.question,
          options: event.payload.options ?? [],
          expectedType: event.payload.expectedType ?? null,
        }
      } else if (event.eventType === 'AGENT_COMPLETED') {
        turn.outcome = {
          kind: 'completed',
          summary: event.payload.summary,
          itinerary: event.payload.itinerary,
          slots: event.payload.slots ?? {},
        }
      } else if (event.eventType === 'AGENT_RUN_FINISHED') {
        if (event.payload.status === 'ANSWERED') {
          turn.outcome = { kind: 'answered', message: event.payload.message }
        } else {
          turn.outcome = {
            kind: 'failed',
            status: event.payload.status,
            reasonCode: event.payload.reasonCode,
            message: event.payload.message,
          }
        }
      }
    },
  }
}

export interface DerivedStage {
  stage: WorkspaceStage
  /** 是否存在等待应答的回合（问题已提出且未给出终态）。 */
  awaitingAnswer: boolean
}

export function deriveStage(turns: readonly AgentTurn[]): DerivedStage {
  const last = turns[turns.length - 1]
  if (!last) return { stage: 'idle', awaitingAnswer: false }
  if (last.outcome) {
    if (last.outcome.kind === 'question') return { stage: 'clarifying', awaitingAnswer: true }
    if (last.outcome.kind === 'completed') return { stage: 'completed', awaitingAnswer: false }
    if (last.outcome.kind === 'failed') return { stage: 'failed', awaitingAnswer: false }
    return { stage: 'idle', awaitingAnswer: false }
  }
  const lastStep = last.steps[last.steps.length - 1]
  if (!lastStep) return { stage: 'starting', awaitingAnswer: false }
  switch (lastStep.phase) {
    case 'RESEARCH':
      return { stage: 'researching', awaitingAnswer: false }
    case 'PLANNING':
      return { stage: 'planning', awaitingAnswer: false }
    case 'VALIDATION':
      return { stage: 'validating', awaitingAnswer: false }
    default:
      return { stage: 'collecting', awaitingAnswer: false }
  }
}
