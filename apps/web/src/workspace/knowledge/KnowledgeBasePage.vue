<script setup lang="ts">
// 知识库管理页：文档列表（关键词过滤）+ 语义检索 + 详情 + 删除 + 粘贴正文导入。
// 数据来自 travel-server /api/knowledge/*；写入走 demo 嵌入链路，属全局城市攻略储备。
import { computed, onMounted, ref } from 'vue'
import {
  Database,
  FileText as FileTextIcon,
  Image as ImageIcon,
  Link as LinkIcon,
  LoaderCircle,
  Plus,
  Search as SearchIcon,
  Trash2,
  Upload as UploadIcon,
  X as XIcon,
} from 'lucide-vue-next'

import {
  deleteKnowledgeDocument,
  deleteKnowledgeDocuments,
  fileToGuideImage,
  getKnowledgeDocument,
  importKnowledgeDocument,
  listKnowledgeDocuments,
  searchKnowledge,
  updateKnowledgeDocument,
  type GuideImageInput,
  type KnowledgeCitation,
  type KnowledgeDetail,
  type KnowledgeDocumentSummary,
} from '../../lib/api'
import { useAuthStore } from '../../app/stores/auth'
import { useWorkspaceSession } from '../session'
import Drawer from '../../components/ui/Drawer.vue'

const auth = useAuthStore()
const session = useWorkspaceSession()

type Mode = 'list' | 'search'
const mode = ref<Mode>('list')

const documents = ref<KnowledgeDocumentSummary[]>([])
const citations = ref<KnowledgeCitation[]>([])
const keyword = ref('')
const searchQuery = ref('')
const loading = ref(false)
const error = ref<string | null>(null)

// 分页
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

// 编辑
const editOpen = ref(false)
const editTarget = ref<KnowledgeDocumentSummary | null>(null)
const editSubmitting = ref(false)
const editError = ref<string | null>(null)
const editForm = ref({
  category: 'poi' as string,
  contentType: '' as string,
  regionProvince: '',
  regionCity: '',
  regionDistrict: '',
  sourceName: '',
  content: '',
})

// 批量删除
const manageMode = ref(false)
const selectedIds = ref<string[]>([])

const detail = ref<KnowledgeDetail | null>(null)
const detailOpen = ref(false)
const confirmDeleteId = ref<string | null>(null)

const importOpen = ref(false)
const importSubmitting = ref(false)
const importError = ref<string | null>(null)
const importSource = ref<'paste' | 'image' | 'video'>('paste')
const importForm = ref({
  city: '',
  category: 'poi' as string,
  title: '',
  content: '',
  sourceUrl: '',
  sourceName: '',
  contentType: '' as string,
  regionProvince: '',
  regionCity: '',
  regionDistrict: '',
})
const imageFiles = ref<{ name: string; payload: GuideImageInput }[]>([])

const IMPORT_SOURCES = [
  { value: 'paste', label: '粘贴正文', hint: '复制攻略可读正文，直接入库并生成向量。' },
  { value: 'image', label: '图片识别', hint: '上传攻略截图（PNG/JPEG/WEBP，最多 5 张），自动 OCR 提取正文。' },
  { value: 'video', label: '视频链接', hint: '粘贴抖音或小红书视频/笔记分享链接，尝试抓取简介正文。' },
] as const

function platformOf(url: string): 'DOUYIN_VIDEO' | 'XIAOHONGSHU_VIDEO' | null {
  const u = url.trim().toLowerCase()
  if (u.includes('douyin.com') || u.includes('www.iesdouyin.com')) return 'DOUYIN_VIDEO'
  if (u.includes('xiaohongshu.com') || u.includes('xhslink.com')) return 'XIAOHONGSHU_VIDEO'
  return null
}

const detectedPlatformLabel = computed(() =>
  importSource.value === 'video' && platformOf(importForm.value.sourceUrl) === 'DOUYIN_VIDEO'
    ? '抖音'
    : importSource.value === 'video' && platformOf(importForm.value.sourceUrl) === 'XIAOHONGSHU_VIDEO'
      ? '小红书'
      : null,
)

async function onPickImages(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? []).slice(0, 5)
  input.value = ''
  importError.value = null
  if (files.length === 0) return
  try {
    imageFiles.value = await Promise.all(files.map(async (f) => ({ name: f.name, payload: await fileToGuideImage(f) })))
  } catch {
    importError.value = '读取图片失败，请重新选择截图'
  }
}

function removeImage(index: number) {
  imageFiles.value.splice(index, 1)
}

const CATEGORIES = [
  { value: 'poi', label: '景点' },
  { value: 'food', label: '美食' },
  { value: 'accommodation', label: '住宿' },
  { value: 'culture', label: '人文' },
  { value: 'season', label: '季节' },
  { value: 'theme', label: '主题' },
  { value: 'travel_tip', label: '出行贴士' },
]

