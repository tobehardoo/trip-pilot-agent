<template>
  <div v-if="evaluation" class="plan-evaluation-panel">
    <div class="mb-3 flex items-center justify-between gap-3 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
      <span class="font-semibold">行程可执行：已验证</span>
      <span class="text-xs">硬约束校验通过</span>
    </div>
    <div class="evaluation-header">
      <span class="text-sm font-semibold">体验评分</span>
      <span class="sr-only">行程质量</span>
      <span class="evaluation-score" :class="scoreClass">{{ evaluation.overallScore }}/100</span>
    </div>

    <div class="evaluation-dimensions">
      <div v-for="dim in dimensions" :key="dim.key" class="dimension-row">
        <span class="dim-label">{{ dim.label }}</span>
        <div class="dim-bar-bg" :class="{ 'dim-bar-na': dim.value === null }">
          <div v-if="dim.value !== null" class="dim-bar" :style="{ width: dim.value + '%' }" :class="dim.barClass" />
        </div>
        <span class="dim-value" :class="{ 'dim-value-na': dim.value === null }">
          {{ dim.value === null ? '未适用' : dim.value }}
        </span>
      </div>
    </div>

    <div v-if="evaluation.warnings.length" class="evaluation-warnings">
      <div
        v-for="(w, i) in evaluation.warnings"
        :key="i"
        class="warning-item"
        :class="'severity-' + w.severity.toLowerCase()"
      >
        <span class="warning-badge">{{ severityLabel(w.severity) }}</span>
        <span class="warning-msg">{{ w.message }}</span>
      </div>
    </div>

    <details v-if="evaluation.decisions.length" class="evaluation-decisions">
      <summary class="text-xs font-medium cursor-pointer">
        决策解释 ({{ evaluation.decisions.length }})
      </summary>
      <div v-for="(d, i) in evaluation.decisions" :key="i" class="decision-item">
        <span class="decision-type">{{ subjectTypeLabel(d.subjectType) }}</span>
        <span class="decision-summary">{{ d.summary }}</span>
      </div>
    </details>

    <p v-if="evaluation.summary" class="evaluation-summary text-xs">{{ evaluation.summary }}</p>
  </div>
  <div v-else-if="showLegacy" class="plan-evaluation-panel evaluation-legacy">
    <p class="text-xs text-muted-foreground">该版本生成时尚未启用质量评估</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { PlanEvaluation } from '../lib/api'

const props = withDefaults(defineProps<{
  evaluation?: PlanEvaluation | null
  showLegacy?: boolean
}>(), {
  showLegacy: false,
})

const scoreClass = computed(() => {
  if (!props.evaluation) return ''
  const s = props.evaluation.overallScore
  if (s >= 85) return 'score-high'
  if (s >= 70) return 'score-mid'
  return 'score-low'
})

const dimensions = computed(() => {
  if (!props.evaluation) return []
  const d = props.evaluation.dimensions
  const scoreColor = (v: number | null) => {
    if (v === null) return ''
    return v >= 85 ? 'bar-high' : v >= 70 ? 'bar-mid' : 'bar-low'
  }
  return [
    { key: 'constraintSatisfaction', label: '约束满足', value: d.constraintSatisfaction, barClass: scoreColor(d.constraintSatisfaction) },
    { key: 'timeFeasibility', label: '时间合理', value: d.timeFeasibility, barClass: scoreColor(d.timeFeasibility) },
    { key: 'budgetFit', label: '预算匹配', value: d.budgetFit, barClass: scoreColor(d.budgetFit) },
    { key: 'routeEfficiency', label: '路线效率', value: d.routeEfficiency, barClass: scoreColor(d.routeEfficiency) },
    { key: 'interestMatch', label: '兴趣匹配', value: d.interestMatch, barClass: scoreColor(d.interestMatch) },
  ]
})

function severityLabel(s: string) {
  return { INFO: '提示', WARNING: '注意', CRITICAL: '严重' }[s] ?? s
}

function subjectTypeLabel(t: string) {
  return { PLAN: '总体', DAY: '当日', ACTIVITY: '活动', TRANSIT: '路段' }[t] ?? t
}
</script>

<style scoped>
.plan-evaluation-panel { padding: 0.75rem; border-radius: 0.5rem; background: rgba(255,255,255,0.05); }
.evaluation-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }
.evaluation-score { font-size: 1.25rem; font-weight: 700; }
.score-high { color: #22c55e; } .score-mid { color: #eab308; } .score-low { color: #ef4444; }
.dimension-row { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.25rem; font-size: 0.75rem; }
.dim-label { width: 4rem; flex-shrink: 0; }
.dim-bar-bg { flex: 1; height: 6px; background: rgba(255,255,255,0.1); border-radius: 3px; overflow: hidden; }
.dim-bar { height: 100%; border-radius: 3px; transition: width 0.3s; }
.bar-high { background: #22c55e; } .bar-mid { background: #eab308; } .bar-low { background: #ef4444; }
.dim-value { width: 3rem; text-align: right; }
.dim-value-na { color: rgba(255,255,255,0.5); }
.dim-bar-na { background: rgba(255,255,255,0.04); }
.evaluation-warnings { margin-top: 0.5rem; }
.warning-item { display: flex; align-items: flex-start; gap: 0.25rem; margin-bottom: 0.25rem; font-size: 0.75rem; }
.warning-badge { font-size: 0.625rem; padding: 0 0.25rem; border-radius: 0.25rem; flex-shrink: 0; }
.severity-info .warning-badge { background: rgba(59,130,246,0.2); color: #93c5fd; }
.severity-warning .warning-badge { background: rgba(234,179,8,0.2); color: #fde047; }
.severity-critical .warning-badge { background: rgba(239,68,68,0.2); color: #fca5a5; }
.evaluation-decisions { margin-top: 0.5rem; }
.decision-item { display: flex; gap: 0.5rem; padding: 0.25rem 0; font-size: 0.75rem; border-top: 1px solid rgba(255,255,255,0.05); }
.decision-type { color: rgba(255,255,255,0.5); flex-shrink: 0; }
.evaluation-summary { margin-top: 0.5rem; color: rgba(255,255,255,0.6); }
.evaluation-legacy { text-align: center; }
</style>
