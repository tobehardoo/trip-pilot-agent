import { describe, expect, test, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { composeTripTitle, daySpanOf } from '../src/workspace/lib/present'
import { useTripStore } from '../src/workspace/stores/tripStore'
import { useWorkspaceSession } from '../src/workspace/session'
import { useAuthStore } from '../src/app/stores/auth'
import * as api from '../src/lib/api'

// 使用 vi.mock 工厂确保所有 import 方都收到 mock 的绑定
vi.mock('../src/lib/api', () => {
  class ApiError extends Error {
    status: number
    code: string
    constructor(status: number, code: string, message: string) {
      super(message)
      this.status = status
      this.code = code
    }
  }
  const mockCreateTrip = vi.fn()
  const mockListTrips = vi.fn()
  const mockGetTrip = vi.fn()
  const mockGetCurrentItinerary = vi.fn()
  const mockUpdateTripConstraints = vi.fn()
  const mockUpdateTripMetadata = vi.fn()
  const mockRefreshSession = vi.fn()
  return {
    ApiError,
    createTrip: mockCreateTrip,
    listTrips: mockListTrips,
    getTrip: mockGetTrip,
    getCurrentItinerary: mockGetCurrentItinerary,
    updateTripConstraints: mockUpdateTripConstraints,
    updateTripMetadata: mockUpdateTripMetadata,
    refreshSession: mockRefreshSession,
    login: vi.fn(),
    logoutSession: vi.fn(),
    register: vi.fn(),
  }
})

describe('daySpanOf（日期跨度天数解析）', () => {
  test('同日区间 → 1 天', () => {
    expect(daySpanOf('9月12日 — 9月12日')).toBe(1)
  })

  test('9月12日 — 9月14日 → 3 天', () => {
    expect(daySpanOf('9月12日 — 9月14日')).toBe(3)
  })

  test('跨月 9月30日 — 10月2日 → 3 天', () => {
    expect(daySpanOf('9月30日 — 10月2日')).toBe(3)
  })

  test('跨年 12月30日 — 1月2日 → 4 天', () => {
    expect(daySpanOf('12月30日 — 1月2日')).toBe(4)
  })

  test('连字符分隔也可解析（9月3日-9月5日）', () => {
    expect(daySpanOf('9月3日-9月5日')).toBe(3)
  })

  test('结束早于开始（倒置区间）→ null（不产生巨数）', () => {
    expect(daySpanOf('9月14日 — 9月12日')).toBeNull()
  })

  test('无法解析（单日期/纯文本）→ null', () => {
    expect(daySpanOf('9月12日')).toBeNull()
    expect(daySpanOf('杭州周末游')).toBeNull()
    expect(daySpanOf('')).toBeNull()
  })
})

describe('composeTripTitle（目的地 + 日期跨度自动命名）', () => {
  test('上海 + 9月12日—9月14日 → 上海三日旅行', () => {
    expect(composeTripTitle('上海', '9月12日 — 9月14日')).toBe('上海三日旅行')
  })

  test('2 天用"两"（广州两日旅行）', () => {
    expect(composeTripTitle('广州', '9月6日 — 9月7日')).toBe('广州两日旅行')
  })

  test('跨月区间同样按天数命名', () => {
    expect(composeTripTitle('成都', '9月30日 — 10月3日')).toBe('成都四日旅行')
  })

  test('日期无法解析时回退为 目的地+旅行', () => {
    expect(composeTripTitle('北京', '')).toBe('北京旅行')
    expect(composeTripTitle('杭州', '未定')).toBe('杭州旅行')
  })

  test('目的地为空时用"未命名"占位', () => {
    expect(composeTripTitle('', '9月12日 — 9月14日')).toBe('未命名三日旅行')
  })
})

describe('tripStore（真实 API 驱动）', () => {
  beforeEach(() => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    // 初始化认证态，使得 withAccessToken 通过代际检查
    auth.applySession({
      accessToken: 'test-token',
      tokenType: 'Bearer',
      expiresIn: 3600,
      user: { id: 'test', displayName: 'Test', email: 'test@example.com' },
    })
    useWorkspaceSession()
    vi.clearAllMocks()
    vi.mocked(api.createTrip).mockResolvedValue({
      id: 'trip-test-123',
      title: '上海三日旅行',
      destination: '上海',
      startDate: '2026-09-12',
      endDate: '2026-09-14',
      status: 'draft',
      version: 1,
      constraints: {
        schemaVersion: 1,
        travelers: 2,
        travelerType: 'COUPLE',
        budgetAmount: 3000,
        preferences: ['历史文化', '美食'],
        mustVisitPlaces: ['上海博物馆', '豫园'],
        transitModes: [],
        accommodationPreference: null,
        pace: 'MODERATE',
        mealBudget: null,
      },
      createdAt: '2026-09-01T10:00:00Z',
      updatedAt: '2026-09-01T10:00:00Z',
      archivedAt: null,
    })
    vi.mocked(api.listTrips).mockResolvedValue([])
    vi.mocked(api.refreshSession).mockResolvedValue({
      accessToken: 'test-token',
      tokenType: 'Bearer',
      expiresIn: 3600,
      user: { id: 'test', displayName: 'Test', email: 'test@example.com' },
    })
  })

  test('createTrip → API 调用成功 → 自动选中并加入列表', async () => {
    vi.mocked(api.createTrip).mockResolvedValue({
      id: 'trip-test-123',
      title: '上海三日旅行',
      destination: '上海',
      startDate: '2026-09-12',
      endDate: '2026-09-14',
      status: 'draft',
      version: 1,
      constraints: {
        schemaVersion: 1,
        travelers: 2,
        travelerType: 'COUPLE',
        budgetAmount: 3000,
        preferences: ['历史文化', '美食'],
        mustVisitPlaces: ['上海博物馆', '豫园'],
        transitModes: [],
        accommodationPreference: null,
        pace: 'MODERATE',
        mealBudget: null,
      },
      createdAt: '2026-09-01T10:00:00Z',
      updatedAt: '2026-09-01T10:00:00Z',
      archivedAt: null,
    })

    const store = useTripStore()
    const created = await store.createTrip({
      title: '',
      destination: '上海',
      arrivalAt: '2026-09-12',
      departureAt: '2026-09-14',
      constraints: {
        travelers: 2,
        budgetAmount: 3000,
        travelerType: 'COUPLE',
        preferences: ['历史文化', '美食'],
        mustVisitPlaces: ['上海博物馆', '豫园'],
        transitModes: [],
        accommodationPreference: null,
        pace: 'MODERATE',
        mealBudget: null,
      },
    })

    expect(created.title).toBe('上海三日旅行')
    expect(store.currentTripId).toBe('trip-test-123')
    expect(store.trips.some((t) => t.id === 'trip-test-123')).toBe(true)
  })

  test('listTrips → API 调用成功 → trips 状态更新', async () => {
    const mockTrips: api.Trip[] = [
      {
        id: 'trip-1',
        title: '上海三日旅行',
        destination: '上海',
        startDate: '2026-09-12',
        endDate: '2026-09-14',
        status: 'draft',
        version: 1,
        constraints: { schemaVersion: 1, travelers: 2, travelerType: 'COUPLE', budgetAmount: null, preferences: [], mustVisitPlaces: [], transitModes: [], accommodationPreference: null, pace: 'MODERATE', mealBudget: null },
        createdAt: '2026-09-01T10:00:00Z',
        updatedAt: '2026-09-01T10:00:00Z',
        archivedAt: null,
      },
    ]
    vi.mocked(api.listTrips).mockResolvedValue(mockTrips)

    const store = useTripStore()
    await store.loadTrips()

    expect(store.listStatus).toBe('ready')
    expect(store.trips).toEqual(mockTrips)
  })

  test('listTrips → API 失败 → error 状态 + 中文文案', async () => {
    vi.mocked(api.listTrips).mockRejectedValue(new api.ApiError(500, 'INTERNAL_ERROR', '获取列表失败'))

    const store = useTripStore()
    await store.loadTrips()

    expect(store.listStatus).toBe('error')
    expect(store.listError).toBe('获取列表失败')
  })
})