const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(CATEGORIES.map((c) => [c.value, c.label]))
const CONTENT_TYPES = [
  { value: '', label: '自动归类' },
  { value: 'attraction', label: '景点' },
  { value: 'hotel', label: '酒店/住宿' },
  { value: 'restaurant', label: '餐饮/饭馆' },
  { value: 'transport', label: '交通' },
  { value: 'itinerary', label: '行程' },
  { value: 'culture', label: '人文' },
  { value: 'tip', label: '贴士' },
]
const CONTENT_TYPE_LABEL: Record<string, string> = Object.fromEntries(
  CONTENT_TYPES.filter((c) => c.value).map((c) => [c.value, c.label]))
const RELIABILITY_LABEL: Record<string, string> = {
  OFFICIAL: '官方',
  CURATED: '整理',
  COMMUNITY: '社区',
}

function regionLabel(p: string, cty: string, d: string) {
  const parts = [p, cty, d].filter(Boolean)
  return parts.join('·') || '未标注'
}

function fmt(value: string) {
  return new Date(value).toLocaleString('zh-CN')
}

async function loadList() {
  loading.value = true
  error.value = null
  try {
    const result = await session.withAccessToken((token) =>
      listKnowledgeDocuments(token, { keyword: keyword.value || undefined, page: page.value, size: pageSize.value }))
    documents.value = result.items
    total.value = result.total
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '读取知识库失败'
  } finally {
    loading.value = false
  }
}

async function gotoPage(p: number) {
  page.value = Math.max(1, p)
  await loadList()
}

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

function toggleManage() {
  manageMode.value = !manageMode.value
  selectedIds.value = []
}

function toggleSelect(id: string) {
  selectedIds.value = selectedIds.value.includes(id)
    ? selectedIds.value.filter((x) => x !== id)
    : [...selectedIds.value, id]
}

const allSelected = computed(() =>
  documents.value.length > 0 && documents.value.every((d) => selectedIds.value.includes(d.documentId)))

function toggleSelectAll() {
  selectedIds.value = allSelected.value
    ? []
    : documents.value.map((d) => d.documentId)
}

async function confirmBatchDelete() {
  if (!selectedIds.value.length || manageMode.value === false) return
  try {
    await session.withAccessToken((token) => deleteKnowledgeDocuments(token, selectedIds.value))
    selectedIds.value = []
    manageMode.value = false
    await loadList()
  } catch {
    error.value = '批量删除失败，请稍后重试'
  }
}

function openEdit(doc: KnowledgeDocumentSummary) {
  editTarget.value = doc
  editForm.value = {
    category: doc.category,
    contentType: doc.contentType ?? '',
    regionProvince: doc.regionProvince ?? '',
    regionCity: doc.regionCity ?? '',
    regionDistrict: doc.regionDistrict ?? '',
    sourceName: doc.sourceName ?? '',
    content: doc.content,
  }
  editError.value = null
  editOpen.value = true
}

async function confirmEdit() {
  const doc = editTarget.value
  if (!doc) return
  editSubmitting.value = true
  editError.value = null
  try {
    await session.withAccessToken((token) => updateKnowledgeDocument(token, doc.documentId, {
      category: editForm.value.category,
      contentType: editForm.value.contentType || undefined,
      regionProvince: editForm.value.regionProvince.trim() || undefined,
      regionCity: editForm.value.regionCity.trim() || undefined,
      regionDistrict: editForm.value.regionDistrict.trim() || undefined,
      sourceName: editForm.value.sourceName.trim() || undefined,
      content: editForm.value.content.trim() || undefined,
    }))
    editOpen.value = false
    if (detail.value?.document.documentId === doc.documentId) {
      detail.value = null
      detailOpen.value = false
    }
    await loadList()
  } catch (cause) {
    editError.value = cause instanceof Error ? cause.message : '保存失败，请稍后重试'
  } finally {
    editSubmitting.value = false
  }
}

async function runSearch() {
  loading.value = true
  error.value = null
  try {
    citations.value = await session.withAccessToken((token) =>
      searchKnowledge(token, searchQuery.value.trim(), { limit: 20 }))
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '检索知识库失败'
  } finally {
    loading.value = false
  }
}

async function switchMode(next: Mode) {
  mode.value = next
  error.value = null
  if (next === 'list') await loadList()
  else if (searchQuery.value) await runSearch()
}

async function openDetail(documentId: string) {
  try {
    detail.value = await session.withAccessToken((token) => getKnowledgeDocument(token, documentId))
    detailOpen.value = true
  } catch {
    error.value = '无法读取文档详情'
  }
}

