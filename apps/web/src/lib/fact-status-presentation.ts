import type { ItineraryFactImpact } from './api'

/**
 * 「本次规划依据」的展示层降噪工具。
 *
 * 只做纯展示转换（聚合 + 用户层摘要），不修改、不丢弃任何事实字段。
 * 聚合键是结构化字段（category + sourceName），不是完整中文 reason——
 * 这样同一 Provider 的同类事实无论出现多少次都聚合成一组，用户先看到
 * 数据状态总览，展开「高级诊断」后仍能逐条看到原始明细（含 evidence /
 * source / reliability / stale / conflicted / refreshFailed）。
 */

export interface FactImpactGroup {
  category: string
  sourceName: string
  count: number
  items: ItineraryFactImpact[]
}

export interface UserFacingIssue {
  /** 用户可理解的一句话（如「2 个地点营业时间建议出发前确认」）。 */
  message: string
  /** 行动建议（如「出发前通过官方渠道再次确认」）。 */
  action: string
  /** 严重程度，用于视觉区分，不改变底层语义。 */
  severity: 'warning' | 'info'
}

export interface FactStatusSummary {
  totalCount: number
  groupCount: number
  /** 全部事实中标记为待确认/异常的条数（stale / conflicted / refreshFailed）。 */
  issueCount: number
  /** 是否全部正常（无 stale/conflicted/refreshFailed）。 */
  allHealthy: boolean
  issues: UserFacingIssue[]
}

const USER_ACTION_HINTS: Record<string, { message: (n: number) => string; action: string }> = {
  OPENING_HOURS: {
    message: (n) => `${n} 个地点营业时间建议出发前确认`,
    action: '出发前通过官方渠道（高德/商户电话）再次确认营业时间。',
  },
  WEATHER: {
    message: () => '部分天气辅助数据未同步',
    action: '不影响核心行程安排；出行前请查看最新天气。',
  },
  ROUTE: {
    message: () => '部分路线信息使用估算',
    action: '可能影响实际通勤时间，请预留额外时间。',
  },
}

function normalizeCategory(category: string): string {
  const upper = category.toUpperCase()
  if (upper.includes('OPENING')) return 'OPENING_HOURS'
  if (upper.includes('WEATHER')) return 'WEATHER'
  if (upper.includes('ROUTE') || upper.includes('TRANSIT') || upper.includes('TRAFFIC')) return 'ROUTE'
  return category.toUpperCase()
}

/**
 * 事实类别的用户词汇（展示层），键与 USER_ACTION_HINTS 同源。
 * 未识别的类别返回通用文案——绝不把原始枚举值直接上屏。
 */
const FACT_CATEGORY_LABELS: Record<string, string> = {
  OPENING_HOURS: '营业时间',
  WEATHER: '天气',
  ROUTE: '路线',
}

export function factCategoryLabel(category: string): string {
  return FACT_CATEGORY_LABELS[normalizeCategory(category)] ?? '其他行程信息'
}

/** 按结构化字段（category + sourceName）聚合，组内保留全部原始明细。 */
export function aggregateFactImpacts(facts: ItineraryFactImpact[]): FactImpactGroup[] {
  const groups = new Map<string, FactImpactGroup>()
  for (const fact of facts) {
    const category = normalizeCategory(fact.category)
    const key = `${category}::${fact.sourceName}`
    const existing = groups.get(key)
    if (existing) {
      existing.count += 1
      existing.items.push(fact)
    } else {
      groups.set(key, { category, sourceName: fact.sourceName, count: 1, items: [fact] })
    }
  }
  return [...groups.values()].sort((a, b) => a.category.localeCompare(b.category) || a.sourceName.localeCompare(b.sourceName))
}

/** 用户层摘要：总览计数 + 影响用户的异常（带行动建议）。 */
export function summarizeFactStatus(facts: ItineraryFactImpact[]): FactStatusSummary {
  const issueFacts = facts.filter((f) => f.stale || f.conflicted || f.refreshFailed)
  const byCategory = new Map<string, ItineraryFactImpact[]>()
  for (const fact of issueFacts) {
    const category = normalizeCategory(fact.category)
    const list = byCategory.get(category) ?? []
    list.push(fact)
    byCategory.set(category, list)
  }
  const issues: UserFacingIssue[] = []
  for (const [category, list] of byCategory) {
    const hint = USER_ACTION_HINTS[category]
    if (hint) {
      issues.push({ message: hint.message(list.length), action: hint.action, severity: 'warning' })
    } else {
      issues.push({
        message: `${list.length} 项${factCategoryLabel(category)}待确认`,
        action: '建议出发前自行核实相关信息。',
        severity: 'warning',
      })
    }
  }
  return {
    totalCount: facts.length,
    groupCount: aggregateFactImpacts(facts).length,
    issueCount: issueFacts.length,
    allHealthy: issueFacts.length === 0,
    issues,
  }
}
