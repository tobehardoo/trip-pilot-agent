<script setup lang="ts">
import { computed, ref } from 'vue'
import { AlertTriangle, CalendarDays, ChevronDown, CircleHelp, Coins, Route, X } from 'lucide-vue-next'

import {
  readCandidateItinerary,
  readFeasibilityReport,
  type CandidateDay,
  type CandidateItinerary,
  type FeasibilityReport,
} from '../lib/feasibility'
import { formatChineseDate, formatChineseDateList, ruleIssueSummary } from '../lib/feasibility-presentation'
import { commuteModeLabel } from '../lib/transit'
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

const emit = defineEmits<{ abandon: []; edit: []; verify: [] }>()

const reportRead = computed(() => readFeasibilityReport(props.report))
const candidateRead = computed(() => readCandidateItinerary(props.candidate))

// ── User status truth table (B15) ─────────────────────────────────────────

const userStatus = computed(() => {
  if (props.malformedReport || (props.report !== null && !reportRead.value.ok)) {
    return { title: '暂时无法读取规划结果', badge: '结果异常', tone: 'danger' as const }
  }
  if (reportRead.value.ok) {
    if (reportRead.value.value.status === 'NEEDS_REPAIR') {
      return { title: '方案需要调整', badge: '存在需要处理的问题', tone: 'warning' as const }
    }
    return { title: '方案还需要完善', badge: '部分信息待核实', tone: 'info' as const }
  }
  return { title: '暂时无法读取规划结果', badge: '结果异常', tone: 'danger' as const }
})

const statusDescription = computed(() => {
  if (userStatus.value.title === '方案需要调整') {
    return '当前安排存在冲突，请修改旅行要求后重新规划。'
  }
  if (userStatus.value.title === '方案还需要完善') {
    return '已生成一份预览方案，但部分信息暂时无法核实，因此还不能保存。'
  }
  return '系统无法安全读取本次规划结果，请重新规划。'
})

// ── Issue summaries (UNKNOWN/FAIL only, Chinese, counts from typed refs) ──

const issues = computed(() => {
  if (!reportRead.value.ok) return []
  return reportRead.value.value.ruleResults
    .filter((rule) => rule.outcome === 'FAIL' || rule.outcome === 'UNKNOWN')
    .map((rule) => ruleIssueSummary(rule))
})

const issueTitle = computed(() => {
  if (!reportRead.value.ok) return ''
  const prefix = reportRead.value.value.status === 'NEEDS_REPAIR' ? '需要调整' : '待核实信息'
  return `${prefix}（${issues.value.length}）`
})

const hasEvidenceGaps = computed(() => {
  if (!reportRead.value.ok) return false
  return reportRead.value.value.ruleResults.some((rule) =>
    rule.outcome === 'UNKNOWN'
      && (rule.ruleId === 'OPENING_HOURS' || rule.ruleId === 'VISIT_DURATION'),
  )
})

const showAllIssues = ref(false)
const visibleIssues = computed(() => (showAllIssues.value ? issues.value : issues.value.slice(0, 3)))

// ── Preview plan (collapsible day cards) ──────────────────────────────────

const expandedDays = ref<Set<string>>(new Set())
const expandedLegs = ref<Set<string>>(new Set())

function isDayExpanded(date: string) {
  return expandedDays.value.has(date) || props.highlightDate === date
}

function toggleDay(date: string) {
  const next = new Set(expandedDays.value)
  if (next.has(date)) next.delete(date)
  else next.add(date)
  expandedDays.value = next
}

function isLegExpanded(dayDate: string, index: number) {
  return expandedLegs.value.has(`${dayDate}-${index}`)
}

function toggleLeg(dayDate: string, index: number) {
  const next = new Set(expandedLegs.value)
  const key = `${dayDate}-${index}`
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedLegs.value = next
}

function formatTime(dateTime: string) {
  const value = new Date(dateTime)
  if (Number.isNaN(value.getTime())) return dateTime
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    timeZone: 'Asia/Shanghai',
  }).format(value)
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
  return commuteModeLabel(mode)
}

