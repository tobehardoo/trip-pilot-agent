<script setup lang="ts">
// 设置中心 · 常规分区（F-UI-11 P0 / D3）：账号信息 + 退出登录。
// 自 WorkspaceSidebar 底部账号区迁移（workspace-settings-logout → settings-general-logout）。
// 退出登录走 session.logout：服务端登出失败也保证本地会话清空（session.ts 既有语义）。
// 主操作按钮 h-12（48px）满足 B15.1 R3 ≥44px 闸口。
import { computed, ref } from 'vue'
import { LogOut } from 'lucide-vue-next'

import { useWorkspaceSession } from '../../session'

const session = useWorkspaceSession()
const user = computed(() => session.user)
const loggingOut = ref(false)

async function logout(): Promise<void> {
  if (loggingOut.value) return
  loggingOut.value = true
  try {
    await session.logout()
  } finally {
    loggingOut.value = false
  }
}
</script>

<template>
  <div data-testid="settings-general">
    <dl class="m-0">
      <div class="flex items-center justify-between gap-4 border-b border-tp-div py-3">
        <dt class="text-[13px] text-tp-sub">昵称</dt>
        <dd class="m-0 truncate text-[13px] text-tp-ink" data-testid="settings-account-name">
          {{ user?.displayName || '未登录' }}
        </dd>
      </div>
      <div class="flex items-center justify-between gap-4 border-b border-tp-div py-3">
        <dt class="text-[13px] text-tp-sub">邮箱</dt>
        <dd class="m-0 truncate font-mono text-xs text-tp-ink" data-testid="settings-account-email">
          {{ user?.email || '—' }}
        </dd>
      </div>
      <div class="flex items-center justify-between gap-4 py-3">
        <dt class="text-[13px] text-tp-sub">用户 ID</dt>
        <dd class="m-0 truncate font-mono text-xs text-tp-ink" data-testid="settings-account-id">
          {{ user?.id || '—' }}
        </dd>
      </div>
    </dl>

    <button
      type="button"
      class="mt-6 flex h-12 items-center justify-center gap-2 rounded-md bg-tp-ink px-5 text-[13px] font-medium text-white transition-colors hover:opacity-90 disabled:opacity-50"
      :disabled="loggingOut"
      data-testid="settings-general-logout"
      @click="logout"
    >
      <LogOut :size="14" aria-hidden="true" />{{ loggingOut ? '退出中…' : '退出登录' }}
    </button>
    <p class="m-0 mt-2 text-[11px] leading-4 text-tp-mute">
      退出后需要重新登录才能继续使用 TripPilot。
    </p>
  </div>
</template>
