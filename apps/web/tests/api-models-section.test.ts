// API 与模型分区测试（F-UI-11 P0）。
// 覆盖 useApiConfigs + ApiModelsSection 的读写语义（自 WorkspaceSidebar 弹卡等价迁移）：
//   · 加载回填与配置状态派生（✓ 已配置 / 未配置）；掩码 key 不回填到可编辑字段
//   · 保存：本次填写的 provider 下发；未修改的已配置 provider 不下发（防覆盖真 key）
//   · 保存：显式「清空」的 provider 以空 key 提交 → 后端真正删除
//   · 保存失败：服务端文案透出、不吞错
//   · 清空：本地表单清空 + 状态回落「未配置」
//   · 读取失败：统一文案「读取 API 配置失败」
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, test, vi } from 'vitest'

import { useAuthStore } from '../src/app/stores/auth'
import ApiModelsSection from '../src/workspace/settings/sections/ApiModelsSection.vue'
import { authResponse, response, urlOf } from './harness'

const CONFIGS = [
  {
    provider: 'KNOWLEDGE',
    apiKey: 'sk-masked-1234',
    apiBaseUrl: 'https://dashscope.example.com',
    model: 'text-embedding-v4',
    updatedAt: '2026-09-01T00:00:00Z',
  },
  {
    provider: 'AMAP',
    apiKey: null,
    apiBaseUrl: null,
    model: null,
    updatedAt: '2026-09-01T00:00:00Z',
  },
]

function renderSection() {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore(pinia).applySession(authResponse)
  return render(ApiModelsSection, { global: { plugins: [pinia] } })
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('ApiModelsSection（F-UI-11 P0）', () => {
  test('加载回填并派生配置状态；掩码 key 不进可编辑表单', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input)
      if (url.endsWith('/api/config/api-configs')) return response(CONFIGS)
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderSection()

    // 回填：服务端已配置的 provider 状态徽标为「已配置」，但掩码 key 不回填到输入框
    await waitFor(() => {
      expect(screen.getByTestId('settings-provider-status-KNOWLEDGE').textContent).toContain('✓ 已配置')
    })
    const knowledgeKey = screen.getByTestId('settings-provider-key-KNOWLEDGE') as HTMLInputElement
    expect(knowledgeKey.value).toBe('')
    expect((screen.getByTestId('settings-provider-model-KNOWLEDGE') as HTMLInputElement).value)
      .toBe('text-embedding-v4')
    // 未配置的 provider 保持「未配置」
    expect(screen.getByTestId('settings-provider-status-AMAP').textContent).toContain('未配置')
    expect(screen.getByTestId('settings-provider-status-WEATHER').textContent).toContain('未配置')
    // 4 个 provider 行全部渲染
    expect(screen.getByTestId('settings-provider-PLANNER')).toBeTruthy()
  })

  test('保存：未修改的已配置 provider 不下发（防覆盖真 key），仅提交本次填写的', async () => {
    let getCalls = 0
    const putBodies: unknown[] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/config/api-configs') && init?.method === 'PUT') {
        putBodies.push(JSON.parse(String(init.body)))
        return response({})
      }
      if (url.endsWith('/api/config/api-configs')) {
        getCalls += 1
        return response(CONFIGS)
      }
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderSection()
    // 等待初始 load 完成后再操作，避免与保存竞态
    await waitFor(() => {
      expect(screen.getByTestId('settings-provider-status-KNOWLEDGE').textContent).toContain('✓ 已配置')
    })

    // 给未配置的 PLANNER 填入 Key
    fireEvent.update(screen.getByTestId('settings-provider-key-PLANNER'), '  sk-planner  ')

    fireEvent.click(screen.getByTestId('settings-api-save'))

    await waitFor(() => {
      expect(screen.getByTestId('settings-api-message').textContent).toContain('已保存')
    })
    // 保存后重新拉取（弹卡同款语义）
    expect(getCalls).toBe(2)
    expect(putBodies.length).toBe(1)

    const items = putBodies[0] as Array<Record<string, unknown>>
    // 只下发 PLANNER；KNOWLEDGE（已配置但未修改）不下发 → 真 key 不会被掩码串覆盖
    expect(items.map((i) => i.provider).sort()).toEqual(['PLANNER'])
    const planner = items.find((i) => i.provider === 'PLANNER') as Record<string, unknown>
    expect(planner.apiKey).toBe('sk-planner')
    expect(planner.apiBaseUrl).toBeUndefined()
    expect(planner.model).toBeUndefined()
  })

  test('清空后保存：以空 key 提交，后端真正删除该 provider 配置', async () => {
    let getCalls = 0
    const putBodies: unknown[] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (url.endsWith('/api/config/api-configs') && init?.method === 'PUT') {
        putBodies.push(JSON.parse(String(init.body)))
        return response({})
      }
      if (url.endsWith('/api/config/api-configs')) {
        getCalls += 1
        return response(CONFIGS)
      }
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderSection()
    await waitFor(() => {
      expect(screen.getByTestId('settings-provider-status-KNOWLEDGE').textContent).toContain('✓ 已配置')
    })

    fireEvent.click(screen.getByTestId('settings-provider-clear-KNOWLEDGE'))
    await waitFor(() => {
      expect(screen.getByTestId('settings-provider-status-KNOWLEDGE').textContent).toContain('未配置')
    })

    fireEvent.click(screen.getByTestId('settings-api-save'))

    await waitFor(() => {
      expect(screen.getByTestId('settings-api-message').textContent).toContain('已保存')
    })
    const items = putBodies[0] as Array<Record<string, unknown>>
    expect(items.map((i) => i.provider).sort()).toEqual(['KNOWLEDGE'])
    // 删除项：不带 apiKey（空 key → 后端 delete）
    expect(items[0].apiKey).toBeUndefined()
  })

  test('保存失败：服务端错误文案透出，不吞错', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input)
      if (init?.method === 'PUT') return response({ message: '配置服务不可用' }, 500)
      if (url.endsWith('/api/config/api-configs')) return response(CONFIGS)
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderSection()
    await waitFor(() => {
      expect(screen.getByTestId('settings-provider-status-KNOWLEDGE').textContent).toContain('✓ 已配置')
    })

    fireEvent.click(screen.getByTestId('settings-api-save'))

    const message = await screen.findByTestId('settings-api-message')
    await waitFor(() => {
      expect(message.textContent).toContain('配置服务不可用')
    })
    expect(message.className).toContain('text-tp-warn')
  })

  test('清空：本地表单清空，状态回落「未配置」', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (urlOf(input).endsWith('/api/config/api-configs')) return response(CONFIGS)
      throw new Error('Unexpected request')
    })
    vi.stubGlobal('fetch', fetchMock)

    renderSection()
    await waitFor(() => {
      expect(screen.getByTestId('settings-provider-status-KNOWLEDGE').textContent).toContain('✓ 已配置')
    })

    fireEvent.click(screen.getByTestId('settings-provider-clear-KNOWLEDGE'))

    await waitFor(() => {
      expect((screen.getByTestId('settings-provider-key-KNOWLEDGE') as HTMLInputElement).value).toBe('')
    })
    expect(screen.getByTestId('settings-provider-status-KNOWLEDGE').textContent).toContain('未配置')
  })

  test('读取失败：统一文案「读取 API 配置失败」', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response({ message: 'boom' }, 500)))

    renderSection()

    expect(await screen.findByTestId('settings-api-load-error').then((el) => el.textContent))
      .toContain('读取 API 配置失败')
  })
})
