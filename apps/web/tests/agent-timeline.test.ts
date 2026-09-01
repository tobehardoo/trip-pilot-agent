// Agent UX 2.0 Phase C：时间线投影的核心不变量。
// 1) 工具名绝不原样上屏（映射到业务语言或兜底）；
// 2) 阶段只由真实 step 事件推导——没有事件就没有阶段；
// 3) 事件折叠成回合，终态封口。

import { describe, expect, it } from 'vitest'

import type { AgentDialogEventView } from '../src/lib/api'
import {
  createTurnReducer,
  deriveStage,
  toolPresentation,
} from '../src/lib/agent-timeline'

function stepEvent(
  eventId: number,
  tool: string,
  overrides: Partial<{ seq: number; ok: boolean; summary: string; errorCode: string }> = {},
): AgentDialogEventView {
  return {
    eventId,
    tripId: 'trip-1',
    runId: 'run-1',
    eventType: 'AGENT_STEP',
    payload: {
      seq: overrides.seq ?? 0,
      tool,
      ok: overrides.ok ?? true,
      summary: overrides.summary ?? '已完成',
      errorCode: overrides.errorCode ?? null,
    },
  } as AgentDialogEventView
}

function askEvent(eventId: number, expectedType = 'CHOICE'): AgentDialogEventView {
  return {
    eventId,
    tripId: 'trip-1',
    runId: 'run-1',
    eventType: 'AGENT_ASK_USER',
    payload: { question: '你想去哪个城市？', options: ['成都', '北京'], expectedType },
  } as AgentDialogEventView
}

describe('toolPresentation', () => {
  it('maps known tools to business language and phases', () => {
    expect(toolPresentation('update_constraints')).toEqual({
      title: '理解旅行需求',
      phase: 'UNDERSTANDING',
    })
    expect(toolPresentation('search_place').phase).toBe('RESEARCH')
    expect(toolPresentation('build_itinerary').title).toBe('生成行程方案')
    expect(toolPresentation('validate_itinerary').phase).toBe('VALIDATION')
  })

  it('never leaks an unknown tool name to the UI', () => {
    const presentation = toolPresentation('deploy_to_production')
    expect(presentation.title).not.toContain('deploy_to_production')
    expect(presentation.title).toBe('处理旅行事务')
  })
})

describe('createTurnReducer', () => {
  it('groups steps into the open turn and closes it on a question', () => {
    const reducer = createTurnReducer()
    reducer.pushUserMessage('十一想去成都玩')
    reducer.applyEvent(stepEvent(1, 'update_constraints'))
    reducer.applyEvent(stepEvent(2, 'search_place', { seq: 1 }))
    reducer.applyEvent(askEvent(3))

    expect(reducer.turns).toHaveLength(1)
    const [turn] = reducer.turns
    expect(turn.userText).toBe('十一想去成都玩')
    expect(turn.steps).toHaveLength(2)
    expect(turn.outcome?.kind).toBe('question')
  })

  it('starts a new turn after a terminal outcome', () => {
    const reducer = createTurnReducer()
    reducer.applyEvent(askEvent(1))
    reducer.applyEvent(stepEvent(2, 'update_constraints', { seq: 0 }))
    expect(reducer.turns).toHaveLength(2)
  })

  it('maps AGENT_RUN_FINISHED to failed or answered outcomes', () => {
    const reducer = createTurnReducer()
    reducer.applyEvent(stepEvent(1, 'build_itinerary'))
    reducer.applyEvent({
      eventId: 2,
      tripId: 'trip-1',
      runId: 'run-1',
      eventType: 'AGENT_RUN_FINISHED',
      payload: { status: 'STOPPED', reasonCode: 'CEILING_REACHED', message: '这次处理达到了单轮步骤上限。' },
    } as AgentDialogEventView)
    expect(reducer.turns[0].outcome?.kind).toBe('failed')

    const reducer2 = createTurnReducer()
    reducer2.applyEvent({
      eventId: 3,
      tripId: 'trip-1',
      runId: 'run-2',
      eventType: 'AGENT_RUN_FINISHED',
      payload: { status: 'ANSWERED', reasonCode: 'ANSWERED', message: '好的，我记下了。' },
    } as AgentDialogEventView)
    expect(reducer2.turns[0].outcome?.kind).toBe('answered')
  })
})

describe('deriveStage', () => {
  it('stays idle with no turns', () => {
    expect(deriveStage([])).toEqual({ stage: 'idle', awaitingAnswer: false })
  })

  it('reports starting only until the first step arrives', () => {
    const reducer = createTurnReducer()
    reducer.pushUserMessage('十一想去成都玩')
    expect(deriveStage(reducer.turns).stage).toBe('starting')
    reducer.applyEvent(stepEvent(1, 'update_constraints'))
    expect(deriveStage(reducer.turns).stage).toBe('collecting')
  })

  it('follows the real step phases without inventing later ones', () => {
    const reducer = createTurnReducer()
    reducer.applyEvent(stepEvent(1, 'update_constraints'))
    reducer.applyEvent(stepEvent(2, 'get_route', { seq: 1 }))
    expect(deriveStage(reducer.turns).stage).toBe('researching')
    reducer.applyEvent(stepEvent(3, 'build_itinerary', { seq: 2 }))
    expect(deriveStage(reducer.turns).stage).toBe('planning')
    // 没有 validate_itinerary 事件时绝不显示“验证方案”
    reducer.applyEvent(askEvent(4))
    expect(deriveStage(reducer.turns).stage).toBe('clarifying')
    expect(deriveStage(reducer.turns).awaitingAnswer).toBe(true)
  })

  it('closes with completed or failed from the terminal events', () => {
    const reducer = createTurnReducer()
    reducer.applyEvent({
      eventId: 1,
      tripId: 'trip-1',
      runId: 'run-1',
      eventType: 'AGENT_COMPLETED',
      payload: { summary: '行程已生成：测试', itinerary: { title: '测试', days: [] }, slots: {} },
    } as AgentDialogEventView)
    expect(deriveStage(reducer.turns).stage).toBe('completed')

    const reducer2 = createTurnReducer()
    reducer2.applyEvent({
      eventId: 2,
      tripId: 'trip-1',
      runId: 'run-2',
      eventType: 'AGENT_RUN_FINISHED',
      payload: { status: 'EXPIRED', reasonCode: 'RUN_EXPIRED', message: '已自动结束' },
    } as AgentDialogEventView)
    expect(deriveStage(reducer2.turns).stage).toBe('failed')
  })
})
