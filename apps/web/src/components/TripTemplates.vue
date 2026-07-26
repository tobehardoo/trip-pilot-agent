<script setup lang="ts">
import { CalendarDays, MapPin, Sparkles } from 'lucide-vue-next'

interface TripTemplate {
  id: string
  title: string
  destination: string
  theme: string
  days: number
  places: number
  gradientClass: string
  emoji: string
}

const templates: TripTemplate[] = [
  {
    id: 'tpl-gz',
    title: '广州 City Walk',
    destination: '广州',
    theme: '历史文化探索',
    days: 3,
    places: 6,
    gradientClass: 'dest-gz',
    emoji: '🏙️',
  },
  {
    id: 'tpl-cs',
    title: '长沙美食之旅',
    destination: '长沙',
    theme: '美食探店',
    days: 2,
    places: 8,
    gradientClass: 'dest-cs',
    emoji: '🍜',
  },
  {
    id: 'tpl-hz',
    title: '杭州周末游',
    destination: '杭州',
    theme: '自然休闲',
    days: 3,
    places: 5,
    gradientClass: 'dest-hz',
    emoji: '🌿',
  },
]

defineEmits<{
  select: [template: TripTemplate]
}>()
</script>

<template>
  <section class="mb-10">
    <div class="flex items-center gap-2 mb-5">
      <Sparkles :size="18" class="text-warm-500" aria-hidden="true" />
      <h2 class="text-lg font-bold text-surface-800">快速开始</h2>
      <span class="text-xs text-surface-400 font-medium">选择一个旅行模板快速创建</span>
    </div>

    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      <button
        v-for="tmpl in templates"
        :key="tmpl.id"
        type="button"
        class="group relative h-40 rounded-2xl overflow-hidden text-left shadow-travel-card hover:shadow-travel-card-hover transition-all duration-300 hover:-translate-y-1 active:scale-[0.98]"
        @click="$emit('select', tmpl)"
      >
        <!-- Gradient Background -->
        <div :class="tmpl.gradientClass" class="absolute inset-0" />
        <!-- Dot Pattern -->
        <div class="absolute inset-0 opacity-15 hero-pattern" />
        <!-- Content -->
        <div class="relative z-10 flex flex-col justify-between h-full p-5 text-white">
          <div>
            <span class="text-2xl">{{ tmpl.emoji }}</span>
          </div>
          <div>
            <h3 class="text-lg font-bold">{{ tmpl.title }}</h3>
            <p class="text-sm text-white/80 mt-0.5">{{ tmpl.theme }}</p>
            <div class="flex items-center gap-3 mt-3 text-xs text-white/70">
              <span class="inline-flex items-center gap-1">
                <CalendarDays :size="12" aria-hidden="true" />
                {{ tmpl.days }}天{{ tmpl.days - 1 }}夜
              </span>
              <span class="inline-flex items-center gap-1">
                <MapPin :size="12" aria-hidden="true" />
                {{ tmpl.places }}个推荐地点
              </span>
            </div>
          </div>
        </div>
        <!-- Hover shimmer -->
        <div class="absolute inset-0 bg-white/0 group-hover:bg-white/5 transition-colors duration-300" />
      </button>
    </div>
  </section>
</template>
