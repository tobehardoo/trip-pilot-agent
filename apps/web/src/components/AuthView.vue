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
  <main class="auth-layout">
    <section class="brand-panel" aria-label="TripPilot">
      <div class="brand-mark"><Compass :size="30" stroke-width="2" /></div>
      <div>
        <p class="brand-name">TripPilot</p>
        <p class="brand-caption">旅行规划工作台</p>
      </div>
      <div class="route-line" aria-hidden="true">
        <span></span><span></span><span></span>
      </div>
      <p class="brand-city">GUANGZHOU · 23°N</p>
    </section>

    <section class="auth-panel">
      <form class="auth-form" @submit.prevent="submit">
        <div class="form-heading">
          <p class="eyebrow">{{ mode === 'login' ? '欢迎回来' : '开始规划' }}</p>
          <h1>{{ mode === 'login' ? '登录 TripPilot' : '创建 TripPilot 账户' }}</h1>
        </div>

        <div v-if="mode === 'register'" class="field">
          <label for="display-name">显示名称</label>
          <div class="input-shell">
            <UserPlus :size="18" aria-hidden="true" />
            <input id="display-name" v-model.trim="displayName" autocomplete="name" maxlength="80" required />
          </div>
        </div>

        <div class="field">
          <label for="email">邮箱</label>
          <div class="input-shell">
            <Mail :size="18" aria-hidden="true" />
            <input id="email" v-model.trim="email" type="email" autocomplete="email" maxlength="254" required />
          </div>
        </div>

        <div class="field">
          <label for="password">密码</label>
          <div class="input-shell">
            <LockKeyhole :size="18" aria-hidden="true" />
            <input
              id="password"
              v-model="password"
              type="password"
              :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
              minlength="10"
              maxlength="72"
              required
            />
          </div>
          <span v-if="mode === 'register'" class="field-note">至少 10 个字符</span>
        </div>

        <p v-if="error" class="error-message" role="alert">{{ error }}</p>

        <button class="primary-button" type="submit" :disabled="busy">
          <LoaderCircle v-if="busy" class="spin" :size="18" aria-hidden="true" />
          <LogIn v-else-if="mode === 'login'" :size="18" aria-hidden="true" />
          <UserPlus v-else :size="18" aria-hidden="true" />
          {{ mode === 'login' ? '登录' : '创建账户并登录' }}
        </button>

        <div class="mode-switch">
          <span>{{ mode === 'login' ? '还没有账户？' : '已有账户？' }}</span>
          <button type="button" @click="switchMode(mode === 'login' ? 'register' : 'login')">
            {{ mode === 'login' ? '创建账户' : '返回登录' }}
          </button>
        </div>
      </form>
    </section>
  </main>
</template>

<style scoped>
.auth-layout {
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(300px, 0.9fr) minmax(460px, 1.1fr);
  color: #17201d;
  background: #f5f7f6;
}

.brand-panel {
  position: relative;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  padding: 44px;
  overflow: hidden;
  color: #f9fbfa;
  background-color: #173d33;
  background-image:
    linear-gradient(rgba(237, 242, 240, 0.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(237, 242, 240, 0.06) 1px, transparent 1px);
  background-size: 42px 42px;
}

.brand-panel::after {
  content: '';
  position: absolute;
  right: -120px;
  bottom: 90px;
  width: 360px;
  height: 360px;
  border: 1px solid rgba(230, 180, 74, 0.38);
  border-radius: 50%;
}

.brand-mark {
  width: 50px;
  height: 50px;
  display: grid;
  place-items: center;
  margin-bottom: 22px;
  color: #173d33;
  background: #e6b44a;
  border-radius: 6px;
}

.brand-name,
.brand-caption,
.brand-city {
  margin: 0;
  letter-spacing: 0;
}

.brand-name {
  font-size: 42px;
  font-weight: 760;
  line-height: 1;
}

.brand-caption {
  margin-top: 10px;
  color: #c8d8d2;
  font-size: 15px;
}

.route-line {
  width: min(320px, 78%);
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: auto;
  border-top: 1px dashed rgba(249, 251, 250, 0.45);
}

.route-line span {
  width: 10px;
  height: 10px;
  margin-top: -5px;
  background: #e6b44a;
  border: 2px solid #173d33;
  border-radius: 50%;
  outline: 1px solid #e6b44a;
}

.brand-city {
  margin-top: 18px;
  color: #9eb8af;
  font-size: 11px;
  font-weight: 700;
}

.auth-panel {
  display: grid;
  place-items: center;
  padding: 40px;
}

.auth-form {
  width: min(100%, 410px);
}

.form-heading {
  margin-bottom: 32px;
}

.eyebrow {
  margin: 0 0 8px;
  color: #a06a00;
  font-size: 12px;
  font-weight: 750;
}

h1 {
  margin: 0;
  font-size: 30px;
  line-height: 1.25;
  letter-spacing: 0;
}

.field {
  margin-bottom: 18px;
}

.field label {
  display: block;
  margin-bottom: 7px;
  color: #34443f;
  font-size: 13px;
  font-weight: 700;
}

.input-shell {
  height: 46px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 13px;
  color: #71817b;
  background: #fff;
  border: 1px solid #cdd7d3;
  border-radius: 5px;
}

.input-shell:focus-within {
  border-color: #26725f;
  box-shadow: 0 0 0 3px rgba(38, 114, 95, 0.12);
}

.input-shell input {
  min-width: 0;
  flex: 1;
  border: 0;
  outline: 0;
  color: #17201d;
  background: transparent;
  font: inherit;
}

.field-note {
  display: block;
  margin-top: 6px;
  color: #697872;
  font-size: 12px;
}

.error-message {
  margin: 0 0 16px;
  padding: 10px 12px;
  color: #8a2929;
  background: #fff0ef;
  border-left: 3px solid #bb4942;
  font-size: 13px;
}

.primary-button {
  width: 100%;
  height: 46px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #fff;
  background: #236552;
  border: 0;
  border-radius: 5px;
  font: inherit;
  font-weight: 750;
  cursor: pointer;
}

.primary-button:hover:not(:disabled) {
  background: #194d3e;
}

.primary-button:disabled {
  cursor: wait;
  opacity: 0.65;
}

.mode-switch {
  display: flex;
  justify-content: center;
  gap: 6px;
  margin-top: 20px;
  color: #697872;
  font-size: 13px;
}

.mode-switch button {
  padding: 0;
  color: #236552;
  background: transparent;
  border: 0;
  font: inherit;
  font-weight: 750;
  cursor: pointer;
}

.spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 760px) {
  .auth-layout {
    grid-template-columns: 1fr;
  }

  .brand-panel {
    min-height: 180px;
    padding: 24px;
  }

  .brand-mark {
    width: 42px;
    height: 42px;
    margin-bottom: 14px;
  }

  .brand-name {
    font-size: 32px;
  }

  .route-line,
  .brand-city {
    display: none;
  }

  .auth-panel {
    place-items: start center;
    padding: 34px 20px 48px;
  }
}
</style>
