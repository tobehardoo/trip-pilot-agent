// API 与模型分区测试（F-UI-11 P0）。
// 覆盖 useApiConfigs + ApiModelsSection 的读写语义（自 WorkspaceSidebar 弹卡等价迁移）：
//   · 加载回填与配置状态派生（✓ 已配置 / 未配置）
//   · 保存：仅提交 apiKey 非空的 provider；空 Base URL / model 不下发；成功后重拉并提示「已保存」
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
    apiKey: 'sk-knowledge',
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
  test('加载回填表单并派生配置状态', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input)
      if (url.endsWith('/api/config/api-configs')) return response(CONFIGS)
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderSection()

    // 回填：服务端有配置的 provider（等待异步 load 完成）
    const knowledgeKey = await waitFor(() => {
      const input = screen.getByTestId('settings-provider-key-KNOWLEDGE') as HTMLInputElement
      expect(input.value).toBe('sk-knowledge')
      return input
    })
    expect((screen.getByTestId('settings-provider-model-KNOWLEDGE') as HTMLInputElement).value).toBe('text-embedding-v4')

    // 状态徽标（纯文字色）：已配置 vs 未配置
    expect(screen.getByTestId('settings-provider-status-KNOWLEDGE').textContent).toContain('✓ 已配置')
    expect(screen.getByTestId('settings-provider-status-AMAP').textContent).toContain('未配置')
    expect(screen.getByTestId('settings-provider-status-WEATHER').textContent).toContain('未配置')
    // 4 个 provider 行全部渲染
    expect(screen.getByTestId('settings-provider-PLANNER')).toBeTruthy()
  })

  test('保存：仅提交 apiKey 非空的 provider，成功后提示「已保存」并重拉', async () => {
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
      expect((screen.getByTestId('settings-provider-key-KNOWLEDGE') as HTMLInputElement).value).toBe('sk-knowledge')
    })

    // 给未配置的 PLANNER 填入 Key；AMAP 保持为空
    fireEvent.update(screen.getByTestId('settings-provider-key-PLANNER'), '  sk-planner  ')

    fireEvent.click(screen.getByTestId('settings-api-save'))

    await waitFor(() => {
      expect(screen.getByTestId('settings-api-message').textContent).toContain('已保存')
    })
    // 保存后重新拉取（弹卡同款语义）
    expect(getCalls).toBe(2)
    expect(putBodies.length).toBe(1)

    const items = putBodies[0] as Array<Record<string, unknown>>
    // KNOWLEDGE（服务端已有）+ PLANNER（本次填写）入选；AMAP / WEATHER 空 Key 被过滤
    expect(items.map((i) => i.provider).sort()).toEqual(['KNOWLEDGE', 'PLANNER'])
    const planner = items.find((i) => i.provider === 'PLANNER') as Record<string, unknown>
    expect(planner.apiKey).toBe('sk-planner')
    expect(planner.apiBaseUrl).toBeUndefined()
    expect(planner.model).toBeUndefined()
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
    await screen.findByTestId('settings-provider-key-KNOWLEDGE')

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
      expect((screen.getByTestId('settings-provider-key-KNOWLEDGE') as HTMLInputElement).value).toBe('sk-knowledge')
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
