<script setup lang="ts">
import {
  CalendarDays,
  CircleGauge,
  Compass,
  ArrowRight,
  LogOut,
  MapPin,
  Plus,
  Users,
  Wallet,
  X,
} from 'lucide-vue-next'
import { reactive, ref } from 'vue'

import type { CreateTripInput, Trip, User } from '../lib/api'
import { useModalFocus } from '../lib/modal'

const props = defineProps<{
  user: User
  trips: Trip[]
  busy: boolean
  error: string | null
  createTrip: (input: CreateTripInput) => Promise<void>
}>()

const emit = defineEmits<{
  logout: []
  openTrip: [tripId: string]
}>()

const preferenceOptions = ['岭南文化', '本地美食', '城市漫步', '自然风景', '亲子体验', '夜间活动']
const dialogOpen = ref(false)
const dialogElement = ref<HTMLElement | null>(null)
const submitting = ref(false)
const form = reactive({
  title: '',
  destination: '广州',
  startDate: '',
  endDate: '',
  budgetAmount: 3000,
  travelers: 1,
  travelerType: 'SOLO' as 'SOLO' | 'COUPLE' | 'FAMILY' | 'FRIENDS' | 'BUSINESS',
  pace: 'BALANCED' as 'RELAXED' | 'BALANCED' | 'INTENSIVE',
  preferences: [] as string[],
})

function formatDate(date: string) {
  return date.replaceAll('-', '.')
}

function paceLabel(pace: Trip['constraints']['pace']) {
  return { RELAXED: '舒缓', BALANCED: '均衡', INTENSIVE: '紧凑' }[pace]
}

function travelerTypeLabel(type: Trip['constraints']['travelerType']) {
  return { SOLO: '独自', COUPLE: '伴侣', FAMILY: '家庭', FRIENDS: '朋友', BUSINESS: '商务' }[type]
}

function statusLabel(status: string) {
  return { DRAFT: '草稿', PLANNING: '规划中', READY: '可使用', FAILED: '规划失败' }[status] ?? status
}

function resetForm() {
  form.title = ''
  form.destination = '广州'
  form.startDate = ''
  form.endDate = ''
  form.budgetAmount = 3000
  form.travelers = 1
  form.travelerType = 'SOLO'
  form.pace = 'BALANCED'
  form.preferences = []
}

const { handleKeydown: handleDialogKeydown, rememberTrigger } = useModalFocus(
  dialogOpen,
  dialogElement,
  () => { dialogOpen.value = false },
)

function openDialog(event?: Event) {
  rememberTrigger(event?.currentTarget)
  resetForm()
  dialogOpen.value = true
}

function togglePreference(preference: string) {
  const index = form.preferences.indexOf(preference)
  if (index >= 0) form.preferences.splice(index, 1)
  else form.preferences.push(preference)
}