function dayTimeRange(day: CandidateDay) {
  if (day.activities.length === 0) return ''
  const first = formatTime(day.activities[0].startTime)
  const last = formatTime(day.activities[day.activities.length - 1].endTime)
  return `${first}–${last}`
}

function daySummary(day: CandidateDay) {
  const date = formatChineseDate(day.date)
  const count = `${day.activities.length}项安排`
  const range = dayTimeRange(day)
  return `${date} · ${count} · ${range}`
}

function dayPlaceNames(day: CandidateDay, limit = 2) {
  const names = day.activities.slice(0, limit).map((a) => a.title)
  return names.length === 0 ? '' : names.join('、')
}

function dayTransitSummary(day: CandidateDay) {
  if (day.transitLegs.length === 0) return ''
  const totalSeconds = day.transitLegs.reduce((sum, leg) => sum + leg.durationSeconds, 0)
  return `当天交通：${day.transitLegs.length}段 · 约${formatDuration(totalSeconds)}`
}

function candidateTransitLabel(day: CandidateDay, legIndex: number) {
  const leg = day.transitLegs[legIndex]
  const from = day.activities[leg.fromActivityIndex]?.title ?? '未知地点'
  const to = day.activities[leg.toActivityIndex]?.title ?? '未知地点'
  const estimate = leg.estimated ? '（估算）' : ''
  return `${from} → ${to} · ${modeLabel(leg.mode)}${estimate} · ${formatDuration(leg.durationSeconds)} · ${formatDistance(leg.distanceMeters)}`
}

// ── Saved itinerary comparison (user-readable diffs only) ─────────────────

function savedDayActivityTitles(day: NonNullable<typeof props.currentItinerary>['days'][number]) {
  return day.activities.map((a) => a.title)
}

const comparisonDiffs = computed(() => {
  if (!candidateRead.value.ok || !props.currentItinerary) return []
  const diffs: string[] = []
  const candidateTitles = new Set(
    candidateRead.value.value.days.flatMap((day) => day.activities.map((a) => a.title)),
  )
  const savedTitles = new Set(
    props.currentItinerary.days.flatMap((day) => savedDayActivityTitles(day)),
  )
  let added = 0
  candidateTitles.forEach((title) => {
    if (!savedTitles.has(title)) added += 1
  })
  if (added > 0) diffs.push(`新增${added}个地点`)
  if (candidateRead.value.value.days.length !== props.currentItinerary.days.length) {
    const delta = candidateRead.value.value.days.length - props.currentItinerary.days.length
    diffs.push(delta > 0 ? `增加${delta}天安排` : `减少${Math.abs(delta)}天安排`)
  }
  const candidateTransit = candidateRead.value.value.days.reduce(
    (sum, day) => sum + day.transitLegs.reduce((s, leg) => s + leg.durationSeconds, 0), 0,
  )
  const savedTransit = props.currentItinerary.days.reduce(
    (sum, day) => sum + (day.transitLegs ?? []).reduce((s, leg) => s + (leg.durationSeconds ?? 0), 0), 0,
  )
  const transitDelta = candidateTransit - savedTransit
  if (Math.abs(transitDelta) >= 60) {
    diffs.push(transitDelta > 0
      ? `预计交通时间增加${formatDuration(transitDelta)}`
      : `预计交通时间减少${formatDuration(-transitDelta)}`)
  }
  return diffs
})
</script>

