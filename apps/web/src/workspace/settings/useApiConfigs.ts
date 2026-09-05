// 设置中心 · 第三方 API 配置读写（F-UI-11 P0）。
// 行为自 WorkspaceSidebar 弹卡逐行迁移（2026-09-04 D3，能力零缩水）。
//
// 2026-09-05 修复两个缺陷（防损坏 + 真正删除）：
//   · 防损坏：后端 list 返回的是掩码 key（如 weat****4455），旧实现直接回填到
//     可编辑表单，用户不重新输入就保存会把真 key 覆盖成掩码占位串。现在掩码
//     key 不进表单（apiKey 置空，靠「已配置」徽标 + 占位提示），未修改的
//     provider 保存时不下发 → 永不覆盖。
//   · 真正删除：旧实现保存时过滤掉空 key 的 provider，后端拿不到删除信号，
//     「清空」只清了本地表单。现在「清空」标记删除意图，保存时以空 key 提交，
//     后端 UserApiConfigService.save 对空 key 执行 delete。
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

function emptyFlags(): Record<string, boolean> {
  return Object.fromEntries(API_PROVIDERS.map((p) => [p.key, false]))
}

export function useApiConfigs() {
  const session = useWorkspaceSession()

  const form = reactive<Record<string, ApiConfigFormValue>>(emptyForm())
  /** 服务端当前已配置的 provider（load 时记录）：派生「已配置」状态与删除语义。 */
  const serverConfigured = reactive<Record<string, boolean>>(emptyFlags())
  /** 用户点过「清空」的 provider：保存时以空 key 提交，让后端真正删除。 */
  const cleared = reactive<Record<string, boolean>>(emptyFlags())
  const loading = ref(false)
  const loadError = ref<string | null>(null)
  const saving = ref(false)
  const message = ref<string | null>(null)
  const messageTone = ref<'ok' | 'error'>('ok')

  /** 拉取服务端配置并回填表单；掩码 key 不回填到可编辑字段（防覆盖真 key）。 */
  async function load(): Promise<void> {
    loading.value = true
    loadError.value = null
    try {
      const list = await session.withAccessToken((token) => listApiConfigs(token))
      Object.assign(form, emptyForm())
      Object.assign(serverConfigured, emptyFlags())
      Object.assign(cleared, emptyFlags())
      for (const cfg of list as UserApiConfig[]) {
        if (!form[cfg.provider]) continue
        serverConfigured[cfg.provider] = Boolean(cfg.apiKey)
        form[cfg.provider] = {
          apiKey: '',
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

  /**
   * 保存（与后端「覆盖全部 provider」语义对齐）：
   *   · 显式清空的 provider → 空 key 提交 → 后端删除；
   *   · 本次填了 key 的 provider → upsert（新增/更换）；
   *   · 其余（未配置或未修改的已配置项）→ 不下发，服务端保持不变。
   */
  async function save(): Promise<void> {
    saving.value = true
    message.value = null
    try {
      const items: Array<{
        provider: string
        apiKey?: string
        apiBaseUrl?: string
        model?: string
      }> = []
      for (const p of API_PROVIDERS) {
        const value = form[p.key]
        if (cleared[p.key]) {
          // 显式清空：不带 key 提交 → 后端对空 key 执行删除
          items.push({ provider: p.key })
          continue
        }
        const key = value.apiKey.trim()
        if (!key) continue
        items.push({
          provider: p.key,
          apiKey: key,
          apiBaseUrl: value.apiBaseUrl.trim() || undefined,
          model: value.model.trim() || undefined,
        })
      }
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

  /** 清空本地表单并标记删除意图（保存时真正删除服务端配置）。 */
  function clearProvider(key: string): void {
    if (!form[key]) return
    form[key] = { apiKey: '', apiBaseUrl: '', model: '' }
    cleared[key] = true
  }

  /** 用户在该 provider 上输入了内容：撤销删除意图（改为新增/更换）。 */
  function touchProvider(key: string): void {
    if (cleared[key]) cleared[key] = false
  }

  /** 配置状态派生：服务端已配置（未清空）或本次填写了 key。 */
  const configured = computed<Record<string, boolean>>(() =>
    Object.fromEntries(
      API_PROVIDERS.map((p) => [
        p.key,
        (serverConfigured[p.key] && !cleared[p.key]) || Boolean(form[p.key]?.apiKey.trim()),
      ]),
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
    touchProvider,
  }
}