async function confirmDelete(documentId: string) {
  confirmDeleteId.value = null
  try {
    await session.withAccessToken((token) => deleteKnowledgeDocument(token, documentId))
    documents.value = documents.value.filter((d) => d.documentId !== documentId)
    if (detail.value?.document.documentId === documentId) detailOpen.value = false
  } catch {
    error.value = '删除失败，请稍后重试'
  }
}

async function submitImport() {
  if (!importForm.value.city.trim()) {
    importError.value = '请填写目的地'
    return
  }
  const sourceType: 'PASTE_TEXT' | 'IMAGE_OCR' | 'DOUYIN_VIDEO' | 'XIAOHONGSHU_VIDEO' | undefined =
    importSource.value === 'image' ? 'IMAGE_OCR'
    : importSource.value === 'video' ? (platformOf(importForm.value.sourceUrl) ?? undefined)
    : undefined

  if (importSource.value === 'paste') {
    if (!importForm.value.title.trim() || !importForm.value.content.trim()) {
      importError.value = '请填写标题和正文'
      return
    }
  }
  if (importSource.value === 'image' && imageFiles.value.length === 0) {
    importError.value = '请至少选择一张攻略截图'
    return
  }
  if (importSource.value === 'video') {
    if (!importForm.value.sourceUrl.trim()) {
      importError.value = '请粘贴抖音或小红书分享链接'
      return
    }
    if (!sourceType) {
      importError.value = '暂只支持抖音或小红书链接，请改用「粘贴正文」导入'
      return
    }
  }

  importSubmitting.value = true
  importError.value = null
  const form = importForm.value
  const input = {
    city: form.city.trim(),
    category: form.category,
    title: form.title.trim() || undefined,
    content: importSource.value === 'paste' ? form.content.trim() : undefined,
    sourceUrl: form.sourceUrl.trim() || undefined,
    sourceName: form.sourceName.trim() || undefined,
    sourceType,
    contentType: form.contentType || undefined,
    regionProvince: form.regionProvince.trim() || undefined,
    regionCity: form.regionCity.trim() || undefined,
    regionDistrict: form.regionDistrict.trim() || undefined,
    images: importSource.value === 'image' ? imageFiles.value.map((f) => f.payload) : undefined,
  }
  try {
    await session.withAccessToken((token) => importKnowledgeDocument(token, input))
    importOpen.value = false
    importForm.value = { city: '', category: 'poi', title: '', content: '', sourceUrl: '', sourceName: '', contentType: '', regionProvince: '', regionCity: '', regionDistrict: '' }
    imageFiles.value = []
    await loadList()
  } catch (cause) {
    importError.value = cause instanceof Error ? cause.message : '导入失败，请稍后重试'
  } finally {
    importSubmitting.value = false
  }
}

onMounted(loadList)
</script>

