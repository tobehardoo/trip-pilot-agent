<script setup lang="ts">
// 登录/注册页（F-UI-11：Workspace 风格，tp-* 设计令牌）。
// 极简居中卡片，无渐变、无大圆角、无彩色强调。
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
  <main class="flex min-h-screen items-center justify-center bg-tp-bg">
    <div class="flex w-full max-w-[400px] flex-col px-6">
      <!-- Logo + 品牌 -->
      <div class="mb-8 flex items-center gap-2.5">
        <div class="flex h-8 w-8 items-center justify-center rounded border border-tp-line bg-tp-panel text-tp-sub">
          <Compass :size="16" stroke-width="1.5" aria-hidden="true" />
        </div>
        <div>
          <p class="m-0 text-sm font-medium leading-5 text-tp-ink">TripPilot</p>
          <p class="m-0 text-[11px] leading-4 text-tp-mute">旅行规划工作台</p>
        </div>
      </div>

      <!-- 标题 -->
      <h1 class="m-0 text-base font-semibold leading-6 text-tp-ink">
        {{ mode === 'login' ? '登录' : '创建账户' }}
      </h1>
      <p class="m-0 mt-1 text-xs leading-4 text-tp-sub">
        {{ mode === 'login' ? '欢迎回来，登录后继续你的旅行规划。' : '创建一个账户开始规划你的旅行。' }}
      </p>

      <!-- 表单 -->
      <form class="mt-6 space-y-4" @submit.prevent="submit">
        <!-- Display Name (register only) -->
        <div v-if="mode === 'register'">
          <label for="display-name" class="mb-1 block text-[11px] font-medium leading-4 text-tp-sub">显示名称</label>
          <div class="flex items-center gap-2 rounded border border-tp-line bg-tp-panel px-2.5 text-tp-mute focus-within:border-tp-ink">
            <UserPlus :size="14" aria-hidden="true" />
            <input id="display-name" v-model.trim="displayName" autocomplete="name" maxlength="80" required
              class="h-8 min-w-0 flex-1 border-0 bg-transparent text-xs text-tp-ink outline-0 placeholder:text-tp-faint" />
          </div>
        </div>

        <!-- Email -->
        <div>
          <label for="email" class="mb-1 block text-[11px] font-medium leading-4 text-tp-sub">邮箱 / 用户名</label>
          <div class="flex items-center gap-2 rounded border border-tp-line bg-tp-panel px-2.5 text-tp-mute focus-within:border-tp-ink">
            <Mail :size="14" aria-hidden="true" />
            <input id="email" v-model.trim="email" type="text" inputmode="email" autocomplete="username" maxlength="254" required
              class="h-8 min-w-0 flex-1 border-0 bg-transparent text-xs text-tp-ink outline-0 placeholder:text-tp-faint" />
          </div>
        </div>

        <!-- Password -->
        <div>
          <label for="password" class="mb-1 block text-[11px] font-medium leading-4 text-tp-sub">密码</label>
          <div class="flex items-center gap-2 rounded border border-tp-line bg-tp-panel px-2.5 text-tp-mute focus-within:border-tp-ink">
            <LockKeyhole :size="14" aria-hidden="true" />
            <input
              id="password"
              v-model="password"
              type="password"
              :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
              minlength="10"
              maxlength="72"
              required
              class="h-8 min-w-0 flex-1 border-0 bg-transparent text-xs text-tp-ink outline-0 placeholder:text-tp-faint"
            />
          </div>
          <span v-if="mode === 'register'" class="mt-1 block text-[11px] leading-4 text-tp-mute">至少 10 个字符</span>
        </div>

        <!-- Error -->
        <p v-if="error" class="m-0 rounded bg-tp-warn/10 px-2.5 py-2 text-[11px] leading-4 text-tp-warn" role="alert">{{ error }}</p>

        <!-- Submit -->
        <button
          type="submit"
          :disabled="busy"
          class="flex h-8 w-full items-center justify-center gap-1.5 rounded bg-tp-ink text-xs font-medium text-white transition-colors hover:bg-[#3D3D3B] disabled:opacity-40"
        >
          <LoaderCircle v-if="busy" class="animate-spin" :size="14" aria-hidden="true" />
          <LogIn v-else-if="mode === 'login'" :size="14" aria-hidden="true" />
          <UserPlus v-else :size="14" aria-hidden="true" />
          {{ mode === 'login' ? '登录' : '创建账户并登录' }}
        </button>

        <!-- Mode Switch -->
        <div class="flex justify-center gap-1 text-xs text-tp-sub">
          <span>{{ mode === 'login' ? '还没有账户？' : '已有账户？' }}</span>
          <button type="button" class="bg-transparent border-0 p-0 font-medium text-tp-ink hover:text-tp-body cursor-pointer" @click="switchMode(mode === 'login' ? 'register' : 'login')">
            {{ mode === 'login' ? '创建账户' : '返回登录' }}
          </button>
        </div>
      </form>
    </div>
  </main>
</template>