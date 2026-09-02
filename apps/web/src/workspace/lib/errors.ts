// Workspace 用户可读错误文案（F-UI-11 Phase 0）。
//
// 事实边界（迁移自 TripWorkspace.vue errorMessage，语义保持）：
// 后端技术文案（如 "Agent dialog service rejected the request"、裸 409）
// 不得直达用户，按 ApiError.code 映射为中文；非 ApiError 一律按
// "无法连接服务器" 呈现，不允许把内部异常暴露给用户。
import { ApiError } from '../../lib/api'

/** 会话在请求在途时发生变化（401 轮换 / 登出），调用方应静默放弃本次结果。 */
export class SessionChangedError extends Error {
  constructor(message = 'Session changed while request was in flight') {
    super(message)
  }
}

export function presentableError(cause: unknown): string {
  if (cause instanceof ApiError) {
    if (cause.code === 'GUIDE_SERVICE_UNAVAILABLE') return '攻略服务暂时不可用，请稍后重试'
    if (cause.code === 'GUIDE_SERVICE_INVALID_RESPONSE') return '天气或攻略同步失败，请稍后重试'
    if (cause.code === 'GUIDE_IMPORT_REJECTED') return '攻略导入被拒绝，请检查链接或内容后重试'
    if (cause.code === 'PLACE_SEARCH_UNAVAILABLE') return '地点搜索暂时不可用，请稍后重试'
    if (cause.code === 'AGENT_DIALOGUE_UNAVAILABLE') return 'AI 助手服务暂时不可用，请稍后重试'
    if (cause.code === 'AGENT_TRIP_NOT_READY') return cause.message
    if (cause.code === 'INVALID_MESSAGE' || cause.code === 'INVALID_ANSWER') {
      return '请输入 1 到 2000 个字符后重试'
    }
    if (cause.code === 'INVALID_CREDENTIALS') return '邮箱或密码不正确'
    if (cause.code === 'UNAUTHORIZED') return '登录状态已失效，请重新登录'
    if (cause.status === 409 && cause.code === 'TRIP_VERSION_CONFLICT') {
      return '旅行信息已被更新，请刷新后再修改。'
    }
    return cause.message
  }
  return '无法连接服务器，请稍后重试'
}
