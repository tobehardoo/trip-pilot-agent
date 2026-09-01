import { cleanup, fireEvent, screen } from '@testing-library/vue'
import { afterEach, beforeAll, describe, expect, test, vi } from 'vitest'

import App from '../src/App.vue'
import { authResponse, installMatchMediaMock, render, response, signIn, urlOf } from './harness'

beforeAll(() => {
  installMatchMediaMock()
})

describe('TripPilot workspace shell', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  test('shows login and registration modes to unauthenticated visitors', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response({ code: 'INVALID_REFRESH_TOKEN' }, 401)))
    render(App)

    expect(await screen.findByRole('heading', { name: '登录' })).toBeTruthy()
    expect(screen.getByLabelText('邮箱 / 用户名')).toBeTruthy()
    expect(screen.getByLabelText('密码')).toBeTruthy()

    await fireEvent.click(screen.getByRole('button', { name: '创建账户' }))

    expect(screen.getByRole('heading', { name: '创建账户' })).toBeTruthy()
    expect(screen.getByLabelText('显示名称')).toBeTruthy()
  })

  test('logs in and shows the workspace empty state', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/login')) return response(authResponse)
      if (url.endsWith('/api/trips') && init?.method !== 'POST') return response([])
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })

    await signIn(fetchMock)

    expect(screen.getAllByText('TripPilot').length).toBeGreaterThan(0)

    const tripsRequest = fetchMock.mock.calls.find(([input]) => urlOf(input).endsWith('/api/trips'))
    expect(tripsRequest?.[1]?.headers).toMatchObject({ Authorization: 'Bearer access-token' })
  })

  test('restores a session by rotating the HttpOnly refresh cookie', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/refresh')) return response(authResponse)
      if (url.endsWith('/api/trips')) return response([])
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(App)

    // 等待 workspace shell 渲染
    expect(await screen.findByTestId('workspace-shell')).toBeTruthy()
    expect(screen.getAllByText('TripPilot').length).toBeGreaterThan(0)
    const refreshRequest = fetchMock.mock.calls.find(([input]) => urlOf(input).endsWith('/api/auth/refresh'))
    expect(refreshRequest?.[1]?.credentials).toBe('same-origin')
    expect(refreshRequest?.[1]?.body).toBeUndefined()
  })

  test('returns to login when access-token refresh is rejected', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input)
      if (url.endsWith('/api/auth/refresh')) return response({ code: 'INVALID_REFRESH_TOKEN' }, 401)
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(App)

    expect(await screen.findByRole('heading', { name: '登录' })).toBeTruthy()
  })
})
