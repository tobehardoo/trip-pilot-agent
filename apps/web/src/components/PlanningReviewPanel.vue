<script setup lang="ts">
import { computed, ref } from 'vue'
import { AlertTriangle, CalendarDays, ChevronDown, Coins, GitCompareArrows, Route, X } from 'lucide-vue-next'

import {
  formatValidatedAt,
  readCandidateItinerary,
  readFeasibilityReport,
  type CandidateItinerary,
  type CandidateTransitLeg,
  type FeasibilityReport,
} from '../lib/feasibility'
import FeasibilityReportPanel from './FeasibilityReportPanel.vue'
import Badge from './ui/Badge.vue'
import Button from './ui/Button.vue'
import Card from './ui/Card.vue'

const props = withDefaults(defineProps<{
  report: FeasibilityReport | null
  malformedReport?: boolean
  candidate: unknown
  abandonBusy?: boolean
  highlightDate?: string | null
  currentItinerary: {
    title: string
    estimatedTotalCost: number
    days: Array<{
      date: string
      activities: Array<{ id?: string | null; title: string }>
      transitLegs?: Array<{
        fromActivityId?: string | null
        toActivityId?: string | null
        mode?: string
        distanceMeters?: number
        durationSeconds?: number
        estimated?: boolean
      }>
    }>
  } | null
}>(), {
  malformedReport: false,
  abandonBusy: false,
  highlightDate: null,
})

const emit = defineEmits<{ abandon: [] }>()

const reportRead = computed(() => readFeasibilityReport(props.report))
const candidateRead = computed(() => readCandidateItinerary(props.candidate))

// B13_FIX R7 (P1-4): validation details are secondary information and stay
// collapsed by default; the candidate and its main risks lead the panel.
const showValidationDetails = ref(false)

// B13_FIX R7 (P1-4): only FAIL/UNKNOWN rules are "main risks" shown up
// front; PASS/NA and technical fields live behind the details toggle.
const mainRisks = computed(() => {
  if (!reportRead.value.ok) return []
  return reportRead.value.value.ruleResults.filter(
    (rule) => rule.outcome === 'FAIL' || rule.outcome === 'UNKNOWN',
  )
})

function formatTime(dateTime: string) {
  const value = new Date(dateTime)
  if (Number.isNaN(value.getTime())) return dateTime
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    timeZone: 'Asia/Shanghai',
  }).format(value)
}

function formatDay(date: string) {
  const [, month, day] = date.split('-')
  return `${Number(month)}月${Number(day)}日`
}

function formatMoney(amount: number) {
  return `¥${amount}`
}

