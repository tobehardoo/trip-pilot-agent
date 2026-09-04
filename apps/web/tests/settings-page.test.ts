// 设置中心页面测试（F-UI-11 P0 / 方案 A）。
// 覆盖：分组导航渲染与切换、常规分区账号展示（D3：账号并入设置页）、
// 返回工作区的路由语义（有旅行回旅行，无旅行回创建模式）。
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { afterEach, describe, expect, test } from 'vitest'

import { createTripPilotRouter } from '../src/app/router'
import { useAuthStore } from '../src/app/stores/auth'
import { useTripStore } from '../src/workspace/stores/tripStore'
import SettingsPage from '../src/workspace/settings/SettingsPage.vue'
import { authResponse } from './harness'

function renderSettings() {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore(pinia).applySession(authResponse)
  const router = createTripPilotRouter(createMemoryHistory())
  const utils = render(SettingsPage, { global: { plugins: [pinia, router] } })
  return { router, pinia, utils }
}

afterEach(() => {
  cleanup()
})

describe('SettingsPage（F-UI-11 方案 A）', () => {
  test('渲染分组导航，默认落在「常规」分区并展示账号信息', async () => {
    renderSettings()

    expect(await screen.findByTestId('settings-nav-general')).toBeTruthy()
    expect(screen.getByTestId('settings-nav-api')).toBeTruthy()
    expect(screen.getByTestId('settings-section-title').textContent).toContain('常规')

    // D3：账号信息从侧栏底部迁入「常规」分区
    expect(screen.getByTestId('settings-account-name').textContent).toContain('旅行者')
    expect(screen.getByTestId('settings-account-email').textContent).toContain('traveler@example.com')
    expect(screen.getByTestId('settings-general-logout')).toBeTruthy()
  })

  test('切换到「API 与模型」分区并展示 4 个 provider 行', async () => {
    renderSettings()

    fireEvent.click(await screen.findByTestId('settings-nav-api'))

    expect(await screen.findByTestId('settings-section-title').then((el) => el.textContent)).toContain('API 与模型')
    expect(screen.getByTestId('settings-provider-WEATHER')).toBeTruthy()
    expect(screen.getByTestId('settings-provider-AMAP')).toBeTruthy()
    expect(screen.getByTestId('settings-provider-KNOWLEDGE')).toBeTruthy()
    expect(screen.getByTestId('settings-provider-PLANNER')).toBeTruthy()
  })

  test('「返回工作区」：无选中旅行时回到创建模式路由', async () => {
    const { router } = renderSettings()
    await router.isReady()

    fireEvent.click(screen.getByTestId('settings-back'))

    await waitFor(() => {
      expect(router.currentRoute.value.name).toBe('workspace')
    })
    expect(router.currentRoute.value.path).toBe('/workspace')
  })

  test('「返回工作区」：有选中旅行时回到该旅行路由', async () => {
    const { router, pinia } = renderSettings()
    await router.isReady()
    // 选中旅行 → 返回目标应为 /workspace/trips/{id}
    useTripStore(pinia).currentTripId = 'trip-1'

    fireEvent.click(screen.getByTestId('settings-back'))

    await waitFor(() => {
      expect(router.currentRoute.value.name).toBe('workspace-trip')
    })
    expect(router.currentRoute.value.params.tripId).toBe('trip-1')
  })

  test('用户条仅展示（D3）：退出登录只出现在「常规」分区一处', async () => {
    renderSettings()

    const page = await screen.findByTestId('settings-page')
    expect(page.querySelectorAll('[data-testid="settings-general-logout"]').length).toBe(1)
  })
})
