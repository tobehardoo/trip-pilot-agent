<script setup lang="ts">
// 设置中心左导航（F-UI-11 P0）。纯展示组件：分组标题 + 分区条目 + 图标；
// 激活态由父级（SettingsPage）传入，条目配方对齐 WorkspaceSidebar（h-7、12px、
// 激活 = tp-active + 2px 内嵌左标记），无彩色块。
import { KeyRound, UserRound } from 'lucide-vue-next'

import { SETTINGS_SECTIONS, type SettingsSectionKey } from './sections'

defineProps<{ active: SettingsSectionKey }>()
const emit = defineEmits<{ navigate: [key: SettingsSectionKey] }>()
</script>

<template>
  <nav aria-label="设置分区">
    <p class="mb-1 px-2 text-[10px] font-medium uppercase tracking-[0.08em] text-tp-mute">基础设置</p>
    <button
      v-for="section in SETTINGS_SECTIONS"
      :key="section.key"
      type="button"
      class="flex h-7 w-full items-center gap-2 rounded px-2 text-xs transition-colors"
      :class="active === section.key ? 'bg-tp-active text-tp-ink' : 'text-tp-sub hover:bg-tp-hover hover:text-tp-ink'"
      :aria-current="active === section.key ? 'page' : undefined"
      :data-testid="`settings-nav-${section.key}`"
      @click="emit('navigate', section.key)"
    >
      <UserRound v-if="section.key === 'general'" :size="13" class="shrink-0 text-tp-sub" aria-hidden="true" />
      <KeyRound v-else :size="13" class="shrink-0 text-tp-sub" aria-hidden="true" />
      {{ section.label }}
    </button>
  </nav>
</template>
