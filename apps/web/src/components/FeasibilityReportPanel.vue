<script setup lang="ts">
import { computed, ref } from 'vue'
import { AlertTriangle, BadgeCheck, CheckCircle2, ChevronDown, CircleHelp, ShieldCheck } from 'lucide-vue-next'

import {
  EVIDENCE_STATE_LABEL,
  FEASIBILITY_STATUS_LABEL,
  RULE_OUTCOME_LABEL,
  formatValidatedAt,
  parseTypedEntityReference,
  ruleIdLabel,
  type EvidenceReference,
  type FeasibilityReport,
  type FeasibilityRuleResult,
  type RepairAttempt,
} from '../lib/feasibility'
import Badge from './ui/Badge.vue'
import Card from './ui/Card.vue'

const props = withDefaults(defineProps<{
  report: FeasibilityReport | null
  malformed?: boolean
  defaultCollapsed?: boolean
}>(), {
  malformed: false,
  defaultCollapsed: false,
})

// B13_FIX R7 (P1-4): technical details (reasonCode, validatorVersion,
// repair ids, evidence refs) are collapsed by default — PASS/NA and raw
// codes are not primary user information.
const showTechnical = ref(!props.defaultCollapsed)

const statusVariant = computed(() => {
  if (!props.report) return 'default'
  return {
    VERIFIED: 'success',
    NEEDS_REPAIR: 'danger',
    UNVERIFIED: 'warning',
  }[props.report.status] as 'success' | 'danger' | 'warning'
})

const statusClass = computed(() => {
  if (!props.report) return ''
  return {
    VERIFIED: 'status-verified',
    NEEDS_REPAIR: 'status-needs-repair',
    UNVERIFIED: 'status-unverified',
  }[props.report.status]
})

// B13_FIX R7 (P1-4): only FAIL/UNKNOWN rules surface as user-facing
// findings; PASS/NA rows are details.
const findings = computed(() => {
  if (!props.report) return []
  return props.report.ruleResults.filter(
    (rule) => rule.outcome === 'FAIL' || rule.outcome === 'UNKNOWN',
  )
})

function outcomeVariant(outcome: FeasibilityRuleResult['outcome']) {
  return {
    PASS: 'success',
    FAIL: 'danger',
    UNKNOWN: 'secondary',
    NOT_APPLICABLE: 'outline',
  }[outcome] as 'success' | 'danger' | 'secondary' | 'outline'
}

function evidenceVariant(state: EvidenceReference['state']) {
  return {
    VERIFIED: 'success',
    STALE: 'warning',
    CONFLICTING: 'danger',
    UNKNOWN: 'secondary',
  }[state] as 'success' | 'warning' | 'danger' | 'secondary'
}

function evidenceLabel(reference: EvidenceReference) {
  return EVIDENCE_STATE_LABEL[reference.state]
}

function entityShortLabel(ref: string) {
  const parsed = parseTypedEntityReference(ref)
  if (parsed.kind === 'unknown') return ref
  return parsed.value
}

function attemptStatusLabel(status: RepairAttempt['resultingStatus']) {
  return FEASIBILITY_STATUS_LABEL[status] ?? status
}

function hasRepairAttempts() {
  return !!props.report && props.report.repairAttempts.length > 0
}

function hasEvidence(rule: FeasibilityRuleResult) {
  return rule.evidenceRefs.length > 0
}
</script>

