/**
 * 行程数据来源词汇（F-UI-4 泄漏清零的唯一来源）。
 *
 * `provider` / `activity.source` 是系统级枚举，属于 L3：默认界面只显示
 * 用户语言，未知枚举一律不上屏（返回 null 由调用方不渲染），避免把
 * `AMAP`、`MIXED` 这类原始值泄漏到可读界面上。
 */

export type DataSource = 'AMAP' | 'DEMO' | 'MIXED' | 'PLANNER'

export const DATA_SOURCE_LABELS: Record<DataSource, string> = {
  AMAP: '真实数据',
  DEMO: '演示数据',
  MIXED: '混合数据',
  PLANNER: '规划器数据',
}

export function dataSourceLabel(value: string | null | undefined): string | null {
  if (!value) return null
  return Object.prototype.hasOwnProperty.call(DATA_SOURCE_LABELS, value)
    ? DATA_SOURCE_LABELS[value as DataSource]
    : null
}

/** 演示/降级来源必须在 L1 保持可见，不能因为收进抽屉而被隐藏。 */
export function isDemoSource(value: string | null | undefined): boolean {
  return value === 'DEMO'
}
