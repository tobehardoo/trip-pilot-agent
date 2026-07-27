import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, test } from 'vitest'

const session = {
  user: {
    id: '11111111-1111-1111-1111-111111111111',
    email: 'traveler@example.com',
    displayName: '旅行者',
  },
  accessToken: 'access-token',
  tokenType: 'Bearer',
  expiresIn: 900,
}

describe('authentication store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  test('owns the restored session lifecycle', async () => {
    const { useAuthStore } = await import('../src/app/stores/auth')
    const store = useAuthStore()

    expect(store.phase).toBe('restoring')
    store.applySession(session)
    expect(store.phase).toBe('authenticated')
    expect(store.user).toEqual(session.user)
    expect(store.accessToken).toBe('access-token')

    store.clearSession()
    expect(store.phase).toBe('guest')
    expect(store.user).toBeNull()
    expect(store.accessToken).toBe('')
  })
})
