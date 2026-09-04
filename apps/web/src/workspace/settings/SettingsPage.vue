<script setup lang="ts">
// 设置中心页面壳（F-UI-11 P0，方案 A：路由 /workspace/settings 整页替换工作区）。
// 结构：左分组导航（返回工作区 + 分区 + 仅展示用户条）+ 右分区内容。
// 用户条仅展示（D3）：账号管理与退出登录在「常规」分区，不在此重复操作入口。
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft } from 'lucide-vue-next'

import { useTripStore } from '../stores/tripStore'
import { useWorkspaceSession } from '../session'
import SettingsNav from './SettingsNav.vue'
import GeneralSection from './sections/GeneralSection.vue'
import ApiModelsSection from './sections/ApiModelsSection.vue'
import { SETTINGS_SECTIONS, type SettingsSectionKey } from './sections'

const router = useRouter()
const tripStore = useTripStore()
const session = useWorkspaceSession()

const activeSection = ref<SettingsSectionKey>('general')
const sectionMeta = computed(
  () => SETTINGS_SECTIONS.find((s) => s.key === activeSection.value) ?? SETTINGS_SECTIONS[0],
)
const userInitial = computed(() => (session.user?.displayName ?? '设').slice(0, 1))

/** 返回工作区：有选中旅行则回到该旅行，否则回创建模式（保持工作上下文）。 */
function goBack(): void {
  const tripId = tripStore.currentTripId
  void router.push(tripId ? `/workspace/trips/${tripId}` : '/workspace')
}
</script>

<template>
  <div class="flex h-screen min-h-0 overflow-hidden bg-tp-bg" data-testid="settings-page">
    <!-- 左：分组导航 -->
    <aside class="flex w-60 shrink-0 flex-col border-r border-tp-line bg-tp-panel">
      <div class="px-2 pb-1 pt-3">
        <button
          type="button"
          class="flex h-7 w-full items-center gap-2 rounded px-2 text-xs text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
          data-testid="settings-back"
          @click="goBack"
        >
          <ArrowLeft :size="13" aria-hidden="true" /> 返回工作区
        </button>
      </div>

      <div class="px-2 py-2">
        <SettingsNav :active="activeSection" @navigate="activeSection = $event" />
      </div>

      <!-- 用户条：仅展示（D3） -->
      <div class="mt-auto flex items-center gap-2 border-t border-tp-div px-4 py-3">
        <span
          class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-tp-active text-[11px] text-tp-sub"
          aria-hidden="true"
        >{{ userInitial }}</span>
        <div class="min-w-0 flex-1">
          <p class="m-0 truncate text-xs leading-4 text-tp-ink">{{ session.user?.displayName || '未登录' }}</p>
          <p class="m-0 truncate text-[11px] leading-4 text-tp-mute">{{ session.user?.email || '—' }}</p>
        </div>
        <span class="shrink-0 text-[10px] text-tp-faint" title="账号管理在「常规」分区">仅展示</span>
      </div>
    </aside>

    <!-- 右：分区内容 -->
    <main class="min-w-0 flex-1 overflow-y-auto" data-testid="settings-content">
      <!-- 拉伸式布局：内容铺满右栏宽度（无 max-w 居中），与工作台 shell 同一伸缩语义 -->
      <div class="w-full px-8 py-7">
        <header>
          <h1 class="m-0 text-lg font-medium leading-6 text-tp-ink" data-testid="settings-section-title">
            {{ sectionMeta.label }}
          </h1>
          <p class="m-0 mt-1 text-xs leading-4 text-tp-sub">{{ sectionMeta.description }}</p>
        </header>

        <div class="mt-5">
          <GeneralSection v-if="activeSection === 'general'" />
          <ApiModelsSection v-else-if="activeSection === 'api'" />
        </div>
      </div>
    </main>
  </div>
</template>
