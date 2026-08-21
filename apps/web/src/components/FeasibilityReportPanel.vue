<script setup lang="ts">
import { computed } from 'vue'
import { AlertTriangle, BadgeCheck, CircleHelp } from 'lucide-vue-next'

import { readFeasibilityReport, type FeasibilityReport } from '../lib/feasibility'
import Badge from './ui/Badge.vue'
import Card from './ui/Card.vue'

const props = withDefaults(defineProps<{
  report: FeasibilityReport | null
  malformed?: boolean
}>(), {
  malformed: false,
})

const reportRead = computed(() => readFeasibilityReport(props.report))

// B15: this panel is only rendered on the succeeded path.  A VERIFIED report
// shows a plain saved confirmation.  B16 (Information Missing != Planning
// Failed): an UNVERIFIED/NEEDS_REPAIR report that still saved is a
// PASS_WITH_WARNINGS state - the version exists, but some facts (opening
// hours, visit duration, route endpoints) could not be verified.  The panel
// shows the saved confirmation plus an explicit pre-trip verification
// reminder; it never hides that verification is incomplete.
const verified = computed(() => reportRead.value.ok && reportRead.value.value.status === 'VERIFIED')
const savableWithWarnings = computed(() => {
  if (!reportRead.value.ok || reportRead.value.value.status === 'VERIFIED') return false
  const report = reportRead.value.value
  return report.summary.failCount === 0 && report.missingRequiredRuleIds.length === 0
})
</script>

<template>
  <Card class="feasibility-panel" aria-label="行程验证结果">
    <div v-if="malformed" class="feasibility-malformed" role="alert">
      <AlertTriangle :size="18" aria-hidden="true" />
      <div>
        <h3 class="font-semibold text-surface-800">行程验证结果暂时无法读取</h3>
        <p class="text-sm text-surface-500">数据格式异常，无法安全展示。请稍后重试。</p>
      </div>
    </div>

    <div v-else-if="!report" class="feasibility-empty">
      <CircleHelp :size="18" aria-hidden="true" />
      <p class="text-sm text-surface-500">暂无行程验证结果</p>
    </div>

    <template v-else-if="verified">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="min-w-0">
          <h3 class="text-base font-bold text-surface-800">行程已验证并保存</h3>
          <p class="mt-0.5 text-sm text-surface-600">行程已通过全部检查并保存为正式行程。</p>
        </div>
        <Badge variant="success" size="md">
          <BadgeCheck :size="14" aria-hidden="true" />
          已保存
        </Badge>
      </div>
    </template>

    <template v-else-if="savableWithWarnings">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="min-w-0">
          <h3 class="text-base font-bold text-surface-800">行程已生成，部分信息仍待确认</h3>
          <p class="mt-0.5 text-sm text-surface-600">
            行程已保存为正式版本，但部分信息（如营业时间、游玩时长、路线端点）暂未核实。
            出发前请自行确认相关安排。
          </p>
        </div>
        <Badge variant="success" size="md">
          <BadgeCheck :size="14" aria-hidden="true" />
          已保存
        </Badge>
      </div>
    </template>

    <div v-else class="feasibility-empty">
      <CircleHelp :size="18" aria-hidden="true" />
      <p class="text-sm text-surface-500">暂无行程验证结果</p>
    </div>
  </Card>
</template>

<style scoped>
.feasibility-panel {
  border-left: 3px solid #10b981;
}
.feasibility-malformed,
.feasibility-empty {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--surface-500, #71717a);
}
</style>
