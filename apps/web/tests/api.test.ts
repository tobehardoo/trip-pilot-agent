import { afterEach, expect, test, vi } from 'vitest'

import { ApiError, createTrip, type CreateTripInput } from '../src/lib/api'

afterEach(() => {
  vi.unstubAllGlobals()
})

test('turns an empty unauthorized response into a structured API error', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: false,
    status: 401,
    json: async () => { throw new SyntaxError('Unexpected end of JSON input') },
  } as Response)))
  const input: CreateTripInput = {
    title: '广州周末四日',
    destination: '广州',
    startDate: '2026-07-18',
    endDate: '2026-07-21',
    constraints: {
      budgetAmount: 4000,
      travelers: 2,
      travelerType: 'FRIENDS',
      pace: 'BALANCED',
      preferences: ['岭南文化'],
      fixedSchedules: [],
    },
  }

  await expect(createTrip('expired-token', input)).rejects.toEqual(
    new ApiError(401, 'REQUEST_FAILED', '请求失败'),
  )
})