<template>
  <Card padding="sm" class="review-panel" aria-label="规划结果">
    <!-- 1. Status and actions -->
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0">
        <h2 class="text-lg font-bold text-surface-800">{{ userStatus.title }}</h2>
        <p class="mt-1 text-sm text-surface-600">{{ statusDescription }}</p>
      </div>
      <Badge
        :variant="userStatus.tone === 'danger' ? 'danger' : userStatus.tone === 'warning' ? 'warning' : 'secondary'"
        size="md"
      >
        <AlertTriangle v-if="userStatus.tone === 'warning' || userStatus.tone === 'danger'" :size="14" aria-hidden="true" />
        <CircleHelp v-else :size="14" aria-hidden="true" />
        {{ userStatus.badge }}
      </Badge>
    </div>

    <p v-if="reportRead.ok" class="mt-1 text-sm text-surface-500">
      修改并保存要求后，可以重新开始规划。
    </p>

    <div class="mt-4 flex flex-wrap items-center gap-3">
      <Button variant="primary" size="lg" data-testid="edit-requirements" @click="emit('edit')">
        修改要求
      </Button>
      <Button
        variant="outline"
        size="lg"
        data-testid="abandon-candidate"
        :disabled="abandonBusy"
        @click="emit('abandon')"
      >
        <X v-if="!abandonBusy" :size="14" aria-hidden="true" />
        {{ abandonBusy ? '正在放弃…' : '放弃本方案' }}
      </Button>
    </div>

    <!-- 2. Preview plan -->
    <h3 class="mt-6 text-sm font-semibold text-surface-700">预览方案</h3>
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
          v-for="day in candidateRead.value.days"
          :key="day.date"
          :id="`candidate-day-${day.date}`"
          class="rounded-xl border p-3"
          :class="day.date === props.highlightDate
            ? 'border-primary-400 bg-primary-50 ring-1 ring-primary-300'
            : 'border-surface-200/70'"
        >
          <button
            type="button"
            class="flex w-full flex-wrap items-center justify-between gap-2 text-left focus-visible:outline-2 focus-visible:outline-primary-500"
            :aria-expanded="isDayExpanded(day.date)"
            :data-testid="`candidate-day-toggle-${day.date}`"
            @click="toggleDay(day.date)"
            @keydown.enter.prevent="toggleDay(day.date)"
            @keydown.space.prevent="toggleDay(day.date)"
          >
            <span class="flex items-center gap-2 text-sm">
              <CalendarDays :size="14" class="text-surface-400" aria-hidden="true" />
              <span class="font-semibold text-surface-700">{{ daySummary(day) }}</span>
            </span>
            <span class="flex items-center gap-2">
              <span v-if="dayPlaceNames(day)" class="text-xs text-surface-500">{{ dayPlaceNames(day) }}<template v-if="day.activities.length > 2">等</template></span>
              <ChevronDown :size="16" class="text-surface-400 transition-transform" :class="{ 'rotate-180': isDayExpanded(day.date) }" aria-hidden="true" />
            </span>
          </button>
          <p v-if="dayTransitSummary(day)" class="mt-1 text-xs text-surface-500">{{ dayTransitSummary(day) }}</p>

          <div v-if="isDayExpanded(day.date)" class="mt-3 space-y-3">
            <ul class="space-y-2">
              <li v-for="activity in day.activities" :key="activity.activityId ?? activity.title" class="flex flex-wrap items-center gap-2 text-sm text-surface-600">
                <span class="text-xs tabular-nums text-surface-400">
                  {{ formatTime(activity.startTime) }}–{{ formatTime(activity.endTime) }}
                </span>
                <span class="truncate">{{ activity.title }}</span>
                <span v-if="activity.estimatedCost > 0" class="ml-auto text-xs font-semibold text-surface-500">
                  {{ formatMoney(activity.estimatedCost) }}
                </span>
              </li>
            </ul>
            <ul v-if="day.transitLegs.length" class="space-y-2">
              <li
                v-for="(leg, legIndex) in day.transitLegs"
                :key="`${day.date}-leg-${legIndex}`"
                class="rounded-lg border border-surface-200/60"
              >
                <button
                  type="button"
                  class="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-surface-500 focus-visible:outline-2 focus-visible:outline-primary-500"
                  :aria-expanded="isLegExpanded(day.date, legIndex)"
                  :data-testid="`candidate-leg-toggle-${day.date}-${legIndex}`"
                  @click="toggleLeg(day.date, legIndex)"
                >
                  <Route :size="13" class="text-surface-400" aria-hidden="true" />
                  <span class="truncate">{{ modeLabel(leg.mode) }} · {{ formatDuration(leg.durationSeconds) }}</span>
                  <ChevronDown :size="14" class="ml-auto text-surface-400 transition-transform" :class="{ 'rotate-180': isLegExpanded(day.date, legIndex) }" aria-hidden="true" />
                </button>
                <p v-if="isLegExpanded(day.date, legIndex)" class="border-t border-surface-200/60 px-3 py-2 text-xs text-surface-500">
                  {{ candidateTransitLabel(day, legIndex) }}
                </p>
              </li>
            </ul>
          </div>
        </li>
      </ul>
      <p v-if="candidateRead.value.days.length === 0" class="text-sm text-surface-400">预览方案暂无日期</p>
    </div>
    <div v-else class="mt-2 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800" role="alert">
      <AlertTriangle :size="16" class="inline" aria-hidden="true" />
      预览方案暂时无法读取，请稍后重试。
    </div>

    <!-- 3. Issue summary -->
    <div v-if="issues.length" class="mt-6">
      <h3 class="text-sm font-semibold text-surface-700">{{ issueTitle }}</h3>
      <ul class="mt-2 space-y-2">
        <li
          v-for="(issue, index) in visibleIssues"
          :key="`${issue.label}-${index}`"
          :data-testid="`issue-card-${index}`"
          class="rounded-xl border p-3"
          :class="issue.kind === 'fail' ? 'border-red-200 bg-red-50' : 'border-amber-200 bg-amber-50'"
        >
          <div class="flex flex-wrap items-center gap-2">
            <Badge :variant="issue.kind === 'fail' ? 'danger' : 'warning'">
              {{ issue.kind === 'fail' ? '需要调整' : '待核实' }}
            </Badge>
            <span class="text-sm font-semibold text-surface-800">{{ issue.label }}</span>
          </div>
          <p class="mt-1 text-sm text-surface-700">{{ issue.text }}</p>
          <p v-if="issue.dates" class="mt-1 text-xs text-surface-500">{{ issue.dates }}</p>
        </li>
      </ul>
      <button
        v-if="issues.length > 3"
        type="button"
        class="mt-2 text-sm font-semibold text-primary-600 hover:text-primary-700 focus-visible:outline-2"
        @click="showAllIssues = !showAllIssues"
      >
        {{ showAllIssues ? '收起' : `查看全部 ${issues.length} 项` }}
      </button>

      <div
        v-if="hasEvidenceGaps"
        class="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-sky-200 bg-sky-50 p-3"
      >
        <p class="m-0 max-w-2xl text-sm leading-relaxed text-sky-900">
          可先同步城市情报或补充可信攻略，再重新规划；同步不会自动把未核实信息判为通过。
        </p>
        <Button variant="outline" size="sm" data-testid="verify-evidence" @click="emit('verify')">
          去补充核实信息
        </Button>
      </div>
    </div>

    <!-- 4. Saved itinerary -->
    <div class="mt-6">
      <template v-if="currentItinerary">
        <h3 class="text-sm font-semibold text-surface-700">已保存行程</h3>
        <div class="mt-2 rounded-xl border border-surface-200/70 p-3">
          <div class="flex items-center gap-2 text-sm">
            <span class="font-semibold text-surface-700">{{ currentItinerary.title }}</span>
            <span class="ml-auto text-sm font-semibold text-surface-600">{{ formatMoney(currentItinerary.estimatedTotalCost) }}</span>
          </div>
          <div v-if="comparisonDiffs.length" class="mt-2">
            <p class="text-xs font-semibold text-surface-500">与已保存行程相比</p>
            <ul class="mt-1 list-disc pl-4 text-sm text-surface-600">
              <li v-for="diff in comparisonDiffs" :key="diff">{{ diff }}</li>
            </ul>
          </div>
        </div>
      </template>
      <p v-else class="text-sm text-surface-500">方案验证通过后会自动保存为正式行程。</p>
    </div>
  </Card>
</template>

<style scoped>
.review-panel {
  border-left: 3px solid #f59e0b;
}
@media (prefers-reduced-motion: reduce) {
  .review-panel * {
    transition: none !important;
  }
}
</style>
