// 设置中心 · 第三方 API 配置读写（F-UI-11 P0）。
// 行为自 WorkspaceSidebar 弹卡逐行迁移（2026-09-04 D3，能力零缩水）：
//   · 保存时仅提交 apiKey 非空的 provider；apiBaseUrl / model 为空不下发字段；
//   · 保存成功后重新拉取对齐服务端状态（区别：成功提示不再被重拉立刻清除）；
//   · 读取失败统一文案「读取 API 配置失败」，不吞错误。
// 新增（不构成缩水）：每行「清空」按钮 + 配置状态派生（✓ 已配置 / 未配置，纯文字色）。
import { computed, reactive, ref } from 'vue'

import { listApiConfigs, saveApiConfigs, type UserApiConfig } from '../../lib/api'
import { useWorkspaceSession } from '../session'

export interface ApiProviderMeta {
  key: string
  label: string
  keyPlaceholder: string
  showModel: boolean
}

export interface ApiConfigFormValue {
  apiKey: string
  apiBaseUrl: string
  model: string
}

/** 供应商清单（顺序 = 设置页展示顺序，与原弹卡一致）。 */
export const API_PROVIDERS: ApiProviderMeta[] = [
  { key: 'WEATHER', label: '天气（和风）', keyPlaceholder: '和风天气 API Key', showModel: false },
  { key: 'AMAP', label: '高德地图', keyPlaceholder: '高德 Web 服务 Key', showModel: false },
  { key: 'KNOWLEDGE', label: '知识库嵌入', keyPlaceholder: 'DashScope API Key', showModel: true },
  { key: 'PLANNER', label: '规划', keyPlaceholder: '规划方 API Key', showModel: false },
]

function emptyForm(): Record<string, ApiConfigFormValue> {
  return Object.fromEntries(
    API_PROVIDERS.map((p) => [p.key, { apiKey: '', apiBaseUrl: '', model: '' }]),
  )
}

export function useApiConfigs() {
  const session = useWorkspaceSession()

  const form = reactive<Record<string, ApiConfigFormValue>>(emptyForm())
  const loading = ref(false)
  const loadError = ref<string | null>(null)
  const saving = ref(false)
  const message = ref<string | null>(null)
  const messageTone = ref<'ok' | 'error'>('ok')

  /** 拉取服务端配置并回填表单；响应中缺失的 provider 保持空表单。 */
  async function load(): Promise<void> {
    loading.value = true
    loadError.value = null
    try {
      const list = await session.withAccessToken((token) => listApiConfigs(token))
      Object.assign(form, emptyForm())
      for (const cfg of list as UserApiConfig[]) {
        if (!form[cfg.provider]) continue
        form[cfg.provider] = {
          apiKey: cfg.apiKey ?? '',
          apiBaseUrl: cfg.apiBaseUrl ?? '',
          model: cfg.model ?? '',
        }
      }
    } catch {
      loadError.value = '读取 API 配置失败'
    } finally {
      loading.value = false
    }
  }

  /** 保存：仅提交 apiKey 非空的 provider（弹卡同款语义），成功后重拉对齐。 */
  async function save(): Promise<void> {
    saving.value = true
    message.value = null
    try {
      const items = API_PROVIDERS
        .filter((p) => form[p.key]?.apiKey.trim())
        .map((p) => ({
          provider: p.key,
          apiKey: form[p.key].apiKey.trim(),
          apiBaseUrl: form[p.key].apiBaseUrl.trim() || undefined,
          model: form[p.key].model.trim() || undefined,
        }))
      await session.withAccessToken((token) => saveApiConfigs(token, items))
      message.value = '已保存'
      messageTone.value = 'ok'
      await load()
    } catch (cause) {
      message.value = cause instanceof Error ? cause.message : '保存失败'
      messageTone.value = 'error'
    } finally {
      saving.value = false
    }
  }

  /** 清空本地表单（不触发删除端点——弹卡从未调用 DELETE，保持同口径）。 */
  function clearProvider(key: string): void {
    if (!form[key]) return
    form[key] = { apiKey: '', apiBaseUrl: '', model: '' }
  }

  /** 配置状态派生：apiKey 非空即视为已配置（与服务端保存语义一致）。 */
  const configured = computed<Record<string, boolean>>(() =>
    Object.fromEntries(
      API_PROVIDERS.map((p) => [p.key, Boolean(form[p.key]?.apiKey.trim())]),
    ),
  )

  return {
    API_PROVIDERS,
    form,
    loading,
    loadError,
    saving,
    message,
    messageTone,
    configured,
    load,
    save,
    clearProvider,
  }
}
