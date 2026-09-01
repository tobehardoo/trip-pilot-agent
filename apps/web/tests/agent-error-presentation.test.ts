// Agent UX 2.0 P0-2：后端技术文案不得直达用户。

import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '../src/lib/api'
import {
  AGENT_START_TIMEOUT_COPY,
  AGENT_STREAM_LOST_COPY,
  agentErrorCopy,
} from '../src/lib/agent-error-presentation'

describe('agentErrorCopy', () => {
  it('maps the backend rejection literal by error code', () => {
    const copy = agentErrorCopy(new ApiError(502, 'AGENT_DIALOGUE_UNAVAILABLE', 'Agent dialog service rejected the request'))
    expect(copy.title).toBe('AI 助手服务暂时不可用')
    expect(copy.detail).not.toContain('rejected')
  })

  it('maps validation codes without leaking the raw message', () => {
    const copy = agentErrorCopy(new ApiError(400, 'INVALID_MESSAGE', 'message must be 1..2000 non-blank characters'))
    expect(copy.detail).toContain('2000')
    expect(copy.detail).not.toContain('non-blank')
  })

  it('maps by HTTP status when the code is unknown', () => {
    const copy = agentErrorCopy(new ApiError(404, 'SOMETHING_NEW', 'Trip was not found'))
    expect(copy.title).toBe('找不到这次旅行')
  })

  it('falls back to neutral copy for unmapped errors and logs the original', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const copy = agentErrorCopy(new Error('some internal stack detail'))
    expect(copy.title).toBe('这次操作没有完成')
    expect(copy.detail).not.toContain('some internal stack detail')
    expect(warn).toHaveBeenCalled()
    warn.mockRestore()
  })
})

describe('builtin copies', () => {
  it('keeps the starting timeout and stream loss copies user-safe', () => {
    expect(AGENT_START_TIMEOUT_COPY.title).toBe('暂时没有收到助手的响应')
    expect(AGENT_STREAM_LOST_COPY.title).toBe('与助手的连接已断开')
  })
})
