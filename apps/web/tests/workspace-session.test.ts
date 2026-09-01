import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

const session = {
  user: {
    id: '11111111-1111-1111-1111-111111111111',
    email: 'traveler@example.com',
    displayName: '旅行者',
  },
  accessToken: 'access-token',
  tokenType: 'Bearer',
  expiresIn: 900,
}

const refreshedSession = {
  ...session,
  accessToken: 'rotated-token',
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

/** stub global fetch；返回按 path 分发的调用记录 */
function stubFetch(handler: (path: string, init: RequestInit | undefined, call: number) => Response | Promise<Response>) {
  const calls: Array<{ path: string; init?: RequestInit }> = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const raw = String(input)
    const path = raw.startsWith('/') ? raw.split('?')[0]! : new URL(raw).pathname
    calls.push({ path, init })
    return handler(path, init, calls.length)
  }))
  return calls
}

async function setup() {
  const { useAuthStore } = await import('../src/app/stores/auth')
  const { useWorkspaceSession } = await import('../src/workspace/session')
  const auth = useAuthStore()
  const sessionStore = useWorkspaceSession()
  return { auth, sessionStore }
}

describe('workspace session store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  test('restoreSession 成功 → authenticated', async () => {
    const calls = stubFetch((path) => {
      expect(path).toBe('/api/auth/refresh')
      return jsonResponse(session)
    })
    const { sessionStore } = await setup()

    expect(await sessionStore.restoreSession()).toBe(true)
    expect(sessionStore.phase).toBe('authenticated')
    expect(sessionStore.user).toEqual(session.user)
    expect(calls).toHaveLength(1)
  })

  test('restoreSession 失败 → guest（不能进入业务）', async () => {
    stubFetch(() => jsonResponse({}, 401))
    const { sessionStore } = await setup()

    expect(await sessionStore.restoreSession()).toBe(false)
    expect(sessionStore.phase).toBe('guest')
  })

  test('authenticate 失败写入用户可读 error，不抛出', async () => {
    stubFetch((path) => {
      expect(path).toBe('/api/auth/login')
      return jsonResponse({ code: 'INVALID_CREDENTIALS', message: '邮箱或密码不正确' }, 401)
    })
    const { sessionStore } = await setup()
    sessionStore.clearLocalSession()

    await sessionStore.authenticate({ mode: 'login', email: 'a@b.c', password: 'wrong-password', displayName: '' })
    expect(sessionStore.phase).toBe('guest')
    expect(sessionStore.error).toBe('邮箱或密码不正确')
  })

  test('withAccessToken：401 → 单飞 refresh → 自动重试原请求（带新令牌）', async () => {
    const { auth, sessionStore } = await setup()
    auth.applySession(session)

    const calls = stubFetch(async (path, init, call) => {
      if (path === '/api/trips') {
        // 第 1 次 401，refresh 后重试必须携带新令牌
        if (call === 1) return jsonResponse({ code: 'EXPIRED' }, 401)
        expect((init?.headers as Record<string, string>).Authorization).toBe('Bearer rotated-token')
        return jsonResponse([{ id: 't1' }])
      }
      expect(path).toBe('/api/auth/refresh')
      return jsonResponse(refreshedSession)
    })

    const { ApiError } = await import('../src/lib/api')
    const result = await sessionStore.withAccessToken(async (token) => {
      const response = await fetch('/api/trips', { headers: { Authorization: `Bearer ${token}` } })
      if (!response.ok) {
        const body = await response.json() as { code?: string }
        throw new ApiError(response.status, body.code ?? 'REQUEST_FAILED', '请求失败')
      }
      return response.json()
    })

    expect(result).toEqual([{ id: 't1' }])
    expect(calls.filter((c) => c.path === '/api/auth/refresh')).toHaveLength(1)
    expect(sessionStore.phase).toBe('authenticated')
  })

  test('withAccessToken：refresh 也 401 → 清空会话回 guest', async () => {
    stubFetch(() => jsonResponse({ code: 'EXPIRED' }, 401))
    const { auth, sessionStore } = await setup()
    auth.applySession(session)

    const { ApiError } = await import('../src/lib/api')
    await expect(sessionStore.withAccessToken(async () => {
      throw new ApiError(401, 'EXPIRED', 'token 过期')
    })).rejects.toMatchObject({ status: 401 })
    expect(sessionStore.phase).toBe('guest')
  })

  test('logout：服务端失败也保证本地会话清空', async () => {
    stubFetch(() => jsonResponse({}, 500))
    const { auth, sessionStore } = await setup()
    auth.applySession(session)

    await sessionStore.logout()
    expect(sessionStore.phase).toBe('guest')
  })
})
