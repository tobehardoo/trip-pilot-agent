import { createMemoryHistory } from 'vue-router'
import { describe, expect, test } from 'vitest'

import { createTripPilotRouter } from '../src/app/router'

describe('TripPilot router', () => {
  test('resolves the V2 application routes with stable route names', async () => {
    const router = createTripPilotRouter(createMemoryHistory())

    await router.push('/workspace')
    await router.isReady()
    expect(router.currentRoute.value.name).toBe('workspace')

    await router.push('/workspace/trips/trip%20id')
    expect(router.currentRoute.value).toMatchObject({
      name: 'workspace-trip',
      params: { tripId: 'trip id' },
    })

    // 设置中心（F-UI-11 方案 A）：独立路由，可深链
    await router.push('/workspace/settings')
    expect(router.currentRoute.value.name).toBe('workspace-settings')

    await router.push('/share/shared%20version')
    expect(router.currentRoute.value).toMatchObject({
      name: 'shared-itinerary',
      params: { shareToken: 'shared version' },
    })

    // 根路径重定向到 workspace
    await router.push('/')
    await router.isReady()
    // 重定向后路由名可能为 workspace 或 workspace-trip（取决于是否有参数）
    expect(['workspace', 'workspace-trip']).toContain(router.currentRoute.value.name)
  })
})