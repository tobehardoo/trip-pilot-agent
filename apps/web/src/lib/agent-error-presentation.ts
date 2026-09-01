// Agent 错误的用户语言映射（Agent UX 2.0 §9）。
// 后端技术文案（如 "Agent dialog service rejected the request"）禁止上屏；
// 未映射的错误一律落兜底文案，原始信息只进控制台。

import { ApiError } from './api'

export interface AgentErrorCopy {
  title: string
  detail: string
}

const CODE_COPY: Record<string, AgentErrorCopy> = {
  AGENT_DIALOGUE_UNAVAILABLE: {
    title: 'AI 助手服务暂时不可用',
    detail: '我们没有完成这次请求。请稍后重试。',
  },
  INVALID_MESSAGE: {
    title: '消息无法发送',
    detail: '请输入 1 到 2000 个字符后重试。',
  },
  INVALID_ANSWER: {
    title: '回复无法发送',
    detail: '请输入 1 到 2000 个字符后重试。',
  },
  TRIP_NOT_FOUND: {
    title: '找不到这次旅行',
    detail: '行程可能已被删除，请刷新页面后重试。',
  },
  VALIDATION_FAILED: {
    title: '请求格式不正确',
    detail: '请调整内容后重试。',
  },
}

const STATUS_COPY: Record<number, AgentErrorCopy> = {
  401: { title: '登录状态已过期', detail: '请重新登录后再使用 AI 助手。' },
  404: { title: '找不到这次旅行', detail: '行程可能已被删除，请刷新页面后重试。' },
  409: {
    title: '数据已被更新',
    detail: '行程刚发生了变化，请刷新页面后重试。',
  },
  502: {
    title: 'AI 助手服务暂时不可用',
    detail: '我们没有完成这次请求。请稍后重试。',
  },
}

export const AGENT_START_TIMEOUT_COPY: AgentErrorCopy = {
  title: '暂时没有收到助手的响应',
  detail: '这次启动没有完成。你可以重新尝试，或稍后再来。',
}

export const AGENT_STREAM_LOST_COPY: AgentErrorCopy = {
  title: '与助手的连接已断开',
  detail: '重新连接后会自动补齐错过的进展。',
}

export function agentErrorCopy(cause: unknown): AgentErrorCopy {
  if (cause instanceof ApiError) {
    const byCode = CODE_COPY[cause.code]
    if (byCode) return byCode
    const byStatus = STATUS_COPY[cause.status]
    if (byStatus) return byStatus
  }
  if (typeof console !== 'undefined' && cause instanceof Error && cause.message) {
    console.warn('[agent-workspace] unmapped error:', cause.message)
  }
  return {
    title: '这次操作没有完成',
    detail: '出了点问题，请稍后重试。若持续失败，请关闭助手后重新打开。',
  }
}