async function saveTrip() {
  submitting.value = true
  try {
    await props.createTrip({
      title: form.title,
      destination: form.destination,
      startDate: form.startDate,
      endDate: form.endDate,
      constraints: {
        budgetAmount: form.budgetAmount,
        travelers: form.travelers,
        travelerType: form.travelerType,
        pace: form.pace,
        preferences: [...form.preferences],
        fixedSchedules: [],
      },
    })
    dialogOpen.value = false
  } catch {
    // The parent renders the API error while the dialog remains open.
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand-lockup">
        <span class="brand-icon"><Compass :size="20" aria-hidden="true" /></span>
        <div>
          <strong>TripPilot</strong>
          <span>旅行规划工作台</span>
        </div>
      </div>
      <div class="user-actions">
        <div class="user-copy">
          <strong>{{ user.displayName }}</strong>
          <span>{{ user.email }}</span>
        </div>
        <button class="icon-button" type="button" title="退出登录" aria-label="退出登录" @click="emit('logout')">
          <LogOut :size="18" aria-hidden="true" />
        </button>
      </div>
    </header>

    <main class="dashboard">
      <div class="page-heading">
        <div>
          <p class="eyebrow">TRIPS</p>
          <h1>我的旅行</h1>
        </div>
        <button class="primary-button" type="button" @click="openDialog">
          <Plus :size="18" aria-hidden="true" />
          创建旅行
        </button>
      </div>

      <p v-if="error" class="error-message" role="alert">{{ error }}</p>

      <section v-if="busy" class="loading-state" aria-label="正在加载旅行">
        <span></span><span></span><span></span>
      </section>

      <section v-else-if="trips.length === 0" class="empty-state">
        <MapPin :size="30" stroke-width="1.6" aria-hidden="true" />
        <h2>还没有旅行</h2>
        <button type="button" @click="openDialog"><Plus :size="17" /> 创建第一条旅行</button>
      </section>

      <section v-else class="trip-grid" aria-label="旅行列表">
        <article v-for="trip in trips" :key="trip.id" class="trip-card">
          <div class="card-topline">
            <span class="status-badge">{{ statusLabel(trip.status) }}</span>
            <span class="destination"><MapPin :size="15" /> {{ trip.destination }}</span>
          </div>
          <h2>{{ trip.title }}</h2>
          <div class="date-range">
            <CalendarDays :size="17" aria-hidden="true" />
            <span>{{ formatDate(trip.startDate) }} — {{ formatDate(trip.endDate) }}</span>
          </div>
          <dl class="constraint-row">
            <div>
              <dt><Wallet :size="15" />预算</dt>
              <dd>¥{{ trip.constraints.budgetAmount ?? '未设' }}</dd>
            </div>
            <div>
              <dt><Users :size="15" />同行</dt>
              <dd>{{ trip.constraints.travelers }} 人 · {{ travelerTypeLabel(trip.constraints.travelerType) }}</dd>
            </div>
            <div>
              <dt><CircleGauge :size="15" />节奏</dt>
              <dd>{{ paceLabel(trip.constraints.pace) }}</dd>
            </div>
          </dl>
          <div class="card-footer">
            <div class="preference-list">
              <span v-for="preference in trip.constraints.preferences.slice(0, 3)" :key="preference">
                {{ preference }}
              </span>
            </div>
            <button
              class="open-trip-button"
              type="button"
              :title="`打开 ${trip.title}`"
              :aria-label="`打开 ${trip.title}`"
              @click="emit('openTrip', trip.id)"
            >
              <ArrowRight :size="17" aria-hidden="true" />
            </button>
          </div>
        </article>
      </section>
    </main>

    <div v-if="dialogOpen" class="dialog-backdrop" @click.self="dialogOpen = false">
      <section
        ref="dialogElement"
        class="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-trip-title"
        tabindex="-1"
        @keydown="handleDialogKeydown"
      >
        <header class="dialog-header">
          <div>
            <p class="eyebrow">NEW TRIP</p>
            <h2 id="create-trip-title">创建旅行</h2>
          </div>
          <button class="icon-button" type="button" title="关闭" aria-label="关闭" @click="dialogOpen = false">
            <X :size="19" />
          </button>
        </header>

        <form @submit.prevent="saveTrip">
          <div class="form-grid">
            <div class="field field-wide">
              <label for="trip-title">旅行名称</label>
              <input id="trip-title" v-model.trim="form.title" maxlength="120" required data-modal-initial-focus />
            </div>
            <div class="field field-wide">
              <label for="destination">目的地</label>
              <input id="destination" v-model.trim="form.destination" maxlength="120" required />
            </div>
            <div class="field">
              <label for="start-date">开始日期</label>
              <input id="start-date" v-model="form.startDate" type="date" required />
            </div>
            <div class="field">
              <label for="end-date">结束日期</label>
              <input id="end-date" v-model="form.endDate" type="date" :min="form.startDate" required />
            </div>
            <div class="field">
              <label for="budget">预算</label>
              <div class="number-input"><span>¥</span><input id="budget" v-model.number="form.budgetAmount" type="number" min="0" step="0.01" required /></div>
            </div>
            <div class="field">
              <label for="travelers">同行人数</label>
              <input id="travelers" v-model.number="form.travelers" type="number" min="1" max="50" required />
            </div>
            <div class="field field-wide">
              <label for="traveler-type">同行类型</label>
              <select id="traveler-type" v-model="form.travelerType" required>
                <option value="SOLO">独自出行</option>
                <option value="COUPLE">伴侣同行</option>
                <option value="FAMILY">家庭出行</option>
                <option value="FRIENDS">朋友同行</option>
                <option value="BUSINESS">商务出行</option>
              </select>
            </div>
          </div>

          <fieldset class="option-group">
            <legend>旅行节奏</legend>
            <div class="segmented-control">
              <label><input v-model="form.pace" type="radio" value="RELAXED" />舒缓</label>
              <label><input v-model="form.pace" type="radio" value="BALANCED" />均衡</label>
              <label><input v-model="form.pace" type="radio" value="INTENSIVE" />紧凑</label>
            </div>
          </fieldset>

          <fieldset class="option-group">
            <legend>偏好</legend>
            <div class="preference-options">
              <label v-for="preference in preferenceOptions" :key="preference">
                <input
                  type="checkbox"
                  :value="preference"
                  :checked="form.preferences.includes(preference)"
                  @change="togglePreference(preference)"
                />
                {{ preference }}
              </label>
            </div>
          </fieldset>

          <p v-if="error" class="error-message" role="alert">{{ error }}</p>

          <footer class="dialog-actions">
            <button class="secondary-button" type="button" @click="dialogOpen = false">取消</button>
            <button class="primary-button" type="submit" :disabled="submitting">保存旅行</button>
          </footer>
        </form>
      </section>
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  min-height: 100vh;
  color: #17201d;
  background: #f2f5f4;
}

.topbar {
  height: 68px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 0 28px;
  color: #f9fbfa;
  background: #173d33;
  border-bottom: 3px solid #e6b44a;
}

.brand-lockup,
.user-actions,
.card-topline,
.date-range,
.card-footer,
.dialog-header,
.dialog-actions {
  display: flex;
  align-items: center;
}

.brand-lockup {
  gap: 10px;
}

.brand-icon {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  color: #173d33;
  background: #e6b44a;
  border-radius: 5px;
}

.brand-lockup div,
.user-copy {
  display: grid;
}

.brand-lockup strong {
  font-size: 16px;
}

.brand-lockup span:not(.brand-icon),
.user-copy span {
  color: #b9ccc5;
  font-size: 11px;
}

.user-actions {
  gap: 14px;
  min-width: 0;
}

.user-copy {
  min-width: 0;
  max-width: 280px;
  text-align: right;
}

.user-copy strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}

