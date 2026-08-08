<script setup lang="ts">
import { Pencil, Plus, X } from 'lucide-vue-next'
import type {
  ConstraintDraft,
  FieldMeta,
  StructuredDestination,
  ValueSource,
} from '../lib/constraint-draft'
import CityCascadePicker from './CityCascadePicker.vue'

const props = defineProps<{
  draft: ConstraintDraft
}>()

const emit = defineEmits<{
  edit: [field: string]
  remove: [field: string, value?: string]
  append: [field: string]
  destinationChange: [selection: StructuredDestination]
}>()

function handleDestinationChange(sel: StructuredDestination) {
  emit('destinationChange', sel)
}

function sourceLabel(source: ValueSource): string {
  const map: Record<ValueSource, string> = {
    explicit: '已输入',
    inferred: '已推断',
    default: '默认',
    ambiguous: '需确认',
    unset: '未设置',
  }
  return map[source]
}

function sourceClass(source: ValueSource): string {
  const map: Record<ValueSource, string> = {
    explicit: 'bg-primary-50 text-primary-700',
    inferred: 'bg-amber-50 text-amber-700',
    default: 'bg-surface-100 text-surface-500',
    ambiguous: 'bg-red-50 text-red-600',
    unset: 'bg-surface-50 text-surface-400',
  }
  return map[source]
}

function displayValue(field: FieldMeta<unknown>): string {
  if (field.source === 'unset') return '未设置'
  if (Array.isArray(field.value)) return (field.value as string[]).join('、') || '无'
  if (field.value === null) return '不限'
  return String(field.value)
}
</script>

