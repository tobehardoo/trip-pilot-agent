// 设置中心分区元数据（F-UI-11 P0）。
// D2 决议：P0 仅「常规 + API 与模型」两个分区；P1（索引库摘要）/P2（使用统计、记忆）
// 分区在此追加，导航与页面标题/描述均由本清单驱动。
export type SettingsSectionKey = 'general' | 'api'

export interface SettingsSectionMeta {
  key: SettingsSectionKey
  label: string
  description: string
}

export const SETTINGS_SECTIONS: SettingsSectionMeta[] = [
  { key: 'general', label: '常规', description: '账号信息与登录状态。' },
  { key: 'api', label: 'API 与模型', description: '管理用户自建第三方 API 配置，保存后规划与检索即时生效。' },
]