function formatDuration(seconds: number) {
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} 分钟`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest === 0 ? `${hours} 小时` : `${hours} 小时 ${rest} 分`
}

function formatDistance(meters: number) {
  if (meters < 1000) return `${meters} 米`
  return `${(meters / 1000).toFixed(1)} 公里`
}

function modeLabel(mode: string) {
  return {
    WALKING: '步行',
    TRANSIT: '公共交通',
    DRIVING: '驾车',
    TAXI: '出租车',
  }[mode] ?? mode
}

function candidateActivityTitle(day: CandidateItinerary['days'][number], index: number) {
  const activity = day.activities[index]
  return activity ? activity.title : '未知活动'
}

function candidateTransitLabel(day: CandidateItinerary['days'][number], leg: CandidateTransitLeg) {
  const from = candidateActivityTitle(day, leg.fromActivityIndex)
  const to = candidateActivityTitle(day, leg.toActivityIndex)
  const estimate = leg.estimated ? '（估算）' : ''
  return `${from} → ${to} · ${modeLabel(leg.mode)}${estimate} · ${formatDuration(leg.durationSeconds)} · ${formatDistance(leg.distanceMeters)}`
}

function formalActivityTitle(day: NonNullable<typeof props.currentItinerary>['days'][number], id: string | null | undefined) {
  if (!id) return '未知活动'
  const activity = day.activities.find((item) => item.id === id)
  return activity ? activity.title : '未知活动'
}

function formalTransitLabel(
  day: NonNullable<typeof props.currentItinerary>['days'][number],
  leg: NonNullable<NonNullable<typeof props.currentItinerary>['days'][number]['transitLegs']>[number],
) {
  const from = formalActivityTitle(day, leg.fromActivityId)
  const to = formalActivityTitle(day, leg.toActivityId)
  const estimate = leg.estimated ? '（估算）' : ''
  return `${from} → ${to} · ${modeLabel(leg.mode ?? '')}${estimate} · ${formatDuration(leg.durationSeconds ?? 0)} · ${formatDistance(leg.distanceMeters ?? 0)}`
}

function candidateDays(candidate: CandidateItinerary) {
  return candidate.days
}
</script>

<template>
  <Card padding="sm" class="review-panel" aria-label="规划需要确认">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0">
        <p class="text-xs font-semibold uppercase tracking-widest text-amber-600">Review</p>
        <h2 class="mt-1 text-lg font-bold text-surface-800">规划需要确认</h2>
        <p class="mt-0.5 text-sm text-surface-500">候选行程尚未成为正式版本，当前正式版本保持不变。</p>
      </div>
      <Badge variant="warning" size="md">
        <AlertTriangle :size="14" aria-hidden="true" />
        待确认
      </Badge>
    </div>

    <p class="mt-3 text-sm text-surface-600">
      你可以调整约束后重新规划；此界面不会把候选行程写入正式版本。
    </p>

    <!-- Candidate first (B13_FIX R7 / P1-4): the candidate summary, date
         navigation and main risks lead the panel. -->
    <h3 class="mt-3 text-sm font-semibold text-surface-700">候选行程</h3>
    <div v-if="candidateRead.ok" class="mt-2">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <strong class="text-base text-surface-800">{{ candidateRead.value.title }}</strong>
        <span class="inline-flex items-center gap-1 text-sm font-semibold text-surface-600">
          <Coins :size="14" aria-hidden="true" />
          {{ formatMoney(candidateRead.value.estimatedTotalCost) }}
        </span>
      </div>
      <ul class="mt-3 space-y-3">
        <li
          v-for="day in candidateDays(candidateRead.value)"
          :key="day.date"
          :id="`candidate-day-${day.date}`"
          class="rounded-xl border p-3"
          :class="day.date === props.highlightDate
            ? 'border-primary-400 bg-primary-50 ring-1 ring-primary-300'
            : 'border-surface-200/70'"
        >
          <div class="flex items-center gap-2 text-sm">
            <CalendarDays :size="14" class="text-surface-400" aria-hidden="true" />
            <span class="font-semibold text-surface-700">{{ formatDay(day.date) }}</span>
            <span class="text-xs text-surface-400">{{ day.activities.length }} 项活动</span>
          </div>
          <ul class="mt-2 space-y-1">
            <li v-for="activity in day.activities" :key="activity.activityId ?? activity.title" class="flex items-center gap-2 text-sm text-surface-600">
              <span class="text-xs tabular-nums text-surface-400">
                {{ formatTime(activity.startTime) }}–{{ formatTime(activity.endTime) }}
              </span>
              <span class="truncate">{{ activity.title }}</span>
            </li>
          </ul>
          <ul v-if="day.transitLegs.length" class="mt-2 space-y-1 border-t border-surface-200/70 pt-2">
            <li v-for="(leg, legIndex) in day.transitLegs" :key="`${day.date}-leg-${legIndex}`" class="flex items-center gap-2 text-xs text-surface-500">
              <Route :size="13" class="text-surface-400" aria-hidden="true" />
              <span>{{ candidateTransitLabel(day, leg) }}</span>
            </li>
          </ul>
        </li>
      </ul>
      <p v-if="candidateRead.value.days.length === 0" class="text-sm text-surface-400">候选行程暂无日期</p>
    </div>
    <div v-else class="mt-2 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800" role="alert">
      <AlertTriangle :size="16" class="inline" aria-hidden="true" />
      候选行程暂时无法读取，请稍后重试。
    </div>

    <!-- Main risks (B13_FIX R7 / P1-4): only FAIL/UNKNOWN aggregations are
         user-facing; PASS/NA and technical fields stay collapsed. -->
    <h3 class="mt-5 text-sm font-semibold text-surface-700">主要风险</h3>
    <ul v-if="mainRisks.length" class="mt-2 space-y-2">
      <li
        v-for="rule in mainRisks"
        :key="rule.ruleId"
        class="rounded-xl border p-3"
        :class="rule.outcome === 'FAIL' ? 'border-red-200 bg-red-50' : 'border-amber-200 bg-amber-50'"
      >
        <div class="flex flex-wrap items-center gap-2">
          <Badge :variant="rule.outcome === 'FAIL' ? 'danger' : 'warning'">
            {{ rule.outcome === 'FAIL' ? '失败' : '未知' }}
          </Badge>
          <span class="text-sm font-semibold text-surface-800">{{ rule.message }}</span>
        </div>
        <p v-if="rule.affectedDates.length" class="mt-1 text-xs text-surface-500">
          受影响日期：{{ rule.affectedDates.join('、') }}
        </p>
      </li>
    </ul>
    <p v-else class="mt-2 text-sm text-surface-500">
      {{ reportRead.ok ? '未发现主要风险' : '暂无验证结果' }}
    </p>

    <!-- Abandon action: the only user action on a review candidate. -->
    <div class="mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-surface-200/70 p-3">
      <Button
        variant="outline"
        size="sm"
        data-testid="abandon-candidate"
        :disabled="abandonBusy"
        @click="emit('abandon')"
      >
        <X v-if="!abandonBusy" :size="14" aria-hidden="true" />
        {{ abandonBusy ? '正在放弃…' : '放弃候选' }}
      </Button>
      <p class="m-0 text-xs text-surface-500">
        放弃候选不会删除当前正式版本，之后可以调整约束重新规划。
      </p>
    </div>

    <!-- Validation details (B13_FIX R7 / P1-4): collapsed by default;
         reasonCode/validatorVersion/UUIDs live behind the toggle. -->
    <div class="mt-4">
      <button
        type="button"
        class="flex w-full items-center justify-between rounded-xl border border-surface-200/70 bg-surface-50/60 px-4 py-3 text-sm font-semibold text-surface-700 hover:bg-surface-100"
        :aria-expanded="showValidationDetails"
        data-testid="validation-details-toggle"
        @click="showValidationDetails = !showValidationDetails"
      >
        <span>查看验证详情</span>
        <ChevronDown :size="16" class="transition-transform" :class="{ 'rotate-180': showValidationDetails }" aria-hidden="true" />
      </button>
      <div v-if="showValidationDetails" class="mt-3">
        <FeasibilityReportPanel
          v-if="malformedReport"
          :report="null"
          :malformed="true"
        />
        <FeasibilityReportPanel v-else :report="reportRead.ok ? reportRead.value : null" />
      </div>
    </div>

    <!-- Comparison with formal itinerary -->
    <h3 class="mt-5 text-sm font-semibold text-surface-700">与当前正式版本对照</h3>
    <div v-if="currentItinerary" class="mt-2 rounded-xl border border-surface-200/70 p-3">
      <div class="flex items-center gap-2 text-sm">
        <GitCompareArrows :size="14" class="text-surface-400" aria-hidden="true" />
        <span class="font-semibold text-surface-700">{{ currentItinerary.title }}</span>
        <span class="ml-auto text-sm font-semibold text-surface-600">{{ formatMoney(currentItinerary.estimatedTotalCost) }}</span>
      </div>
      <ul class="mt-2 space-y-1">
        <li v-for="day in currentItinerary.days" :key="day.date" class="text-sm text-surface-600">
          <span class="text-xs text-surface-400">{{ formatDay(day.date) }}</span>
          <ul class="ml-4 mt-0.5 list-disc pl-4">
            <li v-for="activity in day.activities" :key="activity.title">{{ activity.title }}</li>
          </ul>
          <ul v-if="day.transitLegs?.length" class="ml-4 mt-0.5 space-y-0.5">
            <li v-for="(leg, legIndex) in day.transitLegs" :key="`formal-${day.date}-leg-${legIndex}`" class="flex items-center gap-2 text-xs text-surface-500">
              <Route :size="13" class="text-surface-400" aria-hidden="true" />
              <span>{{ formalTransitLabel(day, leg) }}</span>
            </li>
          </ul>
        </li>
      </ul>
    </div>
    <p v-else class="mt-2 text-sm text-surface-500">当前尚无正式版本</p>

    <!-- Metadata -->
    <p v-if="reportRead.ok" class="mt-4 border-t border-surface-200/70 pt-3 text-xs text-surface-400">
      验证时间 {{ formatValidatedAt(reportRead.value.validatedAt) }}
    </p>
  </Card>
</template>

<style scoped>
.review-panel {
  border-left: 3px solid #f59e0b;
}
</style>