.user-copy span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dashboard {
  width: min(1180px, calc(100% - 40px));
  margin: 0 auto;
  padding: 42px 0 70px;
}

.page-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 28px;
}

.eyebrow {
  margin: 0 0 5px;
  color: #8a650f;
  font-size: 11px;
  font-weight: 800;
}

h1,
h2,
p {
  letter-spacing: 0;
}

h1 {
  margin: 0;
  font-size: 28px;
}

.primary-button,
.secondary-button,
.empty-state button {
  min-height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 0 16px;
  border-radius: 5px;
  font: inherit;
  font-size: 13px;
  font-weight: 750;
  cursor: pointer;
}

.primary-button {
  color: #fff;
  background: #236552;
  border: 1px solid #236552;
}

.primary-button:hover:not(:disabled) {
  background: #194d3e;
}

.primary-button:disabled {
  cursor: wait;
  opacity: 0.65;
}

.secondary-button {
  color: #34443f;
  background: #fff;
  border: 1px solid #cbd5d1;
}

.icon-button {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  padding: 0;
  color: inherit;
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.24);
  border-radius: 5px;
  cursor: pointer;
}

.trip-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.trip-card {
  min-width: 0;
  padding: 20px;
  background: #fff;
  border: 1px solid #d4ddda;
  border-top: 3px solid #2f705e;
  border-radius: 6px;
}

.card-topline {
  justify-content: space-between;
  gap: 12px;
}

.status-badge {
  padding: 3px 7px;
  color: #6c531a;
  background: #fbf1d5;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 750;
}

.destination {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #687872;
  font-size: 12px;
}

.trip-card h2 {
  margin: 18px 0 8px;
  overflow-wrap: anywhere;
  font-size: 19px;
}

.date-range {
  gap: 7px;
  color: #566760;
  font-size: 13px;
}

.constraint-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin: 20px 0;
  padding: 14px 0;
  border-block: 1px solid #e4e9e7;
}

.constraint-row div {
  min-width: 0;
}

.constraint-row dt {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #71817b;
  font-size: 11px;
}

.constraint-row dd {
  margin: 5px 0 0;
  overflow-wrap: anywhere;
  font-size: 13px;
  font-weight: 750;
}

.card-footer {
  justify-content: space-between;
  gap: 8px;
}

.open-trip-button {
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  padding: 0;
  color: #236552;
  background: #fff;
  border: 1px solid #a9bdb6;
  border-radius: 5px;
  cursor: pointer;
}

.open-trip-button:hover {
  color: #fff;
  background: #236552;
  border-color: #236552;
}

.preference-list {
  min-width: 0;
  display: flex;
  gap: 5px;
  overflow: hidden;
}

.preference-list span {
  flex: 0 0 auto;
  padding: 3px 6px;
  color: #53635d;
  background: #eef2f0;
  border-radius: 4px;
  font-size: 10px;
}

