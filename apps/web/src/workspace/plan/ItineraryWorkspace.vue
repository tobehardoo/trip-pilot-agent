<script setup lang="ts">
// 旅行方案工作区（F-UI-11 Phase 3+4：真实 Itinerary 数据 + 版本/分享/攻略）。
//
// 信息架构：旅行概览 → 旅行路线（地图）→ 每日行程 → 地点攻略。
// 地图使用 store 中真实的 Itinerary 数据（getCurrentItinerary API）。
import { computed, ref, watch, onMounted } from 'vue'
import { ChevronDown, ChevronRight, Lock, Unlock, Trash2 } from 'lucide-vue-next'

import TripOverview from './TripOverview.vue'
import TripRouteMap from './TripRouteMap.vue'
import ItineraryVersionPanel from '../../components/ItineraryVersionPanel.vue'
import ItineraryActionsPanel from '../../components/ItineraryActionsPanel.vue'
import GuideIntelligencePanel from '../../components/GuideIntelligencePanel.vue'

import { useTripStore } from '../stores/tripStore'
import type { Trip, Itinerary, ItineraryActivity, ItineraryTransitLeg, CreatedItineraryShare, ItineraryVersionDiff, GuideImportInput } from '../../lib/api'
import { formatChinaDate } from '../lib/present'

const props = defineProps<{
  trip: Trip
  itinerary: Itinerary | null
}>()

const tripStore = useTripStore()
const selectedActivityId = ref<string | null>(null)

const itineraryDays = computed(() => props.itinerary?.days ?? [])

// 活动攻略折叠状态
const expandedKeys = ref<string[]>([])

const activityKey = (dayIndex: number, activity: ItineraryActivity) =>
  `${dayIndex}-${activity.startTime}-${activity.title}`

const isExpanded = (dayIndex: number, activity: ItineraryActivity) =>
  expandedKeys.value.includes(activityKey(dayIndex, activity))

const hasGuide = (activity: ItineraryActivity) =>
  Boolean(activity.reason || activity.tips || activity.transportNote || activity.precaution || activity.description)

function toggleGuide(dayIndex: number, activity: ItineraryActivity) {
  const key = activityKey(dayIndex, activity)
  expandedKeys.value = expandedKeys.value.includes(key)
    ? expandedKeys.value.filter((k) => k !== key)
    : [...expandedKeys.value, key]
}

// 加载版本、分享、攻略数据
onMounted(() => {
  if (props.itinerary) {
    void tripStore.loadVersions()
    void tripStore.loadShares()
    void tripStore.loadGuideImports()
  }
})

// 切换旅行时清空地图高亮
watch(() => props.trip.id, () => {
  selectedActivityId.value = null
  if (props.itinerary) {
    void tripStore.loadVersions()
    void tripStore.loadShares()
    void tripStore.loadGuideImports()
  }
})

const currentVersionId = computed(() => props.itinerary?.versionId ?? '')

// ── 活动编辑（Phase 4） ────────────────────────────────────────────
const editingBusy = ref(false)
const confirmDelete = ref<string | null>(null) // activity id

async function toggleLock(activity: ItineraryActivity) {
  if (editingBusy.value || !props.itinerary) return
  editingBusy.value = true
  try {
    await tripStore.applyEdit({
      baseVersionId: props.itinerary.versionId,
      operation: activity.locked ? 'UNLOCK_ACTIVITY' : 'LOCK_ACTIVITY',
      activityId: activity.id,
    }, crypto.randomUUID())
  } catch {
    // 静默失败
  } finally {
    editingBusy.value = false
  }
}

async function deleteActivity(activityId: string) {
  if (editingBusy.value || !props.itinerary) return
  editingBusy.value = true
  confirmDelete.value = null
  try {
    await tripStore.applyEdit({
      baseVersionId: props.itinerary.versionId,
      operation: 'DELETE_ACTIVITY',
      activityId,
    }, crypto.randomUUID())
  } catch {
    // 静默失败
  } finally {
    editingBusy.value = false
  }
}

// 版本管理回调
const getDiff = (from: string, to: string): Promise<ItineraryVersionDiff> => tripStore.diffVersions(from, to)
const rollback = (source: string, expected: string, key: string): Promise<void> => tripStore.rollbackVersion(source, expected, key)

