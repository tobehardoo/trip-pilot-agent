import type { EvaluationWarning } from './api'

/**
 * 体验评分 warning 的展示层聚合工具。
 *
 * 只做「按结构化字段分组 + 摘要统计」的纯展示转换，不修改、不丢弃、
 * 不改变任何 warning 的语义。分组键是稳定的 `code`（不是中文 message），
 * 这样同一种风险（例如换乘缓冲不足）无论出现几次都聚合成一组，用户
 * 先看到「有几类风险、严重程度如何」，展开后仍能看到每一条原始明细。
 */

export type WarningSeverity = EvaluationWarning['severity']

export interface WarningGroup {
  code: string
  severity: WarningSeverity
  count: number
  /** 组内第一条 warning 的 message，作为该风险类的代表文案。 */
  label: string
  items: EvaluationWarning[]
}

export interface WarningSummary {
  groupCount: number
  totalCount: number
  /** 涉及的独立活动数（entityType=ACTIVITY 且 entityId 非空时去重）。 */
  affectedActivityCount: number
}

const SEVERITY_ORDER: Record<WarningSeverity, number> = { INFO: 0, WARNING: 1, CRITICAL: 2 }

export function highestSeverity(severities: WarningSeverity[]): WarningSeverity {
  if (severities.length === 0) return 'INFO'
  return severities.reduce((a, b) => (SEVERITY_ORDER[b] > SEVERITY_ORDER[a] ? b : a))
}

export function groupEvaluationWarnings(warnings: EvaluationWarning[]): WarningGroup[] {
  const groups = new Map<string, WarningGroup>()
  for (const w of warnings) {
    const existing = groups.get(w.code)
    if (existing) {
      existing.count += 1
      existing.severity = highestSeverity([existing.severity, w.severity])
      existing.items.push(w)
    } else {
      groups.set(w.code, {
        code: w.code,
        severity: w.severity,
        count: 1,
        label: w.message,
        items: [w],
      })
    }
  }
  // 固定顺序：先按严重度降序，同严重度按 code 字典序，保证渲染稳定。
  return [...groups.values()].sort((a, b) => {
    const bySeverity = SEVERITY_ORDER[b.severity] - SEVERITY_ORDER[a.severity]
    return bySeverity !== 0 ? bySeverity : a.code.localeCompare(b.code)
  })
}

export function summarizeWarnings(warnings: EvaluationWarning[]): WarningSummary {
  const activityIds = new Set<string>()
  for (const w of warnings) {
    if (w.entityType === 'ACTIVITY' && w.entityId) activityIds.add(w.entityId)
  }
  return {
    groupCount: new Set(warnings.map((w) => w.code)).size,
    totalCount: warnings.length,
    affectedActivityCount: activityIds.size,
  }
}
