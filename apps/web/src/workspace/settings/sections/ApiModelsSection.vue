<script setup lang="ts">
// 设置中心 · API 与模型分区（F-UI-11 P0）：4 个 provider 的 Key / Base URL / 模型配置。
// 能力自 WorkspaceSidebar 弹卡等价迁移：读写语义、错误文案、KNOWLEDGE 模型字段全部保留；
// 状态徽标（✓ 已配置 / 未配置）为纯文字色，符合基准状态色预算。
// 主操作按钮 h-12（48px）满足 B15.1 R3 ≥44px 闸口。
import { onMounted } from 'vue'

import { useApiConfigs } from '../useApiConfigs'

const {
  API_PROVIDERS,
  form,
  loading,
  loadError,
  saving,
  message,
  messageTone,
  configured,
  load,
  save,
  clearProvider,
} = useApiConfigs()

onMounted(() => {
  void load()
})
</script>

<template>
  <div data-testid="settings-api">
    <p
      v-if="loadError"
      class="m-0 mb-3 text-xs leading-4 text-tp-warn"
      role="alert"
      data-testid="settings-api-load-error"
    >{{ loadError }}</p>

    <p
      v-if="loading"
      class="m-0 mb-3 flex items-center gap-1.5 text-xs leading-4 text-tp-mute"
      role="status"
      data-testid="settings-api-loading"
    >
      <span class="inline-block h-1.5 w-1.5 rounded-full bg-tp-dot animate-pulse" aria-hidden="true" />
      正在读取配置……
    </p>

    <!-- provider 列表：行式布局 + Divider 分组（基准规则 10：默认 Divider，仅此处允许带边框容器） -->
    <div class="rounded-md border border-tp-line bg-white" data-testid="settings-api-list">
      <section
        v-for="(p, index) in API_PROVIDERS"
        :key="p.key"
        :class="index > 0 ? 'border-t border-tp-div' : ''"
        :data-testid="`settings-provider-${p.key}`"
      >
        <div class="flex items-center gap-2 px-4 pt-3">
          <h3 class="m-0 text-[13px] font-medium text-tp-ink">{{ p.label }}</h3>
          <span class="font-mono text-[11px] text-tp-mute">{{ p.key }}</span>
          <button
            type="button"
            class="rounded px-1.5 py-0.5 text-[11px] text-tp-sub transition-colors hover:bg-tp-hover hover:text-tp-ink"
            :data-testid="`settings-provider-clear-${p.key}`"
            @click="clearProvider(p.key)"
          >清空</button>
          <span
            class="ml-auto text-xs"
            :class="configured[p.key] ? 'text-tp-ok' : 'text-tp-mute'"
            :data-testid="`settings-provider-status-${p.key}`"
          >{{ configured[p.key] ? '✓ 已配置' : '未配置' }}</span>
        </div>

        <div class="grid gap-3 px-4 pb-4 pt-2 sm:grid-cols-2">
          <label class="block">
            <span class="mb-1 block text-[11px] text-tp-mute">API Key</span>
            <input
              v-model="form[p.key].apiKey"
              type="password"
              :placeholder="p.keyPlaceholder"
              class="h-8 w-full rounded border border-tp-line bg-white px-2 font-mono text-xs text-tp-ink outline-none focus:border-tp-sub"
              :data-testid="`settings-provider-key-${p.key}`"
            />
          </label>
          <label class="block">
            <span class="mb-1 block text-[11px] text-tp-mute">Base URL（可选）</span>
            <input
              v-model="form[p.key].apiBaseUrl"
              type="text"
              placeholder="可选"
              class="h-8 w-full rounded border border-tp-line bg-white px-2 font-mono text-xs text-tp-ink outline-none focus:border-tp-sub"
              :data-testid="`settings-provider-baseurl-${p.key}`"
            />
          </label>
          <label v-if="p.showModel" class="block">
            <span class="mb-1 block text-[11px] text-tp-mute">模型</span>
            <input
              v-model="form[p.key].model"
              type="text"
              placeholder="如 text-embedding-v4"
              class="h-8 w-full rounded border border-tp-line bg-white px-2 font-mono text-xs text-tp-ink outline-none focus:border-tp-sub"
              :data-testid="`settings-provider-model-${p.key}`"
            />
          </label>
        </div>
      </section>
    </div>

    <div class="mt-4 flex items-center justify-end gap-3">
      <p
        v-if="message"
        class="m-0 text-xs"
        :class="messageTone === 'error' ? 'text-tp-warn' : 'text-tp-sub'"
        role="status"
        data-testid="settings-api-message"
      >{{ message }}</p>
      <button
        type="button"
        :disabled="saving"
        class="flex h-12 items-center justify-center rounded-md bg-tp-ink px-5 text-[13px] font-medium text-white transition-colors hover:opacity-90 disabled:opacity-50"
        data-testid="settings-api-save"
        @click="save"
      >{{ saving ? '保存中…' : '保存配置' }}</button>
    </div>
  </div>
</template>
