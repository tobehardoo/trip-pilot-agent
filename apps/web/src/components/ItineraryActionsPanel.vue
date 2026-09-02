<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import Button from './ui/Button.vue'

export interface ItineraryShareStatus {
  id: string
  versionId: string
  expiresAt: string | null
  revokedAt: string | null
  createdAt: string
}

export interface CreatedItineraryShare extends ItineraryShareStatus {
  shareToken: string
}

const props = defineProps<{
  versionId: string
  shares: ItineraryShareStatus[]
  createShare: (versionId: string, expiresAt?: string) => Promise<CreatedItineraryShare>
  revokeShare: (shareId: string) => Promise<void>
  download: (versionId: string, format: 'ics' | 'pdf') => Promise<void>
}>()

const localShares = ref<ItineraryShareStatus[]>([])
const latestShareUrl = ref<string | null>(null)
const busyAction = ref<string | null>(null)
const error = ref<string | null>(null)

watch(() => props.shares, (shares) => {
  localShares.value = [...shares]
}, { immediate: true })

const activeShares = computed(() => localShares.value.filter((share) => !share.revokedAt))

function shareUrl(token: string) {
  return `${window.location.origin}/share/${encodeURIComponent(token)}`
}

async function create() {
  busyAction.value = 'share'
  error.value = null
  try {
    const created = await props.createShare(props.versionId, undefined)
    localShares.value = [created, ...localShares.value.filter((share) => share.id !== created.id)]
    latestShareUrl.value = shareUrl(created.shareToken)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '无法创建分享链接'
  } finally {
    busyAction.value = null
  }
}

async function revoke(shareId: string) {
  busyAction.value = `revoke-${shareId}`
  error.value = null
  try {
    await props.revokeShare(shareId)
    localShares.value = localShares.value.map((share) => (
      share.id === shareId ? { ...share, revokedAt: new Date().toISOString() } : share
    ))
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '无法撤销分享链接'
  } finally {
    busyAction.value = null
  }
}

async function exportItinerary(format: 'ics' | 'pdf') {
  busyAction.value = format
  error.value = null
  try {
    await props.download(props.versionId, format)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '导出失败'
  } finally {
    busyAction.value = null
  }
}

async function copyUrl() {
  if (!latestShareUrl.value || !navigator.clipboard) return
  await navigator.clipboard.writeText(latestShareUrl.value)
}
</script>

<template>
  <section class="space-y-4" aria-label="行程分享与导出">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h3 class="m-0 text-[13px] font-medium leading-5 text-tp-ink">分享与导出</h3>
        <p class="mt-1 text-xs leading-5 text-tp-sub">分享固定版本，导出当前选择的行程版本。</p>
      </div>
      <div class="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" :loading="busyAction === 'ics'" data-testid="export-ics" @click="exportItinerary('ics')">
          导出日历
        </Button>
        <Button size="sm" variant="outline" :loading="busyAction === 'pdf'" data-testid="export-pdf" @click="exportItinerary('pdf')">
          导出 PDF
        </Button>
        <Button size="sm" :loading="busyAction === 'share'" data-testid="create-itinerary-share" @click="create">
          创建只读链接
        </Button>
      </div>
    </div>

    <p v-if="error" class="mt-3 text-xs leading-5 text-tp-warn" role="alert">{{ error }}</p>

    <div v-if="latestShareUrl" class="mt-3 flex flex-wrap items-center gap-2 rounded-lg bg-tp-panel px-3 py-2 text-xs">
      <a :href="latestShareUrl" target="_blank" rel="noreferrer" class="min-w-0 flex-1 break-all text-tp-ink underline" data-testid="share-url">
        {{ latestShareUrl }}
      </a>
      <Button size="sm" variant="ghost" aria-label="复制分享链接" title="复制分享链接" @click="copyUrl">复制</Button>
    </div>

    <ul v-if="activeShares.length" class="mt-3 space-y-2 p-0" aria-label="活跃分享链接">
      <li v-for="share in activeShares" :key="share.id" class="flex items-center justify-between gap-3 text-xs leading-5 text-tp-body">
        <span>创建于 {{ new Date(share.createdAt).toLocaleString('zh-CN') }}</span>
        <Button
          size="sm"
          variant="ghost"
          :loading="busyAction === `revoke-${share.id}`"
          :data-testid="`revoke-share-${share.id}`"
          @click="revoke(share.id)"
        >
          撤销
        </Button>
      </li>
    </ul>
  </section>
</template>
