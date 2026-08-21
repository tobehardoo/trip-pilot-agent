<script setup lang="ts">
import { Compass, LoaderCircle, LockKeyhole, LogIn, Mail, UserPlus } from 'lucide-vue-next'
import { ref } from 'vue'

export interface AuthSubmission {
  mode: 'login' | 'register'
  email: string
  password: string
  displayName: string
}

defineProps<{
  busy: boolean
  error: string | null
}>()

const emit = defineEmits<{
  submit: [submission: AuthSubmission]
}>()

const mode = ref<'login' | 'register'>('login')
const email = ref('')
const password = ref('')
const displayName = ref('')

function switchMode(nextMode: 'login' | 'register') {
  mode.value = nextMode
}

function submit() {
  emit('submit', {
    mode: mode.value,
    email: email.value,
    password: password.value,
    displayName: displayName.value,
  })
}
</script>

<template>
  <main class="min-h-screen grid grid-cols-1 md:grid-cols-[0.9fr_1.1fr]">
    <!-- Brand Panel -->
    <section
      class="relative flex flex-col min-h-[180px] md:min-h-screen p-6 md:p-11 overflow-hidden text-white bg-gradient-to-br from-primary-800 via-primary-900 to-primary-950"
      aria-label="TripPilot"
    >
      <!-- Grid pattern overlay -->
      <div
        class="absolute inset-0 opacity-[0.04]"
        style="background-image: linear-gradient(rgb(255 255 255 / 0.6) 1px, transparent 1px), linear-gradient(90deg, rgb(255 255 255 / 0.6) 1px, transparent 1px); background-size: 42px 42px;"
        aria-hidden="true"
      />

      <!-- Decorative circle -->
      <div class="absolute -right-28 bottom-24 w-96 h-96 rounded-full border border-primary-400/30" aria-hidden="true" />

      <div class="relative z-10">
        <div class="flex h-12 w-12 items-center justify-center rounded-xl bg-primary-500 text-white shadow-lg mb-5">
          <Compass :size="28" stroke-width="2" aria-hidden="true" />
        </div>
        <p class="text-3xl sm:text-4xl md:text-5xl font-extrabold tracking-tight leading-none m-0">TripPilot</p>
        <p class="mt-3 text-sm sm:text-base text-primary-200/80 m-0">旅行规划工作台</p>
      </div>

      <!-- Route dots -->
      <div class="relative z-10 mt-auto hidden md:flex items-center justify-between w-4/5 max-w-xs pt-0 border-t border-dashed border-white/40">
        <span class="w-2.5 h-2.5 -mt-1.5 rounded-full bg-primary-400 border-2 border-primary-900 outline outline-1 outline-primary-400" />
        <span class="w-2.5 h-2.5 -mt-1.5 rounded-full bg-primary-400 border-2 border-primary-900 outline outline-1 outline-primary-400" />
        <span class="w-2.5 h-2.5 -mt-1.5 rounded-full bg-primary-400 border-2 border-primary-900 outline outline-1 outline-primary-400" />
      </div>
      <p class="relative z-10 mt-4 hidden md:block text-xs font-semibold text-primary-300/70 m-0">广州 · 北纬 23°</p>
    </section>

    <!-- Auth Panel -->
    <section class="grid place-items-center p-8 md:p-10">
      <form class="w-full max-w-[410px]" @submit.prevent="submit">
        <div class="mb-8">
          <p class="text-xs font-semibold uppercase tracking-widest text-primary-500 mb-2 m-0">
            {{ mode === 'login' ? '欢迎回来' : '开始规划' }}
          </p>
          <h1 class="text-2xl sm:text-3xl font-bold text-surface-900 tracking-tight m-0">
            {{ mode === 'login' ? '登录 TripPilot' : '创建 TripPilot 账户' }}
          </h1>
        </div>

        <!-- Display Name (register only) -->
        <div v-if="mode === 'register'" class="mb-4">
          <label for="display-name" class="block text-sm font-semibold text-surface-700 mb-1.5">显示名称</label>
          <div class="flex items-center gap-2.5 h-11 rounded-xl border border-surface-200 bg-white px-3.5 focus-within:ring-2 focus-within:ring-primary-400/40 focus-within:border-primary-400 transition-shadow text-surface-400">
            <UserPlus :size="17" aria-hidden="true" />
            <input id="display-name" v-model.trim="displayName" autocomplete="name" maxlength="80" required
              class="min-w-0 flex-1 border-0 bg-transparent text-surface-800 outline-0 text-sm font-medium placeholder:text-surface-300" />
          </div>
        </div>

        <!-- Email -->
        <div class="mb-4">
          <label for="email" class="block text-sm font-semibold text-surface-700 mb-1.5">邮箱</label>
          <div class="flex items-center gap-2.5 h-11 rounded-xl border border-surface-200 bg-white px-3.5 focus-within:ring-2 focus-within:ring-primary-400/40 focus-within:border-primary-400 transition-shadow text-surface-400">
            <Mail :size="17" aria-hidden="true" />
            <input id="email" v-model.trim="email" type="email" autocomplete="email" maxlength="254" required
              class="min-w-0 flex-1 border-0 bg-transparent text-surface-800 outline-0 text-sm font-medium placeholder:text-surface-300" />
          </div>
        </div>

        <!-- Password -->
        <div class="mb-1">
          <label for="password" class="block text-sm font-semibold text-surface-700 mb-1.5">密码</label>
          <div class="flex items-center gap-2.5 h-11 rounded-xl border border-surface-200 bg-white px-3.5 focus-within:ring-2 focus-within:ring-primary-400/40 focus-within:border-primary-400 transition-shadow text-surface-400">
            <LockKeyhole :size="17" aria-hidden="true" />
            <input
              id="password"
              v-model="password"
              type="password"
              :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
              minlength="10"
              maxlength="72"
              required
              class="min-w-0 flex-1 border-0 bg-transparent text-surface-800 outline-0 text-sm font-medium placeholder:text-surface-300"
            />
          </div>
          <span v-if="mode === 'register'" class="block mt-1.5 text-xs text-surface-400">至少 10 个字符</span>
        </div>

        <!-- Error -->
        <p v-if="error" class="mt-4 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700 border-l-4 border-red-400" role="alert">{{ error }}</p>

        <!-- Submit -->
        <button
          class="mt-5 w-full h-11 inline-flex items-center justify-center gap-2 rounded-xl bg-primary-600 text-white text-sm font-semibold hover:bg-primary-700 active:scale-[0.98] transition-all duration-200 disabled:opacity-50 disabled:cursor-wait shadow-sm"
          type="submit"
          :disabled="busy"
        >
          <LoaderCircle v-if="busy" class="animate-spin" :size="17" aria-hidden="true" />
          <LogIn v-else-if="mode === 'login'" :size="17" aria-hidden="true" />
          <UserPlus v-else :size="17" aria-hidden="true" />
          {{ mode === 'login' ? '登录' : '创建账户并登录' }}
        </button>

        <!-- Mode Switch -->
        <div class="flex justify-center gap-1.5 mt-5 text-sm text-surface-500">
          <span>{{ mode === 'login' ? '还没有账户？' : '已有账户？' }}</span>
          <button type="button" class="font-semibold text-primary-600 hover:text-primary-700 p-0 bg-transparent border-0 cursor-pointer" @click="switchMode(mode === 'login' ? 'register' : 'login')">
            {{ mode === 'login' ? '创建账户' : '返回登录' }}
          </button>
        </div>
      </form>
    </section>
  </main>
</template>