<template>
  <Card class="feasibility-panel" :class="statusClass" aria-label="硬可行性验证结果">
    <div v-if="malformed" class="feasibility-malformed" role="alert">
      <AlertTriangle :size="18" aria-hidden="true" />
      <div>
        <h3 class="font-semibold text-surface-800">验证结果暂时无法读取</h3>
        <p class="text-sm text-surface-500">报告数据格式异常，无法安全展示。请稍后重试或联系支持。</p>
      </div>
    </div>

    <div v-else-if="!report" class="feasibility-empty">
      <CircleHelp :size="18" aria-hidden="true" />
      <p class="text-sm text-surface-500">此版本没有可用的硬可行性报告</p>
    </div>

    <template v-else>
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="min-w-0">
          <p class="text-xs font-semibold uppercase tracking-widest text-surface-400">Feasibility</p>
          <h3 class="mt-1 text-base font-bold text-surface-800">硬可行性验证</h3>
          <p class="mt-0.5 text-xs text-surface-500">这是行程硬约束的唯一权威结论，不代表体验评分。</p>
        </div>
        <Badge :variant="statusVariant" size="md">
          <ShieldCheck v-if="report.status === 'VERIFIED'" :size="14" aria-hidden="true" />
          <AlertTriangle v-else :size="14" aria-hidden="true" />
          {{ FEASIBILITY_STATUS_LABEL[report.status] }}
        </Badge>
      </div>

      <!-- B13_FIX R7 (P1-4): summary + FAIL/UNKNOWN findings are the primary
           user view; PASS/NA counts stay compact. -->
      <dl class="feasibility-summary mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
        <div class="summary-cell"><dt>规则总数</dt><dd>{{ report.summary.totalCount }}</dd></div>
        <div class="summary-cell"><dt>通过</dt><dd class="text-emerald-600">{{ report.summary.passCount }}</dd></div>
        <div class="summary-cell"><dt>失败</dt><dd class="text-red-600">{{ report.summary.failCount }}</dd></div>
        <div class="summary-cell"><dt>未知</dt><dd class="text-amber-600">{{ report.summary.unknownCount }}</dd></div>
        <div class="summary-cell"><dt>不适用</dt><dd>{{ report.summary.notApplicableCount }}</dd></div>
        <div class="summary-cell"><dt>缺失规则</dt><dd>{{ report.summary.missingRequiredCount }}</dd></div>
      </dl>

      <!-- Findings: only FAIL/UNKNOWN, in plain Chinese with affected dates. -->
      <h4 class="mt-5 text-sm font-semibold text-surface-700">主要问题</h4>
      <ul v-if="findings.length" class="mt-2 space-y-3">
        <li v-for="rule in findings" :key="rule.ruleId" class="rounded-xl border border-surface-200/70 bg-surface-50/60 p-3">
          <div class="flex flex-wrap items-center gap-2">
            <Badge :variant="outcomeVariant(rule.outcome)">{{ RULE_OUTCOME_LABEL[rule.outcome] }}</Badge>
            <span class="text-sm font-semibold text-surface-800">{{ ruleIdLabel(rule.ruleId) }}</span>
          </div>
          <p class="mt-1.5 text-sm text-surface-600">{{ rule.message }}</p>
          <div v-if="rule.affectedDates.length" class="mt-2 flex flex-wrap gap-2 text-xs">
            <span v-for="date in rule.affectedDates" :key="`${rule.ruleId}-d-${date}`" class="rounded-md bg-surface-100 px-1.5 py-0.5 text-surface-600">
              {{ date }}
            </span>
          </div>
        </li>
      </ul>
      <p v-else class="mt-2 text-sm text-surface-400">未发现 FAIL 或 UNKNOWN 规则</p>

      <!-- Technical details (B13_FIX R7 / P1-4): collapsed by default. -->
      <button
        type="button"
        class="mt-4 flex w-full items-center justify-between rounded-xl border border-surface-200/70 bg-surface-50/60 px-4 py-3 text-sm font-semibold text-surface-700 hover:bg-surface-100"
        :aria-expanded="showTechnical"
        data-testid="feasibility-technical-toggle"
        @click="showTechnical = !showTechnical"
      >
        <span>查看技术详情</span>
        <ChevronDown :size="16" class="transition-transform" :class="{ 'rotate-180': showTechnical }" aria-hidden="true" />
      </button>
      <div v-if="showTechnical" class="mt-3">
        <!-- Rule results -->
        <h4 class="text-sm font-semibold text-surface-700">规则明细</h4>
        <ul v-if="report.ruleResults.length" class="feasibility-rules mt-2 space-y-3">
          <li v-for="rule in report.ruleResults" :key="rule.ruleId" class="feasibility-rule rounded-xl border border-surface-200/70 bg-surface-50/60 p-3">
            <div class="flex flex-wrap items-center gap-2">
              <Badge :variant="outcomeVariant(rule.outcome)">{{ RULE_OUTCOME_LABEL[rule.outcome] }}</Badge>
              <span class="text-sm font-semibold text-surface-800">{{ ruleIdLabel(rule.ruleId) }}</span>
              <span v-if="rule.repairable" class="text-xs text-amber-600">可修复</span>
            </div>
            <p class="mt-1.5 text-sm text-surface-600">{{ rule.message }}</p>
            <p class="mt-0.5 text-xs text-surface-400">{{ rule.reasonCode }}</p>

            <div v-if="rule.affectedDates.length || rule.affectedEntityRefs.length" class="mt-2 flex flex-wrap gap-2 text-xs">
              <span v-for="date in rule.affectedDates" :key="`${rule.ruleId}-d-${date}`" class="rounded-md bg-surface-100 px-1.5 py-0.5 text-surface-600">
                {{ date }}
              </span>
              <span v-for="ref in rule.affectedEntityRefs" :key="`${rule.ruleId}-e-${ref}`" class="rounded-md bg-surface-100 px-1.5 py-0.5 text-surface-600" :title="ref">
                {{ entityShortLabel(ref) }}
              </span>
            </div>
            <p v-else class="mt-2 text-xs text-surface-400">无影响日期或实体</p>

            <div v-if="hasEvidence(rule)" class="mt-2 space-y-1">
              <div v-for="evidence in rule.evidenceRefs" :key="evidence.evidenceId" class="flex flex-wrap items-center gap-1.5 text-xs">
                <Badge :variant="evidenceVariant(evidence.state)">{{ evidenceLabel(evidence) }}</Badge>
                <span class="text-surface-600">{{ evidence.evidenceType }}</span>
                <span v-if="evidence.hardConstraintEligible" class="text-surface-600">具备硬约束资格</span>
                <span v-else class="text-surface-400">不具备硬约束资格</span>
              </div>
            </div>
          </li>
        </ul>
        <p v-else class="mt-2 text-sm text-surface-400">无规则明细</p>

        <!-- Repair attempts -->
        <h4 class="mt-5 text-sm font-semibold text-surface-700">修复历史</h4>
        <ul v-if="hasRepairAttempts()" class="mt-2 space-y-2">
          <li v-for="attempt in report.repairAttempts" :key="attempt.attemptIndex" class="rounded-xl border border-surface-200/70 p-3 text-sm">
            <div class="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">尝试 {{ attempt.attemptIndex }}</Badge>
              <span class="text-surface-600">{{ attempt.actionCodes.join('、') || '未记录动作' }}</span>
              <Badge :variant="attempt.resultingStatus === 'VERIFIED' ? 'success' : 'warning'">
                {{ attemptStatusLabel(attempt.resultingStatus) }}
              </Badge>
            </div>
            <p class="mt-1 text-xs text-surface-500">
              触发规则：{{ attempt.triggeringRuleIds.join('、') || '无' }}
              <span v-if="attempt.affectedDates.length"> · 日期：{{ attempt.affectedDates.join('、') }}</span>
            </p>
            <p v-if="attempt.affectedEntityRefs.length" class="mt-1 text-xs text-surface-500">
              影响实体：
              <span v-for="ref in attempt.affectedEntityRefs" :key="`${attempt.attemptIndex}-${ref}`" class="mr-1.5 inline-block rounded-md bg-surface-100 px-1.5 py-0.5 text-surface-600" :title="ref">
                {{ entityShortLabel(ref) }}
              </span>
            </p>
          </li>
        </ul>
        <p v-else class="mt-2 text-sm text-surface-400">无修复尝试</p>

        <!-- Metadata -->
        <div class="mt-4 border-t border-surface-200/70 pt-3 text-xs text-surface-400">
          <span>{{ report.validatorVersion }}</span>
          <span v-if="report.validatedAt" class="ml-3">验证时间 {{ formatValidatedAt(report.validatedAt) }}</span>
        </div>
      </div>
    </template>
  </Card>
</template>

<style scoped>
.feasibility-panel {
  border-left: 3px solid var(--surface-300, #d4d4d8);
}
.feasibility-panel.status-verified {
  border-left-color: #10b981;
}
.feasibility-panel.status-needs-repair {
  border-left-color: #ef4444;
}
.feasibility-panel.status-unverified {
  border-left-color: #f59e0b;
}
.feasibility-malformed,
.feasibility-empty {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--surface-500, #71717a);
}
.feasibility-summary {
  margin-top: 1rem;
}
.summary-cell {
  border-radius: 0.5rem;
  background: var(--surface-50, #fafafa);
  padding: 0.4rem 0.6rem;
}
.summary-cell dt {
  font-size: 0.7rem;
  color: var(--surface-400, #a1a1aa);
}
.summary-cell dd {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--surface-700, #3f3f46);
}
</style>