.empty-state,
.loading-state {
  min-height: 330px;
  display: grid;
  place-items: center;
  align-content: center;
  color: #71817b;
  border-block: 1px solid #d9e1de;
}

.empty-state h2 {
  margin: 12px 0 18px;
  color: #34443f;
  font-size: 17px;
}

.empty-state button {
  color: #236552;
  background: transparent;
  border: 1px solid #99b4aa;
}

.loading-state {
  display: flex;
  gap: 6px;
}

.loading-state span {
  width: 8px;
  height: 8px;
  background: #2f705e;
  border-radius: 50%;
  animation: pulse 0.9s infinite alternate;
}

.loading-state span:nth-child(2) { animation-delay: 0.2s; }
.loading-state span:nth-child(3) { animation-delay: 0.4s; }

@keyframes pulse {
  to { opacity: 0.25; transform: translateY(-4px); }
}

.error-message {
  margin: 0 0 18px;
  padding: 10px 12px;
  color: #8a2929;
  background: #fff0ef;
  border-left: 3px solid #bb4942;
  font-size: 13px;
}

.dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 20;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(15, 29, 24, 0.62);
}

.dialog {
  width: min(620px, 100%);
  max-height: calc(100vh - 40px);
  overflow-y: auto;
  padding: 24px;
  background: #fff;
  border-radius: 7px;
  box-shadow: 0 22px 70px rgba(10, 28, 22, 0.24);
}

.dialog-header {
  justify-content: space-between;
  margin-bottom: 22px;
}

.dialog-header h2 {
  margin: 0;
  font-size: 21px;
}

.dialog-header .icon-button {
  color: #45564f;
  border-color: #d4ddda;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.field-wide {
  grid-column: 1 / -1;
}

.field label,
.option-group legend {
  display: block;
  margin-bottom: 7px;
  color: #34443f;
  font-size: 12px;
  font-weight: 750;
}

.field input,
.field select,
.number-input {
  width: 100%;
  height: 42px;
  padding: 0 11px;
  color: #17201d;
  background: #fff;
  border: 1px solid #cbd5d1;
  border-radius: 5px;
  outline: 0;
  font: inherit;
}

.field input:focus,
.number-input:focus-within {
  border-color: #26725f;
  box-shadow: 0 0 0 3px rgba(38, 114, 95, 0.1);
}

.number-input {
  display: flex;
  align-items: center;
  gap: 6px;
}

.number-input span {
  color: #71817b;
}

.number-input input {
  height: 38px;
  padding: 0;
  border: 0;
  box-shadow: none;
}

.option-group {
  margin: 20px 0 0;
  padding: 0;
  border: 0;
}

.segmented-control {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  padding: 3px;
  background: #edf1ef;
  border-radius: 5px;
}

.segmented-control label {
  position: relative;
  display: grid;
  place-items: center;
  min-height: 34px;
  border-radius: 4px;
  color: #5f7069;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.segmented-control label:has(input:checked) {
  color: #194d3e;
  background: #fff;
  box-shadow: 0 1px 4px rgba(23, 61, 51, 0.12);
}

.segmented-control label:has(input:focus-visible),
.preference-options label:has(input:focus-visible) {
  outline: 2px solid #26725f;
  outline-offset: 2px;
}

.segmented-control input,
.preference-options input {
  position: absolute;
  opacity: 0;
}

.preference-options {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.preference-options label {
  position: relative;
  padding: 7px 10px;
  color: #52625c;
  background: #fff;
  border: 1px solid #cbd5d1;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
}

.preference-options label:has(input:checked) {
  color: #194d3e;
  background: #e8f2ee;
  border-color: #5c9685;
}

.dialog-actions {
  justify-content: flex-end;
  gap: 10px;
  margin-top: 24px;
  padding-top: 18px;
  border-top: 1px solid #e2e8e5;
}

@media (max-width: 900px) {
  .trip-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 620px) {
  .topbar {
    height: 62px;
    padding: 0 16px;
  }

  .brand-lockup span:not(.brand-icon),
  .user-copy span {
    display: none;
  }

  .user-copy {
    max-width: 110px;
  }

  .dashboard {
    width: min(100% - 28px, 1180px);
    padding-top: 28px;
  }

  .page-heading {
    align-items: center;
  }

  .trip-grid,
  .form-grid {
    grid-template-columns: 1fr;
  }

  .field-wide {
    grid-column: auto;
  }

  .dialog {
    padding: 19px;
  }
}
</style>
