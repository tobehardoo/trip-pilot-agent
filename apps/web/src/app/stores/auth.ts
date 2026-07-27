import { ref } from 'vue'
import { defineStore } from 'pinia'

import type { AuthSession, User } from '../../lib/api'

export type AuthPhase = 'guest' | 'restoring' | 'authenticated'

export const useAuthStore = defineStore('auth', () => {
  const phase = ref<AuthPhase>('restoring')
  const user = ref<User | null>(null)
  const accessToken = ref('')

  function applySession(session: AuthSession) {
    user.value = session.user
    accessToken.value = session.accessToken
    phase.value = 'authenticated'
  }

  function clearSession() {
    phase.value = 'guest'
    user.value = null
    accessToken.value = ''
  }

  return {
    phase,
    user,
    accessToken,
    applySession,
    clearSession,
  }
})
