import { cleanup, fireEvent, render } from '@testing-library/vue'
import { afterEach, expect, test, vi } from 'vitest'

import TripDashboard from '../src/components/TripDashboard.vue'

afterEach(() => cleanup())

test('emits search, archive, and restore actions from the trip list', async () => {
  const trip = {
    id: 'trip-active',
    title: 'Active trip',
    destination: 'Guangzhou',
    startDate: '2026-08-01',
    endDate: '2026-08-02',
    status: 'READY',
    version: 1,
    constraints: {
      budgetAmount: 2000,
      travelers: 1,
      travelerType: 'SOLO' as const,
      pace: 'BALANCED' as const,
      preferences: [],
      fixedSchedules: [],
    },
    createdAt: '2026-07-01T00:00:00Z',
    updatedAt: '2026-07-01T00:00:00Z',
    archivedAt: null,
  }
  const view = render(TripDashboard, {
    props: {
      user: { id: 'user-1', email: 'traveler@example.com', displayName: 'Traveler' },
      trips: [trip, { ...trip, id: 'trip-archived', archivedAt: '2026-07-02T00:00:00Z' }],
      busy: false,
      error: null,
      createTrip: vi.fn(async () => {}),
    },
  })

  await fireEvent.update(view.getByTestId('trip-destination-search'), 'Guangzhou')
  await fireEvent.submit(view.getByTestId('trip-search-form'))
  await fireEvent.click(view.getByTestId('include-archived'))
  await fireEvent.click(view.getByTestId('archive-trip-trip-active'))
  await fireEvent.click(view.getByTestId('restore-trip-trip-archived'))

  expect(view.emitted('search')?.[0]).toEqual(['Guangzhou'])
  expect(view.emitted('includeArchived')?.[0]).toEqual([true])
  expect(view.emitted('archiveTrip')?.[0]).toEqual(['trip-active'])
  expect(view.emitted('restoreTrip')?.[0]).toEqual(['trip-archived'])
})

test('B13 offers exactly one create entry and opens an empty form', async () => {
  const view = render(TripDashboard, {
    props: {
      user: { id: 'user-1', email: 'traveler@example.com', displayName: 'Traveler' },
      trips: [],
      busy: false,
      error: null,
      createTrip: vi.fn(async () => {}),
    },
  })

  expect(view.getAllByRole('button', { name: '创建旅行' })).toHaveLength(1)
  await fireEvent.click(view.getByRole('button', { name: '创建旅行' }))

  expect(view.container.querySelector<HTMLInputElement>('#trip-title')?.value).toBe('')
  expect((view.getByLabelText('省 / 直辖市') as HTMLSelectElement).value).toBe('')
  expect(view.queryByLabelText('城市')).toBeNull()
  expect(view.queryByText('快速开始')).toBeNull()
  expect(view.queryByText('用一句话描述旅行计划')).toBeNull()
})
