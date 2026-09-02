// 创建会话（Composer 前置对话）——Composer 交互重构（2026-09-02 design §3.1）。
//
// 职责边界：前端只持有 sessionId 与每轮全量响应（transcript + slots + ready）。
// 槽位状态机（收集顺序、ready 判定）完全在 agent-service；前端绝不复制一份。
//
// 首轮携带 tripContext：Composer Required Context（目的地 + 日期）以
// source=TRIP 种子化进对话（服务端锁定，Agent 不重复询问）。
// [重新开始] = 生成新 sessionId + 清空投影（服务端旧会话自然废弃）。
import { ref } from 'vue'

import {
  sendAgentCreateDialogue,
  type AgentDialogInput,
  type AgentDialogOption,
  type AgentDialogReply,
  type AgentDialogTripContext,
} from '../../lib/api'
import { presentableError, SessionChangedError } from '../lib/errors'
import { useWorkspaceSession } from '../session'

export type CreationDialogOption = AgentDialogOption

export function useCreationSession() {
  const session = useWorkspaceSession()
  const sessionId = ref<string | null>(null)
  const reply = ref<AgentDialogReply | null>(null)
  const sending = ref(false)
  const error = ref<string | null>(null)

  function newSessionId(): string {
    const cryptoRef = globalThis.crypto as Crypto | undefined
    if (cryptoRef && typeof cryptoRef.randomUUID === 'function') return cryptoRef.randomUUID()
    // jsdom 及旧环境没有 WebCrypto——会话键只需进程内唯一。
    return `create-${Date.now()}-${Math.round(Math.random() * 1e9)}`
  }

  async function call(input: AgentDialogInput): Promise<void> {
    if (!sessionId.value) sessionId.value = newSessionId()
    sending.value = true
    error.value = null
    try {
      reply.value = await session.withAccessToken((token) =>
        sendAgentCreateDialogue(token, sessionId.value as string, input))
    } catch (cause) {
      if (cause instanceof SessionChangedError) return
      error.value = presentableError(cause)
    } finally {
      sending.value = false
    }
  }

  /** 首条消息携带 Required Context 种子；后续轮次服务端已持有事实，不再传。 */
  function send(text: string, context: AgentDialogTripContext): Promise<void> {
    const first = reply.value === null
    return call(first ? { message: text, tripContext: context } : { message: text })
  }

  /** 对话卡片点选（SET/CONFIRM/EDIT/SKIP/ASK），回复是确定性的。 */
  function choose(option: CreationDialogOption): Promise<void> {
    return call({ option })
  }

  function reset(): void {
    sessionId.value = null
    reply.value = null
    error.value = null
  }

  return { sessionId, reply, sending, error, send, choose, reset }
}
