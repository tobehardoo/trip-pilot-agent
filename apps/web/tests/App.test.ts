import { render, screen } from '@testing-library/vue'
import { expect, test } from 'vitest'

import App from '../src/App.vue'

test('renders the planning workspace identity', () => {
  render(App)

  expect(screen.getByRole('heading', { name: 'TripPilot' })).toBeTruthy()
  expect(screen.getByText('智能旅行规划工作台')).toBeTruthy()
})