// 分享回调
const createShare = (versionId: string, expiresAt?: string): Promise<CreatedItineraryShare> => tripStore.createShare(versionId, expiresAt)
const revokeShare = (shareId: string): Promise<void> => tripStore.revokeShare(shareId)
const downloadExport = (versionId: string, format: 'ics' | 'pdf'): Promise<void> => tripStore.downloadExport(versionId, format)

// 攻略回调
const importGuide = (input: GuideImportInput): Promise<void> => tripStore.importGuide(input)
const setGuideEnabled = (id: string, enabled: boolean): Promise<void> => tripStore.setGuideEnabled(id, enabled)
</script>

<template>
  <article class="mx-auto flex w-full max-w-3xl flex-col px-6 py-5" aria-label="旅行方案">
    <!-- ① 旅行概览 -->
    <TripOverview :trip="trip" />

    <div class="mt-4 border-t border-tp-div" role="separator" />

    <!-- 完成提示 -->
    <p class="m-0 mt-3 flex gap-2 text-xs leading-5 text-tp-mute" data-testid="agent-message-done">
      <span class="shrink-0 text-tp-ok" aria-hidden="true">✓</span>
      <span>
        旅行方案已经完成，共 {{ itineraryDays.length }} 天的行程。
      </span>
    </p>

    <!-- ② 旅行路线（地图） -->
    <TripRouteMap
      :trip="trip"
      :itinerary="itinerary"
      :selected-activity-id="selectedActivityId"
      @select-activity="selectedActivityId = $event"
    />

    <template v-if="itineraryDays.length > 0">
      <div class="mt-5 border-t border-tp-div" role="separator" />

      <!-- ③ 每日行程 -->
      <section class="mt-4" aria-label="行程">
        <h2 class="m-0 text-[13px] font-medium leading-5 text-tp-ink">行程</h2>

        <section
          v-for="(day, dayIndex) in itineraryDays"
          :key="day.date"
          class="mt-4"
          :aria-label="'第' + (dayIndex + 1) + '天'"
          :data-testid="`plan-day-${dayIndex}`"
        >
          <div class="flex items-baseline justify-between gap-3">
            <h3 class="m-0 text-[13px] font-medium leading-5 text-tp-ink">第{{ dayIndex + 1 }}天</h3>
            <span class="shrink-0 font-mono text-[11px] leading-4 text-tp-mute">
              {{ formatChinaDate(day.date) }}
            </span>
          </div>

          <div class="mt-2 border-t border-tp-div" role="separator" />

          <!-- 活动列表 -->
          <div class="divide-y divide-tp-div" data-testid="plan-day-activities">
            <div
              v-for="(activity, order) in day.activities"
              :key="activityKey(dayIndex, activity)"
              class="flex gap-3 py-2.5"
              :data-testid="`plan-activity-${activity.title}`"
            >
              <!-- 时间列 -->
              <span class="w-10 shrink-0 pt-px font-mono text-xs leading-5 text-tp-mute">{{ activity.startTime }}</span>

              <!-- 内容列 -->
              <div class="min-w-0 flex-1">
                <div class="flex items-start justify-between gap-2">
                  <div class="min-w-0 flex-1">
                    <p class="m-0 text-[13px] font-medium leading-5 text-tp-ink">
                      {{ activity.title }}
                      <span v-if="activity.typeName" class="ml-2 text-[11px] font-normal text-tp-mute">
                        {{ activity.typeName }}
                      </span>
                      <span v-if="activity.locked" class="ml-1.5 inline-flex items-center text-tp-mute" title="已锁定">
                        <Lock :size="10" aria-hidden="true" />
                      </span>
                    </p>
                  </div>
                  <!-- 编辑按钮 -->
                  <div class="flex shrink-0 items-center gap-1">
                    <button
                      type="button"
                      :disabled="editingBusy"
                      class="flex h-6 w-6 items-center justify-center rounded text-tp-faint transition-colors hover:bg-tp-hover hover:text-tp-ink disabled:opacity-30"
                      :title="activity.locked ? '解锁' : '锁定'"
                      :data-testid="`activity-${activity.locked ? 'unlock' : 'lock'}-${activity.title}`"
                      @click="toggleLock(activity)"
                    >
                      <component :is="activity.locked ? Unlock : Lock" :size="12" aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      :disabled="editingBusy"
                      class="flex h-6 w-6 items-center justify-center rounded text-tp-faint transition-colors hover:bg-tp-warn/10 hover:text-tp-warn disabled:opacity-30"
                      :title="'删除活动'"
                      :data-testid="`activity-delete-${activity.title}`"
                      @click="confirmDelete = activity.id"
                    >
                      <Trash2 :size="12" aria-hidden="true" />
                    </button>
                  </div>
                </div>
                <p v-if="activity.description" class="m-0 mt-0.5 text-xs leading-5 text-tp-body">
                  {{ activity.description }}
                </p>

                <!-- 攻略折叠 -->
                <button
                  v-if="hasGuide(activity)"
                  type="button"
                  class="mt-1.5 flex h-6 items-center gap-1 rounded px-1 text-[11px] text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
                  :aria-expanded="isExpanded(dayIndex, activity)"
                  :data-testid="`activity-guide-toggle-${activity.title}`"
                  @click="toggleGuide(dayIndex, activity)"
                >
                  <component
                    :is="isExpanded(dayIndex, activity) ? ChevronDown : ChevronRight"
                    :size="12"
                    aria-hidden="true"
                  />
                  {{ isExpanded(dayIndex, activity) ? '收起攻略' : '查看攻略' }}
                </button>

                <dl v-if="isExpanded(dayIndex, activity)" class="m-0 mt-1 space-y-0.5">
                  <div v-if="activity.reason" class="flex gap-2">
                    <dt class="m-0 shrink-0 text-xs leading-5 text-tp-faint">推荐理由</dt>
                    <dd class="m-0 text-xs leading-5 text-tp-body">{{ activity.reason }}</dd>
                  </div>
                  <div v-if="activity.tips" class="flex gap-2">
                    <dt class="m-0 shrink-0 text-xs leading-5 text-tp-faint">游览建议</dt>
                    <dd class="m-0 text-xs leading-5 text-tp-body">{{ activity.tips }}</dd>
                  </div>
                  <div v-if="activity.transportNote" class="flex gap-2">
                    <dt class="m-0 shrink-0 text-xs leading-5 text-tp-faint">交通</dt>
                    <dd class="m-0 text-xs leading-5 text-tp-body">{{ activity.transportNote }}</dd>
                  </div>
                  <div v-if="activity.precaution" class="flex gap-2">
                    <dt class="m-0 shrink-0 text-xs leading-5 text-tp-faint">注意事项</dt>
                    <dd class="m-0 text-xs leading-5 text-tp-warn">{{ activity.precaution }}</dd>
                  </div>
                </dl>
              </div>
              <!-- 删除确认 -->
              <div
                v-if="confirmDelete === activity.id"
                class="flex items-center gap-2 pt-1"
              >
                <span class="text-[11px] leading-4 text-tp-warn">确定删除此活动？</span>
                <button
                  type="button"
                  :disabled="editingBusy"
                  class="flex h-6 items-center rounded bg-tp-warn px-2 text-[11px] font-medium text-white disabled:opacity-50"
                  @click="deleteActivity(activity.id)"
                >删除</button>
                <button
                  type="button"
                  :disabled="editingBusy"
                  class="flex h-6 items-center rounded bg-tp-hover px-2 text-[11px] text-tp-sub disabled:opacity-50"
                  @click="confirmDelete = null"
                >取消</button>
              </div>
            </div>
          </div>
        </section>
      </section>
    </template>

    <!-- ④ 版本管理 -->
    <div v-if="itinerary" class="mt-6 border-t border-tp-div" role="separator" />
    <ItineraryVersionPanel
      v-if="itinerary"
      :versions="tripStore.versions"
      :current-version-id="currentVersionId"
      :busy="false"
      :error="null"
      :get-diff="getDiff"
      :rollback="rollback"
    />

    <!-- ⑤ 分享与导出 -->
    <div v-if="itinerary" class="mt-6 border-t border-tp-div" role="separator" />
    <ItineraryActionsPanel
      v-if="itinerary"
      :version-id="currentVersionId"
      :shares="tripStore.shares"
      :create-share="createShare"
      :revoke-share="revokeShare"
      :download="downloadExport"
    />

    <!-- ⑥ 攻略情报 -->
    <div v-if="itinerary" class="mt-6 border-t border-tp-div" role="separator" />
    <GuideIntelligencePanel
      v-if="itinerary"
      :guide-imports="tripStore.guideImports"
      :destination="trip.destination"
      :start-date="trip.startDate"
      :end-date="trip.endDate"
      :itinerary="itinerary"
      :busy="tripStore.guideImportBusy"
      :error="tripStore.guideImportError"
      :import-guide="importGuide"
      :set-guide-enabled="setGuideEnabled"
    />
  </article>
</template>