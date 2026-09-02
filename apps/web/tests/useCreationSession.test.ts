import { describe, expect, test, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useAuthStore } from '../src/app/stores/auth'
import { useCreationSession } from '../src/workspace/composer/useCreationSession'
import * as api from '../src/lib/api'

vi.mock('../src/lib/api', () => {
  class ApiError extends Error {
    status: number
    code: string
    constructor(status: number, code: string, message: string) {
      super(message)
      this.status = status
      this.code = code
    }
  }
  return {
    ApiError,
    sendAgentCreateDialogue: vi.fn(),
  }
})

const dialogReply = {
  phase: 'COLLECTING' as const,
  ready: false,
  messages: [{ role: 'agent' as const, text: '想去哪个城市？', kind: 'CLARIFY' as const, options: [] }],
  slots: {},
}

describe('useCreationSession（Composer 前置对话）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const auth = useAuthStore()
    auth.applySession({
      accessToken: 'test-token',
      tokenType: 'Bearer',
      expiresIn: 3600,
      user: { id: 'test', displayName: 'Test', email: 'test@example.com' },
    })
    vi.clearAllMocks()
    vi.mocked(api.sendAgentCreateDialogue).mockResolvedValue(dialogReply)
  })

  test('首条消息生成 sessionId 并携带 tripContext 种子', async () => {
    const creation = useCreationSession()
    expect(creation.sessionId.value).toBeNull()

    await creation.send('我想轻松一点', { destination: '广州', startDate: '2026-09-10', endDate: '2026-09-13' })

    expect(api.sendAgentCreateDialogue).toHaveBeenCalledTimes(1)
    const [token, sessionId, input] = vi.mocked(api.sendAgentCreateDialogue).mock.calls[0]
    expect(token).toBe('test-token')
    expect(sessionId).toBeTruthy()
    expect(input.tripContext).toEqual({ destination: '广州', startDate: '2026-09-10', endDate: '2026-09-13' })
    expect(input.message).toBe('我想轻松一点')
    expect(creation.reply.value).toEqual(dialogReply)
    expect(creation.error.value).toBeNull()
  })

  test('后续轮次复用同一 sessionId 且不再携带 tripContext', async () => {
    const creation = useCreationSession()
    await creation.send('第一条', { destination: '广州' })
    await creation.choose({ action: 'CONFIRM', label: '可以' })
    await creation.send('第二条', { destination: '广州' })

    expect(api.sendAgentCreateDialogue).toHaveBeenCalledTimes(3)
    const calls = vi.mocked(api.sendAgentCreateDialogue).mock.calls
    expect(calls[1][2].option).toEqual({ action: 'CONFIRM', label: '可以' })
    expect(calls[1][2].tripContext).toBeUndefined()
    expect(calls[1][1]).toBe(calls[0][1])
    expect(calls[2][2].tripContext).toBeUndefined()
  })

  test('reset 生成新会话：sessionId 与投影清空', async () => {
    const creation = useCreationSession()
    await creation.send('第一条', { destination: '广州' })
    const firstSessionId = creation.sessionId.value
    creation.reset()
    expect(creation.sessionId.value).toBeNull()
    expect(creation.reply.value).toBeNull()

    await creation.send('重新开始', { destination: '上海' })
    expect(creation.sessionId.value).toBeTruthy()
    expect(creation.sessionId.value).not.toBe(firstSessionId)
  })

  test('API 失败 → error 用户文案，sending 复位，reply 不被覆盖', async () => {
    const creation = useCreationSession()
    await creation.send('第一条', { destination: '广州' })

    vi.mocked(api.sendAgentCreateDialogue).mockRejectedValueOnce(
      new api.ApiError(502, 'AGENT_DIALOGUE_UNAVAILABLE', 'Agent dialog service rejected the request'),
    )
    await creation.choose({ action: 'SKIP', label: '跳过' })

    expect(creation.error.value).toBe('AI 助手服务暂时不可用，请稍后重试')
    expect(creation.sending.value).toBe(false)
    expect(creation.reply.value).toEqual(dialogReply)
  })
})
