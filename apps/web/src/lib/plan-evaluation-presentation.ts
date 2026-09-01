import type { DecisionExplanation, EvaluationDimensions, EvaluationWarning } from './api'

/**
 * 体验评分面板的展示层：统一词汇 + warning 聚合。
 *
 * 词汇表（维度名、严重程度、决策对象）集中在此，组件只负责渲染；标签表
 * 以契约联合类型为键，出现契约外的值时解析为 undefined 而不上屏，绝不把
 * 原始枚举直接呈现给用户。
 *
 * 聚合只做「按结构化字段分组 + 摘要统计」的纯展示转换，不修改、不丢弃、
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

/** 评分维度：顺序即渲染顺序，key 是契约字段、label 是用户词汇。 */
export const EVALUATION_DIMENSIONS: ReadonlyArray<{
  key: keyof EvaluationDimensions
  label: string
}> = [
  { key: 'constraintSatisfaction', label: '约束满足' },
  { key: 'timeFeasibility', label: '时间合理' },
  { key: 'budgetFit', label: '预算匹配' },
  { key: 'routeEfficiency', label: '路线效率' },
  { key: 'interestMatch', label: '兴趣匹配' },
]

const WARNING_SEVERITY_LABELS: Record<WarningSeverity, string> = {
  INFO: '提示',
  WARNING: '注意',
  CRITICAL: '严重',
}

const DECISION_SUBJECT_LABELS: Record<DecisionExplanation['subjectType'], string> = {
  PLAN: '总体',
  DAY: '当日',
  ACTIVITY: '活动',
  TRANSIT: '路段',
}

export function warningSeverityLabel(severity: WarningSeverity): string {
  return WARNING_SEVERITY_LABELS[severity]
}

export function decisionSubjectLabel(subjectType: DecisionExplanation['subjectType']): string {
  return DECISION_SUBJECT_LABELS[subjectType]
}
