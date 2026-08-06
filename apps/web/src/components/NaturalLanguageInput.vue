<script setup lang="ts">
import { ref } from 'vue'
import { Sparkles } from 'lucide-vue-next'
import type { ParseResult } from '../lib/constraint-parser'

defineProps<{
  warnings: ParseResult['warnings']
  unrecognized: string[]
}>()

const emit = defineEmits<{
  parse: [text: string]
}>()

const inputText = ref('')
const placeholder = '例如：下周末去广州，两个人，预算 3000，喜欢历史文化'

function handleSubmit() {
  const text = inputText.value.trim()
  if (text) {
    emit('parse', text)
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSubmit()
  }
}
</script>

<template>
  <div class="space-y-3">
    <label class="text-xs font-semibold text-surface-600">用一句话描述旅行计划</label>
    <div class="flex gap-2.5">
      <textarea
        v-model="inputText"
        :placeholder="placeholder"
        rows="2"
        maxlength="500"
        class="flex-1 resize-none rounded-xl border border-surface-200 bg-surface-50 px-4 py-3 text-sm text-surface-800 placeholder:text-surface-400 focus:border-primary-400 focus:outline-none focus:ring-2 focus:ring-primary-100"
        @keydown="handleKeydown"
      />
      <button
        class="shrink-0 self-end rounded-xl bg-primary-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-40 flex items-center gap-1.5"
        :disabled="!inputText.trim()"
        @click="handleSubmit"
      >
        <Sparkles :size="15" />
        解析
      </button>
    </div>

    <!-- 反馈区 -->
    <div v-if="warnings.length > 0" class="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700 space-y-1">
      <p v-for="(w, i) in warnings" :key="i">{{ w.message }}</p>
    </div>
    <div v-if="unrecognized.length > 0" class="text-xs text-surface-400">
      以下内容暂未识别，可以直接点击卡片编辑：{{ unrecognized.join('；') }}
    </div>
  </div>
</template>
