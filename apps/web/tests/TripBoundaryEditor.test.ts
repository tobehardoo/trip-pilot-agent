import { cleanup, fireEvent, render, screen } from '@testing-library/vue'
import { afterEach, expect, test, vi } from 'vitest'

import TripBoundaryEditor from '../src/components/TripBoundaryEditor.vue'

afterEach(() => cleanup())

test('emits canonical +08:00 datetimes on arrival/departure input', async () => {
  const onArrival = vi.fn()
  const onDeparture = vi.fn()
  const view = render(TripBoundaryEditor, {
    props: { arrivalAt: '2026-08-01T10:00:00+08:00', departureAt: '2026-08-05T18:00:00+08:00' },
    attrs: {
      'onUpdate:arrivalAt': onArrival,
      'onUpdate:departureAt': onDeparture,
    },
  })
  await fireEvent.update(view.getByLabelText('抵达时间'), '2026-08-02T09:00')
  expect(onArrival).toHaveBeenCalledWith('2026-08-02T09:00')
  await fireEvent.update(view.getByLabelText('离开时间'), '2026-08-06T19:30')
  expect(onDeparture).toHaveBeenCalledWith('2026-08-06T19:30')
  // Departure input carries the current arrival as its min attribute.
  expect((view.getByLabelText('离开时间') as HTMLInputElement).min).toBe('2026-08-01T10:00:00+08:00')
})

test('shows an error when arrival is not earlier than departure', async () => {
  render(TripBoundaryEditor, {
    props: { arrivalAt: '2026-08-05T18:00:00+08:00', departureAt: '2026-08-05T08:00:00+08:00' },
    attrs: {},
  })
  // B13_FIX R8 (P1-8): boundary inversion must surface a user-visible error.
  expect(screen.getByRole('alert').textContent).toContain('抵达时间必须早于离开时间')
})

test('shows no error for a valid boundary pair', async () => {
  render(TripBoundaryEditor, {
    props: { arrivalAt: '2026-08-01T10:00:00+08:00', departureAt: '2026-08-05T18:00:00+08:00' },
    attrs: {},
  })
  expect(screen.queryByRole('alert')).toBeNull()
})