<template>
  <div class="mx-auto flex w-full max-w-4xl flex-col px-6 py-6">
    <!-- 头部：标题 + 模式切换 + 导入 -->
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="flex items-center gap-2.5">
        <Database :size="18" class="text-tp-mute" aria-hidden="true" />
        <div>
          <h1 class="m-0 text-lg font-bold leading-6 text-tp-ink">知识库</h1>
          <p class="m-0 text-xs leading-4 text-tp-mute">全局城市攻略储备，规划时作为有依据的知识引用</p>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <div class="flex gap-1 rounded-lg border border-tp-line bg-tp-panel p-1" role="group" aria-label="知识库视图">
          <button
            type="button"
            class="rounded-md px-2.5 py-1 text-xs font-medium transition-colors"
            :class="mode === 'list' ? 'bg-tp-ink text-white' : 'bg-white text-tp-body'"
            data-testid="kb-mode-list"
            @click="switchMode('list')"
          >文档</button>
          <button
            type="button"
            class="rounded-md px-2.5 py-1 text-xs font-medium transition-colors"
            :class="mode === 'search' ? 'bg-tp-ink text-white' : 'bg-white text-tp-body'"
            data-testid="kb-mode-search"
            @click="switchMode('search')"
          >检索</button>
        </div>
        <button
          v-if="mode === 'list' && documents.length"
          type="button"
          class="flex h-8 items-center rounded-lg border border-tp-line bg-white px-3 text-xs font-medium text-tp-sub transition-colors hover:border-tp-sub/50"
          :data-testid="manageMode ? 'kb-manage-done' : 'kb-manage-toggle'"
          @click="toggleManage"
        >{{ manageMode ? '完成' : '选择' }}</button>
        <button
          type="button"
          class="flex h-8 items-center gap-1.5 rounded-lg bg-tp-ink px-3 text-xs font-semibold text-white hover:opacity-90"
          data-testid="kb-import-open"
          @click="importOpen = true"
        >
          <Plus :size="14" aria-hidden="true" />导入
        </button>
      </div>
    </div>

    <!-- 搜索/检索输入 -->
    <div class="relative mt-4">
      <SearchIcon :size="14" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-tp-mute" aria-hidden="true" />
      <input
        v-if="mode === 'list'"
        v-model="keyword"
        type="text"
        placeholder="按标题 / 目的地 / 内容过滤"
        class="h-9 w-full rounded-lg border border-tp-line bg-white pl-9 pr-3 text-sm text-tp-ink outline-none focus:border-tp-sub"
        data-testid="kb-keyword"
        @input="loadList"
      />
      <div v-else class="flex gap-2">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="输入语义描述，检索最相关的知识分块，如：适合老人慢游的景点"
          class="h-9 w-full rounded-lg border border-tp-line bg-white pl-9 pr-3 text-sm text-tp-ink outline-none focus:border-tp-sub"
          data-testid="kb-search-query"
          @keydown.enter="runSearch"
        />
        <button
          type="button"
          class="h-9 rounded-lg bg-tp-ink px-4 text-xs font-semibold text-white hover:opacity-90"
          data-testid="kb-search-run"
          @click="runSearch"
        >检索</button>
      </div>
    </div>

    <p v-if="error" class="mt-3 text-xs text-tp-warn" role="alert" data-testid="kb-error">{{ error }}</p>
    <p v-if="loading" class="mt-3 flex items-center gap-1.5 text-xs text-tp-mute" role="status">
      <LoaderCircle class="animate-spin" :size="13" aria-hidden="true" />加载中…
    </p>

    <!-- 列表 -->
    <template v-if="mode === 'list'">
      <p v-if="!loading && documents.length === 0" class="mt-6 rounded-xl border-2 border-dashed border-tp-line px-4 py-10 text-center text-sm text-tp-sub" data-testid="kb-empty">
        知识库还没有文档，点击上方「导入」粘贴一篇攻略正文。已有文档默认来自 V1 官方源。
      </p>
      <template v-else>
        <!-- 批量工具条 -->
        <div v-if="manageMode" class="mt-4 flex items-center justify-between gap-2 rounded-lg border border-tp-line bg-white px-2.5 py-1.5" data-testid="kb-manage-bar">
          <button type="button" class="rounded px-1.5 py-0.5 text-[11px] font-medium text-tp-sub transition-colors hover:bg-tp-hover" @click="toggleSelectAll">{{ allSelected ? '取消全选' : '全选' }}</button>
          <span class="text-[11px] text-tp-mute">已选 {{ selectedIds.length }}</span>
          <button type="button" :disabled="!selectedIds.length" class="flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium text-tp-warn transition-colors hover:bg-tp-warn/10 disabled:opacity-40" data-testid="kb-manage-delete" @click="confirmBatchDelete"><Trash2 :size="11" aria-hidden="true" />删除</button>
        </div>

        <ul class="mt-4 space-y-2 p-0" aria-label="知识文档">
          <li
            v-for="doc in documents"
            :key="doc.documentId"
            class="rounded-xl border border-tp-line bg-white p-3.5 transition-colors hover:border-tp-sub/50"
            data-testid="kb-doc-row"
          >
            <div class="flex items-start justify-between gap-3">
              <button
                v-if="manageMode"
                type="button"
                class="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border border-tp-line transition-colors"
                :class="selectedIds.includes(doc.documentId) ? 'border-tp-ink bg-tp-ink text-white' : 'bg-white text-transparent'"
                :aria-pressed="selectedIds.includes(doc.documentId)"
                :data-testid="`kb-check-${doc.documentId}`"
                @click="toggleSelect(doc.documentId)"
              ><span class="text-[10px] leading-none">✓</span></button>
              <button type="button" :disabled="manageMode" class="min-w-0 flex-1 text-left" data-testid="kb-doc-open" @click="openDetail(doc.documentId)">
                <p class="m-0 truncate text-sm font-medium text-tp-ink">{{ doc.title }}</p>
                <p class="mt-0.5 m-0 text-[11px] text-tp-mute">
                  {{ regionLabel(doc.regionProvince ?? '', doc.regionCity ?? '', doc.regionDistrict ?? '') }}
                  · {{ CONTENT_TYPE_LABEL[doc.contentType ?? ''] ?? '未分板块' }}
                  · {{ CATEGORY_LABEL[doc.category] ?? doc.category }}
                  · {{ RELIABILITY_LABEL[doc.reliabilityLevel] ?? doc.reliabilityLevel }}
                  · V{{ doc.version }} · {{ doc.chunkCount }} 分块 · {{ fmt(doc.collectedAt) }}
                </p>
              </button>
              <div class="flex shrink-0 items-center gap-1">
                <button
                  v-if="!manageMode"
                  type="button"
                  class="hidden h-7 w-7 shrink-0 items-center justify-center rounded text-tp-faint transition-colors hover:bg-tp-hover hover:text-tp-ink group-hover:flex"
                  :title="'编辑文档'"
                  :data-testid="`kb-edit-${doc.documentId}`"
                  @click="openEdit(doc)"
                ><FileTextIcon :size="14" aria-hidden="true" /></button>
                <button
                  v-if="!manageMode"
                  type="button"
                  class="hidden h-7 w-7 shrink-0 items-center justify-center rounded text-tp-faint transition-colors hover:bg-tp-warn/10 hover:text-tp-warn group-hover:flex"
                  :title="'删除文档'"
                  :data-testid="`kb-delete-${doc.documentId}`"
                  @click="confirmDeleteId = doc.documentId"
                ><Trash2 :size="14" aria-hidden="true" /></button>
              </div>
            </div>
            <p v-if="doc.content" class="mt-1.5 m-0 line-clamp-2 text-xs leading-5 text-tp-body">{{ doc.content }}</p>
            <div v-if="confirmDeleteId === doc.documentId" class="mt-2 flex items-center gap-2 rounded-lg bg-tp-warn/10 px-2.5 py-2" data-testid="kb-delete-confirm">
              <span class="text-xs text-tp-warn">确定删除「{{ doc.title }}」？该文档所有版本和向量会被移除。</span>
              <button type="button" class="rounded bg-tp-warn px-2 py-1 text-[11px] font-medium text-white" @click="confirmDelete(doc.documentId)">删除</button>
              <button type="button" class="rounded bg-white px-2 py-1 text-[11px] text-tp-sub" @click="confirmDeleteId = null">取消</button>
            </div>
          </li>
        </ul>

        <!-- 分页 -->
        <div v-if="total > pageSize" class="mt-4 flex items-center justify-between gap-2 text-xs text-tp-mute" data-testid="kb-pagination">
          <span>共 {{ total }} 篇</span>
          <div class="flex items-center gap-1">
            <button type="button" :disabled="page <= 1" class="rounded border border-tp-line bg-white px-2.5 py-1 transition-colors hover:border-tp-sub/50 disabled:opacity-40" data-testid="kb-page-prev" @click="gotoPage(page - 1)">上一页</button>
            <span class="px-1">第 {{ page }} / {{ totalPages }} 页</span>
            <button type="button" :disabled="page >= totalPages" class="rounded border border-tp-line bg-white px-2.5 py-1 transition-colors hover:border-tp-sub/50 disabled:opacity-40" data-testid="kb-page-next" @click="gotoPage(page + 1)">下一页</button>
          </div>
        </div>
      </template>
    </template>

    <!-- 语义检索结果 -->
    <template v-else>
      <ul v-if="!loading && citations.length" class="mt-4 space-y-2 p-0" aria-label="检索结果">
        <li v-for="c in citations" :key="c.chunkId" class="rounded-xl border border-tp-line bg-white p-3.5" data-testid="kb-citation">
          <div class="flex items-center justify-between gap-2">
            <p class="m-0 truncate text-sm font-medium text-tp-ink">{{ c.title }}</p>
            <span class="shrink-0 rounded-full bg-tp-active px-2 py-0.5 text-[10px] font-semibold text-tp-sub">
              {{ Math.round(c.similarity * 100) }}%
            </span>
          </div>
          <p class="mt-1 m-0 text-[11px] text-tp-mute">
            {{ c.city }} · {{ CONTENT_TYPE_LABEL[c.contentType ?? ''] ?? '未分板块' }}
            · {{ CATEGORY_LABEL[c.category] ?? c.category }}
            {{ c.regionCity || c.regionDistrict ? `· ${regionLabel('', c.regionCity ?? '', c.regionDistrict ?? '')}` : '' }}
          </p>
          <p class="mt-1.5 m-0 text-xs leading-5 text-tp-body">{{ c.content }}</p>
        </li>
      </ul>
      <p v-else-if="!loading" class="mt-6 rounded-xl border-2 border-dashed border-tp-line px-4 py-10 text-center text-sm text-tp-sub">
        输入描述执行检索，或先导入一些文档。
      </p>
    </template>

    <!-- 详情抽屉 -->
    <Drawer
      :open="detailOpen"
      :title="detail?.document.title ?? '文档详情'"
      description="仅展示知识文档与其分块原文。"
      width="lg"
      @close="detailOpen = false"
    >
      <template v-if="detail">
        <dl class="m-0 grid gap-x-4 gap-y-2 sm:grid-cols-2">
          <div><dt class="text-[11px] text-tp-mute">目的地</dt><dd class="m-0 text-sm text-tp-ink">{{ detail.document.city }}</dd></div>
          <div><dt class="text-[11px] text-tp-mute">地区</dt><dd class="m-0 text-sm text-tp-ink">{{ regionLabel(detail.document.regionProvince ?? '', detail.document.regionCity ?? '', detail.document.regionDistrict ?? '') }}</dd></div>
          <div><dt class="text-[11px] text-tp-mute">板块</dt><dd class="m-0 text-sm text-tp-ink">{{ CONTENT_TYPE_LABEL[detail.document.contentType ?? ''] ?? '未分板块' }}</dd></div>
          <div><dt class="text-[11px] text-tp-mute">类别</dt><dd class="m-0 text-sm text-tp-ink">{{ CATEGORY_LABEL[detail.document.category] ?? detail.document.category }}</dd></div>
          <div><dt class="text-[11px] text-tp-mute">版本</dt><dd class="m-0 text-sm text-tp-ink">V{{ detail.document.version }}</dd></div>
          <div><dt class="text-[11px] text-tp-mute">可靠级别</dt><dd class="m-0 text-sm text-tp-ink">{{ RELIABILITY_LABEL[detail.document.reliabilityLevel] ?? detail.document.reliabilityLevel }}</dd></div>
          <div class="sm:col-span-2"><dt class="text-[11px] text-tp-mute">来源</dt><dd class="m-0 break-all text-sm text-tp-ink">{{ detail.document.sourceUrl || '—' }}</dd></div>
        </dl>
        <p class="mt-4 mb-2 text-xs font-semibold text-tp-mute">分块原文（{{ detail.chunks.length }}）</p>
        <ol class="m-0 space-y-2 p-0 list-none">
          <li v-for="chunk in detail.chunks" :key="chunk.chunkId" class="rounded-lg bg-tp-panel px-3 py-2.5">
            <p class="m-0 text-xs leading-relaxed text-tp-body">{{ chunk.content }}</p>
          </li>
        </ol>
      </template>
    </Drawer>

    <!-- 导入抽屉 -->
    <Drawer :open="importOpen" title="导入攻略" description="把攻略文本、截图或抖音/小红书视频链接收入知识库并生成向量，供规划检索引用。" width="md" @close="importOpen = false">
      <div class="space-y-3">
        <!-- 来源方式 -->
        <div class="grid grid-cols-3 gap-1.5" role="group" aria-label="导入来源">
          <button
            v-for="s in IMPORT_SOURCES"
            :key="s.value"
            type="button"
            class="rounded-lg border px-2 py-2 text-center transition-colors"
            :class="importSource === s.value ? 'border-tp-sub bg-tp-active' : 'border-tp-line bg-white hover:border-tp-sub/50'"
            :data-testid="`kb-import-src-${s.value}`"
            @click="importSource = s.value"
          >
            <span class="flex items-center justify-center gap-1.5">
              <FileTextIcon v-if="s.value === 'paste'" :size="14" class="text-tp-sub" aria-hidden="true" />
              <ImageIcon v-else-if="s.value === 'image'" :size="14" class="text-tp-sub" aria-hidden="true" />
              <LinkIcon v-else :size="14" class="text-tp-sub" aria-hidden="true" />
              <span class="text-xs font-medium text-tp-ink">{{ s.label }}</span>
            </span>
          </button>
        </div>
        <p class="m-0 text-[11px] text-tp-mute">{{ IMPORT_SOURCES.find((s) => s.value === importSource)?.hint }}</p>

        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block">
            <span class="mb-1 block text-xs font-semibold text-tp-body">目的地</span>
            <input v-model="importForm.city" type="text" placeholder="如：广州" class="h-9 w-full rounded-lg border border-tp-line bg-white px-3 text-sm outline-none focus:border-tp-sub" data-testid="kb-import-city" />
          </label>
          <label class="block">
            <span class="mb-1 block text-xs font-semibold text-tp-body">类别</span>
            <select v-model="importForm.category" class="h-9 w-full rounded-lg border border-tp-line bg-white px-3 text-sm" data-testid="kb-import-category">
              <option v-for="c in CATEGORIES" :key="c.value" :value="c.value">{{ c.label }}</option>
            </select>
          </label>
        </div>

        <!-- 两轴元数据：地区(省/市/区) + 板块(自动/覆盖) -->
        <div class="grid gap-3 sm:grid-cols-3">
          <label class="block">
            <span class="mb-1 block text-xs font-semibold text-tp-body">省（可选）</span>
            <input v-model="importForm.regionProvince" type="text" placeholder="如：广东省" class="h-9 w-full rounded-lg border border-tp-line bg-white px-3 text-sm outline-none focus:border-tp-sub" data-testid="kb-import-region-province" />
          </label>
          <label class="block">
            <span class="mb-1 block text-xs font-semibold text-tp-body">市（可选，默认=目的地）</span>
            <input v-model="importForm.regionCity" type="text" placeholder="如：广州市" class="h-9 w-full rounded-lg border border-tp-line bg-white px-3 text-sm outline-none focus:border-tp-sub" data-testid="kb-import-region-city" />
          </label>
          <label class="block">
            <span class="mb-1 block text-xs font-semibold text-tp-body">区（可选，可自动识别）</span>
            <input v-model="importForm.regionDistrict" type="text" placeholder="如：越秀区" class="h-9 w-full rounded-lg border border-tp-line bg-white px-3 text-sm outline-none focus:border-tp-sub" data-testid="kb-import-region-district" />
          </label>
        </div>
        <label class="block">
          <span class="mb-1 block text-xs font-semibold text-tp-body">板块（默认自动归类）</span>
          <select v-model="importForm.contentType" class="h-9 w-full rounded-lg border border-tp-line bg-white px-3 text-sm" data-testid="kb-import-content-type">
            <option v-for="c in CONTENT_TYPES" :key="c.value" :value="c.value">{{ c.label }}</option>
          </select>
        </label>

        <!-- 粘贴正文：标题 + 正文 -->
        <template v-if="importSource === 'paste'">
          <label class="block">
            <span class="mb-1 block text-xs font-semibold text-tp-body">标题</span>
            <input v-model="importForm.title" type="text" placeholder="如：广州两日游攻略" class="h-9 w-full rounded-lg border border-tp-line bg-white px-3 text-sm outline-none focus:border-tp-sub" data-testid="kb-import-title" />
          </label>
          <label class="block">
            <span class="mb-1 block text-xs font-semibold text-tp-body">正文</span>
            <textarea v-model="importForm.content" rows="6" placeholder="粘贴包含景点、门票、开放时间、交通、预约等内容的正文…" class="w-full rounded-lg border border-tp-line bg-white px-3 py-2 text-sm leading-relaxed outline-none focus:border-tp-sub" data-testid="kb-import-content" />
          </label>
        </template>

        <!-- 图片识别：选择截图 -->
        <template v-if="importSource === 'image'">
          <label class="block">
            <span class="mb-1 block text-xs font-semibold text-tp-body">标题（可选，自动根据图片生成）</span>
            <input v-model="importForm.title" type="text" placeholder="如：广州白云山攻略" class="h-9 w-full rounded-lg border border-tp-line bg-white px-3 text-sm outline-none focus:border-tp-sub" data-testid="kb-import-img-title" />
          </label>
          <div class="rounded-lg border border-dashed border-tp-line bg-tp-panel p-3">
            <p class="m-0 mb-2 text-[11px] text-tp-mute">攻略截图（{{ imageFiles.length }}/5，PNG / JPEG / WEBP）</p>
            <label class="flex h-9 cursor-pointer items-center justify-center gap-1.5 rounded-lg border border-tp-line bg-white text-xs font-semibold text-tp-body hover:border-tp-sub/50">
              <UploadIcon :size="14" aria-hidden="true" />选择图片
              <input type="file" accept="image/png,image/jpeg,image/webp" multiple class="sr-only" data-testid="kb-import-images" @change="onPickImages" />
            </label>
            <ul v-if="imageFiles.length" class="mt-2 space-y-1 p-0">
              <li v-for="(img, i) in imageFiles" :key="i" class="flex items-center gap-2 rounded bg-white px-2 py-1.5 text-xs text-tp-body">
                <ImageIcon :size="13" class="shrink-0 text-tp-mute" aria-hidden="true" />
                <span class="min-w-0 flex-1 truncate">{{ img.name }}</span>
                <button type="button" class="rounded p-0.5 text-tp-faint hover:text-tp-warn" :aria-label="`移除 ${img.name}`" @click="removeImage(i)">
                  <XIcon :size="12" aria-hidden="true" />
                </button>
              </li>
            </ul>
          </div>
        </template>

        <!-- 视频链接 -->
        <template v-if="importSource === 'video'">
          <label class="block">
            <span class="mb-1 block text-xs font-semibold text-tp-body">视频/笔记链接</span>
            <input v-model="importForm.sourceUrl" type="url" placeholder="粘贴抖音或小红书分享链接…" class="h-9 w-full rounded-lg border border-tp-line bg-white px-3 text-sm outline-none focus:border-tp-sub" data-testid="kb-import-url" />
            <span v-if="detectedPlatformLabel" class="mt-1 inline-block rounded-full bg-tp-active px-2 py-0.5 text-[10px] font-semibold text-tp-sub">
              已识别：{{ detectedPlatformLabel }}
            </span>
          </label>
          <label class="block">
            <span class="mb-1 block text-xs font-semibold text-tp-body">标题（可选，自动根据内容生成）</span>
            <input v-model="importForm.title" type="text" placeholder="如：珠海长隆攻略" class="h-9 w-full rounded-lg border border-tp-line bg-white px-3 text-sm outline-none focus:border-tp-sub" data-testid="kb-import-video-title" />
          </label>
        </template>

        <label class="block" v-if="importSource !== 'paste'">
          <span class="mb-1 block text-xs font-semibold text-tp-body">来源（可选）</span>
          <input v-model="importForm.sourceName" type="text" :placeholder="importSource === 'image' ? '如：博主截图' : '如：抖音攻略账号'" class="h-9 w-full rounded-lg border border-tp-line bg-white px-3 text-sm outline-none focus:border-tp-sub" data-testid="kb-import-source" />
        </label>

        <p v-if="importError" class="m-0 text-xs text-tp-warn" role="alert">{{ importError }}</p>
        <button
          type="button"
          :disabled="importSubmitting"
          class="flex h-9 w-full items-center justify-center gap-1.5 rounded-lg bg-tp-ink text-sm font-semibold text-white disabled:opacity-50"
          data-testid="kb-import-submit"
          @click="submitImport"
        >
          <LoaderCircle v-if="importSubmitting" class="animate-spin" :size="14" aria-hidden="true" />
          <Plus v-else :size="14" aria-hidden="true" />{{ importSubmitting ? '导入中…' : '导入知识库' }}
        </button>
      </div>
    </Drawer>

    <!-- 编辑抽屉 -->
    <Drawer :open="editOpen" :title="`编辑文档「${editTarget?.title ?? ''}」`" description="修改元数据（地区/板块/类别等）；正文有改动会重新分块并重新嵌入。" width="md" @close="editOpen = false">
      <div class="space-y-3">
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block">
            <span class="mb-1 block text-xs font-semibold text-tp-body">类别</span>
            <select v-model="editForm.category" class="h-9 w-full rounded-lg border border-tp-line bg-white px-3 text-sm">
              <option v-for="c in CATEGORIES" :key="c.value" :value="c.value">{{ c.label }}</option>
            </select>
          </label>
          <label class="block">
            <span class="mb-1 block text-xs font-semibold text-tp-body">板块</span>
            <select v-model="editForm.contentType" class="h-9 w-full rounded-lg border border-tp-line bg-white px-3 text-sm">
              <option v-for="c in CONTENT_TYPES" :key="c.value" :value="c.value">{{ c.label }}</option>
            </select>
          </label>
        </div>
        <div class="grid gap-3 sm:grid-cols-3">
          <label class="block"><span class="mb-1 block text-xs font-semibold text-tp-body">省</span>
            <input v-model="editForm.regionProvince" type="text" class="h-9 w-full rounded-lg border border-tp-line bg-white px-3 text-sm outline-none focus:border-tp-sub" /></label>
          <label class="block"><span class="mb-1 block text-xs font-semibold text-tp-body">市</span>
            <input v-model="editForm.regionCity" type="text" class="h-9 w-full rounded-lg border border-tp-line bg-white px-3 text-sm outline-none focus:border-tp-sub" /></label>
          <label class="block"><span class="mb-1 block text-xs font-semibold text-tp-body">区</span>
            <input v-model="editForm.regionDistrict" type="text" class="h-9 w-full rounded-lg border border-tp-line bg-white px-3 text-sm outline-none focus:border-tp-sub" /></label>
        </div>
        <label class="block"><span class="mb-1 block text-xs font-semibold text-tp-body">来源名（可选）</span>
          <input v-model="editForm.sourceName" type="text" class="h-9 w-full rounded-lg border border-tp-line bg-white px-3 text-sm outline-none focus:border-tp-sub" /></label>
        <label class="block"><span class="mb-1 block text-xs font-semibold text-tp-body">正文（留空则不改）</span>
          <textarea v-model="editForm.content" rows="6" class="w-full rounded-lg border border-tp-line bg-white px-3 py-2 text-sm leading-relaxed outline-none focus:border-tp-sub" data-testid="kb-edit-content" /></label>
        <p v-if="editError" class="m-0 text-xs text-tp-warn" role="alert">{{ editError }}</p>
        <button type="button" :disabled="editSubmitting" class="flex h-9 w-full items-center justify-center gap-1.5 rounded-lg bg-tp-ink text-sm font-semibold text-white disabled:opacity-50" data-testid="kb-edit-save" @click="confirmEdit">
          <LoaderCircle v-if="editSubmitting" class="animate-spin" :size="14" aria-hidden="true" />
          <FileTextIcon v-else :size="14" aria-hidden="true" />{{ editSubmitting ? '保存中…' : '保存' }}
        </button>
      </div>
    </Drawer>
  </div>
</template>