<template>
  <div class="rounded-2xl border border-surface-200 bg-white p-5">
    <h3 class="m-0 mb-3 text-sm font-bold text-surface-700">已识别的旅行约束</h3>
    <dl class="space-y-2.5">
      <!-- 目的地（级联选择器） -->
      <div class="rounded-lg bg-surface-50 px-3 py-3">
        <dt class="text-xs font-semibold text-surface-500 mb-2">目的地</dt>
        <CityCascadePicker
          :province="(draft.destination.value as any)?.province || ''"
          :city="(draft.destination.value as any)?.city || draft.destination.value as string || ''"
          :districts="(draft.destination.value as any)?.districts || []"
          @change="handleDestinationChange"
        />
      </div>

      <!-- 日期 -->
      <div class="flex items-center justify-between gap-3 rounded-lg bg-surface-50 px-3 py-2">
        <dt class="text-xs font-semibold text-surface-500 shrink-0 w-16">日期</dt>
        <dd class="flex-1 text-sm text-surface-800">
          {{ draft.startDate.value }} ~ {{ draft.endDate.value }}
        </dd>
        <span class="rounded-full px-2 py-0.5 text-[10px] font-medium shrink-0" :class="sourceClass(draft.startDate.source)">
          {{ sourceLabel(draft.startDate.source) }}
        </span>
        <button class="shrink-0 rounded p-1 text-surface-400 hover:text-primary-600 hover:bg-primary-50" title="修改日期" @click="emit('edit', 'startDate')">
          <Pencil :size="13" />
        </button>
      </div>

      <!-- 人数 -->
      <div class="flex items-center justify-between gap-3 rounded-lg bg-surface-50 px-3 py-2">
        <dt class="text-xs font-semibold text-surface-500 shrink-0 w-16">人数</dt>
        <dd class="flex-1 text-sm text-surface-800">{{ draft.travelers.value }} 人</dd>
        <span class="rounded-full px-2 py-0.5 text-[10px] font-medium shrink-0" :class="sourceClass(draft.travelers.source)">
          {{ sourceLabel(draft.travelers.source) }}
        </span>
        <button class="shrink-0 rounded p-1 text-surface-400 hover:text-primary-600 hover:bg-primary-50" title="修改人数" @click="emit('edit', 'travelers')">
          <Pencil :size="13" />
        </button>
      </div>

      <!-- 预算 -->
      <div class="flex items-center justify-between gap-3 rounded-lg bg-surface-50 px-3 py-2">
        <dt class="text-xs font-semibold text-surface-500 shrink-0 w-16">预算</dt>
        <dd class="flex-1 text-sm text-surface-800">{{ displayValue(draft.budgetAmount) }}{{ draft.budgetAmount.value != null ? ' 元' : '' }}</dd>
        <span class="rounded-full px-2 py-0.5 text-[10px] font-medium shrink-0" :class="sourceClass(draft.budgetAmount.source)">
          {{ sourceLabel(draft.budgetAmount.source) }}
        </span>
        <button class="shrink-0 rounded p-1 text-surface-400 hover:text-primary-600 hover:bg-primary-50" title="修改预算" @click="emit('edit', 'budgetAmount')">
          <Pencil :size="13" />
        </button>
      </div>

      <!-- 偏好 -->
      <div class="flex items-center justify-between gap-3 rounded-lg bg-surface-50 px-3 py-2">
        <dt class="text-xs font-semibold text-surface-500 shrink-0 w-16">偏好</dt>
        <dd class="flex-1">
          <span v-if="draft.preferences.value.length === 0" class="text-sm text-surface-400">未设置</span>
          <span v-for="(p, i) in draft.preferences.value" :key="p" class="mr-1.5 inline-flex items-center gap-0.5 rounded-full bg-primary-50 px-2 py-0.5 text-[11px] text-primary-700">
            {{ p }}
            <button class="hover:text-red-500" title="删除" @click="emit('remove', 'preferences', p)">
              <X :size="10" />
            </button>
          </span>
        </dd>
        <button class="shrink-0 rounded p-1 text-surface-400 hover:text-primary-600 hover:bg-primary-50" title="添加偏好" @click="emit('append', 'preferences')">
          <Plus :size="13" />
        </button>
      </div>

      <!-- 必去地点 -->
      <div class="flex items-center justify-between gap-3 rounded-lg bg-surface-50 px-3 py-2">
        <dt class="text-xs font-semibold text-surface-500 shrink-0 w-16">必去</dt>
        <dd class="flex-1">
          <span v-if="draft.mustVisitPlaces.value.length === 0" class="text-sm text-surface-400">未设置</span>
          <span v-for="(p, i) in draft.mustVisitPlaces.value" :key="p" class="mr-1.5 inline-flex items-center gap-0.5 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">
            {{ p }}
            <button class="hover:text-red-500" title="删除" @click="emit('remove', 'mustVisitPlaces', p)">
              <X :size="10" />
            </button>
          </span>
        </dd>
        <button class="shrink-0 rounded p-1 text-surface-400 hover:text-primary-600 hover:bg-primary-50" title="添加必去地点" @click="emit('append', 'mustVisitPlaces')">
          <Plus :size="13" />
        </button>
      </div>

      <!-- 节奏 -->
      <div class="flex items-center justify-between gap-3 rounded-lg bg-surface-50 px-3 py-2">
        <dt class="text-xs font-semibold text-surface-500 shrink-0 w-16">节奏</dt>
        <dd class="flex-1 text-sm text-surface-800">
          {{ { RELAXED: '宽松', BALANCED: '适中', INTENSIVE: '紧凑' }[draft.pace.value as string] || draft.pace.value }}
        </dd>
        <span class="rounded-full px-2 py-0.5 text-[10px] font-medium shrink-0" :class="sourceClass(draft.pace.source)">
          {{ sourceLabel(draft.pace.source) }}
        </span>
        <button class="shrink-0 rounded p-1 text-surface-400 hover:text-primary-600 hover:bg-primary-50" title="修改节奏" @click="emit('edit', 'pace')">
          <Pencil :size="13" />
        </button>
      </div>
    </dl>
  </div>
</template>
