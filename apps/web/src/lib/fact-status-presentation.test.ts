import { describe, expect, it } from 'vitest'

import type { ItineraryFactImpact } from './api'
import { aggregateFactImpacts, summarizeFactStatus } from './fact-status-presentation'

function fact(partial: Partial<ItineraryFactImpact>): ItineraryFactImpact {
  return {
    factId: 'f1', category: 'OPENING_HOURS', date: null, effect: 'AFFECTS_SCHEDULE',
    targetPoiId: null, targetName: null, reason: 'r', sourceName: 'AMap',
    sourceType: 'OFFICIAL', sourceUrl: null, reliabilityLevel: 'OFFICIAL',
    checkedAt: '2026-08-01T00:00:00Z', evidence: 'e',
    stale: false, conflicted: false, refreshFailed: false,
    ...partial,
  }
}

describe('aggregateFactImpacts', () => {
  it('returns [] for no facts', () => {
    expect(aggregateFactImpacts([])).toEqual([])
  })

  it('groups identical category+source facts and keeps all items', () => {
    const groups = aggregateFactImpacts([
      fact({ factId: 'a', category: 'OPENING_HOURS', sourceName: 'AMap' }),
      fact({ factId: 'b', category: 'OPENING_HOURS', sourceName: 'AMap' }),
      fact({ factId: 'c', category: 'WEATHER', sourceName: 'QWeather' }),
    ])
    expect(groups).toHaveLength(2)
    const opening = groups.find((g) => g.category === 'OPENING_HOURS')
    expect(opening?.count).toBe(2)
    expect(opening?.items).toHaveLength(2)
  })

  it('normalizes category spelling across sources', () => {
    const groups = aggregateFactImpacts([
      fact({ factId: 'a', category: 'opening-hours', sourceName: 'AMap' }),
      fact({ factId: 'b', category: 'OPENING_HOURS', sourceName: 'AMap' }),
    ])
    expect(groups).toHaveLength(1)
    expect(groups[0].count).toBe(2)
  })

  it('never drops a fact across grouping', () => {
    const input = [fact({ factId: 'a' }), fact({ factId: 'b' }), fact({ factId: 'c', sourceName: 'QWeather' })]
    const groups = aggregateFactImpacts(input)
    expect(groups.reduce((sum, g) => sum + g.items.length, 0)).toBe(3)
  })
})

describe('summarizeFactStatus', () => {
  it('all healthy when no stale/conflicted/refreshFailed', () => {
    const summary = summarizeFactStatus([fact({ factId: 'a' }), fact({ factId: 'b' })])
    expect(summary.allHealthy).toBe(true)
    expect(summary.issueCount).toBe(0)
    expect(summary.issues).toEqual([])
  })

  it('counts 10+ identical provider facts and collapses them into one issue', () => {
    const many = Array.from({ length: 12 }, (_, i) =>
      fact({ factId: `w${i}`, category: 'WEATHER', sourceName: 'QWeather', stale: true, date: '2026-08-01' }))
    const summary = summarizeFactStatus(many)
    expect(summary.issueCount).toBe(12)
    expect(summary.issues).toHaveLength(1)
    expect(summary.issues[0].message).toContain('天气')
  })

  it('maps opening-hours issues to user-facing confirmation advice', () => {
    const summary = summarizeFactStatus([
      fact({ factId: 'a', category: 'OPENING_HOURS', sourceName: 'AMap', conflicted: true }),
      fact({ factId: 'b', category: 'OPENING_HOURS', sourceName: 'AMap', conflicted: true }),
    ])
    expect(summary.issueCount).toBe(2)
    expect(summary.issues[0].message).toBe('2 个地点营业时间建议出发前确认')
    expect(summary.issues[0].action).toContain('官方渠道')
  })

  it('unknown categories still surface as待确认 with an action', () => {
    const summary = summarizeFactStatus([
      fact({ factId: 'a', category: 'POI_DETAILS', sourceName: 'AMap', refreshFailed: true }),
    ])
    expect(summary.issues[0].message).toContain('POI_DETAILS')
    expect(summary.issues[0].action.length).toBeGreaterThan(0)
  })

  it('reports group count matching the aggregated view', () => {
    const summary = summarizeFactStatus([
      fact({ factId: 'a', category: 'WEATHER', sourceName: 'QWeather' }),
      fact({ factId: 'b', category: 'WEATHER', sourceName: 'QWeather' }),
      fact({ factId: 'c', category: 'OPENING_HOURS', sourceName: 'AMap' }),
    ])
    expect(summary.groupCount).toBe(2)
  })
})
