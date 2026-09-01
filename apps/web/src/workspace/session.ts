// Workspace 会话层（F-UI-11 Phase 0）。
//
// 职责：登录态判定、登录/注册/恢复/登出，以及所有业务请求的统一令牌包装。
// withAccessToken 语义逐行迁移自 TripWorkspace.vue（B14 已验证）：
//   请求 401
//     ↓ 单飞 rotateSession（/api/auth/refresh，HttpOnly Cookie）
//     ↓ 自动重试原请求一次
//     ↓ 仍 401 → 清空本地会话（回登录页）
// SessionChangedError 代际保护：登出/换会话后在途请求的结果一律作废。
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { useAuthStore } from '../app/stores/auth'
import {
  ApiError,
  login as loginSession,
  logoutSession,
  refreshSession,
  register as registerSession,
  type AuthSession,
} from '../lib/api'
import { presentableError, SessionChangedError } from './lib/errors'

export type { AuthSubmission } from '../components/AuthView.vue'

export const useWorkspaceSession = defineStore('workspace-session', () => {
  const auth = useAuthStore()
  const busy = ref(false)
  const error = ref<string | null>(null)

  let sessionGeneration = 0
  let refreshInFlight: Promise<void> | null = null

  function isCurrentSession(generation: number): boolean {
    return generation === sessionGeneration && auth.phase === 'authenticated'
  }

  function assertCurrentSession(generation: number): void {
    if (!isCurrentSession(generation)) {
      throw new SessionChangedError('Session changed while request was in flight')
    }
  }

  function applySession(session: AuthSession): void {
    auth.applySession(session)
  }

  /** 清空本地会话；generation 自增使所有在途请求作废。 */
  function clearLocalSession(): void {
    sessionGeneration += 1
    refreshInFlight = null
    error.value = null
    auth.clearSession()
  }

  /** 令牌轮换（单飞）：并发 401 只发一次 refresh。 */
  function rotateSession(): Promise<void> {
    if (refreshInFlight) return refreshInFlight
    const generation = sessionGeneration
    const refreshOperation = (async () => {
      const session = await refreshSession()
      if (generation !== sessionGeneration || auth.phase !== 'authenticated') {
        try {
          await logoutSession()
        } catch {
          // A stale rotated token must never restore a locally ended session.
        }
        throw new ApiError(401, 'SESSION_CHANGED', '登录状态已变更')
      }
      applySession(session)
    })()
    refreshInFlight = refreshOperation
    return refreshOperation.finally(() => {
      if (refreshInFlight === refreshOperation) refreshInFlight = null
    })
  }

  /**
   * 业务请求统一入口：401 → 轮换 → 重试一次；重试仍 401 → 清会话并向调用方抛出。
   * 任何时刻会话已变更，则抛 SessionChangedError（调用方静默放弃）。
   */
  async function withAccessToken<T>(operation: (token: string) => Promise<T>): Promise<T> {
    const operationGeneration = sessionGeneration
    const execute = async () => {
      const result = await operation(auth.accessToken)
      assertCurrentSession(operationGeneration)
      return result
    }
    try {
      return await execute()
    } catch (cause) {
      if (!isCurrentSession(operationGeneration)) {
        throw new SessionChangedError('Session changed while request was in flight')
      }
      if (!(cause instanceof ApiError) || cause.status !== 401) throw cause
    }
    try {
      await rotateSession()
    } catch (refreshCause) {
      if (!isCurrentSession(operationGeneration)) {
        throw new SessionChangedError('Session changed while request was in flight')
      }
      if (refreshCause instanceof ApiError && refreshCause.status === 401) clearLocalSession()
      throw refreshCause
    }
    try {
      return await execute()
    } catch (retryCause) {
      if (!isCurrentSession(operationGeneration)) {
        throw new SessionChangedError('Session changed while request was in flight')
      }
      if (retryCause instanceof ApiError && retryCause.status === 401) {
        clearLocalSession()
      }
      throw retryCause
    }
  }

  /**
   * 登录/注册：成功后应用会话（认证后的数据装载由页面 watch phase 触发）。
   * 失败写入 error.value（用户文案），不向调用方抛出。
   */
  async function authenticate(submission: {
    mode: 'login' | 'register'
    email: string
    password: string
    displayName: string
  }): Promise<void> {
    const authenticationGeneration = sessionGeneration
    busy.value = true
    error.value = null
    try {
      const session = submission.mode === 'login'
        ? await loginSession(submission.email, submission.password)
        : await registerSession(submission.email, submission.password, submission.displayName)
      if (authenticationGeneration !== sessionGeneration) {
        throw new SessionChangedError('Session changed while authentication was in flight')
      }
      applySession(session)
    } catch (cause) {
      if (!(cause instanceof SessionChangedError) && authenticationGeneration === sessionGeneration) {
        error.value = presentableError(cause)
      }
    } finally {
      busy.value = false
    }
  }

  /** 冷启动会话恢复：/api/auth/refresh（HttpOnly Cookie）；失败回 guest。 */
  async function restoreSession(): Promise<boolean> {
    const restoreGeneration = sessionGeneration
    try {
      const session = await refreshSession()
      if (restoreGeneration !== sessionGeneration) {
        throw new SessionChangedError('Session changed while restoration was in flight')
      }
      applySession(session)
      return true
    } catch (cause) {
      if (!(cause instanceof SessionChangedError) && restoreGeneration === sessionGeneration) {
        clearLocalSession()
      }
      return false
    }
  }

  async function logout(): Promise<void> {
    error.value = null
    try {
      await logoutSession()
    } catch {
      // Local logout must still complete when the server is unavailable.
    }
    clearLocalSession()
  }

  return {
    // 登录态（透传 auth store；模板与页面统一从这里读取）
    phase: computed(() => auth.phase),
    user: computed(() => auth.user),
    busy,
    error,
    isCurrentSession,
    clearLocalSession,
    rotateSession,
    withAccessToken,
    authenticate,
    restoreSession,
    logout,
  }
})
