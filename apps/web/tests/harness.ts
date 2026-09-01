import { fireEvent, render as renderComponent, screen } from '@testing-library/vue'
import type { Component } from 'vue'
import { createPinia } from 'pinia'
import { vi } from 'vitest'

import App from '../src/App.vue'
import { createTripPilotRouter } from '../src/app/router'

/** Installs a jsdom-safe matchMedia stub; call from beforeAll. */
export function installMatchMediaMock() {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
}

/** Renders App with the real pinia + router plugins, other components plain. */
export function render(component: Component, options?: Parameters<typeof renderComponent>[1]) {
  if (component !== App) return renderComponent(component, options)

  return renderComponent(component, {
    ...options,
    global: {
      ...options?.global,
      plugins: [createPinia(), createTripPilotRouter(), ...(options?.global?.plugins ?? [])],
    },
  })
}

export function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

export function urlOf(input: RequestInfo | URL): string {
  return typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
}

export const authResponse = {
  user: {
    id: '11111111-1111-1111-1111-111111111111',
    email: 'traveler@example.com',
    displayName: '旅行者',
  },
  accessToken: 'access-token',
  tokenType: 'Bearer',
  expiresIn: 900,
}

/** Signs in through the real login form and waits for the workspace shell. */
export async function signIn(
  fetchMock: ReturnType<typeof vi.fn>,
  email = 'traveler@example.com',
  password = 'correct-password',
) {
  vi.stubGlobal('fetch', fetchMock)
  render(App)

  // 等待登录页面展示
  await screen.findByRole('heading', { name: '登录' })

  await fireEvent.update(screen.getByLabelText('邮箱 / 用户名'), email)
  await fireEvent.update(screen.getByLabelText('密码'), password)
  await fireEvent.click(screen.getByRole('button', { name: '登录' }))

  // 等待 workspace shell 渲染
  await screen.findByTestId('workspace-shell')
}
