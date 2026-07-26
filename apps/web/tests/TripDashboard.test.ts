import { cleanup, fireEvent, render } from '@testing-library/vue'
import { afterEach, expect, test, vi } from 'vitest'

import TripDashboard from '../src/components/TripDashboard.vue'

afterEach(() => cleanup())

test('prefills the selected template before opening the create dialog', async () => {
  const view = render(TripDashboard, {
    props: {
      user: { id: 'user-1', email: 'traveler@example.com', displayName: 'Traveler' },
      trips: [],
      busy: false,
      error: null,
      createTrip: vi.fn(async () => {}),
    },
  })

  const templateButtons = view.container.querySelectorAll('section button')
  await fireEvent.click(templateButtons[1]!)

  expect(view.container.querySelector<HTMLInputElement>('#trip-title')?.value).not.toBe('')
  expect(view.container.querySelector<HTMLInputElement>('#destination')?.value).not.toBe('广州')
})
