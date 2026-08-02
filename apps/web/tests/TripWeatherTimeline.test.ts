import { cleanup, fireEvent, render, screen } from '@testing-library/vue'
import { afterEach, expect, test } from 'vitest'

import TripWeatherTimeline from '../src/components/TripWeatherTimeline.vue'

afterEach(cleanup)

const weatherFacts = [
  {
    id: 'weather-current',
    category: 'WEATHER' as const,
    statement: '杭州市当前天气：晴，34℃，湿度45%，南风≤3级；高德发布时间 2026-07-30 11:02:15。',
    evidence: 'weather',
    confidence: 0.95,
    observedAt: '2026-07-30T03:20:00Z',
    expiresAt: '2026-07-31T03:20:00Z',
  },
  {
    id: 'weather-forecast',
    category: 'WEATHER' as const,
    statement: '2026-08-01 杭州市天气预报：白天多云 37℃，夜间多云 28℃，东南风1-3级。',
    evidence: 'forecast',
    confidence: 0.9,
    observedAt: '2026-07-30T03:20:00Z',
    expiresAt: '2026-08-02T03:20:00Z',
  },
]

test('shows the travel range with buffer days and only fills dates backed by weather facts', async () => {
  const result = render(TripWeatherTimeline, {
    props: {
      weatherFacts,
      startDate: '2026-08-01',
      endDate: '2026-08-03',
    },
  })

  expect(screen.getByRole('region', { name: '行程天气' })).toBeTruthy()
  expect(screen.getByRole('button', { name: '选择 2026-07-30 天气' })).toBeTruthy()
  expect(screen.getByRole('button', { name: '选择 2026-08-05 天气' })).toBeTruthy()
  expect(screen.getByText('晴')).toBeTruthy()
  expect(screen.getByText('37° / 28°')).toBeTruthy()
  expect(screen.getAllByText('待同步').length).toBeGreaterThan(0)

  await fireEvent.click(screen.getByRole('button', { name: '选择 2026-08-01 天气' }))
  expect(result.emitted().selectDate).toEqual([['2026-08-01']])
})

test('marks a selected date and restores all routes on demand', async () => {
  const result = render(TripWeatherTimeline, {
    props: {
      weatherFacts,
      startDate: '2026-08-01',
      endDate: '2026-08-03',
      selectedDate: '2026-08-02',
      referenceDate: '2026-07-30',
    },
  })

  expect(screen.getByRole('button', { name: '选择 2026-08-02 天气' }).getAttribute('aria-pressed')).toBe('true')
  await fireEvent.click(screen.getByRole('button', { name: '查看全部行程' }))
  expect(result.emitted().showAll).toEqual([[]])
  expect(screen.getAllByText('预报未开放').length).toBeGreaterThan(0)
})

test('keeps a past itinerary timeline bounded to its two-day buffer', () => {
  const historyFact = {
    ...weatherFacts[0],
    id: 'weather-history',
    statement: '2026-07-25 杭州市历史天气：阵雨，最高33℃，最低26℃，湿度80%。',
    observedAt: '2026-07-30T03:20:00Z',
  }
  render(TripWeatherTimeline, {
    props: {
      weatherFacts: [...weatherFacts, historyFact],
      startDate: '2026-07-25',
      endDate: '2026-07-27',
      referenceDate: '2026-07-30',
    },
  })

  expect(screen.queryByRole('button', { name: '选择 2026-07-30 天气' })).toBeNull()
  expect(screen.getByText('阵雨')).toBeTruthy()
  expect(screen.getAllByText('历史天气尚未同步').length).toBeGreaterThan(0)
})

test('exposes horizontal weather navigation when the timeline has more days than fit on screen', () => {
  render(TripWeatherTimeline, {
    props: {
      weatherFacts,
      startDate: '2026-08-01',
      endDate: '2026-08-10',
    },
  })

  expect(screen.getByRole('button', { name: '向左滚动天气' })).toBeTruthy()
  expect(screen.getByRole('button', { name: '向右滚动天气' })).toBeTruthy()
})
